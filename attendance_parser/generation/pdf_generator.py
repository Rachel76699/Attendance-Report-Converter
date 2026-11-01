from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from domain.models import AttendanceReport


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


def generate_pdf(report: AttendanceReport, output_path: str) -> str:
    """
    מייצר דוח PDF מעודכן ותקין המותאם במדויק לסוג הדו"ח (TYPE_A או TYPE_B).
    """
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
        pdfmetrics.registerFont(TTFont('HebrewFont', 'arial.ttf'))
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
    except:
        hebrew_style = styles['Normal']
        hebrew_header_style = styles['Normal']
        title_style = styles['Heading1']

    if report.report_type == "TYPE_B":
        elements.append(Paragraph(f"<b>{rtl('כרטיס עובד לחודש')}</b>", title_style))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(f"<b>{rtl('נ.ע. הנשר כח אדם בע\"מ')}</b>", title_style))
        elements.append(Spacer(1, 8))

        elements.append(Paragraph(f"<b>{rtl('שם העובד: לא זוהה')}</b>", title_style))
        elements.append(Spacer(1, 12))

        table_data = [[
            Paragraph(f'<b>{rtl("הערות")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("סה\"כ שעות")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("שעת יציאה")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("שעת כניסה")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("יום בשבוע")}</b>', hebrew_header_style),
            Paragraph(f'<b>{rtl("תאריך")}</b>', hebrew_header_style)
        ]]

        for r in report.rows:
            table_data.append([
                Paragraph(str(r.location), hebrew_style),
                Paragraph(str(r.total), hebrew_style),
                Paragraph(str(r.exit), hebrew_style),
                Paragraph(str(r.entry), hebrew_style),
                Paragraph(str(r.day), hebrew_style),
                Paragraph(str(r.date), hebrew_style)
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
                Paragraph(str(getattr(r, 'shabbat', '0.00')), hebrew_style),
                Paragraph(str(getattr(r, 'p150', '0.00')), hebrew_style),
                Paragraph(str(getattr(r, 'p125', '0.00')), hebrew_style),
                Paragraph(str(getattr(r, 'p100', '6.50')), hebrew_style),
                Paragraph(str(r.total), hebrew_style),
                Paragraph(str(r.break_time), hebrew_style),
                Paragraph(str(r.exit), hebrew_style),
                Paragraph(str(r.entry), hebrew_style),
                Paragraph(str(r.location), hebrew_style),
                Paragraph(str(r.day), hebrew_style),
                Paragraph(str(r.date), hebrew_style)
            ])

        t = Table(table_data, colWidths=[45, 45, 45, 45, 45, 45, 45, 45, 55, 55, 65])

    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    elements.append(t)

    elements.append(Spacer(1, 15))
    summary = report.summary

    if report.report_type == "TYPE_B":
        summary_data = [
            [Paragraph(f'<b>{summary.total_days}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ ימי עבודה לחודש")}</b>', hebrew_style)],
            [Paragraph(f'<b>{summary.total_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ שעות חודשיות")}</b>', hebrew_style)],
            [Paragraph(f'<b>₪{summary.hourly_rate:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("מחיר לשעה")}</b>', hebrew_style)],
            [Paragraph(f'<b>₪{summary.total_payment:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ לתשלום")}</b>', hebrew_style)]
        ]
    else:
        summary_data = [
            [Paragraph(f'<b>{summary.total_days}</b>', hebrew_style), Paragraph(f'<b>{rtl("ימים")}</b>', hebrew_style)],
            [Paragraph(f'<b>{summary.total_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("סה\"כ שעות")}</b>', hebrew_style)],
            [Paragraph(f'<b>{summary.total_hours:.2f}</b>', hebrew_style), Paragraph(f'<b>{rtl("100% שעות")}</b>', hebrew_style)],
            [Paragraph('<b>0.00</b>', hebrew_style), Paragraph(f'<b>{rtl("125% שעות")}</b>', hebrew_style)]
        ]

    summary_table = Table(summary_data, colWidths=[60, 140])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))

    elements.append(summary_table)

    doc.build(elements)
    return output_path