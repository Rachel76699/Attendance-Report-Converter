
from abc import ABC, abstractmethod
from datetime import datetime

from domain.models import AttendanceRow, AttendanceReport, ReportSummary


class BaseParser(ABC):

    def __init__(self, report_type: str):
        self.report_type = report_type

    def parse(self, raw_text: str) -> AttendanceReport:
        lines = raw_text.splitlines()
        rows = []

        for line in lines:
            if not line.strip() or self._is_header_line(line):
                continue

            row = self._parse_row(line)
            if row is not None:
                rows.append(row)

        summary = self._parse_summary(rows)

        return AttendanceReport(
            report_type=self.report_type,
            rows=rows,
            summary=summary
        )

    @abstractmethod
    def _is_header_line(self, line: str) -> bool:
        pass

    @abstractmethod
    def _parse_row(self, line: str) -> AttendanceRow | None:
        pass

    def _parse_time(self, value: str):
        return datetime.strptime(value, "%H:%M").time()

    def _parse_summary(self, rows: list[AttendanceRow]) -> ReportSummary:
        total_days = len(rows)
        total_hours = round(sum(row.total for row in rows), 2)
        hourly_rate = 30.65

        return ReportSummary(
            total_days=total_days,
            total_hours=total_hours,
            hourly_rate=hourly_rate,
            total_payment=round(total_hours * hourly_rate, 2)
        )
