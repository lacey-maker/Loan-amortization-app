"""Streamlit loan amortization app — event-based, TValue-style.

Run:
    streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from amortization import (
    PERIODS_PER_YEAR,
    Event,
    LoanConfig,
    build_schedule,
)
from exports import to_excel, to_pdf


st.set_page_config(
    page_title="Loan Amortization",
    page_icon="💰",
    layout="wide",
)

st.title("💰 Loan Amortization")
st.caption(
    "Event-based loan modeling: add Loan disbursements and Payment series. "
    "Mix interest-only periods, multiple draws, and balloon payments — like TValue."
)

# ---------- Top: loan-level config ----------
top = st.columns([2, 1, 1, 1])
label = top[0].text_input("Label / Borrower", value="")
rate = top[1].number_input(
    "Nominal Annual Rate (%)",
    min_value=0.0, max_value=100.0,
    value=7.7500, step=0.125, format="%.4f",
)
day_count = top[2].selectbox("Day Count", ["Actual/365", "Actual/360", "30/360"], index=0)
compounding = top[3].selectbox(
    "Compounding (display)",
    ["Monthly", "Daily", "Annually", "Quarterly", "Semi-Annually"],
    index=0,
)

# ---------- Events table ----------
st.subheader("Events")
st.caption(
    "Add rows for each loan disbursement and each payment series. "
    "**Type**: Loan or Payment. "
    "**Special**: leave blank for fixed amount (interest first, then principal); "
    "'Interest Only' = pay accrued interest each period; "
    "'P&I' = solve for level payment; "
    "'Principal' = full amount goes to principal (accrued interest carries)."
)

FREQ_OPTIONS = [""] + list(PERIODS_PER_YEAR.keys())  # blank option for Loan rows
SPECIAL_OPTIONS = ["", "Interest Only", "P&I", "Principal"]

DEFAULT_EVENTS = pd.DataFrame([
    {"Type": "Loan",    "Date": date(2025, 9, 19),  "Amount": 20000.00,  "Number": 1,  "Frequency": "",        "Special": "",              "Label": ""},
    {"Type": "Payment", "Date": date(2025, 10, 19), "Amount": 0.00,      "Number": 5,  "Frequency": "Monthly", "Special": "Interest Only", "Label": ""},
    {"Type": "Loan",    "Date": date(2026, 2, 23),  "Amount": 159000.00, "Number": 1,  "Frequency": "",        "Special": "",              "Label": ""},
    {"Type": "Payment", "Date": date(2026, 3, 19),  "Amount": 0.00,      "Number": 24, "Frequency": "Monthly", "Special": "Interest Only", "Label": ""},
    {"Type": "Payment", "Date": date(2028, 3, 19),  "Amount": 180173.14, "Number": 1,  "Frequency": "",        "Special": "",              "Label": "Balloon"},
])

if "events_df" not in st.session_state:
    st.session_state.events_df = DEFAULT_EVENTS.copy()

reset_col, _ = st.columns([1, 6])
if reset_col.button("Reset to example"):
    st.session_state.events_df = DEFAULT_EVENTS.copy()
    st.rerun()

edited_df = st.data_editor(
    st.session_state.events_df,
    column_config={
        "Type": st.column_config.SelectboxColumn(
            "Type", options=["Loan", "Payment"], required=True, width="small",
        ),
        "Date": st.column_config.DateColumn("Date", required=True, format="MM/DD/YYYY"),
        "Amount": st.column_config.NumberColumn(
            "Amount ($)", format="$%.2f", min_value=0.0, step=100.0,
        ),
        "Number": st.column_config.NumberColumn(
            "Number", min_value=1, max_value=1200, step=1, default=1,
            help="Number of payments in the series (Payment events only).",
        ),
        "Frequency": st.column_config.SelectboxColumn(
            "Frequency", options=FREQ_OPTIONS, width="small",
            help="Leave blank for Loan rows and single payments. Set for payment series.",
        ),
        "Special": st.column_config.SelectboxColumn(
            "Special", options=SPECIAL_OPTIONS, width="medium",
            help="Interest Only = pay accrued interest only. P&I = solve for level payment.",
        ),
        "Label": st.column_config.TextColumn("Label (optional)", width="small"),
    },
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="events_editor",
)
st.session_state.events_df = edited_df

# ---------- Build events list ----------
events: list[Event] = []
for _, row in edited_df.iterrows():
    if pd.isna(row["Date"]) or pd.isna(row["Type"]):
        continue
    try:
        d = row["Date"]
        if hasattr(d, "to_pydatetime"):
            d = d.to_pydatetime().date()
        elif hasattr(d, "date") and callable(d.date):
            d = d.date()
        freq = row["Frequency"] or "Monthly"  # engine ignores it for Loans and single payments
        events.append(Event(
            event_type=row["Type"],
            date=d,
            amount=float(row["Amount"] or 0),
            number=int(row["Number"] or 1),
            frequency=freq,
            special=row["Special"] or "",
            label=str(row["Label"] or ""),
        ))
    except Exception as exc:
        st.warning(f"Skipping row: {exc}")

config = LoanConfig(
    nominal_annual_rate=rate,
    day_count=day_count,
    compounding=compounding,
    label=label,
)

if not events:
    st.info("Add at least one Loan event and one Payment event to build a schedule.")
    st.stop()

try:
    rows, summary = build_schedule(events, config)
except Exception as exc:
    st.error(f"Could not build schedule: {exc}")
    st.stop()

# ---------- Summary tiles ----------
st.subheader("Summary")
m = st.columns(5)
m[0].metric("Total Disbursed", f"${summary['total_disbursed']:,.2f}")
m[1].metric("Total Paid", f"${summary['total_paid']:,.2f}")
m[2].metric("Total Interest", f"${summary['total_interest_paid']:,.2f}")
m[3].metric(
    "Ending Balance",
    f"${summary['ending_balance']:,.2f}",
    delta=(f"+${summary['ending_accrued_interest']:,.2f} accrued"
           if summary["ending_accrued_interest"] > 0.005 else None),
)
m[4].metric("Net Cost (Paid − Disbursed)", f"${summary['net_cost']:,.2f}")

# ---------- Schedule table ----------
st.subheader("Schedule")
df = pd.DataFrame([r.__dict__ for r in rows])
if not df.empty:
    df_display = df.rename(columns={
        "seq": "#",
        "date": "Date",
        "kind": "Type",
        "description": "Description",
        "cash_flow": "Cash Flow",
        "interest": "Interest",
        "principal": "Principal",
        "balance": "Balance",
        "accrued_interest": "Accrued Int.",
    })
    money_cols = ["Cash Flow", "Interest", "Principal", "Balance", "Accrued Int."]
    st.dataframe(
        df_display.style.format({c: "${:,.2f}" for c in money_cols}),
        use_container_width=True,
        height=460,
        hide_index=True,
    )

    # Balance chart
    chart_df = df[["date", "balance"]].copy()
    chart_df.columns = ["Date", "Balance"]
    chart_df = chart_df.set_index("Date")
    st.subheader("Balance Over Time")
    st.line_chart(chart_df, height=240)

# ---------- Exports ----------
st.subheader("Export")
loan_meta = {
    "title": f"Amortization — {label}" if label else "Loan Amortization Schedule",
    "borrower": label,
    "nominal_annual_rate": rate,
    "day_count": day_count,
    "compounding": compounding,
    "first_date": summary.get("first_date"),
    "last_date": summary.get("last_date"),
    "row_count": summary.get("row_count", 0),
}

ex_col1, ex_col2, _ = st.columns([1, 1, 4])
try:
    xlsx_bytes = to_excel(rows, summary, loan_meta)
    ex_col1.download_button(
        "📊 Download Excel",
        data=xlsx_bytes,
        file_name=f"amortization_{label or 'loan'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
except Exception as exc:
    ex_col1.error(f"Excel export failed: {exc}")

try:
    pdf_bytes = to_pdf(rows, summary, loan_meta)
    ex_col2.download_button(
        "📄 Download PDF",
        data=pdf_bytes,
        file_name=f"amortization_{label or 'loan'}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
except Exception as exc:
    ex_col2.error(f"PDF export failed: {exc}")

with st.expander("About this tool"):
    st.markdown("""
    **Loan Amortization** — event-based modeling, like TValue.

    **How to use it**
    1. Set the **rate** and **day count** at the top.
    2. Build your loan in the **Events** table:
        - Each **Loan** row is a disbursement (date + amount).
        - Each **Payment** row is a series: date is the first payment, **Number** is how many,
          **Frequency** controls spacing.
    3. **Special** column on payments:
        - *blank* — fixed amount you type into the Amount column
        - *Interest Only* — auto-computes accrued interest each period
        - *P&I* — solves for level principal+interest payment across the series

    **Tips**
    - Multiple loans? Add multiple Loan rows on different dates — they layer onto the balance.
    - Balloon? Add a final Payment row with the balloon amount, Number=1.
    - Skip a payment? Don't add a row for that period.
    """)
