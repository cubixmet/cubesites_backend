"""Super Admin APIs — require is_platform_admin."""
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User, Workspace
from accounts.permissions import IsPlatformAdmin
from accounts.serializers import UserSerializer, WorkspaceSerializer
from billing.models import (
    BillingPayment,
    Invoice,
    PricingVersion,
    StorageSnapshot,
    Subscription,
    TaxRule,
    Wallet,
    WalletTransaction,
)
from billing.services import average_mb, billing_period, build_invoice_lines, pricing_at, tax_on
from billing.wallet_services import (
    credit_wallet,
    get_or_create_wallet,
    paid_income_paise,
    serialize_tx,
    serialize_wallet,
)
from jobsites.models import Site
from ops.models import ActivityLog, AppNotification, BackupJob, PlatformSettings, RetentionNotice, SupportCase, SupportNote


class AdminOverviewView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        # Collapse repeated COUNT(*) into a few aggregate queries (same response keys).
        ws = Workspace.objects.aggregate(
            contractors=Count("id"),
            activeContractors=Count("id", filter=Q(status=Workspace.Status.ACTIVE)),
            suspended=Count("id", filter=Q(status=Workspace.Status.SUSPENDED)),
        )
        return Response(
            {
                "contractors": ws["contractors"],
                "activeContractors": ws["activeContractors"],
                "suspended": ws["suspended"],
                "sites": Site.objects.count(),
                "pendingPayments": BillingPayment.objects.filter(
                    status=BillingPayment.Status.PENDING_APPROVAL
                ).count(),
                "failedBackups": BackupJob.objects.filter(status=BackupJob.Status.FAILED).count(),
                "openSupport": SupportCase.objects.exclude(
                    status__in=[SupportCase.Status.RESOLVED, SupportCase.Status.CLOSED]
                ).count(),
                "walletBalancePaise": Wallet.objects.aggregate(t=Sum("balance_paise"))["t"] or 0,
                "walletPaidIncomePaise": paid_income_paise(),
            }
        )


class AdminContractorListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        qs = Workspace.objects.all().annotate(
            site_count=Count("sites", distinct=True),
            staff_count=Count("users", distinct=True),
        )
        if q:
            qs = qs.filter(
                Q(business_name__icontains=q)
                | Q(email__icontains=q)
                | Q(owner_name__icontains=q)
                | Q(phone__icontains=q)
            )
        return Response(
            [
                {
                    **WorkspaceSerializer(w).data,
                    "siteCount": w.site_count,
                    "staffCount": w.staff_count,
                }
                for w in qs
            ]
        )


class AdminContractorDetailView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request, pk):
        w = Workspace.objects.select_related("subscription").filter(pk=pk).first()
        if not w:
            return Response({"detail": "Not found."}, status=404)
        sub = getattr(w, "subscription", None)
        wallet = get_or_create_wallet(w)
        return Response(
            {
                "contractor": WorkspaceSerializer(w).data,
                "sites": list(
                    Site.objects.filter(workspace=w).values(
                        "id", "name", "status", "primary_phone", "address", "start_date"
                    )
                ),
                "staff": UserSerializer(
                    UserSerializer.setup_eager_loading(User.objects.filter(workspace=w)),
                    many=True,
                ).data,
                "subscription": {
                    "plan": sub.plan,
                    "status": sub.status,
                    "periodStart": sub.period_start.isoformat(),
                    "periodEnd": sub.period_end.isoformat(),
                }
                if sub
                else None,
                "wallet": serialize_wallet(wallet),
                "walletTransactions": [
                    serialize_tx(tx)
                    for tx in WalletTransaction.objects.filter(workspace=w).select_related(
                        "workspace", "created_by"
                    )[:50]
                ],
                "invoices": [
                    {
                        "id": str(i.id),
                        "number": i.number,
                        "totalPaise": i.total_paise,
                        "status": i.status,
                        "periodStart": i.period_start.isoformat(),
                    }
                    for i in Invoice.objects.filter(workspace=w)[:20]
                ],
            }
        )


class AdminContractorStatusView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        w = Workspace.objects.filter(pk=pk).first()
        if not w:
            return Response({"detail": "Not found."}, status=404)
        status_v = request.data.get("status")
        reason = request.data.get("reason", "")
        if status_v not in Workspace.Status.values:
            return Response({"detail": "Invalid status."}, status=400)
        before = w.status
        w.status = status_v
        w.save(update_fields=["status", "updated_at"])
        ActivityLog.objects.create(
            workspace=w,
            actor=request.user,
            action="update",
            target_type="contractor",
            target_id=str(w.id),
            summary=f"Contractor {before} → {status_v}: {reason or '—'}",
            before={"status": before},
            after={"status": status_v, "reason": reason},
            is_platform=True,
        )
        return Response(WorkspaceSerializer(w).data)


class AdminSitesView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = Site.objects.select_related("workspace")
        cid = request.query_params.get("contractorId")
        if cid:
            qs = qs.filter(workspace_id=cid)
        return Response(
            [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "status": s.status,
                    "contractorId": str(s.workspace_id),
                    "contractorName": s.workspace.business_name,
                    "primaryPhone": s.primary_phone,
                    "address": s.address,
                    "startDate": s.start_date.isoformat(),
                }
                for s in qs[:500]
            ]
        )


class AdminStaffView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = UserSerializer.setup_eager_loading(
            User.objects.filter(workspace__isnull=False).select_related("workspace")
        )
        cid = request.query_params.get("contractorId")
        if cid:
            qs = qs.filter(workspace_id=cid)
        return Response(
            [
                {
                    **UserSerializer(u).data,
                    "contractorId": str(u.workspace_id),
                    "contractorName": u.workspace.business_name,
                    "isOwner": u.role == User.Role.OWNER,
                }
                for u in qs[:500]
            ]
        )


class AdminPaymentListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = BillingPayment.objects.select_related("invoice", "workspace")
        st = request.query_params.get("status")
        if st:
            qs = qs.filter(status=st)
        return Response(
            [
                {
                    "id": str(p.id),
                    "contractorId": str(p.workspace_id),
                    "contractorName": p.workspace.business_name,
                    "invoiceId": str(p.invoice_id),
                    "invoiceNumber": p.invoice.number,
                    "amountPaise": p.amount_paise,
                    "method": p.method,
                    "reference": p.reference,
                    "status": p.status,
                    "proofFilename": p.proof_filename,
                    "at": p.at.isoformat(),
                }
                for p in qs[:200]
            ]
        )


class AdminPaymentReviewView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        pay = BillingPayment.objects.select_related("invoice", "workspace").filter(pk=pk).first()
        if not pay:
            return Response({"detail": "Not found."}, status=404)
        decision = request.data.get("decision")
        reason = request.data.get("reason", "")
        if decision not in ("approved", "rejected"):
            return Response({"detail": "decision must be approved|rejected"}, status=400)
        pay.status = (
            BillingPayment.Status.APPROVED
            if decision == "approved"
            else BillingPayment.Status.REJECTED
        )
        pay.review_reason = reason
        pay.reviewed_by = request.user
        pay.reviewed_at = timezone.now()
        pay.save()
        if decision == "approved":
            pay.invoice.status = Invoice.Status.PAID
            pay.invoice.save(update_fields=["status"])
        else:
            pay.invoice.status = Invoice.Status.DUE
            pay.invoice.save(update_fields=["status"])
        ActivityLog.objects.create(
            workspace=pay.workspace,
            actor=request.user,
            action="update",
            target_type="payment",
            target_id=str(pay.id),
            summary=f"Payment {decision} for {pay.invoice.number}",
            is_platform=True,
        )
        return Response({"id": str(pay.id), "status": pay.status})


class AdminPricingListCreateView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response(
            [
                {
                    "id": str(p.id),
                    "label": p.label,
                    "effectiveFrom": p.effective_from.isoformat(),
                    "sitePerMonth": p.site_per_month,
                    "freeSites": p.free_sites,
                    "staffPerMonth": p.staff_per_month,
                    "freeStaff": p.free_staff,
                    "freeStorageMB": p.free_storage_mb,
                    "storageBlockMB": p.storage_block_mb,
                    "storageBlockPrice": p.storage_block_price,
                    "daysPerMonth": p.days_per_month,
                }
                for p in PricingVersion.objects.all()
            ]
        )

    def post(self, request):
        from datetime import date

        effective = request.data.get("effectiveFrom") or request.data.get("effective_from")
        row = PricingVersion.objects.create(
            label=request.data.get("label", "Pricing"),
            effective_from=effective or timezone.localdate(),
            site_per_month=int(request.data.get("sitePerMonth", 10900)),
            free_sites=int(request.data.get("freeSites", 3)),
            staff_per_month=int(request.data.get("staffPerMonth", 2900)),
            free_staff=int(request.data.get("freeStaff", 1)),
            free_storage_mb=int(request.data.get("freeStorageMB", 250)),
            storage_block_mb=int(request.data.get("storageBlockMB", 250)),
            storage_block_price=int(request.data.get("storageBlockPrice", 500)),
            days_per_month=int(request.data.get("daysPerMonth", 30)),
            created_by=request.user,
        )
        return Response({"id": str(row.id)}, status=201)


class AdminTaxListCreateView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response(
            [
                {
                    "id": str(t.id),
                    "label": t.label,
                    "ratePct": float(t.rate_pct),
                    "inclusive": t.inclusive,
                    "appliesTo": t.applies_to,
                    "effectiveFrom": t.effective_from.isoformat(),
                    "effectiveTo": t.effective_to.isoformat() if t.effective_to else None,
                }
                for t in TaxRule.objects.all()
            ]
        )

    def post(self, request):
        from datetime import timedelta

        effective = request.data.get("effectiveFrom") or timezone.localdate().isoformat()
        # close previous open rule
        prev = TaxRule.objects.filter(effective_to__isnull=True).order_by("-effective_from").first()
        if prev:
            from datetime import date as d

            ef = d.fromisoformat(str(effective))
            prev.effective_to = ef - timedelta(days=1)
            prev.save(update_fields=["effective_to"])
        row = TaxRule.objects.create(
            label=request.data.get("label", "GST"),
            rate_pct=request.data.get("ratePct", 18),
            inclusive=bool(request.data.get("inclusive", False)),
            applies_to=request.data.get("appliesTo")
            or ["site", "staff", "storage", "proration"],
            effective_from=effective,
            gstin=request.data.get("gstin", ""),
        )
        return Response({"id": str(row.id)}, status=201)


class AdminSubscriptionListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response(
            [
                {
                    "id": str(s.id),
                    "contractorId": str(s.workspace_id),
                    "plan": s.plan,
                    "status": s.status,
                    "periodStart": s.period_start.isoformat(),
                    "periodEnd": s.period_end.isoformat(),
                    "expiredAt": s.expired_at.isoformat() if s.expired_at else None,
                }
                for s in Subscription.objects.select_related("workspace")[:500]
            ]
        )


class AdminInvoiceListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response(
            [
                {
                    "id": str(i.id),
                    "number": i.number,
                    "contractorId": str(i.workspace_id),
                    "periodStart": i.period_start.isoformat(),
                    "periodEnd": i.period_end.isoformat(),
                    "issuedAt": i.issued_at.isoformat(),
                    "lines": i.lines,
                    "subtotalPaise": i.subtotal_paise,
                    "taxPaise": i.tax_paise,
                    "totalPaise": i.total_paise,
                    "taxSnapshot": i.tax_snapshot,
                    "status": i.status,
                }
                for i in Invoice.objects.select_related("workspace")[:500]
            ]
        )


class AdminStorageSnapshotListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = StorageSnapshot.objects.select_related("workspace")
        cid = request.query_params.get("contractorId")
        if cid:
            qs = qs.filter(workspace_id=cid)
        return Response(
            [
                {
                    "id": str(s.id),
                    "contractorId": str(s.workspace_id),
                    "date": s.date.isoformat(),
                    "bytes": s.bytes,
                    "corrected": s.corrected,
                    "correctionReason": s.correction_reason,
                }
                for s in qs[:2000]
            ]
        )


class AdminStorageCorrectView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        snap = StorageSnapshot.objects.filter(pk=pk).first()
        if not snap:
            return Response({"detail": "Not found."}, status=404)
        mb = request.data.get("mb")
        reason = request.data.get("reason", "")
        if mb is None:
            return Response({"detail": "mb required"}, status=400)
        snap.bytes = int(float(mb) * 1024 * 1024)
        snap.corrected = True
        snap.correction_reason = reason
        snap.save()
        ActivityLog.objects.create(
            workspace=snap.workspace,
            actor=request.user,
            action="update",
            target_type="storage",
            target_id=str(snap.id),
            summary=f"Corrected storage {snap.date} → {mb} MB",
            is_platform=True,
        )
        return Response(
            {"id": str(snap.id), "date": snap.date.isoformat(), "bytes": snap.bytes, "corrected": True}
        )


class AdminNotificationListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = AppNotification.objects.filter(
            Q(is_platform=True) | Q(workspace__isnull=False)
        ).order_by("-at")
        return Response(
            [
                {
                    "id": str(n.id),
                    "type": n.type or "manual_payment",
                    "title": n.title,
                    "message": n.body,
                    "contractorId": str(n.workspace_id) if n.workspace_id else None,
                    "createdAt": n.at.isoformat(),
                    "read": n.read,
                }
                for n in qs[:200]
            ]
        )


class AdminBackupListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = BackupJob.objects.select_related("workspace")
        return Response(
            [
                {
                    "id": str(b.id),
                    "contractorId": str(b.workspace_id),
                    "contractorName": b.workspace.business_name,
                    "status": b.status,
                    "jobType": b.job_type,
                    "note": b.note,
                    "restoreTestResult": b.restore_test_result,
                    "createdAt": b.created_at.isoformat(),
                }
                for b in qs[:200]
            ]
        )


class AdminBackupRetryView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        job = BackupJob.objects.select_related("workspace").filter(pk=pk).first()
        if not job:
            return Response({"detail": "Not found."}, status=404)
        connected = job.workspace.drive_status in ("connected",)
        job.status = BackupJob.Status.SUCCESS if connected else BackupJob.Status.FAILED
        job.note = "Retry succeeded (stub)" if connected else "Drive not connected"
        job.finished_at = timezone.now()
        job.logs = list(job.logs or []) + [{"at": timezone.now().isoformat(), "msg": job.note}]
        job.save()
        return Response({"id": str(job.id), "status": job.status, "note": job.note})


class AdminSupportListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response(
            [
                {
                    "id": str(c.id),
                    "contractorId": str(c.workspace_id),
                    "contractorName": c.workspace.business_name,
                    "subject": c.subject,
                    "status": c.status,
                    "priority": c.priority,
                    "updatedAt": c.updated_at.isoformat(),
                }
                for c in SupportCase.objects.select_related("workspace")[:200]
            ]
        )


class AdminSupportDetailView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request, pk):
        c = (
            SupportCase.objects.select_related("workspace")
            .prefetch_related("notes")
            .filter(pk=pk)
            .first()
        )
        if not c:
            return Response({"detail": "Not found."}, status=404)
        return Response(
            {
                "id": str(c.id),
                "subject": c.subject,
                "status": c.status,
                "priority": c.priority,
                "contractor": WorkspaceSerializer(c.workspace).data,
                "notes": [
                    {
                        "id": str(n.id),
                        "body": n.body,
                        "internal": n.internal,
                        "createdAt": n.created_at.isoformat(),
                    }
                    for n in c.notes.all()
                ],
            }
        )

    def patch(self, request, pk):
        c = SupportCase.objects.filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        for field in ("status", "priority", "subject"):
            if field in request.data:
                setattr(c, field, request.data[field])
        c.save()
        return Response({"id": str(c.id), "status": c.status, "priority": c.priority})


class AdminSupportNoteView(APIView):
    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        c = SupportCase.objects.filter(pk=pk).first()
        if not c:
            return Response({"detail": "Not found."}, status=404)
        note = SupportNote.objects.create(
            case=c,
            author=request.user,
            body=request.data.get("body", ""),
            internal=bool(request.data.get("internal", True)),
        )
        return Response({"id": str(note.id)}, status=201)


class AdminActivityView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = ActivityLog.objects.filter(is_platform=True).select_related("actor", "workspace")[:200]
        return Response(
            [
                {
                    "id": str(a.id),
                    "at": a.at.isoformat(),
                    "action": a.action,
                    "summary": a.summary,
                    "actor": a.actor.display_name if a.actor else None,
                    "contractorId": str(a.workspace_id) if a.workspace_id else None,
                }
                for a in qs
            ]
        )


class AdminSettingsView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        s, _ = PlatformSettings.objects.get_or_create(
            pk=1, defaults={"reminder_days": [60, 30, 14, 7]}
        )
        return Response(
            {
                "displayName": s.display_name,
                "contactEmail": s.contact_email,
                "backupHourIst": s.backup_hour_ist,
                "reminderDays": s.reminder_days,
                "maintenanceBanner": s.maintenance_banner,
                "notifyPaymentReview": s.notify_payment_review,
                "notifyBackupFailure": s.notify_backup_failure,
            }
        )

    def put(self, request):
        s, _ = PlatformSettings.objects.get_or_create(pk=1)
        mapping = {
            "displayName": "display_name",
            "contactEmail": "contact_email",
            "backupHourIst": "backup_hour_ist",
            "reminderDays": "reminder_days",
            "maintenanceBanner": "maintenance_banner",
            "notifyPaymentReview": "notify_payment_review",
            "notifyBackupFailure": "notify_backup_failure",
        }
        for src, dst in mapping.items():
            if src in request.data:
                setattr(s, dst, request.data[src])
        s.save()
        return self.get(request)


class AdminWalletListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        # Ensure every contractor has a wallet row for listing.
        missing = Workspace.objects.exclude(id__in=Wallet.objects.values_list("workspace_id", flat=True))
        for w in missing.iterator():
            get_or_create_wallet(w)
        wallets = Wallet.objects.select_related("workspace").order_by("-updated_at")
        return Response(
            {
                "wallets": [serialize_wallet(w) for w in wallets],
                "totals": {
                    "balancePaise": wallets.aggregate(t=Sum("balance_paise"))["t"] or 0,
                    "paidIncomePaise": paid_income_paise(),
                    "freeRechargedPaise": WalletTransaction.objects.filter(
                        kind=WalletTransaction.Kind.RECHARGE,
                        funding=WalletTransaction.Funding.FREE,
                        amount_paise__gt=0,
                    ).aggregate(t=Sum("amount_paise"))["t"]
                    or 0,
                },
            }
        )


class AdminWalletTransactionListView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        qs = WalletTransaction.objects.select_related("workspace", "created_by")
        funding = request.query_params.get("funding")
        if funding in WalletTransaction.Funding.values:
            qs = qs.filter(funding=funding)
        kind = request.query_params.get("kind")
        if kind in WalletTransaction.Kind.values:
            qs = qs.filter(kind=kind)
        cid = request.query_params.get("contractorId")
        if cid:
            qs = qs.filter(workspace_id=cid)
        days = request.query_params.get("days")
        if days and str(days).isdigit():
            since = timezone.now() - timedelta(days=int(days))
            qs = qs.filter(created_at__gte=since)
        return Response([serialize_tx(tx) for tx in qs[:300]])


class AdminContractorWalletView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request, pk):
        w = Workspace.objects.filter(pk=pk).first()
        if not w:
            return Response({"detail": "Not found."}, status=404)
        wallet = get_or_create_wallet(w)
        txs = WalletTransaction.objects.filter(workspace=w).select_related("workspace", "created_by")[:50]
        return Response({"wallet": serialize_wallet(wallet), "transactions": [serialize_tx(tx) for tx in txs]})

    def post(self, request, pk):
        """Admin recharge: body { amountPaise | amountInr, funding: free|paid, note?, reference? }."""
        w = Workspace.objects.filter(pk=pk).first()
        if not w:
            return Response({"detail": "Not found."}, status=404)

        funding = (request.data.get("funding") or "").strip().lower()
        if funding not in WalletTransaction.Funding.values:
            return Response(
                {"detail": "funding is required and must be free or paid.", "errors": {"funding": "Choose free or paid."}},
                status=400,
            )

        amount_paise = request.data.get("amountPaise")
        if amount_paise is None and request.data.get("amount_paise") is not None:
            amount_paise = request.data.get("amount_paise")
        if amount_paise is None and request.data.get("amountInr") is not None:
            try:
                amount_paise = int(round(float(request.data.get("amountInr")) * 100))
            except (TypeError, ValueError):
                return Response({"detail": "Invalid amountInr.", "errors": {"amountInr": "Enter a valid amount."}}, status=400)
        try:
            amount_paise = int(amount_paise)
        except (TypeError, ValueError):
            return Response(
                {"detail": "amountPaise (or amountInr) is required.", "errors": {"amount": "Enter a positive amount."}},
                status=400,
            )
        if amount_paise <= 0:
            return Response(
                {"detail": "Recharge amount must be positive.", "errors": {"amount": "Enter a positive amount."}},
                status=400,
            )

        note = (request.data.get("note") or "").strip()
        reference = (request.data.get("reference") or "").strip()
        wallet, tx = credit_wallet(
            workspace=w,
            amount_paise=amount_paise,
            funding=funding,
            note=note,
            reference=reference,
            source=WalletTransaction.Source.ADMIN,
            kind=WalletTransaction.Kind.RECHARGE,
            actor=request.user,
        )
        ActivityLog.objects.create(
            workspace=w,
            actor=request.user,
            action="wallet.recharge",
            target_type="wallet",
            target_id=str(wallet.id),
            summary=f"Wallet recharge {amount_paise} paise ({funding})",
            after={
                "amountPaise": amount_paise,
                "funding": funding,
                "balancePaise": wallet.balance_paise,
                "transactionId": str(tx.id),
            },
            is_platform=True,
        )
        return Response(
            {"wallet": serialize_wallet(wallet), "transaction": serialize_tx(tx)},
            status=201,
        )
