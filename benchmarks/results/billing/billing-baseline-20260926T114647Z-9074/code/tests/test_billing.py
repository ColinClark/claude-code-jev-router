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


# --- Regression tests (#231 and docs/SPEC.md conformance) ---


def test_round_cents_half_up():
    assert round_cents(D("0.125")) == D("0.13")
    assert round_cents(D("0.124")) == D("0.12")
    assert round_cents(D("-0.125")) == D("-0.13")
    assert round_cents(D("12.525")) == D("12.53")


def test_inv_2041_subtotal_rounds_half_up():
    t = compute_totals(Invoice(lines=[Line("Item", D(3), D("4.175"))]))
    assert t.subtotal == D("12.53")
    assert t.total == D("12.53")


def test_tax_rounded_per_line():
    # Each line's tax is 0.005 -> 0.01 per line; rounding the sum instead would give 0.02.
    lines = [Line(f"L{i}", D(1), D("0.05"), D("0.1")) for i in range(3)]
    t = compute_totals(Invoice(lines=lines))
    assert t.tax == D("0.03")
    assert t.total == D("0.18")


def test_coupon_capped_at_remaining_amount():
    inv = Invoice(lines=[Line("Widget", D(1), D("10.00"), D("0.1"))], percent_discount=D(50), coupon=D(20))
    t = compute_totals(inv)
    assert t.discount == D("5.00")
    assert t.coupon == D("5.00")
    assert t.tax == D("0.50")  # coupon does not change tax
    assert t.total == D("0.50")


def test_invalid_percent_discount():
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("Widget", D(1), D("10.00"))], percent_discount=D(101)))


def test_convert_uses_exact_decimal_half_up():
    # float arithmetic gives 1.0049999... -> 1.00; exact decimal gives 1.005 -> 1.01
    assert convert(D("1.005"), "1") == D("1.01")
    assert convert(D("2.675"), D(1)) == D("2.68")
    assert convert(D("100.00"), "1.23456") == D("123.46")


def test_convert_rejects_float_rate():
    with pytest.raises(TypeError):
        convert(D("10.00"), 1.5)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 1, 31), date(2026, 2, 28)),
        (date(2028, 1, 31), date(2028, 2, 29)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 12, 15), date(2027, 1, 15)),
        (date(2026, 12, 31), date(2027, 1, 31)),
    ],
)
def test_period_end_month_edges(start, end):
    assert period_end(start) == end


def test_prorate_jan_31_anchor_upgrade_feb_10():
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("28.00"), D("56.00"))
    assert (p.period_days, p.days_remaining) == (28, 18)
    assert p.credit == D("18.00")
    assert p.charge == D("36.00")


def test_prorate_days_remaining_exact():
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("31.00"), D("62.00"))
    assert (p.period_days, p.days_remaining) == (31, 21)
    assert p.credit == D("21.00")
    assert p.charge == D("42.00")
    # Change on the start date covers the whole period.
    full = prorate(date(2026, 3, 10), date(2026, 3, 10), D("31.00"), D("62.00"))
    assert full.days_remaining == full.period_days
    assert full.credit == D("31.00")


def test_prorate_end_date_is_outside_period():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))


def test_prorate_multiplies_before_dividing():
    # 0.14 * 1 / 28 = 0.005 exactly -> 0.01; 0.14 * (1/28) loses precision to 0.00499... -> 0.00.
    p = prorate(date(2026, 2, 10), date(2026, 3, 9), D("0.14"), D("0.14"))
    assert (p.period_days, p.days_remaining) == (28, 1)
    assert p.credit == D("0.01")
    assert p.charge == D("0.01")
