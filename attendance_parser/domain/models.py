from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class AttendanceRow:
    """Represents a single attendance record row."""
    date: str
    day: str
    entry: str
    exit: str
    total: float
    break_time: str = "00:30"
    location: str = ""


@dataclass(frozen=True)
class ReportSummary:
    """Represents summary totals and payment details."""
    total_days: int
    total_hours: float
    hourly_rate: float
    total_payment: float


@dataclass(frozen=True)
class AttendanceReport:
    """Represents the full attendance report."""
    report_type: str
    rows: List[AttendanceRow]
    summary: ReportSummary