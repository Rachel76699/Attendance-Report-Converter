from abc import ABC, abstractmethod
from datetime import datetime

from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from transformation.strategies import build_summary


class BaseParser(ABC):  # מחלקה אבסטרקטיבית בסיסית המגדירה תבנית אחידה (Template Method) לפענוח דוחות נוכחות

    def __init__(self, report_type: ReportType):
        self.report_type = report_type

    def parse(self, raw_text: str) -> AttendanceReport:  # מתודת הניהול הראשית המנהלת את תהליך פיצול הטקסט, הסינון ובניית הדוח
        lines = raw_text.splitlines()
        rows = []

        for line in lines:
            # דילוג על שורות ריקות או שורות כותרת של הדוח
            if not line.strip() or self._is_header_line(line):
                continue

            row = self._parse_row(line)
            if row is not None:
                rows.append(row)

        summary = self._parse_summary(rows)

        return AttendanceReport(
            report_type=self.report_type,
            rows=tuple(rows),
            summary=summary
        )

    @abstractmethod
    def _is_header_line(self, line: str) -> bool:  # מתודה אבסטרקטיבית לזיהוי שורות כותרת – חובה לממש במחלקות היורשות
        pass

    @abstractmethod
    def _parse_row(self, line: str) -> AttendanceRow | None:  # מתודה אבסטרקטיבית לפענוח שורת נתונים פרטנית – חובה לממש ביורשות
        pass

    def _parse_time(self, value: str):  # מתודת עזר להמרת מחרוזת שעה (לדוגמה "08:30") לאובייקט זמן תקני
        return datetime.strptime(value, "%H:%M").time()

    def _parse_summary(self, rows: list[AttendanceRow]) -> ReportSummary:  # מתודה לחישוב אוטומטי של סיכום השעות, ימי העבודה והתשלום הכולל
        return build_summary(
            rows,
            report_type=self.report_type
        )