import random
from datetime import datetime, timedelta
from domain.models import AttendanceReport, AttendanceRow


class TransformationService:
    """
    Applies deterministic transformations to an attendance report,
    making hours realistic and non-round while preserving data.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)

    def _perturb_time(self, time_str: str) -> str:
        """מוסיף היסט אקראי קטן (למשל 1-7 דקות) כדי להפוך שעות עגולות להגיוניות."""
        if not time_str or ":" not in time_str:
            return time_str
        try:
            dt = datetime.strptime(time_str.strip(), "%H:%M")
            offset_minutes = self.rng.choice([1, 2, 3, 4, 5, 6, 7])
            dt_new = dt + timedelta(minutes=offset_minutes)
            return dt_new.strftime("%H:%M")
        except ValueError:
            return time_str

    def transform(self, report: AttendanceReport) -> AttendanceReport:
        """
        Transforms attendance rows by modifying entry and exit times to be realistic.
        """

        transformed_rows = []

        for row in report.rows:
            new_entry = self._perturb_time(row.entry)
            new_exit = self._perturb_time(row.exit)

            transformed_rows.append(
                AttendanceRow(
                    date=row.date,
                    day=row.day,
                    entry=new_entry,
                    exit=new_exit,
                    total=row.total,
                    break_time=row.break_time,
                    location=row.location  # שמירת ערך המקום המקורי
                )
            )

        return AttendanceReport(
            report_type=report.report_type,
            rows=transformed_rows,
            summary=report.summary
        )