import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta

from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from domain.time_utils import is_sabbath_or_holiday, parse_clock_minutes, special_day_label
from parsing.base_parser import BaseParser
from parsing.text_tools import normalize_ocr_text
from transformation.strategies import build_summary


_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{2,4})(?!\d)")
_TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_WEEKDAY_NAMES = (
    "יום שני", "יום שלישי", "יום רביעי", "יום חמישי",
    "יום שישי", "שבת", "יום ראשון",
)
_HOLIDAY_MARKERS = (
    "חג", "ראש השנה", "כיפור", "סוכות", "שמיני עצרת", "שמחת תורה",
    "פסח", "שביעי של פסח", "שבועות", "יום טוב", "holiday",
)
_SUMMARY_NUMBER_PATTERN = re.compile(r"(?<![\d:])\d[\d,]*\.\d{2}(?!\d)")


class TypeBParser(BaseParser):
    """
    פרסר לפענוח דוחות נוכחות מסוג B (כרטיס עובד) בדיוק לפי מבנה העמודות.
    """

    def __init__(self):
        super().__init__(report_type=ReportType.TYPE_B)

    def _is_header_line(self, line: str) -> bool:
        """בודק האם השורה היא שורת כותרת."""
        if re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', line):
            return False
        return any(h in line for h in ["תאריך", "יום", "כניסה", "יציאה", "סה\"כ", "כרטיס עובד", "הערות", "שענת", "שעות"])

    def _parse_row(self, line: str, date_value: str) -> AttendanceRow:
        """Parse a row by its cell types so OCR-split dates do not shift columns."""
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        time_values = [part for part in parts if _TIME_PATTERN.fullmatch(part)]
        time_indices = [index for index, part in enumerate(parts) if _TIME_PATTERN.fullmatch(part)]
        first_time_index = min(time_indices, default=len(parts))
        total_match = next(
            (
                _NUMBER_PATTERN.fullmatch(part)
                for part in parts[:first_time_index]
                if _NUMBER_PATTERN.fullmatch(part)
                and (time_values or "." in part or "," in part)
            ),
            None,
        )
        total_val = float(total_match.group().replace(",", ".")) if total_match else 0.0
        exit_val = time_values[0] if time_values else ""
        entry_val = time_values[1] if len(time_values) > 1 else ""

        explicit_holiday = next(
            (
                part for part in parts
                if "ערב" not in part
                and any(marker in part.lower() for marker in _HOLIDAY_MARKERS)
            ),
            "",
        )
        parsed_date = datetime.strptime(date_value, "%d/%m/%y").date()
        day_val = explicit_holiday or _WEEKDAY_NAMES[parsed_date.weekday()]
        special_day = is_sabbath_or_holiday(day_val, date_value)
        if special_day and not time_values:
            total_val = 0.0

        total_index = next(
            (
                index for index, part in enumerate(parts[:first_time_index])
                if _NUMBER_PATTERN.fullmatch(part)
            ),
            len(parts),
        )
        notes_val = " ".join(
            part for part in parts[:total_index]
            if any("\u0590" <= character <= "\u05ff" for character in part)
            and part != explicit_holiday
        )
        return AttendanceRow(
            date=date_value,
            day=special_day_label(day_val, special_day),
            entry=None if special_day else parse_clock_minutes(entry_val),
            exit=None if special_day else parse_clock_minutes(exit_val),
            total=total_val,
            location=notes_val,
            special_day=special_day,
        )

    @staticmethod
    def _date_context(lines: list[str]) -> tuple[int, int] | None:
        month_year_counts: Counter[tuple[int, int]] = Counter()
        for line in lines:
            for match in _DATE_PATTERN.finditer(line):
                day, month, year = map(int, match.groups())
                if 1 <= month <= 12 and 1 <= day <= 31:
                    full_year = year + (2000 if year < 100 else 0)
                    month_year_counts[(full_year, month)] += 1
        if not month_year_counts:
            return None
        year, month = month_year_counts.most_common(1)[0][0]
        return year, month

    @staticmethod
    def _date_from_line(line: str) -> date | None:
        for match in _DATE_PATTERN.finditer(line):
            day, month, year = map(int, match.groups())
            year += 2000 if year < 100 else 0
            try:
                return date(year, month, day)
            except ValueError:
                continue
        return None

    @staticmethod
    def _repair_isolated_entry_hour(rows: list[AttendanceRow]) -> list[AttendanceRow]:
        entry_rows = [row for row in rows if row.entry is not None]
        if len(entry_rows) < 8:
            return rows

        hour_counts = Counter(row.entry // 60 for row in entry_rows)
        common_hour, common_count = hour_counts.most_common(1)[0]
        outliers = [row for row in entry_rows if row.entry // 60 != common_hour]
        if (
            len(outliers) != 1
            or common_count / len(entry_rows) < 0.8
            or abs(outliers[0].entry // 60 - common_hour) < 3
        ):
            return rows

        outlier = outliers[0]
        corrected_entry = common_hour * 60 + outlier.entry % 60
        return [
            replace(row, entry=corrected_entry) if row is outlier else row
            for row in rows
        ]

    def parse(self, raw_text: str) -> AttendanceReport:
        """Parse each daily row, recovering OCR-damaged dates from the monthly sequence."""
        lines = normalize_ocr_text(raw_text).splitlines()
        first_row_index = next(
            (
                index for index, line in enumerate(lines)
                if _DATE_PATTERN.search(line)
                or ("|" in line and _TIME_PATTERN.search(line))
            ),
            None,
        )
        row_lines = []
        if first_row_index is not None:
            row_lines = [
                line for line in lines[first_row_index:]
                if line.strip() and (re.search(r"\d", line) or "|" in line)
            ]

        date_context = self._date_context(lines)
        start_date = self._date_from_line(row_lines[0]) if row_lines else None
        if start_date is None and date_context is not None:
            year, month = date_context
            start_date = date(year, month, 1)

        rows = []
        if start_date is not None:
            for index, line in enumerate(row_lines):
                current_date = start_date + timedelta(days=index)
                date_value = f"{current_date.day}/{current_date.month}/{current_date.year % 100:02d}"
                rows.append(self._parse_row(line, date_value))
        rows = self._repair_isolated_entry_hour(rows)

        summary_days = None
        summary_numbers = []
        if first_row_index is not None:
            for line in lines[:first_row_index]:
                day_match = re.match(r"\s*(\d{1,3})\s*\|", line)
                if day_match and summary_days is None:
                    summary_days = int(day_match.group(1))
                summary_numbers.extend(_SUMMARY_NUMBER_PATTERN.findall(line))
        summary = build_summary(rows, report_type=self.report_type)
        if len(summary_numbers) >= 3:
            summary = ReportSummary(
                total_days=summary_days if summary_days is not None else summary.total_days,
                total_hours=float(summary_numbers[-3].replace(",", "")),
                hourly_rate=float(summary_numbers[-2].replace(",", "")),
                total_payment=float(summary_numbers[-1].replace(",", "")),
            )
        elif summary_days is not None:
            summary = replace(summary, total_days=summary_days)

        return AttendanceReport(report_type=ReportType.TYPE_B, rows=tuple(rows), summary=summary)