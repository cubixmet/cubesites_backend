"""Seed demo workspace, users, sites, pricing — aligned with frontend demos."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User, Workspace, default_permissions
from billing.models import PricingVersion, StorageSnapshot, Subscription, TaxRule
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from ledger.models import Entry, Item
from ops.models import AppNotification, BackupJob, PlatformSettings, SupportCase


class Command(BaseCommand):
    help = "Seed CubeSites demo data (idempotent by email)."

    def handle(self, *args, **options):
        PricingVersion.objects.get_or_create(
            label="Launch pricing",
            effective_from="2026-01-01",
            defaults={
                "site_per_month": 10900,
                "free_sites": 3,
                "staff_per_month": 2900,
                "free_staff": 1,
                "free_storage_mb": 250,
                "storage_block_mb": 250,
                "storage_block_price": 500,
                "days_per_month": 30,
            },
        )
        TaxRule.objects.get_or_create(
            label="GST",
            effective_from="2026-01-01",
            defaults={
                "rate_pct": Decimal("18"),
                "inclusive": False,
                "applies_to": ["site", "staff", "storage", "proration"],
            },
        )
        PlatformSettings.objects.get_or_create(
            pk=1, defaults={"reminder_days": [60, 30, 14, 7]}
        )

        admin, created = User.objects.get_or_create(
            email="admin@cubesites.in",
            defaults={
                "username": "admin@cubesites.in",
                "first_name": "Platform",
                "last_name": "Admin",
                "is_platform_admin": True,
                "is_staff": True,
                "role": User.Role.OWNER,
                "permissions": default_permissions("owner"),
                "email_verified": True,
            },
        )
        if created:
            admin.set_password("Admin@123")
            admin.save()
            self.stdout.write(self.style.SUCCESS("Created platform admin admin@cubesites.in / Admin@123"))

        ws, _ = Workspace.objects.get_or_create(
            email="owner@cubesites.demo",
            defaults={
                "business_name": "Sreeja Builders & Contractors",
                "owner_name": "Sreeja Kumar",
                "phone": "+91 98765 43210",
                "district": "Thiruvananthapuram",
                "gstin": "32ABCDE1234F1Z5",
                "status": Workspace.Status.ACTIVE,
            },
        )

        owner, created = User.objects.get_or_create(
            email="owner@cubesites.demo",
            defaults={
                "username": "owner@cubesites.demo",
                "workspace": ws,
                "first_name": "Sreeja",
                "last_name": "Kumar",
                "phone": "+91 98765 43210",
                "role": User.Role.OWNER,
                "permissions": default_permissions("owner"),
                "email_verified": True,
            },
        )
        if created:
            owner.set_password("demo1234")
            owner.save()

        manager, created = User.objects.get_or_create(
            email="manager@cubesites.demo",
            defaults={
                "username": "manager@cubesites.demo",
                "workspace": ws,
                "first_name": "Anil",
                "last_name": "Manager",
                "phone": "+91 98111 22222",
                "role": User.Role.SITE_MANAGER,
                "permissions": default_permissions("site_manager"),
                "email_verified": True,
            },
        )
        if created:
            manager.set_password("demo1234")
            manager.save()

        staff, created = User.objects.get_or_create(
            email="staff@cubesites.demo",
            defaults={
                "username": "staff@cubesites.demo",
                "workspace": ws,
                "first_name": "Ravi",
                "last_name": "Staff",
                "phone": "+91 98222 33333",
                "role": User.Role.STAFF,
                "permissions": default_permissions("staff"),
                "email_verified": True,
            },
        )
        if created:
            staff.set_password("demo1234")
            staff.save()

        today = timezone.localdate()
        period_start = today.replace(day=1)
        Subscription.objects.get_or_create(
            workspace=ws,
            defaults={
                "plan": Subscription.Plan.PAID,
                "status": Subscription.Status.ACTIVE,
                "period_start": period_start,
                "period_end": period_start + timedelta(days=29),
            },
        )

        sites_spec = [
            ("Kakkanad Commercial Complex", "active", "+91 9531 921 973"),
            ("Palarivattom Residence", "active", "+91 9544 100 200"),
            ("Thrissur East Villa", "active", "+91 9555 300 400"),
            ("Tripunithura School Annex", "active", "+91 9566 500 600"),
            ("Kazhakkoottam Villa", "completed", "+91 9577 700 800"),
            ("Old Warehouse Shed", "inactive", "+91 9588 900 100"),
        ]
        sites = []
        for name, status, phone in sites_spec:
            site, created = Site.objects.get_or_create(
                workspace=ws,
                name=name,
                defaults={
                    "primary_phone": phone,
                    "address": "Thiruvananthapuram, Kerala",
                    "status": status,
                    "start_date": today - timedelta(days=90),
                },
            )
            if created:
                SiteStatusEvent.objects.create(site=site, status=status, by=owner)
            sites.append(site)

        for s in sites[:3]:
            SiteAssignment.objects.get_or_create(site=s, user=manager)
        SiteAssignment.objects.get_or_create(site=sites[0], user=staff)

        for typ, name in [
            ("materials", "TMT Steel 12mm (kg)"),
            ("labour", "Mason wages (day)"),
            ("equipment", "Tipper Lorry Trip"),
            ("other", "Site Tea & Snacks"),
        ]:
            Item.objects.get_or_create(
                workspace=ws,
                type=typ,
                normalized=name.lower(),
                defaults={"name": name},
            )

        item = Item.objects.filter(workspace=ws, type="materials").first()
        if item and not Entry.objects.filter(workspace=ws).exists():
            Entry.objects.create(
                workspace=ws,
                site=sites[0],
                type=Entry.Type.MATERIALS,
                item=item,
                description=item.name,
                quantity=10,
                unit_price_paise=6400,
                total_paise=64000,
                date=today - timedelta(days=1),
                created_by=owner,
            )
            Entry.objects.create(
                workspace=ws,
                site=sites[0],
                type=Entry.Type.PAYMENT,
                description="Part payment via NEFT",
                total_paise=5000000,
                date=today - timedelta(days=2),
                created_by=owner,
            )

        for i in range(30):
            d = today - timedelta(days=i)
            StorageSnapshot.objects.get_or_create(
                workspace=ws,
                date=d,
                defaults={"bytes": int((280 + i * 2) * 1024 * 1024)},
            )

        if not AppNotification.objects.filter(workspace=ws).exists():
            AppNotification.objects.create(
                workspace=ws,
                title="Welcome to CuboSites",
                body="Demo workspace is ready. Password for demo users: demo1234",
            )

        if not BackupJob.objects.filter(workspace=ws).exists():
            BackupJob.objects.create(
                workspace=ws,
                status=BackupJob.Status.SUCCESS,
                job_type="scheduled",
                note="Seeded successful backup",
                finished_at=timezone.now(),
            )

        if not SupportCase.objects.filter(workspace=ws).exists():
            SupportCase.objects.create(
                workspace=ws,
                subject="Question about storage billing",
                priority=SupportCase.Priority.MEDIUM,
            )

        self.stdout.write(self.style.SUCCESS("Demo seed complete."))
        self.stdout.write("  Platform: admin@cubesites.in / Admin@123")
        self.stdout.write("  Owner:    owner@cubesites.demo / demo1234")
        self.stdout.write("  Manager:  manager@cubesites.demo / demo1234")
        self.stdout.write("  Staff:    staff@cubesites.demo / demo1234")
