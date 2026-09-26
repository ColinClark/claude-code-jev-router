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


# Regression tests (#231 and docs/SPEC.md conformance)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(D("0.125"), D("0.13")), (D("0.124"), D("0.12")), (D("-0.125"), D("-0.13")), (D("12.525"), D("12.53"))],
)
def test_round_cents_half_up(value, expected):
    assert round_cents(value) == expected


def test_inv_2041_subtotal_rounds_half_up():
    t = compute_totals(Invoice(lines=[Line("INV-2041", D(3), D("4.175"))]))
    assert t.subtotal == D("12.53")
    assert t.total == D("12.53")


def test_coupon_capped_at_amount_after_discount():
    inv = Invoice(lines=[Line("Widget", D(1), D("10.00"), D("0.1"))], percent_discount=D(50), coupon=D(20))
    t = compute_totals(inv)
    assert t.discount == D("5.00")
    assert t.coupon == D("5.00")
    assert t.tax == D("0.50")
    assert t.total == D("0.50")


def test_tax_rounded_per_line():
    # Each line's tax is 0.005 -> 0.01 per line; rounding the sum once would give 0.01 instead of 0.02.
    inv = Invoice(lines=[Line("A", D(1), D("0.05"), D("0.1")), Line("B", D(1), D("0.05"), D("0.1"))])
    assert compute_totals(inv).tax == D("0.02")


def test_empty_invoice_totals_are_cents():
    t = compute_totals(Invoice())
    assert all(str(v) == "0.00" for v in (t.subtotal, t.discount, t.coupon, t.tax, t.total))


def test_convert_uses_exact_decimal_arithmetic():
    # 1.005 * 1 in binary floating point is 1.00499999..., which rounds to 1.00.
    assert convert(D("1.005"), "1") == D("1.01")
    assert convert(D("0.10"), D("1.25")) == D("0.13")
    # The exact product has 29 significant digits; the default 28-digit context would round it to ...0.04.
    assert convert(D("10000000000000000000000000.03"), "1.5") == D("15000000000000000000000000.05")


def test_convert_rejects_float_rate():
    with pytest.raises(TypeError):
        convert(D("10.00"), 1.5)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (date(2026, 1, 31), date(2026, 2, 28)),
        (date(2028, 1, 31), date(2028, 2, 29)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 12, 15), date(2027, 1, 15)),
        (date(2026, 12, 31), date(2027, 1, 31)),
    ],
)
def test_period_end_clamps_and_rolls_year(start, expected):
    assert period_end(start) == expected


def test_prorate_plan_change_anchored_on_jan_31():
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("28.00"), D("56.00"))
    assert (p.period_days, p.days_remaining) == (28, 18)
    assert p.credit == D("18.00")
    assert p.charge == D("36.00")


def test_prorate_days_remaining_is_half_open():
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("31.00"), D("62.00"))
    assert (p.period_days, p.days_remaining) == (31, 21)
    assert (p.credit, p.charge) == (D("21.00"), D("42.00"))
    first_day = prorate(date(2026, 3, 10), date(2026, 3, 10), D("31.00"), D("62.00"))
    assert first_day.days_remaining == 31
    assert first_day.credit == D("31.00")


def test_prorate_end_date_is_outside_period():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))
