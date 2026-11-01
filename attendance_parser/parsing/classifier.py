def classify_report_type(raw_text: str) -> str:
    """
    מזהה את סוג הדו"ח באופן מדויק על סמך טקסט ה-OCR.
    """
    if not raw_text:
        return "TYPE_A"

    type_b_keywords = ["כרטיס עובד", "כרטסת עובד", "שעת כניסה", "שענת כניסה", "שעת יציאה", "יום בשבוע", "הערות"]
    if any(kw in raw_text for kw in type_b_keywords):
        return "TYPE_B"

    type_a_keywords = ["125%", "150%", "שבת", "גליליון"]
    if any(kw in raw_text for kw in type_a_keywords):
        return "TYPE_A"

    return "TYPE_B"