import uuid

from django.conf import settings
from django.db import models


class Site(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        INACTIVE = "inactive", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="sites",
    )
    name = models.CharField(max_length=200)
    primary_phone = models.CharField(max_length=32)
    alt_phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=400, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField()
    reactivated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["workspace", "status"])]

    def __str__(self) -> str:
        return self.name


class SiteStatusEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=20, choices=Site.Status.choices)
    at = models.DateTimeField(auto_now_add=True)
    by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-at"]


class SiteAssignment(models.Model):
    """Staff membership on a site (M2M through table)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="site_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("site", "user")
        # Prefetch/filter by user on staff lists (composite unique starts with site).
        indexes = [models.Index(fields=["user"])]
