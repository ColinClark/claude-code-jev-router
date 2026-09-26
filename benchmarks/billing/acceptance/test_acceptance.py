"""Hidden acceptance tests for the billing benchmark, derived only from the seed's docs/SPEC.md.

The seed contains six spec violations. ISSUE.md reports symptoms of two of them (rounding, Jan 31 crash);
the other four (coupon cap, per-line tax rounding, proration off-by-one, float currency conversion) are
only found by auditing against the spec. Tests are grouped by bug so results show which were fixed.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from billing import Invoice, Line, compute_totals, convert, period_end, prorate, round_cents


# --- bug 1 (reported): round half up -------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.125", "0.13"), ("2.675", "2.68"), ("-0.125", "-0.13"), ("0.124", "0.12"), ("1.005", "1.01")],
)
def test_bug1_round_half_up(value, expected):
    assert round_cents(D(value)) == D(expected)


def test_bug1_reported_invoice_subtotal():
    t = compute_totals(Invoice(lines=[Line("Widget", D(3), D("4.175"))]))
    assert t.subtotal == D("12.53") and t.total == D("12.53")


# --- bug 2 (silent): coupon never exceeds what remains after the discount -------------------------
def test_bug2_coupon_capped_at_subtotal():
    t = compute_totals(Invoice(lines=[Line("Widget", D(1), D("10.00"), D("0.1"))], coupon=D(25)))
    assert t.coupon == D("10.00")
    assert t.tax == D("1.00")
    assert t.total == D("1.00")


def test_bug2_coupon_capped_after_percent_discount():
    t = compute_totals(Invoice(lines=[Line("Widget", D(1), D("10.00"))], percent_discount=D(50), coupon=D(8)))
    assert (t.discount, t.coupon, t.total) == (D("5.00"), D("5.00"), D("0.00"))


# --- bug 3 (silent): tax is rounded per line, then summed -----------------------------------------
def test_bug3_tax_rounded_per_line():
    lines = [Line("A", D(1), D("0.40"), D("0.01")), Line("B", D(1), D("0.40"), D("0.01"))]
    t = compute_totals(Invoice(lines=lines))
    assert t.tax == D("0.00")  # 0.004 + 0.004: each rounds to 0.00; rounding the sum would give 0.01
    assert t.total == D("0.80")


def test_bug3_tax_per_line_with_discount():
    lines = [Line("A", D(1), D("1.10"), D("0.1")), Line("B", D(1), D("1.10"), D("0.1"))]
    t = compute_totals(Invoice(lines=lines, percent_discount=D(50)))
    # per line: 1.10 * 0.5 * 0.1 = 0.055 -> 0.06 each (half up) -> 0.12; rounding the sum (0.11) would differ
    assert t.tax == D("0.12")


# --- bug 4 (silent): days remaining uses the half-open period [start, end) -------------------------
def test_bug4_proration_days_remaining():
    p = prorate(date(2026, 3, 10), date(2026, 3, 25), D("31.00"), D("62.00"))
    assert (p.period_days, p.days_remaining) == (31, 16)
    assert (p.credit, p.charge) == (D("16.00"), D("32.00"))


def test_bug4_change_on_first_day_is_full_period():
    p = prorate(date(2026, 3, 10), date(2026, 3, 10), D("30.00"), D("60.00"))
    assert p.days_remaining == p.period_days == 31
    assert (p.credit, p.charge) == (D("30.00"), D("60.00"))


# --- bug 5 (reported): period end clamps to month end and rolls over the year ---------------------
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2027, 1, 31), date(2027, 2, 28)),
        (date(2028, 1, 31), date(2028, 2, 29)),
        (date(2026, 3, 31), date(2026, 4, 30)),
        (date(2026, 12, 15), date(2027, 1, 15)),
        (date(2026, 12, 31), date(2027, 1, 31)),
        (date(2026, 3, 10), date(2026, 4, 10)),
    ],
)
def test_bug5_period_end(start, end):
    assert period_end(start) == end


def test_bug5_reported_jan31_upgrade():
    p = prorate(date(2027, 1, 31), date(2027, 2, 10), D("28.00"), D("56.00"))
    assert (p.period_days, p.days_remaining) == (28, 18)
    assert (p.credit, p.charge) == (D("18.00"), D("36.00"))


# --- bug 6 (silent): currency conversion is exact decimal arithmetic, rounded half up --------------
@pytest.mark.parametrize(
    ("amount", "rate", "expected"),
    [("2.01", "0.5", "1.01"), ("0.125", "1", "0.13"), ("10.00", "1.2345", "12.35"), ("1.15", "3", "3.45")],
)
def test_bug6_convert_exact(amount, rate, expected):
    assert convert(D(amount), rate) == D(expected)
    assert convert(D(amount), D(rate)) == D(expected)


# --- behavior that must keep working -------------------------------------------------------------
def test_regression_simple_invoice():
    t = compute_totals(Invoice(lines=[Line("Widget", D(2), D("10.00"), D("0.1"))]))
    assert (t.subtotal, t.discount, t.coupon, t.tax, t.total) == (
        D("20.00"),
        D("0.00"),
        D("0.00"),
        D("2.00"),
        D("22.00"),
    )


def test_regression_outside_period_raises():
    with pytest.raises(ValueError):
        prorate(date(2026, 3, 10), date(2026, 4, 10), D("30.00"), D("60.00"))
