"""Bulk related rows for query-performance measurement (safe to re-run)."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User, Workspace, default_permissions
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from django.core.files.base import ContentFile

from ledger.models import Attachment, Entry, Item
from ops.models import ActivityLog, AppNotification, Note, Reminder


class Command(BaseCommand):
    help = "Seed ~50–100 related rows per main model on the demo owner workspace for perf tests."

    def handle(self, *args, **options):
        owner = User.objects.filter(email="owner@cubesites.demo").select_related("workspace").first()
        if not owner or not owner.workspace_id:
            self.stderr.write("Run seed_demo first (owner@cubesites.demo missing).")
            return
        ws = owner.workspace
        today = timezone.localdate()

        # Sites
        sites = list(Site.objects.filter(workspace=ws))
        while len(sites) < 60:
            i = len(sites) + 1
            s = Site.objects.create(
                workspace=ws,
                name=f"Perf Site {i:03d}",
                primary_phone=f"98{i:08d}"[-10:],
                address=f"Addr {i}",
                status=Site.Status.ACTIVE if i % 5 else Site.Status.INACTIVE,
                start_date=today - timedelta(days=i),
            )
            SiteStatusEvent.objects.create(site=s, status=s.status, by=owner)
            sites.append(s)

        # Staff + assignments
        staff = list(
            User.objects.filter(workspace=ws).exclude(role=User.Role.OWNER).exclude(is_platform_admin=True)
        )
        while len(staff) < 40:
            i = len(staff) + 1
            u = User.objects.create_user(
                username=f"perf-staff-{i}@cubesites.demo",
                email=f"perf-staff-{i}@cubesites.demo",
                password="demo1234",
                workspace=ws,
                role=User.Role.STAFF if i % 3 else User.Role.SITE_MANAGER,
                permissions=default_permissions("staff" if i % 3 else "site_manager"),
                first_name=f"Perf{i}",
                last_name="Staff",
                email_verified=True,
                is_active=True,
            )
            staff.append(u)
        for idx, u in enumerate(staff):
            # 2–3 sites each
            for s in sites[idx % 50 : (idx % 50) + 3]:
                SiteAssignment.objects.get_or_create(site=s, user=u)

        # Items
        items = list(Item.objects.filter(workspace=ws))
        while len(items) < 50:
            i = len(items) + 1
            name = f"Perf Item {i:03d}"
            items.append(
                Item.objects.create(
                    workspace=ws,
                    type=Item.Type.MATERIALS if i % 2 else Item.Type.LABOUR,
                    name=name,
                    normalized=name.lower(),
                )
            )

        # Entries + attachments
        entries = Entry.objects.filter(workspace=ws).count()
        need = max(0, 120 - entries)
        for i in range(need):
            site = sites[i % len(sites)]
            item = items[i % len(items)]
            e = Entry.objects.create(
                workspace=ws,
                site=site,
                type=Entry.Type.MATERIALS if i % 4 else Entry.Type.PAYMENT,
                item=None if i % 4 == 0 else item,
                description=item.name if i % 4 else f"Perf payment {i}",
                quantity=None if i % 4 == 0 else Decimal("2.000"),
                unit_price_paise=None if i % 4 == 0 else 10000,
                total_paise=50000 if i % 4 == 0 else 20000,
                date=today - timedelta(days=i % 40),
                created_by=owner,
            )
            if i % 3 == 0:
                att = Attachment(
                    workspace=ws,
                    site=site,
                    entry=e,
                    kind=Attachment.Kind.BILL,
                    name=f"bill-{i}.jpg",
                    size_bytes=32,
                    created_by=owner,
                    date=e.date,
                )
                att.file.save(f"perf-bill-{i}.jpg", ContentFile(b"\xff\xd8\xff\xd9"), save=True)

        # Notes / reminders / activity / notifications
        notes = Note.objects.filter(workspace=ws).count()
        for i in range(max(0, 80 - notes)):
            Note.objects.create(
                workspace=ws,
                site=sites[i % len(sites)] if i % 2 else None,
                title=f"Perf note {i}",
                body="body",
                pinned=i % 10 == 0,
                created_by=owner,
            )
        rems = Reminder.objects.filter(workspace=ws).count()
        now = timezone.now()
        for i in range(max(0, 80 - rems)):
            Reminder.objects.create(
                workspace=ws,
                site=sites[i % len(sites)] if i % 3 else None,
                title=f"Perf rem {i}",
                body="",
                due_at=now + timedelta(days=i % 20),
                done=i % 7 == 0,
                created_by=owner,
            )
        acts = ActivityLog.objects.filter(workspace=ws, is_platform=False).count()
        for i in range(max(0, 100 - acts)):
            ActivityLog.objects.create(
                workspace=ws,
                actor=owner,
                action="update",
                target_type="site",
                target_id=str(sites[i % len(sites)].id),
                site=sites[i % len(sites)],
                summary=f"Perf activity {i}",
            )
        notifs = AppNotification.objects.filter(workspace=ws).count()
        for i in range(max(0, 40 - notifs)):
            AppNotification.objects.create(
                workspace=ws,
                user=owner,
                title=f"Perf notif {i}",
                body="hello",
                read=i % 2 == 0,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Perf seed OK on {ws.business_name}: "
                f"sites={Site.objects.filter(workspace=ws).count()} "
                f"staff={User.objects.filter(workspace=ws).exclude(role=User.Role.OWNER).count()} "
                f"entries={Entry.objects.filter(workspace=ws).count()} "
                f"notes={Note.objects.filter(workspace=ws).count()}"
            )
        )
