"""Event-based loan amortization engine.

Modeled after TValue: a loan is a chronological series of EVENTS — Loan
disbursements and Payment series. Interest accrues continuously between
events using a day-count convention and is paid down on Payment events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from dateutil.relativedelta import relativedelta

EventType = Literal["Loan", "Payment"]
SpecialSeries = Literal["", "Interest Only", "P&I", "Principal"]
Frequency = Literal["Monthly", "Bi-Weekly", "Weekly", "Quarterly", "Semi-Annually", "Annually"]
DayCount = Literal["Actual/365", "Actual/360", "30/360"]

PERIODS_PER_YEAR = {
    "Weekly": 52, "Bi-Weekly": 26, "Monthly": 12,
    "Quarterly": 4, "Semi-Annually": 2, "Annually": 1,
}


def _round(value: float) -> float:
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _advance(d: date, freq: Frequency) -> date:
    if freq == "Monthly":
        return d + relativedelta(months=1)
    if freq == "Quarterly":
        return d + relativedelta(months=3)
    if freq == "Semi-Annually":
        return d + relativedelta(months=6)
    if freq == "Annually":
        return d + relativedelta(years=1)
    if freq == "Bi-Weekly":
        return d + timedelta(weeks=2)
    if freq == "Weekly":
        return d + timedelta(weeks=1)
    raise ValueError(freq)


def _day_count_fraction(d1: date, d2: date, convention: DayCount) -> float:
    """Year fraction between two dates per convention."""
    if convention == "30/360":
        d1d, d2d = min(d1.day, 30), min(d2.day, 30)
        days = 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (d2d - d1d)
        return days / 360.0
    days = (d2 - d1).days
    if convention == "Actual/360":
        return days / 360.0
    return days / 365.0  # Actual/365 default


@dataclass
class Event:
    """A single loan or payment event row from the editor."""
    event_type: EventType
    date: date
    amount: float = 0.0  # disbursement amount or per-payment amount
    number: int = 1  # how many payments in this series (Payment only)
    frequency: Frequency = "Monthly"
    special: SpecialSeries = ""
    label: str = ""


@dataclass
class LoanConfig:
    nominal_annual_rate: float  # percent, e.g. 7.75
    day_count: DayCount = "Actual/365"
    compounding: str = "Monthly"  # informational
    label: str = ""


@dataclass
class ScheduleRow:
    seq: int
    date: date
    kind: str  # "Loan" or "Payment"
    description: str
    cash_flow: float  # absolute dollars (positive)
    interest: float
    principal: float
    balance: float  # principal balance after this row
    accrued_interest: float  # unpaid interest carried after this row


@dataclass
class _Tx:
    """Internal expanded transaction (one row in the schedule)."""
    date: date
    kind: str  # "Loan" or "Payment"
    amount: float
    special: SpecialSeries
    seq_in_series: int  # 1-based
    series_size: int
    series_label: str  # e.g. "Loan 1" or "Series 2"
    frequency: Frequency = "Monthly"


def expand_events(events: list[Event]) -> list[_Tx]:
    """Expand each event into one transaction per actual cash flow."""
    txs: list[_Tx] = []
    loan_count = 0
    payment_series_count = 0
    for ev in events:
        if ev.event_type == "Loan":
            loan_count += 1
            txs.append(_Tx(
                date=ev.date,
                kind="Loan",
                amount=ev.amount,
                special="",
                seq_in_series=1,
                series_size=1,
                series_label=ev.label or f"Loan {loan_count}",
                frequency=ev.frequency,
            ))
        else:
            payment_series_count += 1
            d = ev.date
            label = ev.label or f"Series {payment_series_count}"
            for i in range(max(1, ev.number)):
                txs.append(_Tx(
                    date=d,
                    kind="Payment",
                    amount=ev.amount,
                    special=ev.special,
                    seq_in_series=i + 1,
                    series_size=ev.number,
                    series_label=label,
                    frequency=ev.frequency,
                ))
                d = _advance(d, ev.frequency)
    # Loan before Payment on same date
    txs.sort(key=lambda t: (t.date, 0 if t.kind == "Loan" else 1))
    return txs


def _solve_level_payment(balance: float, daily_rate: float, dates: list[date],
                          day_count: DayCount) -> float:
    """Solve for level periodic payment that pays balance to zero across given dates.

    Uses present-value Newton's method on the actual day-count between dates.
    """
    if not dates or balance <= 0:
        return 0.0

    def pv_residual(pmt: float) -> float:
        bal = balance
        prior = dates[0]
        # interest accrues from "now" (time of first payment minus 1 period?) — for simplicity
        # treat balance as outstanding at first payment date, no accrual for first period
        for i, d in enumerate(dates):
            if i > 0:
                yf = _day_count_fraction(prior, d, day_count)
                bal += bal * daily_rate * 365 * yf  # daily_rate*365 = annual; *yf = period
            bal -= pmt
            prior = d
        return bal  # want zero

    # bisection — robust enough
    lo, hi = 0.0, balance * 10
    for _ in range(80):
        mid = (lo + hi) / 2
        if pv_residual(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build_schedule(
    events: list[Event],
    config: LoanConfig,
) -> tuple[list[ScheduleRow], dict]:
    """Walk events chronologically and produce a schedule + summary.

    Interest accrual model (TValue-aligned):
      For each segment between consecutive transactions, interest is computed as
        balance × period_rate × (segment_days / period_days)
      where the "period" is bounded by the previous Payment date (or the first
      event) and the next Payment date, and period_rate = annual_rate / periods_per_year
      using the next Payment's frequency. This makes IO payments CONSTANT
      month-to-month (since segment_days == period_days when no mid-period
      balance change occurs), while still attributing stub-period interest
      correctly when a Loan event lands mid-period.
    """
    txs = expand_events(events)
    if not txs:
        return [], {
            "total_disbursed": 0, "total_interest_paid": 0, "total_principal_paid": 0,
            "total_paid": 0, "ending_balance": 0, "ending_accrued_interest": 0,
            "row_count": 0, "first_date": None, "last_date": None, "net_cost": 0,
        }

    annual_rate = config.nominal_annual_rate / 100.0

    # Pre-compute the "next payment" for each tx so we can determine
    # period_rate and period_days during the segment leading up to it.
    next_payment_idx: list[int] = [-1] * len(txs)
    nxt = -1
    for i in range(len(txs) - 1, -1, -1):
        if txs[i].kind == "Payment":
            nxt = i
        next_payment_idx[i] = nxt

    # Period start = previous Payment date (or first tx date if none yet)
    def period_bounds_for(payment_idx: int) -> tuple[date, date, int]:
        """Returns (period_start, period_end, period_days) for a payment tx."""
        if payment_idx < 0:
            return txs[0].date, txs[0].date, 1
        end = txs[payment_idx].date
        # find prior payment
        start = None
        for j in range(payment_idx - 1, -1, -1):
            if txs[j].kind == "Payment":
                start = txs[j].date
                break
        if start is None:
            start = txs[0].date  # use first event (loan) as series anchor
        days = max(1, (end - start).days)
        return start, end, days

    rows: list[ScheduleRow] = []
    balance = 0.0
    accrued_interest = 0.0
    last_date = txs[0].date
    seq = 0

    # Index from each P&I tx to its series-start tx
    series_start_idx: dict[int, int] = {}
    last_start = -1
    for i, t in enumerate(txs):
        if t.kind == "Payment" and t.special == "P&I":
            if t.seq_in_series == 1:
                last_start = i
            series_start_idx[i] = last_start
        else:
            last_start = -1
    pi_solved: dict[int, float] = {}

    for i, tx in enumerate(txs):
        seq += 1
        # Accrue interest for the segment from last_date to tx.date,
        # using the period rate of the next-upcoming payment.
        if tx.date > last_date:
            np_idx = next_payment_idx[i] if tx.kind != "Payment" else i
            if np_idx >= 0:
                np = txs[np_idx]
                _, _, period_days = period_bounds_for(np_idx)
                period_rate = annual_rate / PERIODS_PER_YEAR[np.frequency]
                segment_days = (tx.date - last_date).days
                accrued_interest += balance * period_rate * (segment_days / period_days)
            # else: no upcoming payment — fall back to day-count year fraction
            else:
                yf = _day_count_fraction(last_date, tx.date, config.day_count)
                accrued_interest += balance * annual_rate * yf

        row_interest = 0.0
        row_principal = 0.0
        cash_flow = 0.0
        description = ""

        if tx.kind == "Loan":
            balance += tx.amount
            cash_flow = tx.amount
            description = f"{tx.series_label} disbursement"
        else:
            if tx.special == "Interest Only":
                payment = accrued_interest
                description = f"{tx.series_label} — Interest Only ({tx.seq_in_series}/{tx.series_size})"
            elif tx.special == "Principal":
                # Principal-only payment: full amount goes to principal,
                # accrued interest is NOT reduced (carries to next interest payment).
                pay_amt = min(tx.amount, balance)
                balance -= pay_amt
                row_principal = pay_amt
                row_interest = 0.0
                cash_flow = pay_amt
                description = (f"{tx.series_label} — Principal "
                               f"({tx.seq_in_series}/{tx.series_size})"
                               if tx.series_size > 1 else
                               f"{tx.series_label} — Principal Reduction")
                rows.append(ScheduleRow(
                    seq=seq, date=tx.date, kind=tx.kind, description=description,
                    cash_flow=_round(cash_flow),
                    interest=_round(row_interest),
                    principal=_round(row_principal),
                    balance=_round(balance),
                    accrued_interest=_round(accrued_interest),
                ))
                last_date = tx.date
                continue
            elif tx.special == "P&I":
                start_i = series_start_idx[i]
                if start_i not in pi_solved:
                    series_dates = [
                        txs[j].date for j in range(start_i, len(txs))
                        if txs[j].kind == "Payment" and txs[j].special == "P&I"
                        and series_start_idx.get(j) == start_i
                    ]
                    pv_balance = balance + accrued_interest
                    daily = annual_rate / 365.0
                    pi_solved[start_i] = _solve_level_payment(
                        pv_balance, daily, series_dates, config.day_count
                    )
                payment = pi_solved[start_i]
                description = f"{tx.series_label} — P&I ({tx.seq_in_series}/{tx.series_size})"
            else:
                payment = tx.amount
                description = (f"{tx.series_label} — Payment "
                               f"({tx.seq_in_series}/{tx.series_size})"
                               if tx.series_size > 1 else
                               f"{tx.series_label} — Payment")

            interest_portion = min(payment, accrued_interest)
            principal_portion = payment - interest_portion
            if principal_portion > balance:
                principal_portion = balance
                payment = interest_portion + principal_portion
            accrued_interest -= interest_portion
            balance -= principal_portion
            row_interest = interest_portion
            row_principal = principal_portion
            cash_flow = payment

        rows.append(ScheduleRow(
            seq=seq, date=tx.date, kind=tx.kind, description=description,
            cash_flow=_round(cash_flow),
            interest=_round(row_interest),
            principal=_round(row_principal),
            balance=_round(balance),
            accrued_interest=_round(accrued_interest),
        ))
        last_date = tx.date

    total_disbursed = sum(r.cash_flow for r in rows if r.kind == "Loan")
    total_paid = sum(r.cash_flow for r in rows if r.kind == "Payment")
    total_interest = sum(r.interest for r in rows if r.kind == "Payment")
    total_principal = sum(r.principal for r in rows if r.kind == "Payment")

    summary = {
        "total_disbursed": _round(total_disbursed),
        "total_paid": _round(total_paid),
        "total_interest_paid": _round(total_interest),
        "total_principal_paid": _round(total_principal),
        "ending_balance": _round(rows[-1].balance) if rows else 0,
        "ending_accrued_interest": _round(rows[-1].accrued_interest) if rows else 0,
        "net_cost": _round(total_paid - total_disbursed),
        "first_date": rows[0].date if rows else None,
        "last_date": rows[-1].date if rows else None,
        "row_count": len(rows),
    }
    return rows, summary
