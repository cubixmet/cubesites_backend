import uuid

from django.conf import settings
from django.db import models


class PricingVersion(models.Model):
    """Effective-dated platform pricing (paise)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=120)
    effective_from = models.DateField()
    site_per_month = models.BigIntegerField()
    free_sites = models.PositiveIntegerField(default=3)
    staff_per_month = models.BigIntegerField()
    free_staff = models.PositiveIntegerField(default=1)
    free_storage_mb = models.PositiveIntegerField(default=250)
    storage_block_mb = models.PositiveIntegerField(default=250)
    storage_block_price = models.BigIntegerField()
    days_per_month = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-effective_from", "-created_at"]

    def __str__(self) -> str:
        return f"{self.label} ({self.effective_from})"


class TaxRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=40, default="GST")
    rate_pct = models.DecimalField(max_digits=5, decimal_places=2)
    inclusive = models.BooleanField(default=False)
    applies_to = models.JSONField(default=list)  # ["site","staff","storage","proration"]
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]


class Subscription(models.Model):
    class Plan(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        GRACE = "grace", "Grace"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.PAID)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    period_start = models.DateField()
    period_end = models.DateField()
    expired_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.workspace} ({self.status})"


class Invoice(models.Model):
    class Status(models.TextChoices):
        DUE = "due", "Due"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    number = models.CharField(max_length=40, unique=True)
    period_start = models.DateField()
    period_end = models.DateField()
    lines = models.JSONField(default=list)  # [{label, detail, amountPaise, type?}]
    subtotal_paise = models.BigIntegerField()
    tax_paise = models.BigIntegerField(default=0)
    total_paise = models.BigIntegerField()
    tax_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DUE)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_at"]
        unique_together = ("workspace", "period_start")


class BillingPayment(models.Model):
    class Method(models.TextChoices):
        ONLINE = "online", "Online"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        UPI = "upi", "UPI"
        CHEQUE = "cheque", "Cheque"
        CARD = "card", "Card"
        CASH = "cash", "Cash"

    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="billing_payments",
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount_paise = models.BigIntegerField()
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_APPROVAL,
    )
    proof_filename = models.CharField(max_length=255, blank=True)
    review_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


class StorageSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="storage_snapshots",
    )
    date = models.DateField()
    bytes = models.BigIntegerField(null=True, blank=True)
    corrected = models.BooleanField(default=False)
    correction_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date"]
        unique_together = ("workspace", "date")


class Wallet(models.Model):
    """Workspace prepaid balance (paise). Razorpay will credit here later."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance_paise = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.workspace} wallet ({self.balance_paise} paise)"


class WalletTransaction(models.Model):
    """Wallet ledger. Paid recharges count as platform income; free do not."""

    class Kind(models.TextChoices):
        RECHARGE = "recharge", "Recharge"
        DEBIT = "debit", "Debit"
        ADJUSTMENT = "adjustment", "Adjustment"

    class Funding(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"

    class Source(models.TextChoices):
        ADMIN = "admin", "Admin"
        RAZORPAY = "razorpay", "Razorpay"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "accounts.Workspace",
        on_delete=models.CASCADE,
        related_name="wallet_transactions",
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    amount_paise = models.BigIntegerField(help_text="Positive credits the wallet; negative debits.")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.RECHARGE)
    funding = models.CharField(max_length=10, choices=Funding.choices)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.ADMIN)
    note = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    balance_after_paise = models.BigIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "funding", "created_at"]),
            models.Index(fields=["funding", "kind", "created_at"]),
        ]

    @property
    def counts_as_income(self) -> bool:
        return self.kind == self.Kind.RECHARGE and self.funding == self.Funding.PAID and self.amount_paise > 0
