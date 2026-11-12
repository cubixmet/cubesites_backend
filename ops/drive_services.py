"""Google Drive backup: OAuth, export workspace JSON, upload (replace previous file)."""
from __future__ import annotations

import gzip
import io
import json
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone

from accounts.models import User, Workspace
from jobsites.models import Site
from ledger.models import Attachment, Entry, Item
from ops.models import AppNotification, BackupJob, Note, Reminder

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


def drive_redirect_uri() -> str:
    return (
        getattr(settings, "GOOGLE_DRIVE_REDIRECT_URI", "")
        or getattr(settings, "GOOGLE_REDIRECT_URI", "")
        or "http://localhost:8000/api/v1/drive/callback/"
    ).strip()


def frontend_base() -> str:
    return (getattr(settings, "FRONTEND_URL", "") or "http://localhost:8080").rstrip("/")


def _signer() -> TimestampSigner:
    return TimestampSigner(salt="cubosites-drive-oauth")


def build_connect_url(*, workspace_id: str, user_id: str) -> str:
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id or not settings.GOOGLE_CLIENT_SECRET:
        raise ValueError("Google OAuth is not configured.")
    state = _signer().sign(f"{workspace_id}:{user_id}")
    params = {
        "client_id": client_id,
        "redirect_uri": drive_redirect_uri(),
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URI}?{urlencode(params)}"


def parse_oauth_state(state: str, max_age: int = 600) -> tuple[str, str]:
    try:
        raw = _signer().unsign(state, max_age=max_age)
    except SignatureExpired as e:
        raise ValueError("OAuth state expired. Try connecting again.") from e
    except BadSignature as e:
        raise ValueError("Invalid OAuth state.") from e
    workspace_id, _, user_id = raw.partition(":")
    if not workspace_id or not user_id:
        raise ValueError("Invalid OAuth state payload.")
    return workspace_id, user_id


def exchange_code(code: str) -> dict[str, Any]:
    res = requests.post(
        TOKEN_URI,
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": drive_redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    data = res.json()
    if res.status_code >= 400 or "access_token" not in data:
        raise ValueError(data.get("error_description") or data.get("error") or "Token exchange failed.")
    return data


def refresh_access_token(ws: Workspace) -> str:
    if not ws.drive_refresh_token:
        ws.drive_status = "expired"
        ws.save(update_fields=["drive_status", "updated_at"])
        raise ValueError("Google Drive is not connected.")
    if ws.drive_access_token and ws.drive_token_expiry and ws.drive_token_expiry > timezone.now() + timedelta(minutes=2):
        return ws.drive_access_token
    res = requests.post(
        TOKEN_URI,
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": ws.drive_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    data = res.json()
    if res.status_code >= 400 or "access_token" not in data:
        ws.drive_status = "expired"
        ws.save(update_fields=["drive_status", "updated_at"])
        raise ValueError(data.get("error_description") or "Drive token refresh failed — reconnect Google Drive.")
    ws.drive_access_token = data["access_token"]
    expires_in = int(data.get("expires_in") or 3600)
    ws.drive_token_expiry = timezone.now() + timedelta(seconds=expires_in)
    ws.drive_status = "connected"
    fields = ["drive_access_token", "drive_token_expiry", "drive_status", "updated_at"]
    if data.get("refresh_token"):
        ws.drive_refresh_token = data["refresh_token"]
        fields.append("drive_refresh_token")
    ws.save(update_fields=fields)
    return ws.drive_access_token


def fetch_drive_email(access_token: str) -> str:
    res = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if res.status_code >= 400:
        return ""
    return (res.json().get("email") or "").strip()


def save_drive_tokens(ws: Workspace, token: dict[str, Any]) -> Workspace:
    ws.drive_access_token = token["access_token"]
    if token.get("refresh_token"):
        ws.drive_refresh_token = token["refresh_token"]
    expires_in = int(token.get("expires_in") or 3600)
    ws.drive_token_expiry = timezone.now() + timedelta(seconds=expires_in)
    ws.drive_email = fetch_drive_email(token["access_token"])
    ws.drive_status = "connected"
    ws.save(
        update_fields=[
            "drive_access_token",
            "drive_refresh_token",
            "drive_token_expiry",
            "drive_email",
            "drive_status",
            "updated_at",
        ]
    )
    return ws


def disconnect_drive(ws: Workspace) -> None:
    ws.drive_status = "not_connected"
    ws.drive_email = ""
    ws.drive_refresh_token = ""
    ws.drive_access_token = ""
    ws.drive_token_expiry = None
    ws.drive_folder_id = ""
    # Keep drive_file_id / last_backup_at for history reference; file remains in user's Drive.
    ws.save(
        update_fields=[
            "drive_status",
            "drive_email",
            "drive_refresh_token",
            "drive_access_token",
            "drive_token_expiry",
            "drive_folder_id",
            "updated_at",
        ]
    )


def _safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "workspace").strip())[:60]
    return cleaned or "workspace"


def build_workspace_backup(ws: Workspace) -> dict[str, Any]:
    sites = list(Site.objects.filter(workspace=ws).values())
    users = list(
        User.objects.filter(workspace=ws).values(
            "id", "email", "first_name", "last_name", "role", "phone", "is_active", "date_joined"
        )
    )
    items = list(Item.objects.filter(workspace=ws).values())
    entries = list(Entry.objects.filter(workspace=ws).values())
    media = list(Attachment.objects.filter(workspace=ws).values("id", "site_id", "entry_id", "kind", "name", "size_bytes", "date", "created_at"))
    notes = list(Note.objects.filter(workspace=ws).values())
    reminders = list(Reminder.objects.filter(workspace=ws).values())
    return {
        "format": "cubosites.workspace.backup.v1",
        "exportedAt": timezone.now().isoformat(),
        "workspace": {
            "id": str(ws.id),
            "businessName": ws.business_name,
            "ownerName": ws.owner_name,
            "email": ws.email,
            "phone": ws.phone,
            "district": ws.district,
            "gstin": ws.gstin,
        },
        "sites": _jsonable(sites),
        "users": _jsonable(users),
        "items": _jsonable(items),
        "entries": _jsonable(entries),
        "mediaMeta": _jsonable(media),
        "notes": _jsonable(notes),
        "reminders": _jsonable(reminders),
    }


def _jsonable(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif hasattr(v, "hex"):  # UUID
                item[k] = str(v)
            else:
                item[k] = v
        out.append(item)
    return out


def _gzip_json(payload: dict) -> bytes:
    raw = json.dumps(payload, default=str).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return buf.getvalue()


def _ensure_folder(ws: Workspace, access_token: str) -> str:
    if ws.drive_folder_id:
        # Verify folder still exists
        check = requests.get(
            f"{DRIVE_FILES}/{ws.drive_folder_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id,trashed"},
            timeout=20,
        )
        if check.status_code == 200 and not check.json().get("trashed"):
            return ws.drive_folder_id

    meta = {
        "name": "CuboSites Backups",
        "mimeType": "application/vnd.google-apps.folder",
        "description": "Automatic monthly workspace backups from CuboSites",
    }
    res = requests.post(
        DRIVE_FILES,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        params={"fields": "id"},
        json=meta,
        timeout=30,
    )
    if res.status_code >= 400:
        raise ValueError(f"Could not create Drive folder: {res.text[:200]}")
    folder_id = res.json()["id"]
    ws.drive_folder_id = folder_id
    ws.save(update_fields=["drive_folder_id", "updated_at"])
    return folder_id


def _delete_drive_file(access_token: str, file_id: str) -> None:
    if not file_id:
        return
    requests.delete(
        f"{DRIVE_FILES}/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )


def _upload_file(*, access_token: str, folder_id: str, name: str, data: bytes) -> str:
    boundary = "cubosites_backup_boundary"
    meta = json.dumps({"name": name, "parents": [folder_id], "mimeType": "application/gzip"})
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: application/gzip\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    res = requests.post(
        DRIVE_UPLOAD,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        params={"uploadType": "multipart", "fields": "id,name,size"},
        data=body,
        timeout=120,
    )
    if res.status_code >= 400:
        raise ValueError(f"Drive upload failed: {res.text[:300]}")
    return res.json()["id"]


def run_workspace_backup(ws: Workspace, *, job_type: str = "manual", actor: User | None = None) -> BackupJob:
    job = BackupJob.objects.create(
        workspace=ws,
        job_type=job_type,
        status=BackupJob.Status.RUNNING,
        started_at=timezone.now(),
        logs=[{"at": timezone.now().isoformat(), "level": "info", "message": f"Started {job_type} backup"}],
    )
    try:
        if ws.drive_status not in ("connected", "expired") or not ws.drive_refresh_token:
            raise ValueError("Connect Google Drive before running a backup.")
        access = refresh_access_token(ws)
        folder_id = _ensure_folder(ws, access)
        payload = build_workspace_backup(ws)
        blob = _gzip_json(payload)
        month = timezone.localdate().strftime("%Y-%m")
        filename = f"CuboSites-{_safe_name(ws.business_name)}-{month}.json.gz"

        # Replace previous backup file (keep only the latest).
        old_id = ws.drive_file_id
        if old_id:
            _delete_drive_file(access, old_id)
            job.logs.append({"at": timezone.now().isoformat(), "level": "info", "message": f"Deleted previous backup {old_id}"})

        file_id = _upload_file(access_token=access, folder_id=folder_id, name=filename, data=blob)
        ws.drive_file_id = file_id
        ws.drive_last_backup_at = timezone.now()
        ws.drive_status = "connected"
        ws.save(update_fields=["drive_file_id", "drive_last_backup_at", "drive_status", "updated_at"])

        job.status = BackupJob.Status.SUCCESS
        job.finished_at = timezone.now()
        job.drive_file_id = file_id
        job.size_bytes = len(blob)
        job.note = f"Uploaded {filename} ({len(blob)} bytes)"
        job.logs.append({"at": timezone.now().isoformat(), "level": "info", "message": job.note})
        job.save()
        return job
    except Exception as e:
        job.status = BackupJob.Status.FAILED
        job.finished_at = timezone.now()
        job.note = str(e)[:500]
        job.logs.append({"at": timezone.now().isoformat(), "level": "error", "message": str(e)[:500]})
        job.save()
        if ws.notify_backup_failure:
            AppNotification.objects.create(
                workspace=ws,
                user=actor,
                title="Drive backup failed",
                body=str(e)[:400],
                type="backup_failed",
            )
        raise


def workspaces_due_for_monthly_backup():
    """Connected workspaces with no successful backup in the current calendar month."""
    now = timezone.localtime()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = Workspace.objects.filter(drive_status="connected").exclude(drive_refresh_token="")
    due = []
    for ws in qs:
        if not ws.drive_last_backup_at or timezone.localtime(ws.drive_last_backup_at) < month_start:
            due.append(ws)
    return due
