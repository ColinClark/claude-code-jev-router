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


def test_inv_2041_subtotal_rounds_half_up():
    # Issue #231 report 1: 3 x 4.175 = 12.525 must round to 12.53.
    inv = Invoice(lines=[Line("Item", D(3), D("4.175"))])
    t = compute_totals(inv)
    assert t.subtotal == D("12.53")
    assert t.total == D("12.53")


def test_tax_rounded_per_line():
    # SPEC §2.5: each line's tax is rounded before summing.
    # 0.005 tax per line -> 0.01 each -> 0.03 total (rounding the sum would give 0.02).
    inv = Invoice(lines=[Line("A", D(1), D("0.10"), D("0.05"))] * 3)
    t = compute_totals(inv)
    assert t.tax == D("0.03")
    assert t.total == D("0.33")


def test_tax_uses_discounted_line_amount_but_not_coupon():
    inv = Invoice(lines=[Line("A", D(1), D("100.00"), D("0.1"))], percent_discount=D(50), coupon=D(20))
    t = compute_totals(inv)
    assert t.discount == D("50.00")
    assert t.coupon == D("20.00")
    assert t.tax == D("5.00")
    assert t.total == D("35.00")


def test_coupon_capped_at_remaining_amount():
    # SPEC §2.4: coupon applied = min(coupon, subtotal - discount); pre-tax amount never negative.
    inv = Invoice(lines=[Line("A", D(1), D("10.00"), D("0.1"))], percent_discount=D(50), coupon=D(100))
    t = compute_totals(inv)
    assert t.coupon == D("5.00")
    assert t.total == D("0.50")


def test_percent_discount_out_of_range_rejected():
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("A", D(1), D("1.00"))], percent_discount=D(101)))
    with pytest.raises(ValueError):
        compute_totals(Invoice(lines=[Line("A", D(1), D("1.00"))], percent_discount=D(-1)))


def test_empty_invoice():
    t = compute_totals(Invoice())
    assert (t.subtotal, t.discount, t.coupon, t.tax, t.total) == (D("0.00"),) * 5


def test_convert_is_exact_decimal():
    # SPEC §3: exact decimal multiplication, then half-up rounding. Floats would give 1.15*3 = 3.4499999...
    assert convert(D("1.15"), "3") == D("3.45")
    assert convert(D("0.01"), D("0.5")) == D("0.01")
    assert convert(D("100.00"), "1.23456") == D("123.46")
    assert isinstance(convert(D("10.00"), "2"), D)


def test_convert_rejects_float():
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
        (date(2026, 2, 28), date(2026, 3, 28)),
    ],
)
def test_period_end_clamps_and_wraps_year(start, expected):
    # SPEC §4 and issue #231 report 2: Jan 31 anchor must not crash.
    assert period_end(start) == expected


def test_prorate_jan_31_anchor_upgrade_on_feb_10():
    # Issue #231 report 2: previously raised ValueError("day is out of range for month").
    p = prorate(date(2026, 1, 31), date(2026, 2, 10), D("28.00"), D("56.00"))
    assert p.period_days == 28
    assert p.days_remaining == 18
    assert p.credit == D("18.00")
    assert p.charge == D("36.00")


def test_prorate_days_remaining_half_open():
    # SPEC §4: days_remaining = (end - change_date).days, no +1.
    p = prorate(date(2026, 3, 10), date(2026, 3, 20), D("31.00"), D("62.00"))
    assert p.period_days == 31
    assert p.days_remaining == 21
    assert p.credit == D("21.00")
    assert p.charge == D("42.00")


def test_prorate_on_start_and_last_day():
    start = date(2026, 3, 10)
    full = prorate(start, start, D("30.00"), D("60.00"))
    assert full.days_remaining == full.period_days == 31
    assert (full.credit, full.charge) == (D("30.00"), D("60.00"))

    last = prorate(start, date(2026, 4, 9), D("31.00"), D("62.00"))
    assert last.days_remaining == 1
    assert (last.credit, last.charge) == (D("1.00"), D("2.00"))


def test_prorate_rejects_change_on_or_after_end_or_before_start():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 3, 9), D("30.00"), D("60.00"))


def test_prorate_rounds_half_up():
    # SPEC §4: price x days_remaining / period_days, rounded half up.
    # 3.10 * 8/31 = 0.80 exactly; 0.31 * 8/31 = 0.08 exactly.
    p = prorate(date(2026, 3, 1), date(2026, 3, 24), D("3.10"), D("0.31"))
    assert p.days_remaining == 8
    assert (p.credit, p.charge) == (D("0.80"), D("0.08"))
    # Half-up case: 0.155 * 1/31 = 0.005 -> 0.01 (half even would give 0.00).
    q = prorate(date(2026, 3, 1), date(2026, 3, 31), D("0.155"), D("1.55"))
    assert q.days_remaining == 1
    assert (q.credit, q.charge) == (D("0.01"), D("0.05"))
