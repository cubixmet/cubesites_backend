"""Contractor notes & reminders (optional site link)."""
from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsWorkspaceUser, require_user_perm
from accounts.tenancy import visible_site_ids
from jobsites.models import Site
from ops.models import ActivityLog, AppNotification, Note, Reminder


def _site_or_none(workspace, site_id, user):
    if not site_id:
        return None
    site = Site.objects.filter(workspace=workspace, pk=site_id).first()
    if not site:
        return Response({"detail": "Site not found."}, status=404)
    if user.role != user.Role.OWNER and str(site.id) not in {str(x) for x in visible_site_ids(user)}:
        return Response({"detail": "No access to this site."}, status=403)
    return site


def _note_row(n: Note) -> dict:
    return {
        "id": str(n.id),
        "siteId": str(n.site_id) if n.site_id else None,
        "title": n.title,
        "body": n.body,
        "pinned": n.pinned,
        "createdBy": str(n.created_by_id) if n.created_by_id else None,
        "createdAt": n.created_at.isoformat(),
        "updatedAt": n.updated_at.isoformat(),
    }


def _reminder_row(r: Reminder) -> dict:
    return {
        "id": str(r.id),
        "siteId": str(r.site_id) if r.site_id else None,
        "title": r.title,
        "body": r.body,
        "dueAt": r.due_at.isoformat(),
        "done": r.done,
        "notifiedAt": r.notified_at.isoformat() if r.notified_at else None,
        "createdBy": str(r.created_by_id) if r.created_by_id else None,
        "createdAt": r.created_at.isoformat(),
        "updatedAt": r.updated_at.isoformat(),
    }


def _filter_by_site_access(qs, user, site_field="site_id"):
    if user.role == user.Role.OWNER:
        return qs
    ids = list(visible_site_ids(user))
    from django.db.models import Q

    return qs.filter(Q(**{f"{site_field}__in": ids}) | Q(**{f"{site_field}__isnull": True}))


class NoteListCreateView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        require_user_perm(request.user, "viewSite")
        qs = Note.objects.filter(workspace=request.user.workspace)
        qs = _filter_by_site_access(qs, request.user)
        site_id = request.query_params.get("siteId")
        if site_id == "none":
            qs = qs.filter(site__isnull=True)
        elif site_id:
            qs = qs.filter(site_id=site_id)
        return Response([_note_row(n) for n in qs[:200]])

    def post(self, request):
        require_user_perm(request.user, "viewSite")
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()
        if len(title) < 1:
            return Response({"detail": "Title is required.", "errors": {"title": "Enter a title."}}, status=400)
        site_raw = request.data.get("siteId") or request.data.get("site_id")
        site = _site_or_none(request.user.workspace, site_raw, request.user)
        if isinstance(site, Response):
            return site
        note = Note.objects.create(
            workspace=request.user.workspace,
            site=site,
            title=title[:200],
            body=body,
            pinned=bool(request.data.get("pinned")),
            created_by=request.user,
        )
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="create",
            target_type="note",
            target_id=str(note.id),
            site=site,
            summary=f"Added note “{note.title}”",
        )
        return Response(_note_row(note), status=201)


class NoteDetailView(APIView):
    permission_classes = [IsWorkspaceUser]

    def _get(self, request, pk):
        note = Note.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not note:
            return None, Response({"detail": "Not found."}, status=404)
        if request.user.role != request.user.Role.OWNER:
            ids = {str(x) for x in visible_site_ids(request.user)}
            if note.site_id and str(note.site_id) not in ids:
                return None, Response({"detail": "Not found."}, status=404)
        return note, None

    def patch(self, request, pk):
        require_user_perm(request.user, "viewSite")
        note, err = self._get(request, pk)
        if err:
            return err
        if "title" in request.data:
            title = (request.data.get("title") or "").strip()
            if not title:
                return Response({"detail": "Title is required."}, status=400)
            note.title = title[:200]
        if "body" in request.data:
            note.body = (request.data.get("body") or "").strip()
        if "pinned" in request.data:
            note.pinned = bool(request.data.get("pinned"))
        if "siteId" in request.data or "site_id" in request.data:
            site_raw = request.data.get("siteId") if "siteId" in request.data else request.data.get("site_id")
            if site_raw in (None, "", "none"):
                note.site = None
            else:
                site = _site_or_none(request.user.workspace, site_raw, request.user)
                if isinstance(site, Response):
                    return site
                note.site = site
        note.save()
        return Response(_note_row(note))

    def delete(self, request, pk):
        require_user_perm(request.user, "viewSite")
        note, err = self._get(request, pk)
        if err:
            return err
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="delete",
            target_type="note",
            target_id=str(note.id),
            site=note.site,
            summary=f"Deleted note “{note.title}”",
        )
        note.delete()
        return Response({"ok": True})


class ReminderListCreateView(APIView):
    permission_classes = [IsWorkspaceUser]

    def get(self, request):
        require_user_perm(request.user, "viewSite")
        qs = Reminder.objects.filter(workspace=request.user.workspace)
        qs = _filter_by_site_access(qs, request.user)
        site_id = request.query_params.get("siteId")
        if site_id == "none":
            qs = qs.filter(site__isnull=True)
        elif site_id:
            qs = qs.filter(site_id=site_id)
        status = request.query_params.get("status")
        if status == "open":
            qs = qs.filter(done=False)
        elif status == "done":
            qs = qs.filter(done=True)
        elif status == "due":
            qs = qs.filter(done=False, due_at__lte=timezone.now())
        return Response([_reminder_row(r) for r in qs[:300]])

    def post(self, request):
        require_user_perm(request.user, "viewSite")
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()
        due_raw = request.data.get("dueAt") or request.data.get("due_at") or ""
        due_at = parse_datetime(str(due_raw).replace("Z", "+00:00")) if due_raw else None
        if timezone.is_naive(due_at) if due_at else False:
            due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
        errors = {}
        if len(title) < 1:
            errors["title"] = "Enter a title."
        if not due_at:
            errors["dueAt"] = "Pick a date and time for the alarm."
        if errors:
            return Response({"detail": "Validation failed.", "errors": errors}, status=400)
        site_raw = request.data.get("siteId") or request.data.get("site_id")
        site = _site_or_none(request.user.workspace, site_raw, request.user)
        if isinstance(site, Response):
            return site
        rem = Reminder.objects.create(
            workspace=request.user.workspace,
            site=site,
            title=title[:200],
            body=body,
            due_at=due_at,
            created_by=request.user,
        )
        ActivityLog.objects.create(
            workspace=request.user.workspace,
            actor=request.user,
            action="create",
            target_type="reminder",
            target_id=str(rem.id),
            site=site,
            summary=f"Set reminder “{rem.title}” for {rem.due_at.isoformat()}",
        )
        return Response(_reminder_row(rem), status=201)


class ReminderDetailView(APIView):
    permission_classes = [IsWorkspaceUser]

    def _get(self, request, pk):
        rem = Reminder.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not rem:
            return None, Response({"detail": "Not found."}, status=404)
        if request.user.role != request.user.Role.OWNER:
            ids = {str(x) for x in visible_site_ids(request.user)}
            if rem.site_id and str(rem.site_id) not in ids:
                return None, Response({"detail": "Not found."}, status=404)
        return rem, None

    def patch(self, request, pk):
        require_user_perm(request.user, "viewSite")
        rem, err = self._get(request, pk)
        if err:
            return err
        if "title" in request.data:
            title = (request.data.get("title") or "").strip()
            if not title:
                return Response({"detail": "Title is required."}, status=400)
            rem.title = title[:200]
        if "body" in request.data:
            rem.body = (request.data.get("body") or "").strip()
        if "dueAt" in request.data or "due_at" in request.data:
            due_raw = request.data.get("dueAt") if "dueAt" in request.data else request.data.get("due_at")
            due_at = parse_datetime(str(due_raw).replace("Z", "+00:00")) if due_raw else None
            if due_at and timezone.is_naive(due_at):
                due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
            if not due_at:
                return Response({"detail": "Invalid dueAt."}, status=400)
            rem.due_at = due_at
            rem.notified_at = None  # reschedule
        if "done" in request.data:
            rem.done = bool(request.data.get("done"))
        if "siteId" in request.data or "site_id" in request.data:
            site_raw = request.data.get("siteId") if "siteId" in request.data else request.data.get("site_id")
            if site_raw in (None, "", "none"):
                rem.site = None
            else:
                site = _site_or_none(request.user.workspace, site_raw, request.user)
                if isinstance(site, Response):
                    return site
                rem.site = site
        rem.save()
        return Response(_reminder_row(rem))

    def delete(self, request, pk):
        require_user_perm(request.user, "viewSite")
        rem, err = self._get(request, pk)
        if err:
            return err
        rem.delete()
        return Response({"ok": True})


class ReminderNotifyView(APIView):
    """Mark reminder as notified and create an in-app notification (after OS alarm fires)."""

    permission_classes = [IsWorkspaceUser]

    def post(self, request, pk):
        require_user_perm(request.user, "viewSite")
        rem = Reminder.objects.filter(workspace=request.user.workspace, pk=pk).first()
        if not rem:
            return Response({"detail": "Not found."}, status=404)
        if rem.notified_at:
            return Response(_reminder_row(rem))
        rem.notified_at = timezone.now()
        rem.save(update_fields=["notified_at", "updated_at"])
        AppNotification.objects.create(
            workspace=request.user.workspace,
            user=request.user,
            title=f"Reminder: {rem.title}",
            body=rem.body or f"Due {rem.due_at.isoformat()}",
            type="reminder",
        )
        return Response(_reminder_row(rem))
