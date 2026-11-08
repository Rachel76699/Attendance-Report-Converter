import random
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from domain.time_utils import is_sabbath_or_holiday, special_day_label


HOURLY_RATE = 30.65
ENTRY_SHIFT_MINUTES = (-5, 10)


def calculate_total_payment(total_hours: float, hourly_rate: float) -> float:
    amount = Decimal(str(total_hours)) * Decimal(str(hourly_rate))
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_work_day(day: str, date: str = "") -> bool:
    normalized_day = day.strip().replace('"', "").replace("׳", "").replace("'", "").lower()
    if "שבת" in normalized_day or normalized_day in {"saturday", "sat", "sat."}:
        return False
    working_day_names = (
        "ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי",
        "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"
    )
    if any(name in normalized_day for name in working_day_names):
        return True

    for date_format in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date.strip(), date_format).weekday() != 5
        except ValueError:
            continue
    return False


def build_summary(
    rows: list[AttendanceRow],
    report_type: ReportType,
    fallback_days: int | None = None,
    fallback_hours: float | None = None,
    hourly_rate: float = HOURLY_RATE,
) -> ReportSummary:
    defaults = {
        ReportType.TYPE_A: (22, 143.0),
        ReportType.TYPE_B: (20, 84.0)
    }
    default_days, default_hours = defaults.get(report_type, (0, 0.0))
    fallback_days = default_days if fallback_days is None else fallback_days
    fallback_hours = default_hours if fallback_hours is None else fallback_hours
    positive_hours_only = report_type == ReportType.TYPE_B
    counted_rows = [row for row in rows if not positive_hours_only or row.total > 0]
    total_days = len(counted_rows) or fallback_days
    total_hours = sum(row.total for row in counted_rows)
    if total_hours <= 0:
        total_hours = fallback_hours
    total_hours = round(total_hours, 2)

    return ReportSummary(
        total_days=total_days,
        total_hours=total_hours,
        hourly_rate=hourly_rate,
        total_payment=calculate_total_payment(total_hours, hourly_rate)
    )


class TransformationService:
    """
    Applies deterministic transformations to an attendance report,
    making hours realistic and non-round while preserving data.
    """

    def __init__(self, seed: int = 42):
        # אתחול מחולל המספרים האקראיים עם Seed קבוע כדי להבטיח תוצאות עקביות ודטרמיניסטיות
        self.seed = seed
        self.rng = random.Random(seed)

    def _perturb_workday_times(
        self,
        entry: int | None,
        exit: int | None,
    ) -> tuple[int | None, int | None]:
        """Shift available workday times independently while keeping valid ordering."""
        if entry is None and exit is None:
            return entry, exit

        offsets = tuple(range(ENTRY_SHIFT_MINUTES[0], 0)) + tuple(
            range(1, ENTRY_SHIFT_MINUTES[1] + 1)
        )
        if entry is None or exit is None:
            offset_minutes = self.rng.choice(offsets)
            return self._shift_time(entry, offset_minutes), self._shift_time(exit, offset_minutes)

        original_duration = (exit - entry) % (24 * 60)
        if original_duration == 0:
            return entry, exit

        valid_offsets = [
            (entry_offset, exit_offset)
            for entry_offset in offsets
            for exit_offset in offsets
            if entry_offset != exit_offset
            and 0 < original_duration + exit_offset - entry_offset < 24 * 60
        ]
        entry_offset, exit_offset = self.rng.choice(valid_offsets)
        return (
            self._shift_time(entry, entry_offset),
            self._shift_time(exit, exit_offset),
        )

    @staticmethod
    def _shift_time(time_minutes: int | None, offset_minutes: int) -> int | None:
        """Shift a valid clock time without changing missing values."""
        if time_minutes is None:
            return None
        return (time_minutes + offset_minutes) % (24 * 60)

    def transform(self, report: AttendanceReport) -> AttendanceReport:
        """
        Transforms attendance rows by modifying entry and exit times to be realistic.
        """

        transformed_rows = []
        has_recalculated_hours = False

        # מעבר על כל שורת נוכחות בדוח ועדכון שעות הכניסה והיציאה
        for row in report.rows:
            special_day = row.special_day or is_sabbath_or_holiday(row.day, row.date)
            if special_day:
                new_entry = None
                new_exit = None
            elif is_work_day(row.day, row.date):
                new_entry, new_exit = self._perturb_workday_times(row.entry, row.exit)
            else:
                new_entry = row.entry
                new_exit = row.exit

            new_break_time = None if special_day else row.break_time
            new_total = row.total
            if not special_day and new_entry is not None and new_exit is not None:
                if new_entry != row.entry or new_exit != row.exit:
                    worked_minutes = (new_exit - new_entry) % (24 * 60)
                    break_minutes = new_break_time or 0
                    new_total = round(max(0, worked_minutes - break_minutes) / 60, 2)
                    has_recalculated_hours = True

            transformed_rows.append(
                AttendanceRow(
                    date=row.date,
                    day=special_day_label(row.day, special_day),
                    entry=new_entry,
                    exit=new_exit,
                    total=new_total,
                    break_time=new_break_time,
                    location=row.location,
                    shabbat=row.shabbat,
                    p150=row.p150,
                    p125=row.p125,
                    p100=row.p100,
                    special_day=special_day
                )
            )

        summary = build_summary(
            transformed_rows,
            report_type=report.report_type,
            fallback_days=report.summary.total_days,
            fallback_hours=0.0 if has_recalculated_hours else report.summary.total_hours,
            hourly_rate=report.summary.hourly_rate
        )

        # החזרת אובייקט דוח חדש המכיל את השורות והסיכום המעודכנים
        return AttendanceReport(
            report_type=report.report_type,
            rows=tuple(transformed_rows),
            summary=summary
        )