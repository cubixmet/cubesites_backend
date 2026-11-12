from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsWorkspaceUser, require_perm, require_user_perm
from accounts.tenancy import assert_site_access, filter_sites_for_user, visible_site_ids
from billing.services import billing_period, reactivation_charge, site_charge, pricing_at
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from jobsites.serializers import SiteSerializer
from ledger.models import Entry
from ops.models import ActivityLog


class SiteListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsWorkspaceUser]
    serializer_class = SiteSerializer
    pagination_class = None

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsWorkspaceUser(), require_perm("manageStaffSites")()]
        return [IsWorkspaceUser(), require_perm("viewSite")()]

    def get_queryset(self):
        qs = filter_sites_for_user(Site.objects.all(), self.request.user)
        status_f = self.request.query_params.get("status")
        q = self.request.query_params.get("q")
        if status_f and status_f != "all":
            qs = qs.filter(status=status_f)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(address__icontains=q))
        return qs.prefetch_related("status_history")

    def perform_create(self, serializer):
        site = serializer.save(
            workspace=self.request.user.workspace,
            start_date=serializer.validated_data.get("start_date") or timezone.localdate(),
            status=Site.Status.ACTIVE,
        )
        SiteStatusEvent.objects.create(
            site=site, status=Site.Status.ACTIVE, by=self.request.user
        )
        ActivityLog.objects.create(
            workspace=self.request.user.workspace,
            actor=self.request.user,
            action="create",
            target_type="site",
            target_id=str(site.id),
            site=site,
            summary=f'Created site "{site.name}"',
        )


class SiteDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsWorkspaceUser]
    serializer_class = SiteSerializer
    lookup_field = "pk"

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsWorkspaceUser(), require_perm("manageStaffSites")()]
        return [IsWorkspaceUser(), require_perm("viewSite")()]

    def get_queryset(self):
        return filter_sites_for_user(Site.objects.all(), self.request.user).prefetch_related(
            "status_history"
        )


class SiteTotalsView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request, pk):
        # Financial aggregates — never send without viewFinancials.
        require_user_perm(request.user, "viewFinancials")
        site = Site.objects.filter(pk=pk, workspace=request.user.workspace).first()
        if not site:
            return Response({"detail": "Not found."}, status=404)
        assert_site_access(request.user, site)
        fro = request.query_params.get("from")
        to = request.query_params.get("to")
        qs = Entry.objects.filter(site=site)
        if fro:
            qs = qs.filter(date__gte=fro)
        if to:
            qs = qs.filter(date__lte=to)
        expenses = (
            qs.exclude(type=Entry.Type.PAYMENT).aggregate(s=Sum("total_paise"))["s"] or 0
        )
        payments = qs.filter(type=Entry.Type.PAYMENT).aggregate(s=Sum("total_paise"))["s"] or 0
        return Response(
            {
                "expenses": expenses,
                "payments": payments,
                "net": payments - expenses,
                "count": qs.count(),
            }
        )


class SiteStatusView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request, pk):
        site = Site.objects.filter(pk=pk, workspace=request.user.workspace).first()
        if not site:
            return Response({"detail": "Not found."}, status=404)
        new_status = request.data.get("status")
        if new_status not in Site.Status.values:
            return Response({"detail": "Invalid status."}, status=400)
        before = site.status
        quote = None
        if new_status == Site.Status.ACTIVE and before != Site.Status.ACTIVE:
            active = Site.objects.filter(
                workspace=request.user.workspace, status=Site.Status.ACTIVE
            ).count()
            p = pricing_at()
            period = billing_period(p=p)
            if active >= p.free_sites:
                quote = {
                    "amountPaise": reactivation_charge(period["remainingDays"], p),
                    "remainingDays": period["remainingDays"],
                }
            site.reactivated_at = timezone.now()
        site.status = new_status
        site.save()
        SiteStatusEvent.objects.create(site=site, status=new_status, by=request.user)
        action = {
            Site.Status.ACTIVE: "reactivate",
            Site.Status.COMPLETED: "complete",
            Site.Status.INACTIVE: "deactivate",
        }.get(new_status, "update")
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action=action,
            target_type="site",
            target_id=str(site.id),
            site=site,
            summary=f'Changed site "{site.name}" {before} → {new_status}',
            before={"status": before},
            after={"status": new_status},
        )
        data = SiteSerializer(site).data
        if quote is not None:
            data["reactivationQuote"] = quote
        return Response(data)


class SiteAssignView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def put(self, request, pk):
        site = Site.objects.filter(pk=pk, workspace=request.user.workspace).first()
        if not site:
            return Response({"detail": "Not found."}, status=404)
        user_ids = request.data.get("userIds") or request.data.get("user_ids") or []
        from accounts.models import User

        users = User.objects.filter(
            workspace=request.user.workspace, id__in=user_ids
        ).exclude(role=User.Role.OWNER)
        SiteAssignment.objects.filter(site=site).delete()
        SiteAssignment.objects.bulk_create(
            [SiteAssignment(site=site, user=u) for u in users]
        )
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="update",
            target_type="site",
            target_id=str(site.id),
            site=site,
            summary=f"Updated staff assignments ({users.count()} assigned)",
        )
        return Response({"assigned": [str(u.id) for u in users]})
