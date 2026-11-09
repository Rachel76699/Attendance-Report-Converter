class AttendanceConverterError(Exception):
    """Base class for expected attendance-conversion failures."""


class RowParseError(AttendanceConverterError, ValueError):
    """Raised when an attendance row contains a non-empty invalid value."""


class UnsupportedReportTypeError(AttendanceConverterError, ValueError):
    """Raised when a parser is requested for an unsupported report type."""


class TransformationError(AttendanceConverterError, ValueError):
    """Raised when a report cannot satisfy transformation rules."""
