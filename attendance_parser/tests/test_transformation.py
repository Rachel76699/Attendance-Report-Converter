import unittest
from contextlib import redirect_stdout
from io import StringIO
import os
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch
from openpyxl import load_workbook
import pymupdf
import pytest
from application import parse_arguments, process_single_pdf
from domain.exceptions import (
    AttendanceConverterError,
    RowParseError as DomainRowParseError,
    TransformationError,
    UnsupportedReportTypeError,
)
from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from generation import excel_renderer, output_registry, pdf_generator
from generation.excel_renderer import ExcelRenderer
from generation.pdf_generator import generate_pdf
import main as cli
from parsing import classifier, ocr, parser_factory
from parsing.base_parser import RowParseError
from parsing.classifier import classify_report_type
from parsing.text_tools import normalize_ocr_text, reconstruct_ocr_rows
from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser
from transformation.config import TransformationConfig
from transformation.strategies import (
    TransformationService,
    _validate_transformed_row,
    calculate_total_payment,
    is_work_day,
)


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

    def test_attendance_report_normalizes_input_to_its_declared_types(self):
        row = AttendanceRow("02/10/2022", "יום ראשון", 480, 900, 7.0)
        input_rows = [row]
        report = AttendanceReport(
            report_type="TYPE_A",
            rows=input_rows,
            summary=ReportSummary(1, 7.0, 30.65, 214.55),
        )

        input_rows.clear()

        self.assertIs(report.report_type, ReportType.TYPE_A)
        self.assertEqual(report.rows, (row,))
        self.assertIsInstance(report.rows, tuple)

    def test_attendance_report_rejects_an_unknown_report_type(self):
        with self.assertRaises(ValueError):
            AttendanceReport(
                report_type="TYPE_C",
                rows=(),
                summary=ReportSummary(0, 0.0, 30.65, 0.0),
            )

    def test_domain_errors_share_the_expected_base_exception(self):
        for error_type in (
            DomainRowParseError,
            UnsupportedReportTypeError,
            TransformationError,
        ):
            with self.subTest(error_type=error_type):
                self.assertTrue(issubclass(error_type, AttendanceConverterError))

    def test_parser_factory_raises_a_typed_error_for_unknown_report_types(self):
        from parsing.parser_factory import get_parser

        with self.assertRaises(UnsupportedReportTypeError):
            get_parser("TYPE_C")

    def test_transformation_rejects_rows_that_violate_each_invariant(self):
        invalid_rows = (
            AttendanceRow("02/10/2022", "יום ראשון", 1440, 900, 7.0),
            AttendanceRow("02/10/2022", "יום ראשון", 900, 480, 7.0),
            AttendanceRow("02/10/2022", "יום ראשון", 480, 900, -1.0),
            AttendanceRow(
                "02/10/2022",
                "יום ראשון",
                480,
                900,
                7.0,
                p100=6.0,
            ),
        )

        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(TransformationError):
                _validate_transformed_row(row, TransformationConfig())

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

    def test_classifier_recognizes_type_b_when_ocr_corrupts_the_headers(self):
        raw_text = "\n".join([
            ":-nwnVbeJ",
            "21 | u-nn'7 | n-rny | �nt",
            "3.00 | 11:03 | 8:03 | 2/1/23",
            "2.88 | 10:57 | 8:04 | 3/1/23",
            "2.97 | 10:59 | 8:01 | 4/1/23",
        ])

        self.assertIs(classify_report_type(raw_text), ReportType.TYPE_B)
        self.assertEqual(len(TypeBParser().parse(raw_text).rows), 3)

    def test_classifier_does_not_guess_when_report_type_is_unknown(self):
        self.assertIsNone(classify_report_type(""))
        self.assertIsNone(classify_report_type("123"))
        self.assertIsNone(classify_report_type("This is an unrelated document"))

    def test_each_report_type_has_all_required_registered_components(self):
        report_types = set(ReportType)

        self.assertEqual(set(classifier.CLASSIFIER_SCORERS), report_types)
        self.assertEqual(set(parser_factory.PARSER_FACTORIES), report_types)
        self.assertEqual(set(TransformationService().strategies), report_types)
        self.assertEqual(
            set(TransformationConfig().summary_policies),
            report_types,
        )
        self.assertEqual(set(excel_renderer.EXCEL_LAYOUTS), report_types)
        self.assertEqual(set(pdf_generator.PDF_LAYOUTS), report_types)

    def test_unrecognized_file_reports_error_without_generating_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with (
                patch("application.ocr.extract_text_from_pdf", return_value="123"),
                patch("application.parser_factory.get_parser") as get_parser,
                redirect_stdout(output),
            ):
                result = process_single_pdf("123.pdf", directory)

            self.assertFalse(result)
            self.assertIn("not recognized as an attendance report", output.getvalue())
            self.assertIn("No output was generated", output.getvalue())
            get_parser.assert_not_called()
            self.assertEqual(os.listdir(directory), [])

    def test_process_single_pdf_uses_injected_processing_dependencies(self):
        report = TypeAParser().parse(self.raw_text_type_a)
        transformer = Mock()
        transformer.transform.return_value = report
        pdf_renderer = Mock(return_value="report.pdf")
        excel_report_renderer = Mock()
        excel_report_renderer.render.return_value = "report.xlsx"

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("application.ocr.extract_text_from_pdf", return_value=self.raw_text_type_a),
                patch("application.classifier.classify_report_type", return_value=ReportType.TYPE_A),
            ):
                result = process_single_pdf(
                    "report.pdf",
                    directory,
                    transformation_service=transformer,
                    pdf_renderer=pdf_renderer,
                    excel_report_renderer=excel_report_renderer,
                )

        self.assertTrue(result)
        transformer.transform.assert_called_once()
        pdf_renderer.assert_called_once()
        excel_report_renderer.render.assert_called_once()

    def test_processing_error_is_reported_without_traceback(self):
        output = StringIO()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "application.ocr.extract_text_from_pdf",
                side_effect=RuntimeError("OCR backend unavailable"),
            ),
            redirect_stdout(output),
        ):
            result = process_single_pdf("report.pdf", directory)

        self.assertFalse(result)
        self.assertIn("report.pdf", output.getvalue())
        self.assertIn("OCR backend unavailable", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_cli_accepts_force_ocr_and_custom_output_directory(self):
        with patch(
            "sys.argv",
            ["main.py", "reports", "--output", "results", "--force-ocr"],
        ):
            args = parse_arguments()

        self.assertEqual(args.input, "reports")
        self.assertEqual(args.output, "results")
        self.assertTrue(args.force_ocr)

    def test_main_wires_one_shared_transformation_service(self):
        args = SimpleNamespace(
            input="reports",
            output="results",
            force_ocr=True,
        )
        with (
            patch.object(cli, "parse_arguments", return_value=args),
            patch.object(cli, "prepare_paths", return_value=("reports", "results")),
            patch.object(cli, "collect_pdf_files", return_value=["one.pdf", "two.pdf"]),
            patch.object(cli, "TransformationService") as service_factory,
            patch.object(cli, "process_single_pdf", side_effect=[True, True]) as process,
            patch.object(cli, "print_summary"),
        ):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(service_factory.call_count, 1)
        self.assertEqual(service_factory.call_count, 1)
        self.assertEqual(process.call_count, 2)
        for call in process.call_args_list:
            self.assertTrue(call.kwargs["force_ocr"])
            self.assertIs(
                call.kwargs["transformation_service"],
                service_factory.return_value,
            )

    def test_output_format_can_be_registered_in_generation_without_application_changes(self):
        rendered_paths = []

        class CSVRenderer:
            def render(self, report, output_path):
                rendered_paths.append(output_path)
                Path(output_path).write_text(
                    report.report_type.value,
                    encoding="utf-8",
                )
                return output_path

        report = TypeAParser().parse(self.raw_text_type_a)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                output_registry,
                "OUTPUT_RENDERER_FACTORIES",
                MappingProxyType({".csv": CSVRenderer}),
            ):
                paths = output_registry.render_outputs(
                    report,
                    directory,
                    "NEW_report",
                )
            self.assertEqual(paths, (os.path.join(directory, "NEW_report.csv"),))
            self.assertEqual(rendered_paths, list(paths))
            self.assertTrue(os.path.isfile(paths[0]))
            self.assertEqual(
                Path(paths[0]).read_text(encoding="utf-8"),
                ReportType.TYPE_A.value,
            )


    def test_file_with_only_a_generic_keyword_is_rejected_without_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with (
                patch("application.ocr.extract_text_from_pdf", return_value="שבת"),
                redirect_stdout(output),
            ):
                result = process_single_pdf("document.pdf", directory)

            self.assertFalse(result)
            self.assertIn("No attendance rows were found", output.getvalue())
            self.assertIn("No output was generated", output.getvalue())
            self.assertEqual(os.listdir(directory), [])

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

    def test_force_ocr_bypasses_cache_and_refreshes_cached_text(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = os.path.join(directory, "report.pdf")
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "Digital report")
            document.save(pdf_path)
            document.close()
            cache_dir = Path(directory) / "text_cache"

            with (
                patch.object(ocr, "TEXT_CACHE_DIR", cache_dir),
                patch.object(ocr, "_ocr_language_signature", return_value="en-US"),
                patch.object(
                    ocr,
                    "_extract_text_without_cache",
                    side_effect=["Cached text", "Fresh OCR text"],
                ) as extract,
            ):
                self.assertEqual(ocr.extract_text_from_pdf(pdf_path), "Cached text")
                self.assertEqual(
                    ocr.extract_text_from_pdf(pdf_path, force_ocr=True),
                    "Fresh OCR text",
                )
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

    def test_type_a_parser_reports_invalid_numeric_values_instead_of_using_zero(self):
        raw_text = (
            "not-a-number | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | "
            "08:00 | office | יום ראשון | 02/10/2022"
        )

        with self.assertRaisesRegex(RowParseError, "Invalid Shabbat hours"):
            TypeAParser().parse(raw_text)

    def test_invalid_row_is_reported_without_creating_output_files(self):
        raw_text = (
            "not-a-number | 0 | 0 | 6.50 | 6.50 | 00:30 | 15:00 | "
            "08:00 | office | יום ראשון | 02/10/2022"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = StringIO()
            with (
                patch("application.ocr.extract_text_from_pdf", return_value=raw_text),
                patch(
                    "application.classifier.classify_report_type",
                    return_value=ReportType.TYPE_A,
                ),
                redirect_stdout(output),
            ):
                result = process_single_pdf("report.pdf", directory)

            self.assertFalse(result)
            self.assertIn("Invalid Shabbat hours", output.getvalue())
            self.assertEqual(os.listdir(directory), [])

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

        self.assertIsInstance(report, AttendanceReport)
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

    def test_type_b_parser_uses_time_column_order_not_earliest_and_latest(self):
        report = TypeBParser().parse("3.50 | 08:30 | 12:00 | 1/9/22")

        self.assertEqual(report.rows[0].exit, 8 * 60 + 30)
        self.assertEqual(report.rows[0].entry, 12 * 60)

    def test_type_b_parser_reports_invalid_total_instead_of_using_zero(self):
        with self.assertRaisesRegex(RowParseError, "Missing or invalid total hours"):
            TypeBParser().parse("invalid | 12:00 | 8:30 | 1/9/22")

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

    def test_transformation_service_uses_injected_strategy_mapping(self):
        report = TypeAParser().parse(self.raw_text_type_a)
        strategy = Mock()
        strategy.transform.return_value = report
        service = TransformationService(
            strategies={ReportType.TYPE_A: strategy}
        )

        self.assertIs(service.transform(report), report)
        strategy.transform.assert_called_once_with(
            report, service.seed, service.config
        )

    def test_transform_is_deterministic_and_does_not_mutate_the_original_report(self):
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60,
            exit=15 * 60,
            total=6.5,
            break_time=30,
            p100=6.5,
            p125=0.0,
            p150=0.0,
            shabbat=0.0,
        )
        report = AttendanceReport(
            ReportType.TYPE_A,
            (row,),
            ReportSummary(1, 6.5, 30.65, 199.23),
        )
        service = TransformationService(seed=321)

        first = service.transform(report)
        repeated = service.transform(report)
        independent = TransformationService(seed=321).transform(report)

        self.assertEqual(first, repeated)
        self.assertEqual(first, independent)
        self.assertIsNot(first, report)
        self.assertEqual(report.rows, (row,))
        self.assertEqual(report.summary.total_hours, 6.5)

    def test_transformed_type_a_breakdown_and_summary_match_recalculated_hours(self):
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60,
            exit=16 * 60,
            total=11.0,
            break_time=30,
            shabbat=1.0,
            p150=2.0,
            p125=1.5,
            p100=6.5,
        )
        report = AttendanceReport(
            ReportType.TYPE_A,
            (row,),
            ReportSummary(1, 11.0, 30.65, 337.15),
        )

        transformed = TransformationService(seed=42).transform(report)
        transformed_row = transformed.rows[0]
        component_hours = sum(
            value or 0.0
            for value in (
                transformed_row.shabbat,
                transformed_row.p150,
                transformed_row.p125,
                transformed_row.p100,
            )
        )

        self.assertEqual(round(component_hours, 2), transformed_row.total)
        self.assertEqual(transformed.summary.total_hours, transformed_row.total)
        self.assertEqual(
            transformed.summary.total_payment,
            calculate_total_payment(
                transformed.summary.total_hours,
                transformed.summary.hourly_rate,
            ),
        )
        self.assertEqual(row.total, 11.0)
        self.assertEqual((row.shabbat, row.p150, row.p125, row.p100), (1.0, 2.0, 1.5, 6.5))

    def test_time_shift_bounds_come_from_transformation_config(self):
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry=8 * 60,
            exit=15 * 60,
            total=7.0,
        )
        report = AttendanceReport(
            ReportType.TYPE_B,
            (row,),
            ReportSummary(1, 7.0, 30.65, 214.55),
        )
        config = TransformationConfig(
            minimum_shift_minutes=-2,
            maximum_shift_minutes=3,
        )

        transformed_row = TransformationService(seed=42, config=config).transform(
            report
        ).rows[0]

        self.assertTrue(-2 <= transformed_row.entry - row.entry <= 3)
        self.assertTrue(-2 <= transformed_row.exit - row.exit <= 3)
        self.assertNotEqual(transformed_row.entry, row.entry)
        self.assertNotEqual(transformed_row.exit, row.exit)
        self.assertGreater(transformed_row.exit, transformed_row.entry)

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

    def test_sabbath_and_holiday_rows_remain_without_times_after_transformation(self):
        row = AttendanceRow(
            date="05/10/22",
            day="יום כיפור",
            entry=8 * 60,
            exit=12 * 60,
            total=3.5,
        )
        report = AttendanceReport(
            ReportType.TYPE_B,
            (row,),
            ReportSummary(1, 3.5, 30.65, 107.28),
        )

        transformed = TransformationService(seed=42).transform(report)
        transformed_row = transformed.rows[0]

        self.assertTrue(transformed_row.special_day)
        self.assertIsNone(transformed_row.entry)
        self.assertIsNone(transformed_row.exit)
        self.assertEqual(transformed_row.total, row.total)

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

            def write_pdf(report: AttendanceReport, path: str) -> str:
                output_paths.append(path)
                if os.path.basename(path) == "NEW_report.pdf":
                    raise PermissionError(13, "Permission denied", path)
                Path(path).write_bytes(b"pdf")
                return path

            class TestPDFRenderer:
                def render(self, report: AttendanceReport, path: str) -> str:
                    return write_pdf(report, path)

            class TestExcelRenderer:
                def render(self, report: AttendanceReport, path: str) -> str:
                    output_paths.append(path)
                    Path(path).write_bytes(b"xlsx")
                    return path

            with (
                patch("application.ocr.extract_text_from_pdf", return_value=self.raw_text_type_a),
                patch("application.classifier.classify_report_type", return_value=ReportType.TYPE_A),
                patch.object(
                    output_registry,
                    "OUTPUT_RENDERER_FACTORIES",
                    MappingProxyType({
                        ".pdf": TestPDFRenderer,
                        ".xlsx": TestExcelRenderer,
                    }),
                ),
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