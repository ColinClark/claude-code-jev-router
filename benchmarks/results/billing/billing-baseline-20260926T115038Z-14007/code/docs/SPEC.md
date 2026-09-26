# Billing specification

This document is the source of truth for the `billing` package. Code and tests must conform to it.

## 1. Money

- All money values are `decimal.Decimal`. Floats must never be used for money or exchange rates.
- Whenever a money value is rounded to cents, it is rounded **half up** (`0.125` → `0.13`,
  `0.124` → `0.12`, `-0.125` → `-0.13`). `billing.money.round_cents` implements this.

## 2. Invoice totals (`billing.invoice.compute_totals`)

An invoice has lines (`quantity`, `unit_price`, `tax_rate`), an optional `percent_discount` (0–100) and
an optional fixed `coupon` amount.

1. **Line amount** = `quantity × unit_price` (not rounded).
2. **Subtotal** = `round_cents(sum of line amounts)`.
3. **Discount** = `round_cents(subtotal × percent_discount / 100)`.
4. **Coupon applied** = the coupon amount, but never more than what remains after the discount:
   `min(coupon, subtotal − discount)`. Discounts can never make the pre-tax amount negative.
5. **Tax** is computed **per line and rounded per line**, then summed:
   `tax = Σ round_cents(line amount × (1 − percent_discount / 100) × tax_rate)`.
   The coupon does not change tax.
6. **Total** = `subtotal − discount − coupon applied + tax`.

`compute_totals` returns `Totals(subtotal, discount, coupon, tax, total)`, all rounded to cents.

## 3. Currency conversion (`billing.invoice.convert`)

`convert(amount, rate)` returns `round_cents(amount × Decimal(rate))`. `rate` may be a `str` or a
`Decimal`. The multiplication is exact decimal arithmetic.

## 4. Subscription periods and proration (`billing.proration`)

- A billing period starts on an anchor date and ends on the **same day of the next month**. If that day
  does not exist in the next month, the period ends on the **last day of that month**
  (Jan 31 → Feb 28, or Feb 29 in a leap year; Mar 31 → Apr 30; Dec 15 → Jan 15 of the next year).
  `period_end(start)` implements this.
- A period is the half-open date range `[start, end)`; `period_days = (end − start).days`.
- When a plan changes on `change_date` (with `start ≤ change_date < end`), the unused part of the period is
  `days_remaining = (end − change_date).days`, and:
  - `credit = round_cents(old_price × days_remaining / period_days)`
  - `charge = round_cents(new_price × days_remaining / period_days)`
- `prorate(start, change_date, old_price, new_price)` returns
  `Proration(credit, charge, days_remaining, period_days)` and raises `ValueError` if `change_date` is
  outside the period.
