"""Billing math aligned with cubesites/src/lib/billing.ts (amounts in paise)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from django.conf import settings
from django.utils import timezone

from .models import PricingVersion, TaxRule


@dataclass
class Pricing:
    site_per_month: int
    free_sites: int
    staff_per_month: int
    free_staff: int
    free_storage_mb: int
    storage_block_mb: int
    storage_block_price: int
    days_per_month: int


def pricing_at(on: date | None = None) -> Pricing:
    on = on or timezone.localdate()
    row = (
        PricingVersion.objects.filter(effective_from__lte=on)
        .order_by("-effective_from", "-created_at")
        .first()
    )
    if row:
        return Pricing(
            site_per_month=row.site_per_month,
            free_sites=row.free_sites,
            staff_per_month=row.staff_per_month,
            free_staff=row.free_staff,
            free_storage_mb=row.free_storage_mb,
            storage_block_mb=row.storage_block_mb,
            storage_block_price=row.storage_block_price,
            days_per_month=row.days_per_month,
        )
    d = settings.DEFAULT_PRICING
    return Pricing(**{k: d[k] for k in d})


def site_charge(active_sites: int, p: Pricing | None = None) -> dict:
    p = p or pricing_at()
    billable = max(0, active_sites - p.free_sites)
    return {"billable": billable, "amount": billable * p.site_per_month}


def staff_charge(enabled_staff: int, p: Pricing | None = None) -> dict:
    """`enabled_staff` must exclude owner."""
    p = p or pricing_at()
    billable = max(0, enabled_staff - p.free_staff)
    return {"billable": billable, "amount": billable * p.staff_per_month}


def average_mb(bytes_per_day: Iterable[int | None]) -> float:
    values = [b for b in bytes_per_day if b is not None]
    if not values:
        return 0.0
    return sum(values) / len(values) / (1024 * 1024)


def storage_charge(avg_mb: float, p: Pricing | None = None) -> dict:
    p = p or pricing_at()
    over = max(0.0, avg_mb - p.free_storage_mb)
    blocks = int(__import__("math").ceil(over / p.storage_block_mb)) if over > 0 else 0
    return {"overMB": over, "blocks": blocks, "amount": blocks * p.storage_block_price}


def reactivation_charge(remaining_days: int, p: Pricing | None = None) -> int:
    p = p or pricing_at()
    days = max(0, min(p.days_per_month, remaining_days))
    return round((p.site_per_month * days) / p.days_per_month)


def tax_on(subtotal: int, rate_pct: Decimal | float | int) -> int:
    return round((subtotal * float(rate_pct)) / 100)


def billing_period(now=None, p: Pricing | None = None) -> dict:
    p = p or pricing_at()
    now = now or timezone.localtime()
    start = date(now.year, now.month, 1)
    end = start + timedelta(days=p.days_per_month - 1)
    day_index = (now.date() - start).days
    remaining = max(0, p.days_per_month - day_index)
    return {"start": start, "end": end, "remainingDays": remaining}


def tax_rule_at(on: date | None = None) -> TaxRule | None:
    on = on or timezone.localdate()
    return (
        TaxRule.objects.filter(effective_from__lte=on)
        .filter(models_q_effective_to(on))
        .order_by("-effective_from")
        .first()
    )


def models_q_effective_to(on: date):
    from django.db.models import Q

    return Q(effective_to__isnull=True) | Q(effective_to__gte=on)


def build_invoice_lines(
    *,
    active_sites: int,
    enabled_staff: int,
    avg_mb: float,
    p: Pricing | None = None,
) -> list[dict]:
    p = p or pricing_at()
    s = site_charge(active_sites, p)
    st = staff_charge(enabled_staff, p)
    g = storage_charge(avg_mb, p)
    return [
        {
            "label": "Active sites",
            "detail": f"{active_sites} active · {p.free_sites} free · {s['billable']} × ₹{p.site_per_month // 100}",
            "amountPaise": s["amount"],
            "type": "site",
        },
        {
            "label": "Staff accounts",
            "detail": f"{enabled_staff} enabled · {p.free_staff} free · {st['billable']} × ₹{p.staff_per_month // 100}",
            "amountPaise": st["amount"],
            "type": "staff",
        },
        {
            "label": "Storage",
            "detail": f"{avg_mb:.1f} MB avg · {p.free_storage_mb} MB free · {g['blocks']} × ₹{p.storage_block_price // 100}",
            "amountPaise": g["amount"],
            "type": "storage",
        },
    ]
