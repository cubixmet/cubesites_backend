import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Item(models.Model):
    class Type(models.TextChoices):
        MATERIALS = "materials", "Materials"
        LABOUR = "labour", "Labour"
        EQUIPMENT = "equipment", "Equipment"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="items",
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    name = models.CharField(max_length=200)
    normalized = models.CharField(max_length=200, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("workspace", "type", "normalized")

    def __str__(self) -> str:
        return self.name


class Entry(models.Model):
    class Type(models.TextChoices):
        MATERIALS = "materials", "Materials"
        LABOUR = "labour", "Labour"
        EQUIPMENT = "equipment", "Equipment"
        OTHER = "other", "Other"
        PAYMENT = "payment", "Client payment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="entries",
    )
    site = models.ForeignKey("jobsites.Site", on_delete=models.CASCADE, related_name="entries")
    type = models.CharField(max_length=20, choices=Type.choices)
    item = models.ForeignKey(
        Item,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="entries",
    )
    description = models.CharField(max_length=400)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    unit_price_paise = models.BigIntegerField(null=True, blank=True)
    total_paise = models.BigIntegerField(validators=[MinValueValidator(1)])
    date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["workspace", "date"]),
            models.Index(fields=["site", "type"]),
        ]

    @property
    def is_expense(self) -> bool:
        return self.type != self.Type.PAYMENT


class Attachment(models.Model):
    class Kind(models.TextChoices):
        BILL = "bill", "Bill"
        PHOTO = "photo", "Progress photo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    site = models.ForeignKey("jobsites.Site", on_delete=models.CASCADE, related_name="attachments")
    entry = models.ForeignKey(
        Entry,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    file = models.FileField(upload_to="attachments/%Y/%m/")
    caption = models.CharField(max_length=80, blank=True)
    date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
