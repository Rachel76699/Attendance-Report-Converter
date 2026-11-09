from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from domain.exceptions import UnsupportedReportTypeError
from domain.models import AttendanceReport, AttendanceRow, ReportType
from domain.time_utils import format_clock_minutes, format_duration_minutes


def _display_type_a_hour(value: str) -> str:
    return value if value else "---"


@dataclass(frozen=True)
class ExcelLayout:
    headers: tuple[str, ...]
    row_values: Callable[[AttendanceRow], list[object]]


def _type_a_layout() -> ExcelLayout:
    return ExcelLayout(
        headers=(
            "שבת", "150%", "125%", "100%", "סה״כ", "הפסקה",
            "יציאה", "כניסה", "מקום", "יום", "תאריך",
        ),
        row_values=lambda row: [
            row.shabbat,
            row.p150,
            row.p125,
            row.p100,
            row.total,
            _display_type_a_hour(format_duration_minutes(row.break_time)),
            _display_type_a_hour(format_clock_minutes(row.exit)),
            _display_type_a_hour(format_clock_minutes(row.entry)),
            row.location,
            row.day,
            row.date,
        ],
    )


def _type_b_layout() -> ExcelLayout:
    return ExcelLayout(
        headers=(
            "הערות", "סה״כ שעות", "שעת יציאה", "שעת כניסה", "יום בשבוע", "תאריך",
        ),
        row_values=lambda row: [
            row.location,
            row.total,
            format_clock_minutes(row.exit) or "---",
            format_clock_minutes(row.entry) or "---",
            row.day,
            row.date,
        ],
    )


EXCEL_LAYOUTS: Mapping[ReportType, Callable[[], ExcelLayout]] = MappingProxyType({
    ReportType.TYPE_A: _type_a_layout,
    ReportType.TYPE_B: _type_b_layout,
})


class ExcelRenderer:
    def render(self, report: AttendanceReport, output_path: str) -> str:
        layout_factory = EXCEL_LAYOUTS.get(report.report_type)
        if layout_factory is None:
            raise UnsupportedReportTypeError(
                f"No Excel layout configured for report type: {report.report_type}"
            )
        layout = layout_factory()
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "נוכחות"
        worksheet.sheet_view.rightToLeft = True

        worksheet.append(layout.headers)
        for row in report.rows:
            worksheet.append(layout.row_values(row))

        summary_start = worksheet.max_row + 1
        summary_rows = [
            ("ימי עבודה", report.summary.total_days),
            ("סה״כ שעות", report.summary.total_hours),
            ("תעריף לשעה", report.summary.hourly_rate),
            ("סה״כ לתשלום", report.summary.total_payment)
        ]
        for label, value in summary_rows:
            worksheet.append([label, value])

        header_fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        for column in worksheet.columns:
            width = max(len(str(cell.value or "")) for cell in column) + 2
            worksheet.column_dimensions[get_column_letter(column[0].column)].width = min(width, 32)
        for row_index in range(summary_start, worksheet.max_row + 1):
            worksheet.cell(row_index, 1).font = Font(bold=True)
        worksheet.freeze_panes = "A2"

        workbook.save(output_path)
        return output_path
