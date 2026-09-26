"""Invoice totals and currency conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from billing.money import as_money, round_cents

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal = Decimal(0)

    @property
    def amount(self) -> Decimal:
        return as_money(self.quantity) * as_money(self.unit_price)


@dataclass(frozen=True)
class Invoice:
    lines: list[Line] = field(default_factory=list)
    percent_discount: Decimal = Decimal(0)
    coupon: Decimal = Decimal(0)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    discount: Decimal
    coupon: Decimal
    tax: Decimal
    total: Decimal


def _discount_factor(invoice: Invoice) -> Decimal:
    pct = as_money(invoice.percent_discount)
    if not 0 <= pct <= 100:
        raise ValueError("percent_discount must be between 0 and 100")
    return 1 - pct / HUNDRED


def compute_totals(invoice: Invoice) -> Totals:
    factor = _discount_factor(invoice)
    subtotal = round_cents(sum((line.amount for line in invoice.lines), Decimal(0)))
    discount = round_cents(subtotal * as_money(invoice.percent_discount) / HUNDRED)
    coupon = min(round_cents(as_money(invoice.coupon)), subtotal - discount)
    tax = sum((round_cents(line.amount * factor * as_money(line.tax_rate)) for line in invoice.lines), Decimal(0))

    total = subtotal - discount - coupon + tax
    return Totals(subtotal=subtotal, discount=discount, coupon=coupon, tax=round_cents(tax), total=round_cents(total))


def convert(amount: Decimal, rate) -> Decimal:
    """Convert an amount into another currency at the given exchange rate."""
    return round_cents(as_money(amount) * as_money(rate))
