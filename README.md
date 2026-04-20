# Loan Amortization

Self-hosted web app to replace TValue Online. Python + Streamlit.

## Setup

```bash
cd "/Users/laceyangelier/14 Day Automation/loan_amortization"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
streamlit run app.py
```

The app opens at http://localhost:8501.

## Features

- Payment frequencies: weekly, bi-weekly, monthly, quarterly, semi-annual, annual
- Compounding independent of payment frequency (incl. continuous)
- Extra payments: one-time or recurring, with optional end date
- Balloon payments
- Excel (.xlsx) and PDF exports with full schedule + summary
- Payoff date, total interest, and interest-saved metrics

## Files

- `amortization.py` — loan math engine
- `exports.py` — Excel + PDF renderers
- `app.py` — Streamlit UI
