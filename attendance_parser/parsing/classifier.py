import re
from domain.models import ReportType
from parsing.text_tools import normalize_ocr_text


_TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def classify_report_type(raw_text: str) -> ReportType | None:
    """
    מזהה את סוג הדו"ח באופן מדויק על סמך טקסט ה-OCR.
    """
    normalized_text = normalize_ocr_text(raw_text or "").lower()
    text = re.sub(r"\s+", " ", normalized_text).strip()
    if not text:
        return None

    type_b_keywords = [
        "כרטיס עובד", "כרטסת עובד", "כרטסת", "שעת כניסה",
        "שענת כניסה", "שעת יציאה", "יום בשבוע", "הערות",
        "סה\"כ שעות חודשיות", "מחיר לשעה"
    ]
    type_a_keywords = ["125%", "150%", "100%", "שבת", "גליליון"]
    type_b_score = sum(keyword in text for keyword in type_b_keywords)
    type_a_score = sum(keyword in text for keyword in type_a_keywords)
    type_b_rows = 0
    for line in normalized_text.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if (
            3 <= len(parts) - 1 <= 5
            and _NUMBER_PATTERN.fullmatch(parts[0]) is not None
            and len(_TIME_PATTERN.findall(line)) == 2
        ):
            type_b_rows += 1

    if type_b_rows >= 3:
        return ReportType.TYPE_B
    if type_b_score and (type_b_score >= type_a_score or "כרטיס עובד" in text):
        return ReportType.TYPE_B
    if type_a_score:
        return ReportType.TYPE_A

    return None