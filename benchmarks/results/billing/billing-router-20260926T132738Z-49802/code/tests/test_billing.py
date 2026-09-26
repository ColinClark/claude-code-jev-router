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


def test_round_cents_half_up():
    assert round_cents(D("0.125")) == D("0.13")
    assert round_cents(D("-0.125")) == D("-0.13")
    assert round_cents(D("0.124")) == D("0.12")


def test_subtotal_half_up_issue_231():
    t = compute_totals(Invoice(lines=[Line("X", D(3), D("4.175"))]))
    assert t.subtotal == D("12.53")


def test_period_end_clamps_and_rolls_over():
    assert period_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert period_end(date(2024, 1, 31)) == date(2024, 2, 29)
    assert period_end(date(2026, 3, 31)) == date(2026, 4, 30)
    assert period_end(date(2026, 12, 15)) == date(2027, 1, 15)


def test_prorate_upgrade_from_jan_31_issue_231():
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("28.00"), D("56.00"))
    assert p.period_days == 28
    assert p.days_remaining == 18
    assert p.credit == D("18.00")
    assert p.charge == D("36.00")


def test_prorate_days_remaining_no_off_by_one():
    p = prorate(date(2026, 4, 1), date(2026, 4, 11), D("30.00"), D("60.00"))
    assert (p.days_remaining, p.period_days) == (20, 30)
    assert p.credit == D("20.00")
    assert p.charge == D("40.00")


def test_coupon_capped():
    inv = Invoice(lines=[Line("W", D(1), D("10.00"), D("0.1"))], percent_discount=D(10), coupon=D(50))
    t = compute_totals(inv)
    assert t.coupon == D("9.00")
    assert t.tax == D("0.90")
    assert t.total == D("0.90")


def test_tax_rounded_per_line():
    inv = Invoice(lines=[Line("A", D(1), D("0.05"), D("0.1")), Line("B", D(1), D("0.05"), D("0.1"))])
    assert compute_totals(inv).tax == D("0.02")


def test_convert_exact_decimal():
    assert convert(D("1.005"), "1") == D("1.01")
    assert convert(D("0.125"), D("1.0")) == D("0.13")
