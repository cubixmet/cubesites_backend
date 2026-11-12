from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import (
    IsWorkspaceUser,
    can_view_financials,
    redact_money_fields,
    require_user_perm,
)
from accounts.tenancy import visible_site_ids
from ops.models import ActivityLog, AppNotification


class ActivityListView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        require_user_perm(request.user, "viewSite")
        u = request.user
        qs = ActivityLog.objects.filter(workspace=u.workspace, is_platform=False)
        if u.role != u.Role.OWNER:
            ids = visible_site_ids(u)
            qs = qs.filter(models_q_site_or_self(u, ids))
        actor = request.query_params.get("actor")
        action = request.query_params.get("action")
        if actor and actor != "all":
            qs = qs.filter(actor_id=actor)
        if action and action != "all":
            qs = qs.filter(action=action)
        fin = can_view_financials(u)
        rows = []
        for a in qs[:200]:
            row = {
                "id": str(a.id),
                "actorId": str(a.actor_id) if a.actor_id else None,
                "at": a.at.isoformat(),
                "action": a.action,
                "targetType": a.target_type,
                "targetId": a.target_id,
                "siteId": str(a.site_id) if a.site_id else None,
                "summary": a.summary,
                "before": a.before,
                "after": a.after,
            }
            if not fin:
                row = redact_money_fields(row)
            rows.append(row)
        return Response(rows)


def models_q_site_or_self(user, site_ids):
    from django.db.models import Q

    return Q(site_id__in=site_ids) | Q(site__isnull=True, actor=user)


class NotificationListView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        qs = AppNotification.objects.filter(workspace=request.user.workspace, is_platform=False)
        return Response(
            [
                {
                    "id": str(n.id),
                    "title": n.title,
                    "body": n.body,
                    "at": n.at.isoformat(),
                    "read": n.read,
                }
                for n in qs[:100]
            ]
        )


class NotificationReadView(APIView):
    permission_classes = [IsWorkspaceUser]

    def post(self, request, pk):
        n = AppNotification.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not n:
            return Response({"detail": "Not found."}, status=404)
        n.read = True
        n.save(update_fields=["read"])
        return Response({"id": str(n.id), "read": True})


class NotificationReadAllView(APIView):
    permission_classes = [IsWorkspaceUser]

    def post(self, request):
        AppNotification.objects.filter(
            workspace=request.user.workspace, read=False
        ).update(read=True)
        return Response({"ok": True})
