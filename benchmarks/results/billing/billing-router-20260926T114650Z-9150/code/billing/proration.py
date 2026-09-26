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
    """End of the billing period that starts on `start` (same day next month)."""
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def prorate(start: date, change_date: date, old_price, new_price) -> Proration:
    end = period_end(start)
    if not start <= change_date < end:
        raise ValueError("change_date is outside the billing period")
    period_days = (end - start).days
    days_remaining = (end - change_date).days
    return Proration(
        credit=round_cents(as_money(old_price) * days_remaining / period_days),
        charge=round_cents(as_money(new_price) * days_remaining / period_days),
        days_remaining=days_remaining,
        period_days=period_days,
    )
