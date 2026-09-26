"""Money helpers."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def as_money(value) -> Decimal:
    """Coerce an int, str or Decimal into a Decimal money value."""
    if isinstance(value, float):
        raise TypeError("money must not be a float")
    return Decimal(value)


def round_cents(value: Decimal) -> Decimal:
    """Round a Decimal amount to whole cents, half up (0.125 -> 0.13, -0.125 -> -0.13)."""
    return as_money(value).quantize(CENT, rounding=ROUND_HALF_UP)
