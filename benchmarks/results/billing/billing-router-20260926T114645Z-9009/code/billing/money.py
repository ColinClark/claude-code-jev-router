"""Money helpers."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def round_cents(value: Decimal) -> Decimal:
    """Round a Decimal amount to whole cents, half up."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def as_money(value) -> Decimal:
    """Coerce an int, str or Decimal into a Decimal money value."""
    if isinstance(value, float):
        raise TypeError("money must not be a float")
    return Decimal(value)
