"""Paise helpers matching cubesites/src/lib/money.ts."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def to_paise(rupees) -> int:
    return int((Decimal(str(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def total_from(qty, unit_paise: int) -> int:
    """round(round(qty*1000)*unit/1000)"""
    q = Decimal(str(qty))
    scaled = (q * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int((scaled * Decimal(unit_paise) / Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def unit_from(qty, total_paise: int) -> int | None:
    q = Decimal(str(qty))
    if q <= 0:
        return None
    return int((Decimal(total_paise) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_qty(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    q = Decimal(str(raw))
    return q.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
