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


def test_round_cents_half_up_regression():
    assert round_cents(D("0.125")) == D("0.13")
    assert round_cents(D("0.124")) == D("0.12")
    assert round_cents(D("-0.125")) == D("-0.13")
    assert round_cents(D("0.135")) == D("0.14")


def test_inv_2041_subtotal_half_up_regression():
    inv = Invoice(lines=[Line("Item", D(3), D("4.175"))])
    t = compute_totals(inv)
    assert t.subtotal == D("12.53")
    assert t.total == D("12.53")


def test_coupon_capped_at_remaining_regression():
    inv = Invoice(lines=[Line("Widget", D(2), D("10.00"), D("0.1"))], coupon=D(25))
    t = compute_totals(inv)
    assert t.coupon == D("20.00")
    assert t.tax == D("2.00")
    assert t.total == D("2.00")


def test_coupon_capped_after_percent_discount_regression():
    inv = Invoice(lines=[Line("Plan", D(1), D("100.00"))], percent_discount=D(10), coupon=D(500))
    t = compute_totals(inv)
    assert t.discount == D("10.00")
    assert t.coupon == D("90.00")
    assert t.total == D("0.00")


def test_tax_rounded_per_line_regression():
    inv = Invoice(lines=[Line("A", D(1), D("0.05"), D("0.1")), Line("B", D(1), D("0.05"), D("0.1"))])
    t = compute_totals(inv)
    # per line: round_cents(0.005) = 0.01 each -> 0.02 (rounding the sum would give 0.01)
    assert t.tax == D("0.02")
    assert t.total == D("0.12")


def test_percent_discount_out_of_range_raises():
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("A", D(1), D("1.00"))], percent_discount=D(101)))
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("A", D(1), D("1.00"))], percent_discount=D(-1)))


def test_convert_exact_decimal_regression():
    # float math: round(1.005 * 1.0, 2) == 1.0 -> wrong cent
    assert convert(D("1.005"), "1") == D("1.01")
    assert convert(D("10.00"), D("1.2345")) == D("12.35")
    assert convert(D("2.675"), "1") == D("2.68")


def test_convert_rejects_float_rate():
    with pytest.raises(TypeError):
        convert(D(1), 1.5)


@pytest.mark.parametrize("start,expected", [
    (date(2026, 1, 31), date(2026, 2, 28)),
    (date(2028, 1, 31), date(2028, 2, 29)),
    (date(2026, 3, 31), date(2026, 4, 30)),
    (date(2026, 12, 15), date(2027, 1, 15)),
    (date(2026, 12, 31), date(2027, 1, 31)),
])
def test_period_end_clamps_and_rolls_year(start, expected):
    assert period_end(start) == expected


def test_prorate_anchor_jan31_upgrade_feb10():
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("30.00"), D("60.00"))
    assert (p.period_days, p.days_remaining, p.credit, p.charge) == (28, 18, D("19.29"), D("38.57"))


def test_prorate_days_remaining_exact():
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("30.00"), D("60.00"))
    assert (p.period_days, p.days_remaining, p.credit, p.charge) == (31, 21, D("20.32"), D("40.65"))


def test_prorate_change_on_end_raises():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))


def test_prorate_change_on_start_is_full_period():
    p = prorate(date(2026, 3, 10), date(2026, 3, 10), D("30.00"), D("60.00"))
    assert p.days_remaining == p.period_days
    assert p.credit == D("30.00")


def test_prorate_multiplies_before_dividing_regression():
    # 0.14 x 1 / 28 is exactly 0.005 -> 0.01; pre-rounding 1/28 to 28 digits made it 0.00.
    p = prorate(date(2026, 2, 1), date(2026, 2, 28), D("0.14"), D("1.26"))
    assert (p.days_remaining, p.period_days) == (1, 28)
    assert p.credit == D("0.01")
    assert p.charge == D("0.05")


def test_round_cents_rejects_float():
    with pytest.raises(TypeError):
        round_cents(0.125)
