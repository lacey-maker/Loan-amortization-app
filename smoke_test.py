"""Smoke tests for the event-based engine and exports."""
from datetime import date

from amortization import Event, LoanConfig, build_schedule
from exports import to_excel, to_pdf


def test_tvalue_example():
    """Reproduces the user's TValue screenshot:
    - $20,000 loan 9/19/2025
    - 5 IO monthly payments starting 10/19/2025
    - $159,000 additional loan 2/23/2026
    - 24 IO monthly payments starting 3/19/2026
    - $180,173.14 balloon on 3/19/2028
    """
    events = [
        Event("Loan", date(2025, 9, 19), 20000.00),
        Event("Payment", date(2025, 10, 19), 0, number=5, frequency="Monthly", special="Interest Only"),
        Event("Loan", date(2026, 2, 23), 159000.00),
        Event("Payment", date(2026, 3, 19), 0, number=24, frequency="Monthly", special="Interest Only"),
        Event("Payment", date(2028, 3, 19), 180173.14, number=1),
    ]
    cfg = LoanConfig(nominal_annual_rate=7.75, day_count="Actual/365")
    rows, summary = build_schedule(events, cfg)

    assert summary["total_disbursed"] == 179000.00, summary["total_disbursed"]
    # 5 IO + 24 IO + 1 balloon + 2 loan rows = 32 rows
    assert summary["row_count"] == 32, summary["row_count"]
    # ending balance should be near zero (within rounding)
    assert abs(summary["ending_balance"]) < 5.00, summary["ending_balance"]
    # IO payments are nonzero
    io_rows = [r for r in rows if "Interest Only" in r.description]
    assert len(io_rows) == 29
    assert all(r.interest > 0 for r in io_rows)
    print(f"TValue example OK — {summary['row_count']} rows, "
          f"interest paid ${summary['total_interest_paid']:,.2f}, "
          f"net cost ${summary['net_cost']:,.2f}")


def test_simple_amortization():
    """Standard 30-yr amortization via P&I special."""
    events = [
        Event("Loan", date(2026, 1, 1), 250000.00),
        Event("Payment", date(2026, 2, 1), 0, number=360, frequency="Monthly", special="P&I"),
    ]
    cfg = LoanConfig(nominal_annual_rate=6.5, day_count="Actual/365")
    rows, summary = build_schedule(events, cfg)
    # Should pay off near zero
    assert abs(summary["ending_balance"]) < 10.0, summary["ending_balance"]
    assert summary["row_count"] == 361  # 1 loan + 360 payments
    # Standard payment around $1,580/mo (give or take day-count effects)
    pi_rows = [r for r in rows if "P&I" in r.description]
    assert len(pi_rows) == 360
    avg_pmt = sum(r.cash_flow for r in pi_rows) / len(pi_rows)
    assert 1500 < avg_pmt < 1700, avg_pmt
    print(f"Standard amort OK — avg pmt ${avg_pmt:,.2f}, total interest ${summary['total_interest_paid']:,.2f}")


def test_multiple_loans():
    events = [
        Event("Loan", date(2026, 1, 1), 100000),
        Event("Loan", date(2026, 6, 1), 50000),
        Event("Payment", date(2027, 1, 1), 0, number=12, frequency="Monthly", special="Interest Only"),
        Event("Payment", date(2028, 1, 1), 150000, number=1),
    ]
    cfg = LoanConfig(nominal_annual_rate=6.0, day_count="Actual/365")
    rows, summary = build_schedule(events, cfg)
    assert summary["total_disbursed"] == 150000.00
    # 25 rows: 2 loans + 12 IO + 1 balloon = 15. Wait, let me recount: 2 loan + 12 IO + 1 balloon = 15.
    assert summary["row_count"] == 15, summary["row_count"]
    # Loan 2 rows should show balance jumping from 100k to 150k
    loan_rows = [r for r in rows if r.kind == "Loan"]
    assert loan_rows[0].balance == 100000.00
    assert loan_rows[1].balance == 150000.00
    # IO rows after first loan: principal stays at 150k after second loan
    io_rows = [r for r in rows if "Interest Only" in r.description]
    assert all(r.balance == 150000.00 for r in io_rows), [r.balance for r in io_rows]
    print(f"Multiple loans OK — {summary['row_count']} rows, paid ${summary['total_paid']:,.2f}, "
          f"ending balance ${summary['ending_balance']:,.2f}")


def test_exports():
    events = [
        Event("Loan", date(2026, 1, 1), 100000),
        Event("Payment", date(2026, 2, 1), 0, number=12, frequency="Monthly", special="Interest Only"),
        Event("Payment", date(2027, 2, 1), 100000, number=1),
    ]
    cfg = LoanConfig(nominal_annual_rate=6.0, day_count="Actual/365")
    rows, summary = build_schedule(events, cfg)
    meta = {
        "title": "Test Loan", "borrower": "Test",
        "nominal_annual_rate": 6.0, "day_count": "Actual/365",
        "compounding": "Monthly",
        "first_date": summary["first_date"], "last_date": summary["last_date"],
    }
    xlsx = to_excel(rows, summary, meta)
    pdf = to_pdf(rows, summary, meta)
    assert len(xlsx) > 1000 and xlsx[:2] == b"PK"
    assert len(pdf) > 1000 and pdf[:4] == b"%PDF"
    print(f"Exports OK — xlsx {len(xlsx):,} bytes, pdf {len(pdf):,} bytes")


if __name__ == "__main__":
    test_tvalue_example()
    test_simple_amortization()
    test_multiple_loans()
    test_exports()
    print("\nAll smoke tests passed.")
