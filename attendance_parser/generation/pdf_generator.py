import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
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
    elements = []

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

    # פיצול לוגיקה בהתאם לסוג הדוח (TYPE_B או דוח רגיל)
    if report.report_type == ReportType.TYPE_B:
        type_b_cell_style = ParagraphStyle(
            'TypeBCell',
            parent=hebrew_style,
            fontSize=8,
            leading=9,
        )
        type_b_header_style = ParagraphStyle(
            'TypeBHeader',
            parent=hebrew_header_style,
            fontSize=8,
            leading=9,
        )
        elements.append(Paragraph(f"<b>{rtl('כרטיס עובד לחודש')}</b>", title_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"<b>{rtl("שם חברה: לא זוהה")}</b>", title_style))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph(f"<b>{rtl('שם העובד: לא זוהה')}</b>", title_style))
        elements.append(Spacer(1, 12))

        table_data = [[
            Paragraph(f'<b>{rtl("הערות")}</b>', type_b_header_style),
            Paragraph(f'<b>{rtl("סה\"כ שעות")}</b>', type_b_header_style),
            Paragraph(f'<b>{rtl("שעת יציאה")}</b>', type_b_header_style),
            Paragraph(f'<b>{rtl("שעת כניסה")}</b>', type_b_header_style),
            Paragraph(f'<b>{rtl("יום בשבוע")}</b>', type_b_header_style),
            Paragraph(f'<b>{rtl("תאריך")}</b>', type_b_header_style)
        ]]

        for r in report.rows:
            table_data.append([
                Paragraph(rtl(r.location), type_b_cell_style),
                Paragraph(str(r.total), type_b_cell_style),
                Paragraph(format_clock_minutes(r.exit) or "---", type_b_cell_style),
                Paragraph(format_clock_minutes(r.entry) or "---", type_b_cell_style),
                Paragraph(rtl(r.day), type_b_cell_style),
                Paragraph(str(r.date), type_b_cell_style)
            ])

        t = Table(table_data, colWidths=[150, 70, 70, 70, 70, 70])

    else:
        elements.append(Paragraph(f"<b>{rtl('דו\"ח נוכחות')}</b>", title_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"<b>{rtl('נ.ע. הנשר כח אדם בע\"מ')}</b>", title_style))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph(f"<b>{rtl('שם העובד: לא זוהה')}</b>", title_style))
        elements.append(Spacer(1, 12))

        table_data = [[
            Paragraph(f'<b>{rtl("שבת")}</b>', hebrew_header_style),
            Paragraph('<b>150%</b>', hebrew_header_style),
            Paragraph('<b>125%</b>', hebrew_header_style),
            Paragraph('<b>100%</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("סה\"כ")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("הפסקה")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("יציאה")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("כניסה")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("מקום")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("יום")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("תאריך")}</b>', hebrew_header_style)
        ]]

        for r in report.rows:
            table_data.append([
                Paragraph(f"{(r.shabbat or 0.0):.2f}", hebrew_style),
                Paragraph(f"{(r.p150 or 0.0):.2f}", hebrew_style),
                Paragraph(f"{(r.p125 or 0.0):.2f}", hebrew_style),
                Paragraph(f"{(r.p100 or 0.0):.2f}", hebrew_style),
                Paragraph(str(r.total), hebrew_style),
                Paragraph(_display_type_a_hour(format_duration_minutes(r.break_time)), hebrew_style),
                Paragraph(_display_type_a_hour(format_clock_minutes(r.exit)), hebrew_style),
                Paragraph(_display_type_a_hour(format_clock_minutes(r.entry)), hebrew_style),
                Paragraph(rtl(r.location), hebrew_style),
                Paragraph(rtl(r.day), hebrew_style),
                Paragraph(r.date, hebrew_style)
            ])

        t = Table(table_data, colWidths=[45, 45, 45, 45, 45, 45, 45, 45, 55, 55, 65])

    # הגדרת העיצוב הויזואלי (צבעים, יישור וקווים) לטבלה הראשית
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]
    if report.report_type == ReportType.TYPE_B:
        table_style.extend([
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ])
    t.setStyle(TableStyle(table_style))
    elements.append(t)

    elements.append(Spacer(1, 15))
    summary = report.summary

    # בניית טבלת הסיכום בתחתית הדוח בהתאם לסוג הדוח
    if report.report_type == ReportType.TYPE_B:
        summary_data = [
            [Paragraph(f'<b>{summary.total_days}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ ימי עבודה לחודש")}</b>', hebrew_style)],
            [Paragraph(f'<b>{summary.total_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ שעות חודשיות")}</b>', hebrew_style)],
            [Paragraph(f'<b>₪{summary.hourly_rate:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("מחיר לשעה")}</b>', hebrew_style)],
            [Paragraph(f'<b>₪{summary.total_payment:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ לתשלום")}</b>', hebrew_style)]
        ]
    else:
        shabbat_hours = sum(row.shabbat or 0.0 for row in report.rows)
        p150_hours = sum(row.p150 or 0.0 for row in report.rows)
        p125_hours = sum(row.p125 or 0.0 for row in report.rows)
        p100_hours = sum(row.p100 or 0.0 for row in report.rows)
        summary_data = [
            [Paragraph(f'<b>{summary.total_days}</b>', hebrew_style), Paragraph(f'<b>{rtl("ימים")}</b>', hebrew_style)],
            [Paragraph(f'<b>{summary.total_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ שעות")}</b>', hebrew_style)],
            [Paragraph(f'<b>{p100_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("100% שעות")}</b>', hebrew_style)],
            [Paragraph(f'<b>{p125_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("125% שעות")}</b>', hebrew_style)],
            [Paragraph(f'<b>{p150_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("150% שעות")}</b>', hebrew_style)],
            [Paragraph(f'<b>{shabbat_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("שבת")}</b>', hebrew_style)],
            [Paragraph(f'<b>₪{summary.total_payment:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ לתשלום")}</b>', hebrew_style)]
        ]

    summary_table = Table(summary_data, colWidths=[60, 140])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))

    elements.append(summary_table)

    # יצירה והפקה של קובץ ה-PDF בפועל
    doc.build(elements)
    return output_path