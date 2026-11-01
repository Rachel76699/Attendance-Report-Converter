import unittest
from domain.models import AttendanceRow, ReportSummary, AttendanceReport
from parsing.classifier import classify_report_type
from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser
from transformation.strategies import TransformationService


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

    def test_classifier_type_a(self):
        """בדיקת זיהוי נכון של דוח סוג A."""
        text = "נ.ע. הנשר כח אדם בע\"מ 125% שבת"
        report_type = classify_report_type(text)
        self.assertEqual(report_type, "TYPE_A")

    def test_classifier_type_b(self):
        """בדיקת זיהוי נכון של דוח סוג B (כרטיס עובד)."""
        text = "כרטיס עובד לחודש שעת כניסה שעת יציאה הערות"
        report_type = classify_report_type(text)
        self.assertEqual(report_type, "TYPE_B")

    def test_type_a_parser(self):
        """בדיקת פענוח תקינה של שורה בדוח סוג A."""
        parser = TypeAParser()
        report = parser.parse(self.raw_text_type_a)

        self.assertEqual(report.report_type, "TYPE_A")
        self.assertGreaterEqual(len(report.rows), 1)

        row = report.rows[0]
        self.assertEqual(row.date, "02/10/2022")
        self.assertEqual(row.entry, "08:00")
        self.assertEqual(row.exit, "15:00")
        self.assertEqual(row.total, 6.50)

    def test_type_b_parser(self):
        """בדיקת פענוח תקינה של שורה בדוח סוג B."""
        parser = TypeBParser()
        report = parser.parse(self.raw_text_type_b)

        self.assertEqual(report.report_type, "TYPE_B")
        self.assertGreaterEqual(len(report.rows), 1)

        row = report.rows[0]
        self.assertEqual(row.date, "1/9/22")
        self.assertEqual(row.entry, "8:30")
        self.assertEqual(row.exit, "12:00")
        self.assertEqual(row.total, 3.50)

    def test_transformation_service(self):
        """בדיקת שירות שינוי השעות (Transformation) כך ששעות משתנות ואינן נשארות עגולות לחלוטין."""
        row = AttendanceRow(
            date="02/10/2022",
            day="יום ראשון",
            entry="08:00",
            exit="15:00",
            total=6.50,
            break_time="00:30",
            location="גליליון"
        )
        summary = ReportSummary(total_days=1, total_hours=6.5, hourly_rate=30.65, total_payment=199.22)
        report = AttendanceReport(report_type="TYPE_A", rows=[row], summary=summary)

        transformer = TransformationService(seed=42)
        transformed_report = transformer.transform(report)

        t_row = transformed_report.rows[0]

        # מוודא שזמני הכניסה והיציאה עברו שינוי (היסט אקראי) ושאינם שווים בדיוק למקור העגול
        self.assertNotEqual(t_row.entry, "08:00")
        self.assertNotEqual(t_row.exit, "15:00")

        # מוודא שסיכום השעות נשאר ללא שינוי
        self.assertEqual(transformed_report.summary.total_hours, report.summary.total_hours)


if __name__ == "__main__":
    unittest.main()