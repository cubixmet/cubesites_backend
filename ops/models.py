import uuid

from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=40)
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64, blank=True)
    site = models.ForeignKey(
        "jobsites.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    summary = models.CharField(max_length=400)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    is_platform = models.BooleanField(default=False)

    class Meta:
        ordering = ["-at"]


class AppNotification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    type = models.CharField(max_length=40, blank=True)
    at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)
    is_platform = models.BooleanField(default=False)

    class Meta:
        ordering = ["-at"]


class BackupJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="backup_jobs",
    )
    job_type = models.CharField(max_length=40, default="scheduled")  # scheduled | manual
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    drive_file_id = models.CharField(max_length=128, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    restore_test_result = models.CharField(max_length=20, blank=True)
    logs = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SupportCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="support_cases",
    )
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SupportNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    body = models.TextField()
    internal = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class RetentionNotice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="retention_notices",
    )
    channel = models.CharField(max_length=10, default="email")
    days_before = models.PositiveIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default="sent")


class PlatformSettings(models.Model):
    """Singleton-ish platform admin preferences (pk=1)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    display_name = models.CharField(max_length=120, default="CuboSites Admin")
    contact_email = models.EmailField(default="admin@cubesites.in")
    backup_hour_ist = models.PositiveSmallIntegerField(default=2)
    reminder_days = models.JSONField(default=list)  # [60,30,14,7]
    maintenance_banner = models.TextField(blank=True)
    notify_payment_review = models.BooleanField(default=True)
    notify_backup_failure = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class Note(models.Model):
    """Workspace notes — optionally linked to a site, or independent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="notes",
    )
    site = models.ForeignKey(
        "jobsites.Site",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    pinned = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pinned", "-updated_at"]


class Reminder(models.Model):
    """Timed reminders — optionally linked to a site. due_at drives local/PWA notifications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    site = models.ForeignKey(
        "jobsites.Site",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    due_at = models.DateTimeField()
    done = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["done", "due_at"]
        indexes = [models.Index(fields=["workspace", "due_at", "done"])]
