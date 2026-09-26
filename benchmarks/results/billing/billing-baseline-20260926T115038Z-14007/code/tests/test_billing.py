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


# --- Regression tests (issue #231 and SPEC conformance) ---


def test_round_cents_half_up():
    # SPEC §1: half up, not banker's rounding.
    assert round_cents(D("0.125")) == D("0.13")
    assert round_cents(D("0.124")) == D("0.12")
    assert round_cents(D("-0.125")) == D("-0.13")
    assert round_cents(D("12.525")) == D("12.53")


def test_round_cents_rejects_float():
    with pytest.raises(TypeError):
        round_cents(0.125)


def test_issue_231_subtotal_rounds_half_up():
    # INV-2041: 3 x 4.175 = 12.525 -> 12.53, not 12.52.
    inv = Invoice(lines=[Line("Item", D(3), D("4.175"))])
    t = compute_totals(inv)
    assert t.subtotal == D("12.53")
    assert t.total == D("12.53")


def test_tax_rounded_per_line():
    # SPEC §2.5: each line's tax is rounded before summing.
    # Per line: 0.45 * 0.1 = 0.045 -> 0.05, x3 = 0.15. Rounding the summed 0.135 would give 0.14.
    inv = Invoice(lines=[Line(f"L{i}", D(1), D("0.45"), D("0.1")) for i in range(3)])
    t = compute_totals(inv)
    assert t.tax == D("0.15")
    assert t.subtotal == D("1.35")
    assert t.total == D("1.50")


def test_tax_uses_discount_but_not_coupon():
    inv = Invoice(lines=[Line("Plan", D(1), D("100.00"), D("0.2"))], percent_discount=D(10), coupon=D(50))
    t = compute_totals(inv)
    assert t.discount == D("10.00")
    assert t.coupon == D("50.00")
    assert t.tax == D("18.00")
    assert t.total == D("58.00")


def test_coupon_capped_at_remaining_pre_tax_amount():
    # SPEC §2.4: coupon applied = min(coupon, subtotal - discount); never negative pre-tax.
    inv = Invoice(lines=[Line("Widget", D(2), D("10.00"), D("0.1"))], percent_discount=D(50), coupon=D(100))
    t = compute_totals(inv)
    assert t.subtotal == D("20.00")
    assert t.discount == D("10.00")
    assert t.coupon == D("10.00")
    assert t.tax == D("1.00")
    assert t.total == D("1.00")


def test_percent_discount_out_of_range():
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("W", D(1), D("1.00"))], percent_discount=D(101)))
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("W", D(1), D("1.00"))], percent_discount=D(-1)))


def test_empty_invoice():
    t = compute_totals(Invoice(coupon=D(5)))
    assert (t.subtotal, t.discount, t.coupon, t.tax, t.total) == (D("0.00"),) * 5


def test_line_amount_not_rounded_before_subtotal():
    # Two lines of 0.005 each: 0.01 subtotal if summed exactly, 0.02 if each line were rounded first.
    inv = Invoice(lines=[Line("A", D(1), D("0.005")), Line("B", D(1), D("0.005"))])
    assert compute_totals(inv).subtotal == D("0.01")


def test_convert_exact_decimal_half_up():
    # SPEC §3: exact decimal multiplication then half-up rounding; float math would give 0.12 / 1.14.
    assert convert(D("0.125"), "1") == D("0.13")
    assert convert(D("1.15"), "0.995") == D("1.14")  # 1.14425
    assert convert(D("0.35"), D("3.5")) == D("1.23")  # 1.225 -> 1.23 (float: 1.2249999 -> 1.22)
    assert convert(D("10.00"), D("1.5")) == D("15.00")


def test_convert_rejects_float():
    with pytest.raises(TypeError):
        convert(D("10.00"), 1.5)
    with pytest.raises(TypeError):
        convert(10.0, "1.5")


def test_period_end_clamps_to_month_length():
    # SPEC §4 examples.
    assert period_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert period_end(date(2024, 1, 31)) == date(2024, 2, 29)
    assert period_end(date(2026, 3, 31)) == date(2026, 4, 30)
    assert period_end(date(2026, 5, 31)) == date(2026, 6, 30)


def test_period_end_december_wraps_year():
    assert period_end(date(2026, 12, 15)) == date(2027, 1, 15)
    assert period_end(date(2026, 12, 31)) == date(2027, 1, 31)


def test_issue_231_upgrade_on_jan_31_anchor():
    # Anchor Jan 31, change Feb 10: period is [Jan 31, Feb 28) = 28 days, 18 remaining.
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("28.00"), D("56.00"))
    assert p.period_days == 28
    assert p.days_remaining == 18
    assert p.credit == D("18.00")
    assert p.charge == D("36.00")


def test_prorate_days_remaining_exact():
    # SPEC §4: days_remaining = (end - change_date).days, no off-by-one.
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("31.00"), D("62.00"))
    assert p.period_days == 31
    assert p.days_remaining == 21
    assert p.credit == D("21.00")
    assert p.charge == D("42.00")


def test_prorate_on_period_start_and_last_day():
    start = date(2026, 3, 10)
    full = prorate(start, start, D("31.00"), D("62.00"))
    assert full.days_remaining == 31
    assert full.credit == D("31.00")
    last = prorate(start, date(2026, 4, 9), D("31.00"), D("62.00"))
    assert last.days_remaining == 1
    assert last.credit == D("1.00")
    assert last.charge == D("2.00")


def test_prorate_rounds_half_up():
    # 30 days, 15 remaining: 0.25 * 0.5 = 0.125 -> 0.13
    p = prorate(date(2026, 4, 1), date(2026, 4, 16), D("0.25"), D("0.75"))
    assert p.period_days == 30
    assert p.credit == D("0.13")
    assert p.charge == D("0.38")  # 0.375 -> 0.38


def test_prorate_change_before_start_or_at_end_rejected():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 3, 9), D("30.00"), D("60.00"))
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))
