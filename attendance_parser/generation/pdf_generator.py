import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Flowable, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from domain.exceptions import UnsupportedReportTypeError
from domain.models import AttendanceReport, ReportType
from domain.time_utils import format_clock_minutes, format_duration_minutes


def rtl(text: str) -> str:
    """הופכת את סדר המילים והאותיות בעברית להצגה תקינה מימין לשמאל תוך שמירה על מספרים וסמלים."""
    if not text:
        return text
    tokens = text.split(' ')
    processed_tokens = []
    for token in tokens:
        if any('\u0590' <= c <= '\u05ff' for c in token):
            processed_tokens.append(token[::-1])
        else:
            processed_tokens.append(token)
    return " ".join(processed_tokens[::-1])


def _display_type_a_hour(value: str | None) -> str:
    return value if value else "---"


def _bold_rtl(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f"<b>{rtl(text)}</b>", style)


@dataclass(frozen=True)
class PDFLayout:
    header_elements: tuple[Flowable, ...]
    table: Table
    summary_table: Table
    table_styles: tuple[tuple, ...] = ()


PDFLayoutBuilder = Callable[
    [AttendanceReport, ParagraphStyle, ParagraphStyle, ParagraphStyle],
    PDFLayout,
]


def _build_type_b_layout(
    report: AttendanceReport,
    normal_style: ParagraphStyle,
    header_style: ParagraphStyle,
    title_style: ParagraphStyle,
) -> PDFLayout:
    cell_style = ParagraphStyle(
        "TypeBCell",
        parent=normal_style,
        fontSize=8,
        leading=9,
    )
    table_header_style = ParagraphStyle(
        "TypeBHeader",
        parent=header_style,
        fontSize=8,
        leading=9,
    )
    header_elements = (
        _bold_rtl("כרטיס עובד לחודש", title_style),
        Spacer(1, 4),
        _bold_rtl("שם חברה: לא זוהה", title_style),
        Spacer(1, 8),
        _bold_rtl("שם העובד: לא זוהה", title_style),
        Spacer(1, 12),
    )
    table_data = [[
        _bold_rtl("הערות", table_header_style),
        _bold_rtl('סה"כ שעות', table_header_style),
        _bold_rtl("שעת יציאה", table_header_style),
        _bold_rtl("שעת כניסה", table_header_style),
        _bold_rtl("יום בשבוע", table_header_style),
        _bold_rtl("תאריך", table_header_style),
    ]]
    table_data.extend([
        [
            Paragraph(rtl(row.location), cell_style),
            Paragraph(str(row.total), cell_style),
            Paragraph(format_clock_minutes(row.exit) or "---", cell_style),
            Paragraph(format_clock_minutes(row.entry) or "---", cell_style),
            Paragraph(rtl(row.day), cell_style),
            Paragraph(str(row.date), cell_style),
        ]
        for row in report.rows
    ])
    table = Table(table_data, colWidths=[150, 70, 70, 70, 70, 70])
    summary = report.summary
    summary_data = [
        [Paragraph(f"<b>{summary.total_days}</b>", normal_style), _bold_rtl('סה"כ ימי עבודה לחודש', normal_style)],
        [Paragraph(f"<b>{summary.total_hours:.2f}</b>", normal_style), _bold_rtl('סה"כ שעות חודשיות', normal_style)],
        [Paragraph(f"<b>₪{summary.hourly_rate:.2f}</b>", normal_style), _bold_rtl("מחיר לשעה", normal_style)],
        [Paragraph(f"<b>₪{summary.total_payment:.2f}</b>", normal_style), _bold_rtl('סה"כ לתשלום', normal_style)],
    ]
    return PDFLayout(
        header_elements=header_elements,
        table=table,
        summary_table=Table(summary_data, colWidths=[60, 140]),
        table_styles=(
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ),
    )


def _build_type_a_layout(
    report: AttendanceReport,
    normal_style: ParagraphStyle,
    header_style: ParagraphStyle,
    title_style: ParagraphStyle,
) -> PDFLayout:
    header_elements = (
        _bold_rtl("דו\"ח נוכחות", title_style),
        Spacer(1, 4),
        _bold_rtl("נ.ע. הנשר כח אדם בע\"מ", title_style),
        Spacer(1, 8),
        _bold_rtl("שם העובד: לא זוהה", title_style),
        Spacer(1, 12),
    )
    table_data = [[
        _bold_rtl("שבת", header_style),
        Paragraph("<b>150%</b>", header_style),
        Paragraph("<b>125%</b>", header_style),
        Paragraph("<b>100%</b>", header_style),
        _bold_rtl('סה"כ', header_style),
        _bold_rtl("הפסקה", header_style),
        _bold_rtl("יציאה", header_style),
        _bold_rtl("כניסה", header_style),
        _bold_rtl("מקום", header_style),
        _bold_rtl("יום", header_style),
        _bold_rtl("תאריך", header_style),
    ]]
    table_data.extend([
        [
            Paragraph(f"{(row.shabbat or 0.0):.2f}", normal_style),
            Paragraph(f"{(row.p150 or 0.0):.2f}", normal_style),
            Paragraph(f"{(row.p125 or 0.0):.2f}", normal_style),
            Paragraph(f"{(row.p100 or 0.0):.2f}", normal_style),
            Paragraph(str(row.total), normal_style),
            Paragraph(_display_type_a_hour(format_duration_minutes(row.break_time)), normal_style),
            Paragraph(_display_type_a_hour(format_clock_minutes(row.exit)), normal_style),
            Paragraph(_display_type_a_hour(format_clock_minutes(row.entry)), normal_style),
            Paragraph(rtl(row.location), normal_style),
            Paragraph(rtl(row.day), normal_style),
            Paragraph(row.date, normal_style),
        ]
        for row in report.rows
    ])
    table = Table(table_data, colWidths=[45, 45, 45, 45, 45, 45, 45, 45, 55, 55, 65])
    summary = report.summary
    shabbat_hours = sum(row.shabbat or 0.0 for row in report.rows)
    p150_hours = sum(row.p150 or 0.0 for row in report.rows)
    p125_hours = sum(row.p125 or 0.0 for row in report.rows)
    p100_hours = sum(row.p100 or 0.0 for row in report.rows)
    summary_data = [
        [Paragraph(f"<b>{summary.total_days}</b>", normal_style), _bold_rtl("ימים", normal_style)],
        [Paragraph(f"<b>{summary.total_hours:.2f}</b>", normal_style), _bold_rtl('סה"כ שעות', normal_style)],
        [Paragraph(f"<b>{p100_hours:.2f}</b>", normal_style), _bold_rtl("100% שעות", normal_style)],
        [Paragraph(f"<b>{p125_hours:.2f}</b>", normal_style), _bold_rtl("125% שעות", normal_style)],
        [Paragraph(f"<b>{p150_hours:.2f}</b>", normal_style), _bold_rtl("150% שעות", normal_style)],
        [Paragraph(f"<b>{shabbat_hours:.2f}</b>", normal_style), _bold_rtl("שבת", normal_style)],
        [Paragraph(f"<b>₪{summary.total_payment:.2f}</b>", normal_style), _bold_rtl('סה"כ לתשלום', normal_style)],
    ]
    return PDFLayout(
        header_elements=header_elements,
        table=table,
        summary_table=Table(summary_data, colWidths=[60, 140]),
    )


PDF_LAYOUTS: Mapping[ReportType, PDFLayoutBuilder] = MappingProxyType({
    ReportType.TYPE_A: _build_type_a_layout,
    ReportType.TYPE_B: _build_type_b_layout,
})


def generate_pdf(report: AttendanceReport, output_path: str) -> str:
    # הגדרת תבנית המסמך והשוליים עבור קובץ ה-PDF
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=20
    )
    styles = getSampleStyleSheet()

    try:
        # רישום גופן תומך עברית (Arial) לשימוש ברכיבי הטקסט
        windows_dir = os.environ.get("WINDIR", r"C:\Windows")
        font_path = os.path.join(windows_dir, "Fonts", "arial.ttf")
        pdfmetrics.registerFont(TTFont('HebrewFont', font_path))
        hebrew_style = ParagraphStyle(
            'HebrewNormal',
            parent=styles['Normal'],
            fontName='HebrewFont',
            fontSize=9,
            alignment=1
        )
        hebrew_header_style = ParagraphStyle(
            'HebrewHeader',
            parent=styles['Normal'],
            fontName='HebrewFont',
            fontSize=10,
            leading=12,
            alignment=1
        )
        title_style = ParagraphStyle(
            'HebrewTitle',
            parent=styles['Heading1'],
            fontName='HebrewFont',
            fontSize=14,
            alignment=2
        )
    except (OSError, TTFError, ValueError):
        hebrew_style = styles['Normal']
        hebrew_header_style = styles['Normal']
        title_style = styles['Heading1']

    layout_builder = PDF_LAYOUTS.get(report.report_type)
    if layout_builder is None:
        raise UnsupportedReportTypeError(
            f"No PDF layout configured for report type: {report.report_type}"
        )
    layout = layout_builder(
        report,
        hebrew_style,
        hebrew_header_style,
        title_style,
    )
    elements = list(layout.header_elements)
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]
    table_style.extend(layout.table_styles)
    layout.table.setStyle(TableStyle(table_style))
    layout.summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.extend((layout.table, Spacer(1, 15), layout.summary_table))

    # יצירה והפקה של קובץ ה-PDF בפועל
    doc.build(elements)
    return output_path