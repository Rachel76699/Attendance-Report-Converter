import hashlib
import json
import random
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import Mapping

from domain.exceptions import TransformationError
from domain.models import AttendanceReport, AttendanceRow, ReportSummary, ReportType
from domain.time_utils import is_sabbath_or_holiday, special_day_label
from transformation.config import (
    DEFAULT_TRANSFORMATION_CONFIG,
    TransformationConfig,
)


def _decimal_quantum(decimal_places: int) -> Decimal:
    return Decimal(1).scaleb(-decimal_places)


def calculate_total_payment(
    total_hours: float,
    hourly_rate: float,
    config: TransformationConfig = DEFAULT_TRANSFORMATION_CONFIG,
) -> float:
    amount = Decimal(str(total_hours)) * Decimal(str(hourly_rate))
    return float(
        amount.quantize(
            _decimal_quantum(config.currency_decimal_places),
            rounding=ROUND_HALF_UP,
        )
    )


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
    hourly_rate: float | None = None,
    config: TransformationConfig = DEFAULT_TRANSFORMATION_CONFIG,
) -> ReportSummary:
    policy = config.summary_policies.get(report_type)
    if policy is None:
        raise TransformationError(
            f"No summary policy configured for report type: {report_type}"
        )

    fallback_days = policy.fallback_days if fallback_days is None else fallback_days
    fallback_hours = policy.fallback_hours if fallback_hours is None else fallback_hours
    counted_rows = [
        row for row in rows
        if policy.include_zero_hour_rows or row.total > 0
    ]
    total_days = len(counted_rows) or fallback_days
    total_hours = sum(row.total for row in counted_rows)
    if total_hours <= 0:
        total_hours = fallback_hours
    total_hours = round(total_hours, config.hours_decimal_places)
    resolved_hourly_rate = config.hourly_rate if hourly_rate is None else hourly_rate

    return ReportSummary(
        total_days=total_days,
        total_hours=total_hours,
        hourly_rate=resolved_hourly_rate,
        total_payment=calculate_total_payment(
            total_hours, resolved_hourly_rate, config
        ),
    )


def _row_random(seed: int, row: AttendanceRow) -> random.Random:
    row_identity = json.dumps(
        [
            seed,
            row.date,
            row.day,
            row.entry,
            row.exit,
            row.total,
            row.break_time,
            row.location,
            row.shabbat,
            row.p150,
            row.p125,
            row.p100,
            row.special_day,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    stable_seed = int.from_bytes(
        hashlib.blake2b(row_identity, digest_size=8).digest(),
        byteorder="big",
    )
    return random.Random(stable_seed)


def _validate_transformed_row(
    row: AttendanceRow,
    config: TransformationConfig,
) -> None:
    for field, value in (("entry", row.entry), ("exit", row.exit)):
        if value is not None and not 0 <= value < config.minutes_per_day:
            raise TransformationError(
                f"Transformed {field} time is outside a day: {value}"
            )
    if row.entry is not None and row.exit is not None and row.exit <= row.entry:
        raise TransformationError(
            f"Transformed exit time must be after entry time for {row.date}: "
            f"{row.entry} -> {row.exit}"
        )
    if not 0 <= row.total <= config.maximum_daily_hours:
        raise TransformationError(
            f"Transformed total hours are outside the allowed range for "
            f"{row.date}: {row.total}"
        )

    components = (row.shabbat, row.p150, row.p125, row.p100)
    if any(value is not None for value in components):
        component_total = sum(value or 0.0 for value in components)
        if round(component_total, config.hours_decimal_places) != round(
            row.total, config.hours_decimal_places
        ):
            raise TransformationError(
                f"Hour breakdown does not add up to total hours for {row.date}: "
                f"{component_total} != {row.total}"
            )


class ReportTransformationStrategy:
    def transform(
        self,
        report: AttendanceReport,
        seed: int,
        config: TransformationConfig,
    ) -> AttendanceReport:
        transformed_rows = []
        has_recalculated_hours = False

        for row in report.rows:
            transformed_row, recalculated = self._transform_row(row, seed, config)
            _validate_transformed_row(transformed_row, config)
            transformed_rows.append(transformed_row)
            has_recalculated_hours = has_recalculated_hours or recalculated

        summary = build_summary(
            transformed_rows,
            report_type=report.report_type,
            fallback_days=report.summary.total_days,
            fallback_hours=(
                0.0 if has_recalculated_hours else report.summary.total_hours
            ),
            hourly_rate=report.summary.hourly_rate,
            config=config,
        )
        return AttendanceReport(
            report_type=report.report_type,
            rows=tuple(transformed_rows),
            summary=summary,
        )

    def _transform_row(
        self,
        row: AttendanceRow,
        seed: int,
        config: TransformationConfig,
    ) -> tuple[AttendanceRow, bool]:
        special_day = row.special_day or is_sabbath_or_holiday(row.day, row.date)
        if special_day:
            new_entry = None
            new_exit = None
        elif is_work_day(row.day, row.date):
            new_entry, new_exit = self._perturb_workday_times(
                row.entry, row.exit, _row_random(seed, row), config
            )
        else:
            new_entry = row.entry
            new_exit = row.exit

        new_break_time = None if special_day else row.break_time
        new_total = row.total
        recalculated = (
            not special_day
            and new_entry is not None
            and new_exit is not None
            and (new_entry != row.entry or new_exit != row.exit)
        )
        if recalculated:
            worked_minutes = new_exit - new_entry
            break_minutes = new_break_time or 0
            new_total = round(
                max(0, worked_minutes - break_minutes) / config.minutes_per_hour,
                config.hours_decimal_places,
            )

        transformed_row = replace(
            row,
            day=special_day_label(row.day, special_day),
            entry=new_entry,
            exit=new_exit,
            total=new_total,
            break_time=new_break_time,
            special_day=special_day,
        )
        return transformed_row, recalculated

    @staticmethod
    def _perturb_workday_times(
        entry: int | None,
        exit: int | None,
        rng: random.Random,
        config: TransformationConfig,
    ) -> tuple[int | None, int | None]:
        if entry is None and exit is None:
            return entry, exit

        offsets = [
            offset
            for offset in range(
                config.minimum_shift_minutes,
                config.maximum_shift_minutes + 1,
            )
            if config.allow_zero_shift or offset != 0
        ]
        if not offsets:
            raise TransformationError("No non-zero time shifts are configured")
        if entry is None or exit is None:
            offset = rng.choice(offsets)
            return (
                ReportTransformationStrategy._shift_time(entry, offset, config),
                ReportTransformationStrategy._shift_time(exit, offset, config),
            )

        valid_offsets = [
            (entry_offset, exit_offset)
            for entry_offset in offsets
            for exit_offset in offsets
            if entry_offset != exit_offset
            and 0
            < exit + exit_offset - (entry + entry_offset)
            < config.minutes_per_day
            and 0
            <= entry + entry_offset
            < config.minutes_per_day
            and 0
            <= exit + exit_offset
            < config.minutes_per_day
        ]
        if not valid_offsets:
            raise TransformationError(
                f"No valid configured time shifts preserve entry/exit order "
                f"for {entry} -> {exit}"
            )

        entry_offset, exit_offset = rng.choice(valid_offsets)
        return (
            ReportTransformationStrategy._shift_time(entry, entry_offset, config),
            ReportTransformationStrategy._shift_time(exit, exit_offset, config),
        )

    @staticmethod
    def _shift_time(
        time_minutes: int | None,
        offset_minutes: int,
        config: TransformationConfig,
    ) -> int | None:
        if time_minutes is None:
            return None
        return (time_minutes + offset_minutes) % config.minutes_per_day


class TypeATransformationStrategy(ReportTransformationStrategy):
    _COMPONENT_FIELDS = ("shabbat", "p150", "p125", "p100")

    def _transform_row(
        self,
        row: AttendanceRow,
        seed: int,
        config: TransformationConfig,
    ) -> tuple[AttendanceRow, bool]:
        transformed, recalculated = super()._transform_row(row, seed, config)
        if not recalculated:
            return transformed, False

        available_fields = [
            field for field in self._COMPONENT_FIELDS
            if getattr(row, field) is not None
        ]
        if not available_fields:
            return transformed, True

        quantum = _decimal_quantum(config.hours_decimal_places)
        target_total = Decimal(str(transformed.total)).quantize(quantum)
        original_values = [
            Decimal(str(getattr(row, field)))
            for field in available_fields
        ]
        original_total = sum(original_values)
        if original_total <= 0:
            target_field = (
                "p100" if "p100" in available_fields else available_fields[-1]
            )
            new_values = {
                field: Decimal(0).quantize(quantum)
                for field in available_fields
            }
            new_values[target_field] = target_total
        else:
            new_values = {
                field: (target_total * value / original_total).quantize(
                    quantum, rounding=ROUND_HALF_UP
                )
                for field, value in zip(available_fields, original_values)
            }
            remainder = target_total - sum(new_values.values())
            largest_field = max(available_fields, key=new_values.__getitem__)
            new_values[largest_field] += remainder

        return (
            replace(
                transformed,
                **{field: float(value) for field, value in new_values.items()},
            ),
            True,
        )


class TypeBTransformationStrategy(ReportTransformationStrategy):
    pass


_STRATEGIES: Mapping[ReportType, ReportTransformationStrategy] = MappingProxyType({
    ReportType.TYPE_A: TypeATransformationStrategy(),
    ReportType.TYPE_B: TypeBTransformationStrategy(),
})


class TransformationService:
    def __init__(
        self,
        seed: int = 42,
        config: TransformationConfig = DEFAULT_TRANSFORMATION_CONFIG,
        strategies: Mapping[ReportType, ReportTransformationStrategy] | None = None,
    ):
        self.seed = seed
        self.config = config
        resolved_strategies = _STRATEGIES if strategies is None else strategies
        self.strategies = MappingProxyType(dict(resolved_strategies))

    def transform(self, report: AttendanceReport) -> AttendanceReport:
        strategy = self.strategies.get(report.report_type)
        if strategy is None:
            raise TransformationError(
                f"No transformation strategy configured for report type: "
                f"{report.report_type}"
            )
        return strategy.transform(report, self.seed, self.config)
