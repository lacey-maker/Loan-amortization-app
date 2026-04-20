"""Loan amortization engine with extra-payment support."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from dateutil.relativedelta import relativedelta

Frequency = Literal["Monthly", "Bi-Weekly", "Weekly", "Quarterly", "Semi-Annually", "Annually"]

PERIODS_PER_YEAR = {
    "Weekly": 52,
    "Bi-Weekly": 26,
    "Monthly": 12,
    "Quarterly": 4,
    "Semi-Annually": 2,
    "Annually": 1,
}

Compounding = Literal["Monthly", "Daily", "Annually", "Semi-Annually", "Quarterly", "Continuous"]

COMPOUNDING_PER_YEAR = {
    "Daily": 365,
    "Monthly": 12,
    "Quarterly": 4,
    "Semi-Annually": 2,
    "Annually": 1,
}


@dataclass
class ExtraPayment:
    """Additional principal payment applied on top of scheduled P&I."""
    start_date: date
    amount: float
    recurring: bool = False
    frequency: Frequency = "Monthly"
    end_date: date | None = None

    def applies_on(self, period_date: date) -> bool:
        if period_date < self.start_date:
            return False
        if self.end_date and period_date > self.end_date:
            return False
        if not self.recurring:
            return period_date == self.start_date
        return True


LoanType = Literal["Standard", "Interest-Only"]


@dataclass
class LoanInputs:
    principal: float
    annual_rate: float  # as percent, e.g. 6.5
    term_years: float
    start_date: date
    first_payment_date: date | None = None
    payment_frequency: Frequency = "Monthly"
    compounding: Compounding = "Monthly"
    balloon_date: date | None = None
    payment_override: float | None = None  # if user wants fixed payment
    extras: list[ExtraPayment] = field(default_factory=list)
    loan_type: LoanType = "Standard"
    io_period_years: float = 0.0  # interest-only period length (if loan_type == "Interest-Only")
    io_then: Literal["Amortize", "Balloon"] = "Amortize"  # what happens after IO period

    def periods_per_year(self) -> int:
        return PERIODS_PER_YEAR[self.payment_frequency]

    def total_periods(self) -> int:
        return int(round(self.term_years * self.periods_per_year()))

    def period_rate(self) -> float:
        """Periodic rate, respecting compounding convention.

        Converts nominal annual rate with the stated compounding to an
        equivalent rate per payment period.
        """
        annual = self.annual_rate / 100.0
        if annual == 0:
            return 0.0
        if self.compounding == "Continuous":
            # e^(r/n) - 1
            import math
            return math.exp(annual / self.periods_per_year()) - 1
        m = COMPOUNDING_PER_YEAR[self.compounding]
        n = self.periods_per_year()
        # effective annual rate, then convert to period rate
        eff = (1 + annual / m) ** m - 1
        return (1 + eff) ** (1 / n) - 1

    def period_delta(self) -> relativedelta | "timedelta":
        from datetime import timedelta
        freq = self.payment_frequency
        if freq == "Monthly":
            return relativedelta(months=1)
        if freq == "Quarterly":
            return relativedelta(months=3)
        if freq == "Semi-Annually":
            return relativedelta(months=6)
        if freq == "Annually":
            return relativedelta(years=1)
        if freq == "Bi-Weekly":
            return timedelta(weeks=2)
        if freq == "Weekly":
            return timedelta(weeks=1)
        raise ValueError(freq)


@dataclass
class ScheduleRow:
    period: int
    payment_date: date
    beginning_balance: float
    scheduled_payment: float
    extra_payment: float
    interest: float
    principal: float
    total_payment: float
    ending_balance: float


def _round(value: float) -> float:
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def standard_payment(principal: float, period_rate: float, periods: int) -> float:
    """Level P&I payment for a fully-amortizing loan."""
    if periods <= 0:
        return 0.0
    if period_rate == 0:
        return principal / periods
    r = period_rate
    n = periods
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def build_schedule(inputs: LoanInputs) -> tuple[list[ScheduleRow], dict]:
    """Generate an amortization schedule and summary totals."""
    r = inputs.period_rate()
    n = inputs.total_periods()
    ppy = inputs.periods_per_year()

    io_periods = 0
    if inputs.loan_type == "Interest-Only":
        io_periods = int(round(inputs.io_period_years * ppy))
        io_periods = min(io_periods, n)

    # scheduled P&I payment (used once IO period ends, or for the whole loan if Standard)
    if inputs.payment_override:
        scheduled = inputs.payment_override
    elif inputs.loan_type == "Interest-Only" and inputs.io_then == "Balloon" and io_periods >= n:
        scheduled = 0.0  # IO only, balloon at end
    else:
        amort_periods = max(1, n - io_periods)
        scheduled = standard_payment(inputs.principal, r, amort_periods)

    first_pmt = inputs.first_payment_date or (inputs.start_date + inputs.period_delta())
    delta = inputs.period_delta()

    rows: list[ScheduleRow] = []
    balance = inputs.principal
    pmt_date = first_pmt
    period = 0
    max_iter = n * 3 + 500  # safety
    amort_pmt_recalculated = False

    while balance > 0.005 and period < max_iter:
        period += 1
        beginning = balance
        interest = beginning * r
        is_io_period = inputs.loan_type == "Interest-Only" and period <= io_periods

        # extra payments that apply on this date
        extra = 0.0
        for ex in inputs.extras:
            if ex.applies_on(pmt_date):
                extra += ex.amount

        # Recalculate amortizing payment when transitioning out of IO period
        # (in case extras during IO changed the balance).
        if (
            inputs.loan_type == "Interest-Only"
            and not is_io_period
            and not amort_pmt_recalculated
            and not inputs.payment_override
            and inputs.io_then == "Amortize"
        ):
            remaining = max(1, n - io_periods)
            scheduled = standard_payment(beginning, r, remaining)
            amort_pmt_recalculated = True

        # End-of-IO balloon: pay off remaining balance
        end_of_io_balloon = (
            inputs.loan_type == "Interest-Only"
            and inputs.io_then == "Balloon"
            and period == max(io_periods, 1)
        )

        # Explicit balloon date: pay off in full
        if inputs.balloon_date and pmt_date >= inputs.balloon_date:
            principal_portion = beginning
            total_payment = interest + principal_portion + extra
            rows.append(ScheduleRow(
                period=period, payment_date=pmt_date,
                beginning_balance=_round(beginning),
                scheduled_payment=_round(interest + principal_portion),
                extra_payment=_round(extra),
                interest=_round(interest),
                principal=_round(principal_portion),
                total_payment=_round(total_payment),
                ending_balance=0.0,
            ))
            break

        if is_io_period and not end_of_io_balloon:
            # Interest-only: scheduled pays interest; extras reduce principal
            sched_this = interest
            extra_this = extra
            principal_portion = min(extra, beginning)
            if principal_portion >= beginning:
                principal_portion = beginning
                balance = 0.0
            else:
                balance = beginning - principal_portion
            total_payment = sched_this + extra_this
            rows.append(ScheduleRow(
                period=period, payment_date=pmt_date,
                beginning_balance=_round(beginning),
                scheduled_payment=_round(sched_this),
                extra_payment=_round(extra_this),
                interest=_round(interest),
                principal=_round(principal_portion),
                total_payment=_round(total_payment),
                ending_balance=_round(balance),
            ))
            pmt_date = pmt_date + delta
            continue

        if end_of_io_balloon:
            # Final period of IO-only loan: balloon remaining balance
            principal_portion = beginning
            sched_this = interest + principal_portion
            extra_this = 0.0  # already paid everything off
            total_payment = sched_this
            rows.append(ScheduleRow(
                period=period, payment_date=pmt_date,
                beginning_balance=_round(beginning),
                scheduled_payment=_round(sched_this),
                extra_payment=_round(extra_this),
                interest=_round(interest),
                principal=_round(principal_portion),
                total_payment=_round(total_payment),
                ending_balance=0.0,
            ))
            break

        # Standard amortizing period
        sched_principal = scheduled - interest
        principal_portion = sched_principal + extra

        if principal_portion >= beginning:
            principal_portion = beginning
            sched_this = min(scheduled, beginning + interest)
            extra_this = max(0.0, principal_portion - (sched_this - interest))
            total_payment = sched_this + extra_this
            balance = 0.0
        else:
            sched_this = scheduled
            extra_this = extra
            total_payment = sched_this + extra_this
            balance = beginning - principal_portion

        rows.append(ScheduleRow(
            period=period, payment_date=pmt_date,
            beginning_balance=_round(beginning),
            scheduled_payment=_round(sched_this),
            extra_payment=_round(extra_this),
            interest=_round(interest),
            principal=_round(principal_portion),
            total_payment=_round(total_payment),
            ending_balance=_round(balance),
        ))
        pmt_date = pmt_date + delta

    total_interest = sum(row.interest for row in rows)
    total_principal = sum(row.principal for row in rows)
    total_paid = sum(row.total_payment for row in rows)
    total_extra = sum(row.extra_payment for row in rows)

    # Baseline for comparison (standard amortization, no extras, over full term)
    if r > 0:
        baseline_pmt = standard_payment(inputs.principal, r, n)
        baseline_total_interest = baseline_pmt * n - inputs.principal
    else:
        baseline_total_interest = 0.0
    baseline_periods = n
    interest_saved = max(0.0, baseline_total_interest - total_interest)
    periods_saved = max(0, baseline_periods - len(rows))

    summary = {
        "scheduled_payment": _round(scheduled),
        "period_rate": r,
        "periods": len(rows),
        "baseline_periods": baseline_periods,
        "total_interest": _round(total_interest),
        "total_principal": _round(total_principal),
        "total_paid": _round(total_paid),
        "total_extra": _round(total_extra),
        "interest_saved": _round(interest_saved),
        "periods_saved": periods_saved,
        "payoff_date": rows[-1].payment_date if rows else None,
    }
    return rows, summary
