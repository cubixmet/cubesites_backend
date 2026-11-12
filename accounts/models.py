import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

PERMISSION_KEYS = (
    "viewSite",
    "viewFinancials",
    "createEntries",
    "editEntries",
    "manageItems",
    "uploadMedia",
    "reports",
    "manageStaffSites",
)


def default_permissions(role: str) -> dict:
    if role == "owner":
        return {k: True for k in PERMISSION_KEYS}
    if role == "site_manager":
        return {
            "viewSite": True,
            "viewFinancials": True,
            "createEntries": True,
            "editEntries": True,
            "manageItems": True,
            "uploadMedia": True,
            "reports": True,
            "manageStaffSites": False,
        }
    return {
        "viewSite": True,
        "viewFinancials": False,
        "createEntries": True,
        "editEntries": False,
        "manageItems": False,
        "uploadMedia": True,
        "reports": False,
        "manageStaffSites": False,
    }


class Workspace(models.Model):
    """Contractor tenant account (frontend `Account`)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32)
    email = models.EmailField()
    district = models.CharField(max_length=120, blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    tax_label = models.CharField(max_length=40, default="GST")
    tax_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    show_tax_breakup = models.BooleanField(default=True)
    drive_status = models.CharField(
        max_length=20,
        default="not_connected",
        choices=[
            ("not_connected", "Not connected"),
            ("connected", "Connected"),
            ("expired", "Expired"),
            ("token_expired", "Token expired"),
        ],
    )
    drive_email = models.EmailField(blank=True)
    drive_refresh_token = models.TextField(blank=True)
    drive_access_token = models.TextField(blank=True)
    drive_token_expiry = models.DateTimeField(null=True, blank=True)
    drive_folder_id = models.CharField(max_length=128, blank=True)
    drive_file_id = models.CharField(max_length=128, blank=True)
    drive_last_backup_at = models.DateTimeField(null=True, blank=True)
    notify_daily_summary = models.BooleanField(default=True)
    notify_payment_received = models.BooleanField(default=True)
    notify_backup_failure = models.BooleanField(default=True)
    notify_invoice_due = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["business_name"]

    def __str__(self) -> str:
        return self.business_name


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        SITE_MANAGER = "site_manager", "Site manager"
        STAFF = "staff", "Staff"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="users",
    )
    phone = models.CharField(max_length=32, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    permissions = models.JSONField(default=dict, blank=True)
    is_platform_admin = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    google_sub = models.CharField(max_length=64, blank=True, db_index=True)
    auth_provider = models.CharField(
        max_length=20,
        default="password",
        choices=[
            ("password", "Email & password"),
            ("google", "Google"),
            ("mixed", "Google + password"),
        ],
    )
    last_site = models.ForeignKey(
        "jobsites.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["first_name", "email"]

    def save(self, *args, **kwargs):
        if not self.permissions:
            self.permissions = default_permissions(
                self.Role.OWNER if self.is_platform_admin else self.role
            )
        if self.is_platform_admin:
            self.role = self.Role.OWNER
            self.permissions = {k: True for k in PERMISSION_KEYS}
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        full = self.get_full_name().strip()
        return full or self.username

    def has_perm_key(self, key: str) -> bool:
        if self.is_platform_admin or self.role == self.Role.OWNER:
            return True
        return bool(self.permissions.get(key))

    def __str__(self) -> str:
        return self.email or self.username


class EmailOTP(models.Model):
    """One-time codes for email signup and password reset (not used at login time)."""

    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Signup"
        PASSWORD_RESET = "password_reset", "Password reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.SIGNUP)
    payload = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "purpose"])]

