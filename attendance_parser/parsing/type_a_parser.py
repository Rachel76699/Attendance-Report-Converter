import re
from datetime import datetime, timedelta

from domain.models import AttendanceReport, AttendanceRow, ReportType
from domain.time_utils import (
    is_sabbath_or_holiday,
    parse_clock_minutes,
    parse_duration_minutes,
    special_day_label,
)
from parsing.base_parser import BaseParser
from parsing.text_tools import normalize_ocr_text
from transformation.strategies import build_summary


_DATE_PATTERN = re.compile(r"(?<!\d)(\d{2}/\d{2}/\d{4})(?!\d)")
_SPLIT_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*\|\s*/(\d{2}/\d{4})(?!\d)")
_CLOCK_PATTERN = re.compile(r"\d{1,2}:\d{2}")
_WEEKDAY_NAMES = (
    "יום שני", "יום שלישי", "יום רביעי", "יום חמישי",
    "יום שישי", "שבת", "יום ראשון",
)
_HOLIDAY_MARKERS = (
    "חג", "ראש השנה", "כיפור", "סוכות", "שמיני עצרת", "שמחת תורה",
    "פסח", "שביעי של פסח", "שבועות", "יום טוב", "holiday",
)


class TypeAParser(BaseParser):
    """
    פרסר לפענוח דוחות נוכחות מסוג A.
    """

    def __init__(self):
        super().__init__(report_type=ReportType.TYPE_A)

    def _is_header_line(self, line: str) -> bool:
        """בודק האם השורה היא שורת כותרת."""
        return any(h in line for h in ["תאריך", "יום", "כניסה", "סה", "ריראת", "סוי"])

    def _parse_row(self, line: str) -> AttendanceRow:
        """מפענח שורת נתונים בודדת מטקסט הדוח."""
        parts = [part.strip() for part in line.strip().strip("|").split("|")]

        def parse_number(value: str, fallback: float = 0.0) -> float:
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return fallback

        date_match = _DATE_PATTERN.search(line)
        date_val = date_match.group(1) if date_match else ""
        date_index = next(
            (index for index in range(len(parts) - 1, -1, -1) if _DATE_PATTERN.search(parts[index])),
            len(parts),
        )
        data_parts = parts[:date_index]
        if len(data_parts) < 8:
            data_parts = ([""] * (8 - len(data_parts))) + data_parts

        shabbat, p150, p125, p100, total, break_val, exit_val, entry_val = data_parts[:8]
        trailing_fields = data_parts[8:]
        location_val = trailing_fields[-2] if len(trailing_fields) >= 2 else ""
        if not any("\u0590" <= character <= "\u05ff" for character in location_val):
            location_val = ""

        def normalize_clock(value: str) -> str:
            value = value.strip().replace("•", ":").replace(".", ":")
            if re.fullmatch(r"\d{4}", value):
                value = f"{value[:2]}:{value[2:]}"
            return value

        entry_val = normalize_clock(entry_val)
        exit_val = normalize_clock(exit_val)
        day_val = (
            _WEEKDAY_NAMES[datetime.strptime(date_val, "%d/%m/%Y").weekday()]
            if date_val else ""
        )
        total_val = parse_number(total)
        shabbat_val = parse_number(shabbat)
        reported_day = trailing_fields[-1] if trailing_fields else ""
        if any(marker in reported_day.lower() for marker in _HOLIDAY_MARKERS):
            day_val = reported_day
        special_day = is_sabbath_or_holiday(day_val, date_val)

        return AttendanceRow(
            date=date_val,
            day=special_day_label(day_val, special_day),
            entry=None if special_day else parse_clock_minutes(entry_val),
            exit=None if special_day else parse_clock_minutes(exit_val),
            total=total_val,
            break_time=None if special_day else parse_duration_minutes(break_val),
            location=location_val,
            shabbat=shabbat_val,
            p150=parse_number(p150),
            p125=parse_number(p125),
            p100=parse_number(p100),
            special_day=special_day,
        )

    def parse(self, raw_text: str) -> AttendanceReport:
        """מתודת פענוח ראשית לדוח מסוג A."""
        lines = [
            _SPLIT_DATE_PATTERN.sub(r"\1/\2", line)
            for line in normalize_ocr_text(raw_text).splitlines()
        ]
        row_lines = []

        for line in lines:
            has_date = _DATE_PATTERN.search(line) is not None
            has_daily_times = len(_CLOCK_PATTERN.findall(line)) >= 2
            if has_date or has_daily_times:
                row_lines.append(line)

        dates = []
        for line in row_lines:
            date_match = _DATE_PATTERN.search(line)
            dates.append(date_match.group(1) if date_match else None)

        index = 0
        while index < len(dates):
            if dates[index] is not None:
                index += 1
                continue
            first_missing = index
            while index < len(dates) and dates[index] is None:
                index += 1
            previous_date = dates[first_missing - 1] if first_missing > 0 else None
            next_date = dates[index] if index < len(dates) else None
            if previous_date is None or next_date is None:
                continue
            previous = datetime.strptime(previous_date, "%d/%m/%Y")
            following = datetime.strptime(next_date, "%d/%m/%Y")
            missing_count = index - first_missing
            if (following - previous).days == missing_count + 1:
                for offset in range(missing_count):
                    inferred_date = previous + timedelta(days=offset + 1)
                    dates[first_missing + offset] = inferred_date.strftime("%d/%m/%Y")

        rows = []
        for line, date_val in zip(row_lines, dates):
            row_line = line
            if date_val and not _DATE_PATTERN.search(line):
                row_line = f"{line} | {date_val}"
            row = self._parse_row(row_line)
            if date_val and not row.date:
                row = AttendanceRow(
                    date=date_val,
                    day=_WEEKDAY_NAMES[datetime.strptime(date_val, "%d/%m/%Y").weekday()],
                    entry=row.entry,
                    exit=row.exit,
                    total=row.total,
                    break_time=row.break_time,
                    location=row.location,
                    shabbat=row.shabbat,
                    p150=row.p150,
                    p125=row.p125,
                    p100=row.p100,
                    special_day=row.special_day,
                )
            rows.append(row)

        summary = build_summary(rows, report_type=self.report_type)

        return AttendanceReport(report_type=ReportType.TYPE_A, rows=tuple(rows), summary=summary)