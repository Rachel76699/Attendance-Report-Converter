import re
from datetime import datetime


_HOLIDAY_MARKERS = (
    "חג",
    "ראש השנה",
    "כיפור",
    "סוכות",
    "שמיני עצרת",
    "שמחת תורה",
    "פסח",
    "שביעי של פסח",
    "שבועות",
    "יום טוב",
    "holiday",
)


def is_sabbath_or_holiday(day: str, date: str) -> bool:
    normalized_day = day.strip().replace('"', "").replace("׳", "").replace("'", "").lower()
    if "שבת" in normalized_day or normalized_day in {"saturday", "sat", "sat."}:
        return True
    if any(marker in normalized_day for marker in _HOLIDAY_MARKERS):
        return True
    for date_format in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date.strip(), date_format).weekday() == 5
        except ValueError:
            continue
    return False


def special_day_label(day: str, special_day: bool) -> str:
    if not special_day:
        return day
    if any(marker in day.lower() for marker in _HOLIDAY_MARKERS):
        return day
    return "שבת"


def parse_clock_minutes(value: str) -> int | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        return None
    hours, minutes = map(int, match.groups())
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def parse_duration_minutes(value: str) -> int | None:
    match = re.fullmatch(r"(\d+):(\d{2})", value.strip())
    if not match:
        return None
    hours, minutes = map(int, match.groups())
    if minutes > 59:
        return None
    return hours * 60 + minutes


def format_clock_minutes(value: int | None) -> str:
    if value is None:
        return ""
    hours, minutes = divmod(value, 60)
    return f"{hours % 24:02d}:{minutes:02d}"


def format_duration_minutes(value: int | None) -> str:
    if value is None:
        return ""
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}"
