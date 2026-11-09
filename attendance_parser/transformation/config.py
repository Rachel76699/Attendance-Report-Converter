from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from domain.models import ReportType


@dataclass(frozen=True)
class SummaryPolicy:
    fallback_days: int
    fallback_hours: float
    include_zero_hour_rows: bool


def _default_summary_policies() -> Mapping[ReportType, SummaryPolicy]:
    return MappingProxyType({
        ReportType.TYPE_A: SummaryPolicy(22, 143.0, True),
        ReportType.TYPE_B: SummaryPolicy(20, 84.0, False),
    })


@dataclass(frozen=True)
class TransformationConfig:
    hourly_rate: float = 30.65
    minimum_shift_minutes: int = -5
    maximum_shift_minutes: int = 10
    allow_zero_shift: bool = False
    minutes_per_hour: int = 60
    minutes_per_day: int = 24 * 60
    maximum_daily_hours: float = 24.0
    hours_decimal_places: int = 2
    currency_decimal_places: int = 2
    summary_policies: Mapping[ReportType, SummaryPolicy] = field(
        default_factory=_default_summary_policies
    )


DEFAULT_TRANSFORMATION_CONFIG = TransformationConfig()
