"""Subscription billing periods and mid-period plan changes."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from billing.money import as_money, round_cents


@dataclass(frozen=True)
class Proration:
    credit: Decimal
    charge: Decimal
    days_remaining: int
    period_days: int


def period_end(start: date) -> date:
    """Same day next month, clamped to the last day of that month (SPEC §4)."""
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def prorate(start: date, change_date: date, old_price, new_price) -> Proration:
    end = period_end(start)
    if not start <= change_date < end:
        raise ValueError("change_date is outside the billing period")
    period_days = (end - start).days
    days_remaining = (end - change_date).days
    fraction = Decimal(days_remaining) / Decimal(period_days)
    return Proration(
        credit=round_cents(as_money(old_price) * fraction),
        charge=round_cents(as_money(new_price) * fraction),
        days_remaining=days_remaining,
        period_days=period_days,
    )
