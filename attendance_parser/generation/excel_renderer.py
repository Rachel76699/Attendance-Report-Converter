from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from domain.models import AttendanceReport, ReportType
from domain.time_utils import format_clock_minutes, format_duration_minutes


def _display_type_a_hour(value: str) -> str:
    return value if value else "---"


class ExcelRenderer:
    def render(self, report: AttendanceReport, output_path: str) -> str:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "נוכחות"
        worksheet.sheet_view.rightToLeft = True

        if report.report_type == ReportType.TYPE_A:
            headers = [
                "שבת", "150%", "125%", "100%", "סה״כ", "הפסקה",
                "יציאה", "כניסה", "מקום", "יום", "תאריך"
            ]
            row_values = lambda row: [
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
                row.date
            ]
        else:
            headers = ["הערות", "סה״כ שעות", "שעת יציאה", "שעת כניסה", "יום בשבוע", "תאריך"]
            row_values = lambda row: [
                row.location, row.total, format_clock_minutes(row.exit) or "---",
                format_clock_minutes(row.entry) or "---", row.day, row.date
            ]

        worksheet.append(headers)
        for row in report.rows:
            worksheet.append(row_values(row))

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
