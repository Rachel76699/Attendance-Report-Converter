from collections.abc import Callable, Mapping
from types import MappingProxyType

from domain.exceptions import UnsupportedReportTypeError
from domain.models import ReportType
from parsing.base_parser import BaseParser
from parsing.type_a_parser import TypeAParser
from parsing.type_b_parser import TypeBParser


PARSER_FACTORIES: Mapping[ReportType, Callable[[], BaseParser]] = MappingProxyType({
    ReportType.TYPE_A: TypeAParser,
    ReportType.TYPE_B: TypeBParser,
})


def get_parser(report_type: ReportType | str) -> BaseParser:
    # בדיקה האם סוג הדוח הוא TYPE_A והחזרת המפענח המתאים
    try:
        normalized_type = ReportType(report_type)
    except (TypeError, ValueError) as error:
        raise UnsupportedReportTypeError(
            f"Unknown report type: {report_type}"
        ) from error

    parser_factory = PARSER_FACTORIES.get(normalized_type)
    if parser_factory is None:
        raise UnsupportedReportTypeError(f"Unknown report type: {report_type}")
    return parser_factory()