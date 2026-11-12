"""Workspace wallet credits/debits. Amounts are always integer paise."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError

from accounts.models import Workspace
from billing.models import Wallet, WalletTransaction


def get_or_create_wallet(workspace: Workspace) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(workspace=workspace)
    # Avoid a follow-up FK fetch for business_name in serialize_wallet.
    wallet.workspace = workspace
    return wallet


def serialize_tx(tx: WalletTransaction) -> dict:
    return {
        "id": str(tx.id),
        "workspaceId": str(tx.workspace_id),
        "contractorName": tx.workspace.business_name,
        "amountPaise": tx.amount_paise,
        "kind": tx.kind,
        "funding": tx.funding,
        "source": tx.source,
        "note": tx.note,
        "reference": tx.reference,
        "balanceAfterPaise": tx.balance_after_paise,
        "countsAsIncome": tx.counts_as_income,
        "createdBy": getattr(tx.created_by, "email", None) or "",
        "createdAt": tx.created_at.isoformat(),
    }


def serialize_wallet(wallet: Wallet) -> dict:
    # One aggregate instead of two identical table scans.
    totals = WalletTransaction.objects.filter(
        wallet=wallet,
        kind=WalletTransaction.Kind.RECHARGE,
        amount_paise__gt=0,
    ).aggregate(
        paid=Sum("amount_paise", filter=Q(funding=WalletTransaction.Funding.PAID)),
        free=Sum("amount_paise", filter=Q(funding=WalletTransaction.Funding.FREE)),
    )
    return {
        "workspaceId": str(wallet.workspace_id),
        "contractorName": wallet.workspace.business_name,
        "balancePaise": wallet.balance_paise,
        "paidRechargedPaise": totals["paid"] or 0,
        "freeRechargedPaise": totals["free"] or 0,
        "updatedAt": wallet.updated_at.isoformat(),
    }


@transaction.atomic
def credit_wallet(
    *,
    workspace: Workspace,
    amount_paise: int,
    funding: str,
    note: str = "",
    reference: str = "",
    source: str = WalletTransaction.Source.ADMIN,
    kind: str = WalletTransaction.Kind.RECHARGE,
    actor=None,
) -> tuple[Wallet, WalletTransaction]:
    if amount_paise == 0:
        raise ValidationError({"detail": "Amount must not be zero."})
    if funding not in WalletTransaction.Funding.values:
        raise ValidationError({"detail": "funding must be free or paid."})
    if source not in WalletTransaction.Source.values:
        raise ValidationError({"detail": "Invalid source."})
    if kind not in WalletTransaction.Kind.values:
        raise ValidationError({"detail": "Invalid kind."})

    wallet = get_or_create_wallet(workspace)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    new_balance = wallet.balance_paise + amount_paise
    if new_balance < 0:
        raise ValidationError({"detail": "Insufficient wallet balance."})
    wallet.balance_paise = new_balance
    wallet.save(update_fields=["balance_paise", "updated_at"])

    tx = WalletTransaction.objects.create(
        workspace=workspace,
        wallet=wallet,
        amount_paise=amount_paise,
        kind=kind,
        funding=funding,
        source=source,
        note=(note or "")[:255],
        reference=(reference or "")[:120],
        balance_after_paise=new_balance,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return wallet, tx


def paid_income_paise(*, since=None, until=None) -> int:
    qs = WalletTransaction.objects.filter(
        kind=WalletTransaction.Kind.RECHARGE,
        funding=WalletTransaction.Funding.PAID,
        amount_paise__gt=0,
    )
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    if until is not None:
        qs = qs.filter(created_at__lte=until)
    return qs.aggregate(total=Sum("amount_paise"))["total"] or 0
