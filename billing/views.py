from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsWorkspaceUser, require_any_user_perm, require_perm
from billing.models import BillingPayment, Invoice, StorageSnapshot, WalletTransaction
from billing.services import (
    average_mb,
    billing_period,
    build_invoice_lines,
    pricing_at,
    tax_on,
    tax_rule_at,
)
from billing.wallet_services import get_or_create_wallet, serialize_tx, serialize_wallet
from jobsites.models import Site
from ops.models import ActivityLog


def workspace_usage(workspace, period):
    active_sites = Site.objects.filter(workspace=workspace, status=Site.Status.ACTIVE).count()
    enabled_staff = User.objects.filter(
        workspace=workspace, is_active=True
    ).exclude(role=User.Role.OWNER).count()
    snaps = StorageSnapshot.objects.filter(
        workspace=workspace,
        date__gte=period["start"],
        date__lte=period["end"],
    ).values_list("bytes", flat=True)
    avg = average_mb(snaps)
    return active_sites, enabled_staff, avg, list(
        StorageSnapshot.objects.filter(
            workspace=workspace, date__gte=period["start"], date__lte=period["end"]
        ).order_by("date")
    )


class BillingCurrentView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        require_any_user_perm(request.user, ("manageStaffSites", "viewFinancials"))
        ws = request.user.workspace
        p = pricing_at()
        period = billing_period(p=p)
        active, staff, avg, snaps = workspace_usage(ws, period)
        lines = build_invoice_lines(active_sites=active, enabled_staff=staff, avg_mb=avg, p=p)
        subtotal = sum(l["amountPaise"] for l in lines)
        rule = tax_rule_at()
        rate = float(rule.rate_pct) if rule else float(ws.tax_rate_pct)
        label = rule.label if rule else ws.tax_label
        tax = tax_on(subtotal, rate)
        return Response(
            {
                "period": {
                    "start": period["start"].isoformat(),
                    "end": period["end"].isoformat(),
                    "remainingDays": period["remainingDays"],
                },
                "activeSites": active,
                "enabledStaff": staff,
                "avgMB": avg,
                "lines": lines,
                "subtotalPaise": subtotal,
                "taxPaise": tax,
                "taxLabel": label,
                "taxRatePct": rate,
                "totalPaise": subtotal + tax,
                "snapshots": [
                    {"date": s.date.isoformat(), "bytes": s.bytes, "corrected": s.corrected}
                    for s in snaps
                ],
            }
        )


class InvoiceListView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def get(self, request):
        qs = Invoice.objects.filter(workspace=request.user.workspace)
        return Response(
            [
                {
                    "id": str(i.id),
                    "number": i.number,
                    "periodStart": i.period_start.isoformat(),
                    "periodEnd": i.period_end.isoformat(),
                    "lines": i.lines,
                    "subtotalPaise": i.subtotal_paise,
                    "taxPaise": i.tax_paise,
                    "totalPaise": i.total_paise,
                    "status": i.status,
                    "issuedAt": i.issued_at.isoformat(),
                }
                for i in qs
            ]
        )


class IssueInvoiceView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request):
        ws = request.user.workspace
        p = pricing_at()
        period = billing_period(p=p)
        existing = Invoice.objects.filter(workspace=ws, period_start=period["start"]).first()
        if existing:
            return Response({"invoice": _inv(existing), "created": False})
        active, staff, avg, _ = workspace_usage(ws, period)
        lines = build_invoice_lines(active_sites=active, enabled_staff=staff, avg_mb=avg, p=p)
        subtotal = sum(l["amountPaise"] for l in lines)
        rule = tax_rule_at()
        rate = float(rule.rate_pct) if rule else float(ws.tax_rate_pct)
        tax = tax_on(subtotal, rate)
        n = Invoice.objects.filter(workspace=ws).count() + 1
        number = f"CS-{period['start'].year}-{period['start'].month:02d}-{n:03d}"
        inv = Invoice.objects.create(
            workspace=ws,
            number=number,
            period_start=period["start"],
            period_end=period["end"],
            lines=lines,
            subtotal_paise=subtotal,
            tax_paise=tax,
            total_paise=subtotal + tax,
            tax_snapshot={"label": rule.label if rule else ws.tax_label, "ratePct": rate},
            status=Invoice.Status.DUE,
        )
        ActivityLog.objects.create(
            workspace=ws,
            actor=request.user,
            action="create",
            target_type="invoice",
            target_id=str(inv.id),
            summary=f"Issued invoice {inv.number}",
        )
        return Response({"invoice": _inv(inv), "created": True}, status=201)


class ManualPaymentView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request, pk):
        inv = Invoice.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not inv:
            return Response({"detail": "Not found."}, status=404)
        method = request.data.get("method", "upi")
        reference = request.data.get("reference", "")
        amount = int(request.data.get("amountPaise") or request.data.get("amount_paise") or inv.total_paise)
        pay = BillingPayment.objects.create(
            workspace=request.user.workspace,
            invoice=inv,
            amount_paise=amount,
            method=method,
            reference=reference,
            status=BillingPayment.Status.PENDING_APPROVAL,
        )
        inv.status = Invoice.Status.PENDING_APPROVAL
        inv.save(update_fields=["status"])
        return Response(
            {
                "id": str(pay.id),
                "invoiceId": str(inv.id),
                "amountPaise": pay.amount_paise,
                "method": pay.method,
                "reference": pay.reference,
                "status": pay.status,
                "at": pay.at.isoformat(),
            },
            status=201,
        )


def _inv(i: Invoice) -> dict:
    return {
        "id": str(i.id),
        "number": i.number,
        "periodStart": i.period_start.isoformat(),
        "periodEnd": i.period_end.isoformat(),
        "lines": i.lines,
        "subtotalPaise": i.subtotal_paise,
        "taxPaise": i.tax_paise,
        "totalPaise": i.total_paise,
        "status": i.status,
        "issuedAt": i.issued_at.isoformat(),
    }


class WalletView(APIView):
    """Contractor wallet balance + recent ledger (Razorpay will credit later)."""

    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def get(self, request):
        ws = request.user.workspace
        wallet = get_or_create_wallet(ws)
        txs = WalletTransaction.objects.filter(workspace=ws).select_related("workspace", "created_by")[:30]
        return Response(
            {
                "wallet": serialize_wallet(wallet),
                "transactions": [serialize_tx(tx) for tx in txs],
            }
        )
