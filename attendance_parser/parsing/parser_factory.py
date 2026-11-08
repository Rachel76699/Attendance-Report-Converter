from domain.models import ReportType
from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser


def get_parser(report_type: ReportType):  # פונקציית Factory המחזירה Parser מתאים לסוג הדוח
    """
    Factory function to return the appropriate parser instance
    based on the given report type.
    """
    # בדיקה האם סוג הדוח הוא TYPE_A והחזרת המפענח המתאים
    if report_type == ReportType.TYPE_A:
        return TypeAParser()
    if report_type == ReportType.TYPE_B:
        return TypeBParser()
    # זריקת שגיאה במקרה שסוג הדוח שהתקבל אינו מוכר
    raise ValueError(f"Unknown report type: {report_type}")