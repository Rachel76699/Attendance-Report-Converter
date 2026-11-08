from dataclasses import dataclass
from enum import Enum


class ReportType(str, Enum):
    TYPE_A = "TYPE_A"
    TYPE_B = "TYPE_B"


@dataclass(frozen=True)
class AttendanceRow:
    """Shared row model; Type B has no break or overtime fields, so those stay None."""
    date: str
    day: str
    entry: int | None
    exit: int | None
    total: float
    break_time: int | None = None
    location: str = ""
    shabbat: float | None = None
    p150: float | None = None
    p125: float | None = None
    p100: float | None = None
    special_day: bool = False


@dataclass(frozen=True)
class ReportSummary:
    """Represents summary totals and payment details."""
    total_days: int
    total_hours: float
    hourly_rate: float
    total_payment: float


@dataclass(frozen=True)
class AttendanceReport:
    """Canonical report shared by parsers, transformations, and renderers."""
    report_type: ReportType
    rows: tuple[AttendanceRow, ...]
    summary: ReportSummary

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_type", ReportType(self.report_type))
        object.__setattr__(self, "rows", tuple(self.rows))