"""Streamlit loan amortization app — a TValue Online replacement.

Run:
    streamlit run app.py
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from amortization import (
    COMPOUNDING_PER_YEAR,
    PERIODS_PER_YEAR,
    ExtraPayment,
    LoanInputs,
    build_schedule,
    standard_payment,
)
from exports import to_excel, to_pdf


st.set_page_config(
    page_title="Loan Amortization",
    page_icon="💰",
    layout="wide",
)

st.title("💰 Loan Amortization")
st.caption("Build schedules, model extra payments, export to PDF & Excel.")

# ----- Sidebar: loan inputs -----
with st.sidebar:
    st.header("Loan Details")
    borrower = st.text_input("Borrower / Label", value="")
    principal = st.number_input("Loan Amount ($)", min_value=0.0, value=250_000.00, step=1_000.00, format="%.2f")
    annual_rate = st.number_input("Annual Rate (%)", min_value=0.0, max_value=100.0, value=6.500, step=0.125, format="%.4f")
    term_years = st.number_input("Term (years)", min_value=0.0, max_value=60.0, value=30.0, step=0.5)
    payment_frequency = st.selectbox("Payment Frequency", list(PERIODS_PER_YEAR.keys()), index=2)
    compounding = st.selectbox("Compounding", list(COMPOUNDING_PER_YEAR.keys()) + ["Continuous"], index=1)
    start_date = st.date_input("Loan Start Date", value=date.today())
    first_pmt = st.date_input(
        "First Payment Date",
        value=start_date + timedelta(days=30),
    )
    loan_type = st.radio("Loan Type", ["Standard", "Interest-Only"], horizontal=True)
    io_period_years = 0.0
    io_then = "Amortize"
    if loan_type == "Interest-Only":
        io_period_years = st.number_input(
            "Interest-Only Period (years)",
            min_value=0.0, max_value=float(term_years),
            value=min(5.0, float(term_years)), step=0.5,
            help="During this period, payments cover interest only. Set equal to term for fully IO.",
        )
        io_then = st.selectbox(
            "After IO period",
            ["Amortize", "Balloon"],
            help="Amortize: converts to P&I for remaining term. Balloon: remaining balance due at end of IO period.",
        )

    use_custom_pmt = st.checkbox("Override scheduled payment")
    payment_override = None
    if use_custom_pmt:
        payment_override = st.number_input("Custom Payment ($)", min_value=0.0, value=0.0, step=10.0, format="%.2f")
    balloon_enabled = st.checkbox("Balloon payment (explicit date)")
    balloon_date = None
    if balloon_enabled:
        balloon_date = st.date_input("Balloon Date", value=date.today() + timedelta(days=365 * 5))

# ----- Main area -----
st.subheader("Extra Payments")
st.caption("Add one-time or recurring extra principal payments. They're applied on the payment date.")

if "extras" not in st.session_state:
    st.session_state.extras: list[dict] = []

cols = st.columns([1.2, 1.2, 1.2, 1.4, 1.4, 0.8])
cols[0].markdown("**Start Date**")
cols[1].markdown("**Amount ($)**")
cols[2].markdown("**Recurring?**")
cols[3].markdown("**Frequency**")
cols[4].markdown("**End Date (optional)**")
cols[5].markdown("**Remove**")

for i, ex in enumerate(list(st.session_state.extras)):
    c = st.columns([1.2, 1.2, 1.2, 1.4, 1.4, 0.8])
    ex["start_date"] = c[0].date_input("", value=ex["start_date"], key=f"ex_sd_{i}", label_visibility="collapsed")
    ex["amount"] = c[1].number_input("", min_value=0.0, value=float(ex["amount"]), step=50.0, format="%.2f",
                                      key=f"ex_amt_{i}", label_visibility="collapsed")
    ex["recurring"] = c[2].checkbox("", value=ex["recurring"], key=f"ex_rec_{i}", label_visibility="collapsed")
    ex["frequency"] = c[3].selectbox("", list(PERIODS_PER_YEAR.keys()),
                                      index=list(PERIODS_PER_YEAR.keys()).index(ex["frequency"]),
                                      key=f"ex_freq_{i}", label_visibility="collapsed",
                                      disabled=not ex["recurring"])
    end_val = c[4].date_input("", value=ex.get("end_date") or date.today() + timedelta(days=365*5),
                               key=f"ex_end_{i}", label_visibility="collapsed",
                               disabled=not ex["recurring"])
    ex["end_date"] = end_val if ex["recurring"] else None
    if c[5].button("🗑", key=f"ex_del_{i}"):
        st.session_state.extras.pop(i)
        st.rerun()

add_cols = st.columns([1, 1, 6])
if add_cols[0].button("+ Add extra payment"):
    st.session_state.extras.append({
        "start_date": date.today(),
        "amount": 100.00,
        "recurring": False,
        "frequency": "Monthly",
        "end_date": None,
    })
    st.rerun()

if add_cols[1].button("Clear all", disabled=not st.session_state.extras):
    st.session_state.extras = []
    st.rerun()

# ----- Build schedule -----
extras = [
    ExtraPayment(
        start_date=e["start_date"],
        amount=float(e["amount"]),
        recurring=bool(e["recurring"]),
        frequency=e["frequency"],
        end_date=e["end_date"],
    )
    for e in st.session_state.extras
    if e["amount"] > 0
]

inputs = LoanInputs(
    principal=principal,
    annual_rate=annual_rate,
    term_years=term_years,
    start_date=start_date,
    first_payment_date=first_pmt,
    payment_frequency=payment_frequency,
    compounding=compounding,
    balloon_date=balloon_date,
    payment_override=payment_override if payment_override and payment_override > 0 else None,
    extras=extras,
    loan_type=loan_type,
    io_period_years=io_period_years,
    io_then=io_then,
)

try:
    rows, summary = build_schedule(inputs)
except Exception as exc:
    st.error(f"Could not build schedule: {exc}")
    st.stop()

# ----- Summary tiles -----
st.subheader("Summary")
m = st.columns(5)
m[0].metric("Scheduled Payment", f"${summary['scheduled_payment']:,.2f}")
m[1].metric("Total Interest", f"${summary['total_interest']:,.2f}")
m[2].metric("Total Paid", f"${summary['total_paid']:,.2f}")
m[3].metric("Payoff Date", str(summary.get("payoff_date") or "—"))
m[4].metric("Interest Saved", f"${summary['interest_saved']:,.2f}",
            delta=f"−{summary['periods_saved']} periods" if summary["periods_saved"] else None)

# ----- Schedule table -----
st.subheader("Amortization Schedule")
df = pd.DataFrame([r.__dict__ for r in rows])
if not df.empty:
    df_display = df.rename(columns={
        "period": "#",
        "payment_date": "Date",
        "beginning_balance": "Begin Balance",
        "scheduled_payment": "Scheduled",
        "extra_payment": "Extra",
        "interest": "Interest",
        "principal": "Principal",
        "total_payment": "Total Pmt",
        "ending_balance": "End Balance",
    })
    money_cols = ["Begin Balance", "Scheduled", "Extra", "Interest", "Principal", "Total Pmt", "End Balance"]
    st.dataframe(
        df_display.style.format({c: "${:,.2f}" for c in money_cols}),
        use_container_width=True,
        height=460,
        hide_index=True,
    )

# ----- Balance chart -----
if not df.empty:
    st.subheader("Balance Over Time")
    chart_df = df[["payment_date", "ending_balance"]].copy()
    chart_df.columns = ["Date", "Balance"]
    chart_df = chart_df.set_index("Date")
    st.line_chart(chart_df, height=240)

# ----- Exports -----
st.subheader("Export")
loan_type_label = loan_type
if loan_type == "Interest-Only":
    loan_type_label = f"Interest-Only ({io_period_years:g} yrs, then {io_then})"

loan_meta = {
    "title": f"Amortization — {borrower}" if borrower else "Loan Amortization Schedule",
    "borrower": borrower,
    "principal": principal,
    "annual_rate": annual_rate,
    "term_years": term_years,
    "payment_frequency": payment_frequency,
    "compounding": compounding,
    "start_date": start_date,
    "first_payment_date": first_pmt,
    "loan_type": loan_type_label,
}

ex_col1, ex_col2, _ = st.columns([1, 1, 4])
try:
    xlsx_bytes = to_excel(rows, summary, loan_meta)
    ex_col1.download_button(
        "📊 Download Excel",
        data=xlsx_bytes,
        file_name=f"amortization_{borrower or 'loan'}.xlsx",
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
        file_name=f"amortization_{borrower or 'loan'}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
except Exception as exc:
    ex_col2.error(f"PDF export failed: {exc}")

with st.expander("About this tool"):
    st.markdown("""
    **Loan Amortization** — a self-hosted alternative to TValue Online.

    **Current features**
    - Multiple payment frequencies (weekly through annual)
    - Compounding independent of payment frequency
    - Extra payments: one-time or recurring, with optional end date
    - Balloon payments
    - Excel & PDF exports with full schedule and summary

    **Tips**
    - Override the scheduled payment to model interest-only or custom terms.
    - Set an end date on recurring extras to model "pay double for 2 years, then drop off."
    """)
