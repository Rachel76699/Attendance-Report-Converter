import unittest
import os
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
import pymupdf
import pytest
from application import process_single_pdf
from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from parsing import ocr
from parsing.classifier import classify_report_type
from parsing.text_tools import normalize_ocr_text, reconstruct_ocr_rows
from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser
from generation.excel_renderer import ExcelRenderer
from generation.pdf_generator import generate_pdf
from transformation.strategies import TransformationService, calculate_total_payment, is_work_day


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("01102/2023", "01/02/2023"),
        ("20/1123", "20/1/23"),
        ("5/1123", "5/1/23"),
        ("20/1/23 23/1/23 2411/23", "20/1/23 23/1/23 24/1/23"),
        ("O | 125%", "0 | 125%"),
    ],
)
def test_ocr_cleanup_repairs_observed_sample_output(raw_text, expected):
    # Regression cases captured from raw OCR output of the sample PDFs.
    assert normalize_ocr_text(raw_text) == expected


class TestAttendanceSystem(unittest.TestCase):
    """
    מערך בדיקות יחידה (Unit Tests) למערכת עיבוד דוחות הנוכחות.
    """

    def setUp(self):
        # הכנת נתוני דוגמה גולמיים עבור סוג A
        self.raw_text_type_a = """
        143
        נ.ע. הנשר כח אדם בע"מ
        0.00 | 0.00 | 0.00 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | גליליון | יום ראשון | 02/10/2022
        """

        # הכנת נתוני דוגמה גולמיים עבור סוג B (כרטיס עובד)
        self.raw_text_type_b = """
        כרטיס עובד לחודש: 22-090
        | 3.50 | 12:00 | 8:30 | חמישי | 1/9/22
        """

    def test_report_rows_are_stored_as_an_immutable_tuple(self):
        report = TypeAParser().parse(self.raw_text_type_a)

        self.assertIsInstance(report.rows, tuple)
        self.assertIsInstance(report, AttendanceReport)
        self.assertIsInstance(report.report_type, ReportType)
        self.assertTrue(AttendanceRow.__dataclass_params__.frozen)
        self.assertTrue(ReportSummary.__dataclass_params__.frozen)
        self.assertTrue(AttendanceReport.__dataclass_params__.frozen)
        with self.assertRaises(FrozenInstanceError):
            report.rows = ()

    def test_classifier_type_a(self):
        """בדיקת זיהוי נכון של דוח סוג A."""
        text = "נ.ע. הנשר כח אדם בע\"מ 125% שבת"
        report_type = classify_report_type(text)
        self.assertIs(report_type, ReportType.TYPE_A)

    def test_classifier_type_b(self):
        """בדיקת זיהוי נכון של דוח סוג B (כרטיס עובד)."""
        text = "כרטיס עובד לחודש שעת כניסה שעת יציאה הערות"
        report_type = classify_report_type(text)
        self.assertIs(report_type, ReportType.TYPE_B)

    def test_classifier_handles_type_b_without_standard_keyword(self):
        self.assertIs(
            classify_report_type("כרטסת עובד, יום בשבוע, שעת יציאה"),
            ReportType.TYPE_B
        )

    def test_ocr_cleanup_preserves_valid_november_date_and_words(self):
        self.assertEqual(normalize_ocr_text("01/11/23 OCR"), "01/11/23 OCR")

    def test_pdf_extraction_reads_all_pages_and_reuses_cached_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.abspath(directory)
            pdf_path = os.path.join(root, "multipage.pdf")
            cache_dir = os.path.join(root, "text_cache")
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "First page")
            document.new_page().insert_text((72, 72), "Second page")
            document.save(pdf_path)
            document.close()

            with patch.object(ocr, "TEXT_CACHE_DIR", Path(cache_dir)):
                extracted = ocr.extract_text_from_pdf(pdf_path)
                self.assertIn("First page", extracted)
                self.assertIn("Second page", extracted)

                with patch.object(
                    ocr,
                    "_extract_text_without_cache",
                    side_effect=AssertionError("OCR/extraction should use the cache"),
                ) as uncached_extraction:
                    self.assertEqual(ocr.extract_text_from_pdf(pdf_path), extracted)
                    uncached_extraction.assert_not_called()

    def test_pdf_text_cache_is_invalidated_when_ocr_languages_change(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = os.path.join(directory, "report.pdf")
            cache_dir = Path(directory) / "text_cache"
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "Digital report")
            document.save(pdf_path)
            document.close()

            with (
                patch.object(ocr, "TEXT_CACHE_DIR", cache_dir),
                patch.object(ocr, "_ocr_language_signature", side_effect=["en-US", "en-US,he-IL"]),
                patch.object(ocr, "_extract_text_without_cache", return_value="Fresh OCR text") as extract,
            ):
                self.assertEqual(ocr.extract_text_from_pdf(pdf_path), "Fresh OCR text")
                self.assertEqual(ocr.extract_text_from_pdf(pdf_path), "Fresh OCR text")
                self.assertEqual(extract.call_count, 2)

    def test_ocr_table_rows_are_reassembled_by_position(self):
        words = [
            (100, 100, 10, "6.50"),
            (200, 101, 10, "15:00"),
            (300, 100, 10, "08:00"),
            (400, 102, 10, "02/10/2022"),
            (100, 130, 10, "7.00"),
            (200, 131, 10, "16:00"),
            (300, 130, 10, "08:00"),
            (400, 132, 10, "03/10/2022")
        ]

        rows = reconstruct_ocr_rows(words).splitlines()

        self.assertEqual(rows[0], "6.50 | 15:00 | 08:00 | 02/10/2022")
        self.assertEqual(rows[1], "7.00 | 16:00 | 08:00 | 03/10/2022")

    def test_type_a_parser(self):
        """בדיקת פענוח תקינה של שורה בדוח סוג A."""
        parser = TypeAParser()
        report = parser.parse(self.raw_text_type_a)

        self.assertIs(report.report_type, ReportType.TYPE_A)
        self.assertGreaterEqual(len(report.rows), 1)

        row = report.rows[0]
        self.assertEqual(row.date, "02/10/2022")
        self.assertEqual(row.entry, 8 * 60)
        self.assertEqual(row.exit, 15 * 60)
        self.assertEqual(row.break_time, 30)
        self.assertEqual(row.total, 6.50)
        self.assertEqual(row.p100, 6.5)
        self.assertEqual(row.p125, 0.0)
        self.assertEqual(
            report.summary.total_payment,
            calculate_total_payment(report.summary.total_hours, report.summary.hourly_rate)
        )
        self.assertEqual(report.summary.total_payment, 199.23)

    def test_type_a_parser_recovers_missing_date_and_repairs_ocr_fields(self):
        raw_text = "\n".join([
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | office | Thursday | 13/10/2022",
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 16•30 | 08:30",
            "6.50 | 0 | 0 | 0 | 6.50 | 00:30 | 1600 | 08:00 | office | Saturday | 15/10/2022",
        ])

        report = TypeAParser().parse(raw_text)

        self.assertEqual([row.date for row in report.rows], [
            "13/10/2022", "14/10/2022", "15/10/2022"
        ])
        self.assertEqual([row.day for row in report.rows], [
            "יום חמישי", "יום שישי", "שבת"
        ])
        self.assertEqual(report.rows[1].entry, 8 * 60 + 30)
        self.assertEqual(report.rows[1].exit, 16 * 60 + 30)
        self.assertEqual(report.rows[1].location, "")
        self.assertTrue(report.rows[2].special_day)
        self.assertEqual(report.summary.total_days, 3)
        self.assertEqual(report.summary.total_hours, 19.5)

    def test_type_a_parser_repairs_split_date_and_preserves_holiday(self):
        raw_text = (
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | "
            "office | יום כיפור | 05 | /10/2022"
        )

        report = TypeAParser().parse(raw_text)

        self.assertEqual(len(report.rows), 1)
        self.assertEqual(report.rows[0].date, "05/10/2022")
        self.assertEqual(report.rows[0].day, "יום כיפור")
        self.assertTrue(report.rows[0].special_day)
        self.assertIsNone(report.rows[0].entry)

    def test_type_a_fallback_payment_matches_fallback_hours(self):
        report = TypeAParser().parse("")

        self.assertEqual(report.summary.total_hours, 143.0)
        self.assertEqual(
            report.summary.total_payment,
            calculate_total_payment(report.summary.total_hours, report.summary.hourly_rate)
        )

    def test_type_b_parser(self):
        """בדיקת פענוח תקינה של שורה בדוח סוג B."""
        parser = TypeBParser()
        report = parser.parse(self.raw_text_type_b)

        self.assertIs(report.report_type, ReportType.TYPE_B)
        self.assertGreaterEqual(len(report.rows), 1)

        row = report.rows[0]
        self.assertEqual(row.date, "1/9/22")
        self.assertEqual(row.entry, 8 * 60 + 30)
        self.assertEqual(row.exit, 12 * 60)
        self.assertEqual(row.total, 3.50)
        self.assertIsNone(row.break_time)
        self.assertIsNone(row.shabbat)
        self.assertIsNone(row.p150)
        self.assertIsNone(row.p125)
        self.assertIsNone(row.p100)
        self.assertEqual(report.summary.total_hours, 3.5)
        self.assertEqual(report.summary.total_payment, 107.28)

    def test_type_b_parser_recovers_ocr_dates_and_weekdays(self):
        raw_text = """
        3 | ימי עבודה לחודש
        10.50 | שעות חודשיות
        30.65 | מחיר לשעה
        321.83 | לתשלום
        3.50 | 12:00 | 8:30 | 119122
        3.50 | 12:00 | 8:30 | 219/22
        nav | 319/22
        3.50 | 12:00 | 8:30 | 4/9/22
        """

        report = TypeBParser().parse(raw_text)

        self.assertEqual([row.date for row in report.rows], [
            "1/9/22", "2/9/22", "3/9/22", "4/9/22"
        ])
        self.assertEqual(report.rows[2].day, "שבת")
        self.assertTrue(report.rows[2].special_day)
        self.assertEqual(report.rows[2].total, 0.0)
        self.assertEqual(report.summary.total_hours, 10.5)
        self.assertEqual(report.summary.hourly_rate, 30.65)
        self.assertEqual(report.summary.total_days, 3)
        self.assertEqual(report.summary.total_payment, 321.83)
        transformed = TransformationService(seed=42).transform(report)
        self.assertEqual(
            transformed.summary.total_hours,
            round(sum(row.total for row in transformed.rows if row.total > 0), 2)
        )

    def test_type_b_parser_does_not_count_ocr_noise_as_saturday_hours(self):
        report = TypeBParser().parse(
            "3.50 | 12:00 | 8:30 | 6/1/23\n"
            "4.0 | Iff123\n"
            "3.50 | 12:00 | 8:30 | 8/1/23"
        )

        self.assertEqual([row.date for row in report.rows], [
            "6/1/23", "7/1/23", "8/1/23"
        ])
        self.assertEqual(report.rows[1].day, "שבת")
        self.assertEqual(report.rows[1].total, 0.0)

    def test_type_b_holiday_row_is_kept_without_clock_times(self):
        report = TypeBParser().parse(
            "3.50 | 12:00 | 08:00 | יום כיפור | 05/10/22"
        )

        self.assertEqual(len(report.rows), 1)
        row = report.rows[0]
        self.assertTrue(row.special_day)
        self.assertEqual(row.day, "יום כיפור")
        self.assertIsNone(row.entry)
        self.assertIsNone(row.exit)
        self.assertEqual(row.total, 3.5)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "holiday.xlsx")
            ExcelRenderer().render(report, path)
            workbook = load_workbook(path)
            worksheet = workbook["נוכחות"]
            self.assertEqual(worksheet["B2"].value, 3.5)
            self.assertEqual(worksheet["C2"].value, "---")
            self.assertEqual(worksheet["D2"].value, "---")
            self.assertEqual(worksheet["E2"].value, "יום כיפור")
            workbook.close()

            pdf_path = os.path.join(directory, "holiday.pdf")
            generate_pdf(report, pdf_path)
            with pymupdf.open(pdf_path) as document:
                self.assertIn("---", document[0].get_text())

    def test_type_a_saturday_row_is_kept_without_clock_times(self):
        raw = (
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | "
            "office | | 08/10/2022"
        )
        report = TypeAParser().parse(raw)

        self.assertEqual(len(report.rows), 1)
        row = report.rows[0]
        self.assertTrue(row.special_day)
        self.assertEqual(row.day, "שבת")
        self.assertIsNone(row.entry)
        self.assertIsNone(row.exit)
        self.assertIsNone(row.break_time)
        self.assertEqual(row.total, 6.5)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "saturday.xlsx")
            ExcelRenderer().render(report, path)
            workbook = load_workbook(path)
            worksheet = workbook["נוכחות"]
            self.assertEqual(worksheet["E2"].value, 6.5)
            self.assertEqual(worksheet["F2"].value, "---")
            self.assertEqual(worksheet["G2"].value, "---")
            self.assertEqual(worksheet["H2"].value, "---")
            self.assertIsNone(worksheet["I2"].value)
            self.assertEqual(worksheet["J2"].value, "שבת")
            self.assertEqual(worksheet["K2"].value, "08/10/2022")
            workbook.close()

            pdf_path = os.path.join(directory, "saturday.pdf")
            generate_pdf(report, pdf_path)
            with pymupdf.open(pdf_path) as document:
                self.assertIn("---", document[0].get_text())

    def test_type_a_location_is_preserved_and_not_replaced_with_placeholder(self):
        raw = (
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | "
            "משרד | יום ראשון | 02/10/2022"
        )
        report = TypeAParser().parse(raw)

        self.assertEqual(report.rows[0].location, "משרד")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "location.xlsx")
            ExcelRenderer().render(report, path)
            workbook = load_workbook(path)
            worksheet = workbook["נוכחות"]
            self.assertEqual(worksheet["I2"].value, "משרד")
            self.assertEqual(worksheet["J2"].value, "יום ראשון")
            self.assertEqual(worksheet["K2"].value, "02/10/2022")
            workbook.close()

    def test_type_a_parser_preserves_location_when_weekday_is_missing(self):
        raw = (
            "0 | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | 08:00 | "
            "גליליון | 02/10/2022"
        )
        row = TypeAParser().parse(raw).rows[0]

        self.assertEqual(row.location, "גליליון")
        self.assertEqual(row.day, "יום ראשון")

    def test_parser_handles_invalid_clock_values(self):
        raw = "0 | 0 | 0 | 6.50 | 6.50 | 00:60 | 25:61 | 08:30 | office | Sunday | 02/10/2022"
        row = TypeAParser().parse(raw).rows[0]

        self.assertIsNone(row.break_time)
        self.assertIsNone(row.exit)
        self.assertEqual(row.entry, 8 * 60 + 30)

    def test_transformation_service(self):
        """בדיקת שירות שינוי השעות (Transformation) כך ששעות משתנות ואינן נשארות עגולות לחלוטין."""
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60,
            exit=15 * 60,
            total=6.50,
            break_time=30,
            location="גליליון"
        )
        summary = ReportSummary(total_days=1, total_hours=6.5, hourly_rate=30.65, total_payment=199.22)
        report = AttendanceReport(report_type=ReportType.TYPE_A, rows=(row,), summary=summary)

        transformer = TransformationService(seed=42)
        transformed_report = transformer.transform(report)

        t_row = transformed_report.rows[0]

        # שתי השעות מוזזות בנפרד, והכניסה נשארת לפני היציאה.
        self.assertIsNotNone(t_row.entry)
        self.assertNotEqual(t_row.entry, 8 * 60)
        entry_shift = t_row.entry - (8 * 60)
        exit_shift = t_row.exit - (15 * 60)
        self.assertGreaterEqual(entry_shift, -5)
        self.assertLessEqual(entry_shift, 10)
        self.assertNotEqual(t_row.exit, 15 * 60)
        self.assertGreaterEqual(exit_shift, -5)
        self.assertLessEqual(exit_shift, 10)
        self.assertNotEqual(exit_shift, entry_shift)
        self.assertGreater(t_row.exit, t_row.entry)
        self.assertEqual(
            t_row.total,
            round((t_row.exit - t_row.entry - row.break_time) / 60, 2)
        )

        # מוודא שהתשלום מחושב מחדש בהתאם לסך השעות שבשורות
        self.assertEqual(
            transformed_report.summary.total_hours,
            round(sum(row.total for row in transformed_report.rows), 2)
        )
        self.assertEqual(
            transformed_report.summary.total_payment,
            calculate_total_payment(
                transformed_report.summary.total_hours,
                transformed_report.summary.hourly_rate
            )
        )

    def test_type_a_parser_preserves_overtime_columns(self):
        raw = "1.00 | 2.00 | 1.50 | 6.50 | 11.00 | 00:30 | 16:00 | 08:00 | משרד | יום ראשון | 02/10/2022"
        row = TypeAParser().parse(raw).rows[0]

        self.assertEqual((row.shabbat, row.p150, row.p125, row.p100), (1.0, 2.0, 1.5, 6.5))

    def test_transformation_shifts_type_b_times_independently_and_recalculates_hours(self):
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60 + 30,
            exit=12 * 60,
            total=3.5,
        )
        summary = ReportSummary(1, 3.5, 30.65, 107.28)
        report = AttendanceReport(ReportType.TYPE_B, (row,), summary)

        transformed = TransformationService(seed=42).transform(report)
        transformed_row = transformed.rows[0]

        self.assertNotEqual(transformed_row.entry, row.entry)
        self.assertNotEqual(transformed_row.exit, row.exit)
        self.assertNotEqual(
            transformed_row.entry - row.entry,
            transformed_row.exit - row.exit,
        )
        self.assertGreater(transformed_row.exit, transformed_row.entry)
        self.assertEqual(
            transformed_row.total,
            round((transformed_row.exit - transformed_row.entry) / 60, 2),
        )
        self.assertEqual(transformed.summary.total_hours, transformed_row.total)
        self.assertNotEqual(transformed.summary.total_hours, summary.total_hours)

    def test_saturday_times_are_not_changed(self):
        row = AttendanceRow(
            date="03/10/2022",
            day="יום שבת",
            entry=8 * 60,
            exit=15 * 60,
            total=6.5
        )
        report = AttendanceReport(
            report_type=ReportType.TYPE_A,
            rows=(row,),
            summary=ReportSummary(1, 6.5, 30.65, 199.23)
        )

        transformed = TransformationService(seed=42).transform(report).rows[0]

        self.assertFalse(is_work_day(row.day))
        self.assertTrue(transformed.special_day)
        self.assertIsNone(transformed.entry)
        self.assertIsNone(transformed.exit)
        self.assertIsNone(transformed.break_time)
        self.assertEqual(transformed.day, "שבת")
        self.assertEqual(transformed.total, row.total)

    def test_saturday_date_is_preserved_when_weekday_is_missing(self):
        row = AttendanceRow(
            date="15/10/2022",
            day="",
            entry=8 * 60,
            exit=15 * 60,
            total=6.5
        )
        report = AttendanceReport(
            report_type=ReportType.TYPE_A,
            rows=(row,),
            summary=ReportSummary(1, 6.5, 30.65, 199.23)
        )

        transformed = TransformationService(seed=42).transform(report).rows[0]

        self.assertFalse(is_work_day(row.day, row.date))
        self.assertTrue(transformed.special_day)
        self.assertIsNone(transformed.entry)
        self.assertIsNone(transformed.exit)
        self.assertEqual(transformed.day, "שבת")

    def test_excel_renderer_writes_rtl_report_and_summary(self):
        raw = "1.00 | 2.00 | 1.50 | 6.50 | 11.00 | 00:30 | 16:00 | 08:00 | משרד | יום ראשון | 02/10/2022"
        report = TypeAParser().parse(raw)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.xlsx")
            ExcelRenderer().render(report, path)
            workbook = load_workbook(path, read_only=False)
            worksheet = workbook["נוכחות"]

            self.assertTrue(worksheet.sheet_view.rightToLeft)
            self.assertEqual(worksheet["A1"].value, "שבת")
            self.assertEqual(
                (worksheet["A2"].value, worksheet["B2"].value, worksheet["C2"].value),
                (1.0, 2.0, 1.5)
            )
            self.assertEqual(
                (worksheet["F2"].value, worksheet["G2"].value, worksheet["H2"].value),
                ("00:30", "16:00", "08:00")
            )
            self.assertEqual(worksheet.cell(worksheet.max_row, 1).value, "סה״כ לתשלום")
            workbook.close()

    def test_pdf_shows_parsed_125_percent_hours(self):
        raw = "0.00 | 0.00 | 1.50 | 6.50 | 8.00 | 00:30 | 16:00 | 08:00 | משרד | יום ראשון | 02/10/2022"
        report = TypeAParser().parse(raw)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.pdf")
            generate_pdf(report, path)
            with pymupdf.open(path) as document:
                pdf_text = "\n".join(page.get_text() for page in document)

        self.assertIn("1.50", pdf_text)
        self.assertIn("08:00", pdf_text)

    def test_type_b_pdf_keeps_monthly_rows_and_summary_on_one_page(self):
        rows = tuple(
            AttendanceRow(
                date=f"{day}/9/22" if day <= 30 else "1/10/22",
                day="יום ראשון",
                entry=8 * 60 + 30,
                exit=12 * 60,
                total=3.5,
            )
            for day in range(1, 32)
        )
        report = AttendanceReport(
            report_type=ReportType.TYPE_B,
            rows=rows,
            summary=ReportSummary(20, 84.0, 30.65, 2574.60),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "type_b.pdf")
            generate_pdf(report, path)
            with pymupdf.open(path) as document:
                self.assertEqual(len(document), 1)
                self.assertIn("2574.60", document[0].get_text())

    def test_locked_output_uses_an_available_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            output_paths = []

            def write_pdf(report, path):
                output_paths.append(path)
                if os.path.basename(path) == "NEW_report.pdf":
                    raise PermissionError(13, "Permission denied", path)
                Path(path).write_bytes(b"pdf")
                return path

            class TestExcelRenderer:
                def render(self, report, path):
                    output_paths.append(path)
                    Path(path).write_bytes(b"xlsx")
                    return path

            with (
                patch("application.ocr.extract_text_from_pdf", return_value=self.raw_text_type_a),
                patch("application.classifier.classify_report_type", return_value=ReportType.TYPE_A),
                patch("application.pdf_generator.generate_pdf", side_effect=write_pdf),
                patch("application.excel_renderer.ExcelRenderer", TestExcelRenderer),
            ):
                self.assertTrue(process_single_pdf("report.pdf", directory))

            self.assertEqual(
                [os.path.basename(path) for path in output_paths],
                ["NEW_report.pdf", "NEW_report_1.pdf", "NEW_report_1.xlsx"]
            )
            self.assertTrue(os.path.isfile(os.path.join(directory, "NEW_report_1.pdf")))
            self.assertTrue(os.path.isfile(os.path.join(directory, "NEW_report_1.xlsx")))

    def test_transformation_recalculates_stale_summary(self):
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60,
            exit=15 * 60,
            total=7.25
        )
        stale_summary = ReportSummary(
            total_days=1,
            total_hours=6.5,
            hourly_rate=30.65,
            total_payment=199.22
        )
        report = AttendanceReport(
            report_type=ReportType.TYPE_A,
            rows=(row,),
            summary=stale_summary
        )

        transformed_report = TransformationService(seed=42).transform(report)

        transformed_row = transformed_report.rows[0]
        self.assertEqual(
            transformed_row.total,
            round((transformed_row.exit - transformed_row.entry) / 60, 2)
        )
        self.assertEqual(transformed_report.summary.total_hours, transformed_row.total)
        self.assertEqual(
            transformed_report.summary.total_payment,
            calculate_total_payment(transformed_row.total, stale_summary.hourly_rate)
        )

    def test_transformation_preserves_fallback_hours_without_rows(self):
        report = TypeAParser().parse("")

        transformed_report = TransformationService(seed=42).transform(report)

        self.assertEqual(transformed_report.summary.total_hours, report.summary.total_hours)
        self.assertEqual(
            transformed_report.summary.total_payment,
            calculate_total_payment(report.summary.total_hours, report.summary.hourly_rate)
        )


if __name__ == "__main__":
    unittest.main()