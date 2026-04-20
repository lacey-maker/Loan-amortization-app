"""Excel and PDF export for amortization schedules."""
from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)

from amortization import ScheduleRow


HEADERS = [
    "#", "Date", "Beginning Balance", "Scheduled Pmt",
    "Extra Pmt", "Interest", "Principal", "Total Payment", "Ending Balance",
]


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def to_excel(
    rows: list[ScheduleRow],
    summary: dict,
    loan_meta: dict,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Amortization"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="1F4E78")
    title_font = Font(bold=True, size=14)
    label_font = Font(bold=True)
    thin = Side(border_style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right")

    ws["A1"] = loan_meta.get("title", "Loan Amortization Schedule")
    ws["A1"].font = title_font
    ws.merge_cells("A1:I1")

    # loan summary block
    info_pairs = [
        ("Borrower", loan_meta.get("borrower", "")),
        ("Loan Amount", _fmt_money(loan_meta.get("principal", 0))),
        ("Annual Rate", f"{loan_meta.get('annual_rate', 0):.4f}%"),
        ("Term", f"{loan_meta.get('term_years', 0)} years"),
        ("Loan Type", loan_meta.get("loan_type", "Standard")),
        ("Payment Frequency", loan_meta.get("payment_frequency", "")),
        ("Compounding", loan_meta.get("compounding", "")),
        ("Start Date", str(loan_meta.get("start_date", ""))),
        ("First Payment", str(loan_meta.get("first_payment_date", ""))),
        ("Scheduled Payment", _fmt_money(summary["scheduled_payment"])),
    ]
    row_i = 3
    for label, val in info_pairs:
        ws.cell(row=row_i, column=1, value=label).font = label_font
        ws.cell(row=row_i, column=2, value=val)
        row_i += 1

    # summary totals
    row_i += 1
    totals = [
        ("Payoff Date", str(summary.get("payoff_date", ""))),
        ("Total Periods", summary["periods"]),
        ("Total Interest", _fmt_money(summary["total_interest"])),
        ("Total Principal", _fmt_money(summary["total_principal"])),
        ("Total Extra Payments", _fmt_money(summary["total_extra"])),
        ("Total Paid", _fmt_money(summary["total_paid"])),
        ("Interest Saved vs Baseline", _fmt_money(summary["interest_saved"])),
        ("Periods Saved", summary["periods_saved"]),
    ]
    for label, val in totals:
        ws.cell(row=row_i, column=1, value=label).font = label_font
        ws.cell(row=row_i, column=2, value=val)
        row_i += 1

    # schedule header
    row_i += 2
    header_row = row_i
    for col, h in enumerate(HEADERS, start=1):
        c = ws.cell(row=row_i, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border
    row_i += 1

    for r in rows:
        values = [
            r.period,
            r.payment_date,
            r.beginning_balance,
            r.scheduled_payment,
            r.extra_payment,
            r.interest,
            r.principal,
            r.total_payment,
            r.ending_balance,
        ]
        for col, v in enumerate(values, start=1):
            c = ws.cell(row=row_i, column=col, value=v)
            c.border = border
            if col == 1:
                c.alignment = center
            elif col == 2:
                c.number_format = "yyyy-mm-dd"
                c.alignment = center
            else:
                c.number_format = '"$"#,##0.00'
                c.alignment = right
        row_i += 1

    # totals footer
    c = ws.cell(row=row_i, column=1, value="Totals")
    c.font = label_font
    for col, key in [
        (4, "scheduled_payment_total"),
        (5, "extra_total"),
        (6, "interest_total"),
        (7, "principal_total"),
        (8, "paid_total"),
    ]:
        pass
    total_scheduled = sum(r.scheduled_payment for r in rows)
    total_extra = sum(r.extra_payment for r in rows)
    total_interest = sum(r.interest for r in rows)
    total_principal = sum(r.principal for r in rows)
    total_paid = sum(r.total_payment for r in rows)
    for col, val in [(4, total_scheduled), (5, total_extra), (6, total_interest),
                     (7, total_principal), (8, total_paid)]:
        cc = ws.cell(row=row_i, column=col, value=val)
        cc.number_format = '"$"#,##0.00'
        cc.font = label_font
        cc.alignment = right

    # column widths
    widths = [6, 13, 18, 16, 14, 14, 14, 16, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(
    rows: list[ScheduleRow],
    summary: dict,
    loan_meta: dict,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=0.4 * inch, rightMargin=0.4 * inch,
        topMargin=0.4 * inch, bottomMargin=0.4 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=16, spaceAfter=6)
    h = ParagraphStyle("h", parent=styles["Heading3"], fontSize=10, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8)

    elements = []
    elements.append(Paragraph(loan_meta.get("title", "Loan Amortization Schedule"), title_style))

    info = [
        ["Borrower:", loan_meta.get("borrower", ""),
         "Loan Amount:", _fmt_money(loan_meta.get("principal", 0)),
         "Rate:", f"{loan_meta.get('annual_rate', 0):.4f}%"],
        ["Term:", f"{loan_meta.get('term_years', 0)} years",
         "Frequency:", loan_meta.get("payment_frequency", ""),
         "Compounding:", loan_meta.get("compounding", "")],
        ["Loan Type:", loan_meta.get("loan_type", "Standard"),
         "Start:", str(loan_meta.get("start_date", "")),
         "First Pmt:", str(loan_meta.get("first_payment_date", ""))],
        ["", "", "", "",
         "Scheduled Pmt:", _fmt_money(summary["scheduled_payment"])],
    ]
    info_tbl = Table(info, colWidths=[0.9*inch, 1.6*inch, 1.0*inch, 1.6*inch, 1.0*inch, 1.6*inch])
    info_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
        ("FONT", (4, 0), (4, -1), "Helvetica-Bold", 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 8))

    tot_rows = [
        ["Payoff Date:", str(summary.get("payoff_date", "")),
         "Total Periods:", str(summary["periods"]),
         "Total Interest:", _fmt_money(summary["total_interest"])],
        ["Total Paid:", _fmt_money(summary["total_paid"]),
         "Extra Pmts:", _fmt_money(summary["total_extra"]),
         "Interest Saved:", _fmt_money(summary["interest_saved"])],
    ]
    tot_tbl = Table(tot_rows, colWidths=[1.1*inch, 1.6*inch, 1.1*inch, 1.4*inch, 1.3*inch, 1.6*inch])
    tot_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
        ("FONT", (4, 0), (4, -1), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F2F2")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(tot_tbl)
    elements.append(Spacer(1, 10))

    data = [HEADERS]
    for r in rows:
        data.append([
            str(r.period),
            r.payment_date.isoformat(),
            _fmt_money(r.beginning_balance),
            _fmt_money(r.scheduled_payment),
            _fmt_money(r.extra_payment),
            _fmt_money(r.interest),
            _fmt_money(r.principal),
            _fmt_money(r.total_payment),
            _fmt_money(r.ending_balance),
        ])

    # totals row
    data.append([
        "",
        "Totals",
        "",
        _fmt_money(sum(r.scheduled_payment for r in rows)),
        _fmt_money(sum(r.extra_payment for r in rows)),
        _fmt_money(sum(r.interest for r in rows)),
        _fmt_money(sum(r.principal for r in rows)),
        _fmt_money(sum(r.total_payment for r in rows)),
        "",
    ])

    col_widths = [0.4*inch, 0.95*inch, 1.25*inch, 1.15*inch,
                  1.0*inch, 1.0*inch, 1.0*inch, 1.2*inch, 1.25*inch]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F7F9FC")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8EEF5")),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
    ]))
    elements.append(tbl)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(0.4 * inch, 0.25 * inch,
                          f"Generated {date.today().isoformat()}")
        canvas.drawRightString(
            doc.pagesize[0] - 0.4 * inch, 0.25 * inch,
            f"Page {doc.page}"
        )
        canvas.restoreState()

    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
