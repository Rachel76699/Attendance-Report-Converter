import re
from domain.models import ReportType
from parsing.text_tools import normalize_ocr_text


def classify_report_type(raw_text: str) -> ReportType:
    """
    מזהה את סוג הדו"ח באופן מדויק על סמך טקסט ה-OCR.
    """
    text = re.sub(r"\s+", " ", normalize_ocr_text(raw_text or "")).strip().lower()
    if not text:
        return ReportType.TYPE_A

    type_b_keywords = [
        "כרטיס עובד", "כרטסת עובד", "כרטסת", "שעת כניסה",
        "שענת כניסה", "שעת יציאה", "יום בשבוע", "הערות",
        "סה\"כ שעות חודשיות", "מחיר לשעה"
    ]
    type_a_keywords = ["125%", "150%", "100%", "שבת", "גליליון"]
    type_b_score = sum(keyword in text for keyword in type_b_keywords)
    type_a_score = sum(keyword in text for keyword in type_a_keywords)

    if type_b_score and (type_b_score >= type_a_score or "כרטיס עובד" in text):
        return ReportType.TYPE_B
    if type_a_score:
        return ReportType.TYPE_A

    return ReportType.TYPE_B