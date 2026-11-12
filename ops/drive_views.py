"""Contractor Google Drive connect / backup APIs."""
from __future__ import annotations

from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsWorkspaceUser, require_perm
from ops.drive_services import (
    build_connect_url,
    disconnect_drive,
    exchange_code,
    frontend_base,
    parse_oauth_state,
    run_workspace_backup,
    save_drive_tokens,
)
from ops.models import ActivityLog, BackupJob


def _backup_row(j: BackupJob) -> dict:
    return {
        "id": str(j.id),
        "at": (j.finished_at or j.created_at).isoformat(),
        "status": "success" if j.status == BackupJob.Status.SUCCESS else "failed" if j.status == BackupJob.Status.FAILED else j.status,
        "note": j.note,
        "jobType": j.job_type,
        "sizeBytes": j.size_bytes,
        "driveFileId": j.drive_file_id,
    }


class DriveStatusView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def get(self, request):
        ws = request.user.workspace
        jobs = BackupJob.objects.filter(workspace=ws)[:20]
        return Response(
            {
                "status": ws.drive_status,
                "email": ws.drive_email,
                "lastBackupAt": ws.drive_last_backup_at.isoformat() if ws.drive_last_backup_at else None,
                "driveFileId": ws.drive_file_id,
                "backups": [_backup_row(j) for j in jobs],
            }
        )


class DriveConnectView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def get(self, request):
        try:
            url = build_connect_url(workspace_id=str(request.user.workspace_id), user_id=str(request.user.id))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"url": url})


class DriveCallbackView(APIView):
    """Google redirects here (no JWT). Exchange code, then send user back to Settings."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        err = request.query_params.get("error")
        if err:
            return HttpResponseRedirect(f"{frontend_base()}/settings?drive=error&reason={err}")
        code = request.query_params.get("code") or ""
        state = request.query_params.get("state") or ""
        if not code or not state:
            return HttpResponseRedirect(f"{frontend_base()}/settings?drive=error&reason=missing_code")
        try:
            workspace_id, user_id = parse_oauth_state(state)
            from accounts.models import User, Workspace

            user = User.objects.filter(pk=user_id, workspace_id=workspace_id).first()
            ws = Workspace.objects.filter(pk=workspace_id).first()
            if not user or not ws or user.role != User.Role.OWNER:
                raise ValueError("Invalid account for Drive connect.")
            token = exchange_code(code)
            if not token.get("refresh_token") and not ws.drive_refresh_token:
                # User previously granted without offline — force reconnect with consent already requested.
                raise ValueError("Google did not return a refresh token. Remove CuboSites from Google Account → Security → Third-party access and try again.")
            save_drive_tokens(ws, token)
            ActivityLog.objects.create(
                workspace=ws,
                actor=user,
                action="update",
                target_type="drive",
                summary=f"Connected Google Drive ({ws.drive_email or 'account'})",
            )
            return HttpResponseRedirect(f"{frontend_base()}/settings?tab=drive&drive=connected")
        except Exception as e:
            q = urlencode({"drive": "error", "reason": str(e)[:180], "tab": "drive"})
            return HttpResponseRedirect(f"{frontend_base()}/settings?{q}")


class DriveDisconnectView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request):
        ws = request.user.workspace
        disconnect_drive(ws)
        ActivityLog.objects.create(
            workspace=ws,
            actor=request.user,
            action="update",
            target_type="drive",
            summary="Disconnected Google Drive",
        )
        return Response({"ok": True, "status": "not_connected"})


class DriveBackupRunView(APIView):
    """Manual backup — uploads JSON.gz to Drive and deletes the previous backup file."""

    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def post(self, request):
        ws = request.user.workspace
        try:
            job = run_workspace_backup(ws, job_type="manual", actor=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=502)
        ActivityLog.objects.create(
            workspace=ws,
            actor=request.user,
            action="create",
            target_type="backup",
            target_id=str(job.id),
            summary=f"Manual Drive backup ({job.status})",
        )
        return Response({"backup": _backup_row(job), "lastBackupAt": ws.drive_last_backup_at.isoformat() if ws.drive_last_backup_at else None})


class DriveBackupListView(APIView):
    permission_classes = [IsWorkspaceUser, require_perm("manageStaffSites")]

    def get(self, request):
        qs = BackupJob.objects.filter(workspace=request.user.workspace)[:50]
        return Response([_backup_row(j) for j in qs])
