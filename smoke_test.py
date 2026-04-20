"""Quick smoke test for the engine and exports."""
from datetime import date
from amortization import ExtraPayment, LoanInputs, build_schedule
from exports import to_excel, to_pdf


def test_basic():
    inp = LoanInputs(
        principal=250_000,
        annual_rate=6.5,
        term_years=30,
        start_date=date(2026, 1, 1),
        first_payment_date=date(2026, 2, 1),
        payment_frequency="Monthly",
        compounding="Monthly",
    )
    rows, summary = build_schedule(inp)
    # 30yr monthly = 360 periods
    assert len(rows) == 360, f"expected 360, got {len(rows)}"
    # standard payment on 250k @ 6.5%/30yr ≈ $1,580.17
    assert abs(summary["scheduled_payment"] - 1580.17) < 0.50, summary["scheduled_payment"]
    # final ending balance is zero
    assert rows[-1].ending_balance == 0.0
    print(f"Basic OK — scheduled_payment=${summary['scheduled_payment']:.2f}, "
          f"total_interest=${summary['total_interest']:,.2f}")


def test_extra_payments():
    inp = LoanInputs(
        principal=250_000,
        annual_rate=6.5,
        term_years=30,
        start_date=date(2026, 1, 1),
        first_payment_date=date(2026, 2, 1),
        payment_frequency="Monthly",
        compounding="Monthly",
        extras=[ExtraPayment(start_date=date(2026, 2, 1), amount=200.0, recurring=True, frequency="Monthly")],
    )
    rows, summary = build_schedule(inp)
    assert len(rows) < 360, "extra payments should shorten term"
    assert summary["interest_saved"] > 0
    assert summary["periods_saved"] > 0
    print(f"Extras OK — payoff in {len(rows)} periods (saved {summary['periods_saved']}), "
          f"interest saved ${summary['interest_saved']:,.2f}")


def test_zero_rate():
    inp = LoanInputs(
        principal=12_000, annual_rate=0.0, term_years=1,
        start_date=date(2026, 1, 1), first_payment_date=date(2026, 2, 1),
    )
    rows, summary = build_schedule(inp)
    assert len(rows) == 12
    assert abs(summary["scheduled_payment"] - 1000.00) < 0.01
    print(f"Zero-rate OK — payment=${summary['scheduled_payment']:.2f}")


def test_exports():
    inp = LoanInputs(
        principal=100_000, annual_rate=5.0, term_years=15,
        start_date=date(2026, 1, 1), first_payment_date=date(2026, 2, 1),
        extras=[ExtraPayment(start_date=date(2026, 6, 1), amount=5000.0, recurring=False)],
    )
    rows, summary = build_schedule(inp)
    meta = {
        "title": "Test Loan", "borrower": "Test Borrower",
        "principal": 100_000, "annual_rate": 5.0, "term_years": 15,
        "payment_frequency": "Monthly", "compounding": "Monthly",
        "start_date": inp.start_date, "first_payment_date": inp.first_payment_date,
    }
    xlsx = to_excel(rows, summary, meta)
    pdf = to_pdf(rows, summary, meta)
    assert len(xlsx) > 1000 and xlsx[:2] == b"PK", "xlsx not valid"
    assert len(pdf) > 1000 and pdf[:4] == b"%PDF", "pdf not valid"
    print(f"Exports OK — xlsx {len(xlsx):,} bytes, pdf {len(pdf):,} bytes")


def test_interest_only_then_amortize():
    # 5yr IO, then amortize remaining 25yr
    inp = LoanInputs(
        principal=300_000, annual_rate=6.0, term_years=30,
        start_date=date(2026, 1, 1), first_payment_date=date(2026, 2, 1),
        loan_type="Interest-Only", io_period_years=5, io_then="Amortize",
    )
    rows, summary = build_schedule(inp)
    # IO periods = 60 months; during those, principal should be 0
    for i in range(60):
        assert rows[i].principal == 0.0, f"row {i} should be IO, got principal {rows[i].principal}"
        assert abs(rows[i].scheduled_payment - 1500.00) < 1.0, rows[i].scheduled_payment  # 300k * 6%/12
    # After IO, balance should still be the original principal
    assert abs(rows[59].ending_balance - 300_000) < 1.0, rows[59].ending_balance
    # Last row: balance zero
    assert rows[-1].ending_balance == 0.0
    # Should finish around month 360 (60 IO + 300 amortizing)
    assert 358 <= len(rows) <= 360, len(rows)
    print(f"IO→Amortize OK — 60 IO months, then P&I ${rows[60].scheduled_payment:.2f}, total {len(rows)} periods")


def test_interest_only_balloon():
    inp = LoanInputs(
        principal=500_000, annual_rate=5.0, term_years=30,
        start_date=date(2026, 1, 1), first_payment_date=date(2026, 2, 1),
        loan_type="Interest-Only", io_period_years=10, io_then="Balloon",
    )
    rows, summary = build_schedule(inp)
    # 10 years = 120 months: 119 interest-only, final one is balloon
    assert len(rows) == 120, len(rows)
    # Last row should have the full principal
    assert abs(rows[-1].principal - 500_000) < 1.0, rows[-1].principal
    assert rows[-1].ending_balance == 0.0
    # Earlier rows: principal = 0
    assert rows[50].principal == 0.0
    print(f"IO→Balloon OK — final payment ${rows[-1].total_payment:,.2f} on {rows[-1].payment_date}")


def test_interest_only_with_extras():
    # Extras during IO should reduce principal, making the amortizing payment smaller
    inp = LoanInputs(
        principal=200_000, annual_rate=6.0, term_years=15,
        start_date=date(2026, 1, 1), first_payment_date=date(2026, 2, 1),
        loan_type="Interest-Only", io_period_years=3, io_then="Amortize",
        extras=[ExtraPayment(start_date=date(2026, 2, 1), amount=500.0,
                             recurring=True, frequency="Monthly")],
    )
    rows, summary = build_schedule(inp)
    # Balance at end of IO should be < original
    io_end_balance = rows[35].ending_balance  # after 36 months
    assert io_end_balance < 200_000, io_end_balance
    assert rows[-1].ending_balance == 0.0
    print(f"IO + extras OK — balance after IO ${io_end_balance:,.2f}, payoff {len(rows)} periods")


if __name__ == "__main__":
    test_basic()
    test_extra_payments()
    test_zero_rate()
    test_interest_only_then_amortize()
    test_interest_only_balloon()
    test_interest_only_with_extras()
    test_exports()
    print("\nAll smoke tests passed.")
