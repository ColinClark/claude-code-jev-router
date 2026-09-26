from datetime import date
from decimal import Decimal as D

import pytest

from billing import Invoice, Line, compute_totals, convert, period_end, prorate, round_cents


def test_round_cents_basic():
    assert round_cents(D("1.234")) == D("1.23")
    assert round_cents(D("1.236")) == D("1.24")


def test_simple_invoice_with_tax():
    inv = Invoice(lines=[Line("Widget", D(2), D("10.00"), D("0.1"))])
    t = compute_totals(inv)
    assert (t.subtotal, t.discount, t.coupon, t.tax, t.total) == (D("20.00"), D("0.00"), D("0.00"), D("2.00"),
                                                                  D("22.00"))


def test_percent_discount():
    inv = Invoice(lines=[Line("Plan", D(1), D("100.00"), D("0.2"))], percent_discount=D(10))
    t = compute_totals(inv)
    assert t.discount == D("10.00")
    assert t.tax == D("18.00")
    assert t.total == D("108.00")


def test_coupon():
    inv = Invoice(lines=[Line("Widget", D(2), D("10.00"))], coupon=D(5))
    assert compute_totals(inv).total == D("15.00")


def test_convert():
    assert convert(D("10.00"), "2") == D("20.00")


def test_period_end():
    assert period_end(date(2026, 3, 10)) == date(2026, 4, 10)


def test_prorate_upgrade():
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("30.00"), D("60.00"))
    assert D(0) < p.credit < D("30.00")
    assert p.charge > p.credit


def test_prorate_outside_period():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 5, 1), D("30.00"), D("60.00"))


def test_round_cents_half_up_inv_2041():
    inv = Invoice(lines=[Line("Item", D(3), D("4.175"))])
    assert compute_totals(inv).subtotal == D("12.53")
    assert round_cents(D("0.125")) == D("0.13")
    assert round_cents(D("0.124")) == D("0.12")
    assert round_cents(D("-0.125")) == D("-0.13")


def test_period_end_month_end_clamping():
    assert period_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert period_end(date(2028, 1, 31)) == date(2028, 2, 29)
    assert period_end(date(2026, 3, 31)) == date(2026, 4, 30)
    assert period_end(date(2026, 12, 31)) == date(2027, 1, 31)
    assert period_end(date(2026, 12, 15)) == date(2027, 1, 15)
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("30.00"), D("60.00"))
    assert (p.days_remaining, p.period_days) == (18, 28)


def test_prorate_exact_days():
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("31.00"), D("62.00"))
    assert (p.days_remaining, p.period_days) == (21, 31)
    assert p.credit == D("21.00")
    assert p.charge == D("42.00")


def test_coupon_clamped():
    inv = Invoice(lines=[Line("Widget", D(1), D("10.00"))], percent_discount=D(50), coupon=D(20))
    t = compute_totals(inv)
    assert t.coupon == D("5.00")
    assert t.total == D("0.00")


def test_convert_exact_decimal():
    assert convert(D("3.00"), "0.155") == D("0.47")


def test_tax_rounded_per_line_not_summed():
    # Two lines each with a tax contribution of 10.005 must round to 10.01 apiece
    # (per-line rounding), giving 20.02 total tax -- not round(20.010) == 20.01
    # as summing-then-rounding-once would produce.
    inv = Invoice(lines=[
        Line("A", D(1), D("10.005"), D(1)),
        Line("B", D(1), D("10.005"), D(1)),
    ])
    assert compute_totals(inv).tax == D("20.02")
