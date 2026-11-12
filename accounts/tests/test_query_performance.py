"""
Baseline + regression for GET query counts and response shape stability.

Run after each queryset change. Budgets are upper bounds; tighten as we optimize.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, Workspace, default_permissions
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from ledger.models import Entry, Item
from ops.models import ActivityLog, AppNotification, Note, Reminder


def _stable(obj):
    """JSON-serialize with sorted keys for shape comparison (ignore volatile timestamps)."""
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def _strip_volatile(payload):
    """Remove fields that change between identical-ish requests without contract change."""
    if isinstance(payload, list):
        return [_strip_volatile(x) for x in payload]
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if k in {"at", "created_at", "updated_at", "createdAt", "updatedAt", "date_joined"}:
                continue
            out[k] = _strip_volatile(v)
        return out
    return payload


class QueryPerformanceTests(TestCase):
    """Large-ish fixture so N+1 shows up clearly."""

    # Upper-bound query budgets (includes auth session / JWT user load).
    # Values recorded on first green run after optimizations; keep contracts stable.
    BUDGETS = {
        "GET /api/v1/staff/": 8,
        "GET /api/v1/sites/": 6,
        "GET /api/v1/entries/": 8,
        "GET /api/v1/items/": 5,
        "GET /api/v1/notes/": 5,
        "GET /api/v1/reminders/": 5,
        "GET /api/v1/activity/": 5,
        "GET /api/v1/notifications/": 5,
        "GET /api/v1/media/": 5,
        "GET /api/v1/wallet/": 8,  # get_or_create + single recharge aggregate + txs
        "GET /api/v1/billing/current/": 12,
        "GET /api/auth/me/": 6,
        "GET /api/admin/staff/": 5,
        "GET /api/admin/sites/": 5,
        "GET /api/admin/contractors/": 5,
        "GET /api/admin/overview/": 10,
        "GET /api/admin/payments/": 5,
    }

    def setUp(self):
        self.client = APIClient()
        self.ws = Workspace.objects.create(
            business_name="Perf Co",
            owner_name="Owner Perf",
            phone="9000000000",
            email="perf-owner@example.com",
        )
        self.owner = User.objects.create_user(
            username="perf-owner@example.com",
            email="perf-owner@example.com",
            password="pass1234",
            workspace=self.ws,
            role=User.Role.OWNER,
            permissions=default_permissions("owner"),
            first_name="Owner",
            email_verified=True,
        )
        self.admin = User.objects.create_user(
            username="perf-admin@example.com",
            email="perf-admin@example.com",
            password="pass1234",
            is_platform_admin=True,
            is_staff=True,
            first_name="Admin",
            email_verified=True,
        )
        today = timezone.localdate()
        self.sites = []
        for i in range(40):
            s = Site.objects.create(
                workspace=self.ws,
                name=f"Site {i:02d}",
                primary_phone=f"91{i:08d}"[-10:],
                status=Site.Status.ACTIVE,
                start_date=today,
            )
            SiteStatusEvent.objects.create(site=s, status=Site.Status.ACTIVE, by=self.owner)
            self.sites.append(s)
        self.staff = []
        for i in range(30):
            u = User.objects.create_user(
                username=f"perf-s{i}@example.com",
                email=f"perf-s{i}@example.com",
                password="pass1234",
                workspace=self.ws,
                role=User.Role.STAFF,
                permissions=default_permissions("staff"),
                first_name=f"S{i}",
                email_verified=True,
            )
            for s in self.sites[i % 35 : (i % 35) + 3]:
                SiteAssignment.objects.create(site=s, user=u)
            self.staff.append(u)
        self.items = []
        for i in range(25):
            self.items.append(
                Item.objects.create(
                    workspace=self.ws,
                    type=Item.Type.MATERIALS,
                    name=f"Item {i}",
                    normalized=f"item {i}",
                )
            )
        for i in range(80):
            Entry.objects.create(
                workspace=self.ws,
                site=self.sites[i % 40],
                type=Entry.Type.MATERIALS,
                item=self.items[i % 25],
                description=self.items[i % 25].name,
                quantity=Decimal("1"),
                unit_price_paise=1000,
                total_paise=1000,
                date=today,
                created_by=self.owner,
            )
        for i in range(50):
            Note.objects.create(
                workspace=self.ws,
                site=self.sites[i % 40] if i % 2 else None,
                title=f"N{i}",
                body="b",
                created_by=self.owner,
            )
            Reminder.objects.create(
                workspace=self.ws,
                site=self.sites[i % 40] if i % 3 else None,
                title=f"R{i}",
                due_at=timezone.now() + timedelta(days=1),
                created_by=self.owner,
            )
            ActivityLog.objects.create(
                workspace=self.ws,
                actor=self.owner,
                action="update",
                target_type="site",
                target_id=str(self.sites[i % 40].id),
                site=self.sites[i % 40],
                summary=f"A{i}",
            )
            AppNotification.objects.create(
                workspace=self.ws,
                user=self.owner,
                title=f"T{i}",
                body="x",
            )

        # Second workspace so admin lists have multiple tenants
        ws2 = Workspace.objects.create(
            business_name="Other Co",
            owner_name="Other",
            phone="9111111111",
            email="other@example.com",
        )
        for i in range(10):
            Site.objects.create(
                workspace=ws2,
                name=f"O{i}",
                primary_phone="9222222222",
                status=Site.Status.ACTIVE,
                start_date=today,
            )

        self.snapshots = {}

    def _login(self, email):
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": email, "password": "pass1234"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['tokens']['access']}")

    def _get(self, path, label=None):
        label = label or f"GET {path}"
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(path)
        self.assertEqual(res.status_code, 200, f"{label}: {res.content[:300]}")
        data = res.json()
        n = len(ctx)
        budget = self.BUDGETS.get(label)
        # First call stores snapshot; second identical call in same test can compare
        self.snapshots[label] = {
            "queries": n,
            "shape": _strip_volatile(_stable(data)),
            "count": len(data) if isinstance(data, list) else None,
        }
        if budget is not None:
            self.assertLessEqual(
                n,
                budget,
                f"{label} used {n} queries (budget {budget}). SQL:\n"
                + "\n".join(q["sql"][:180] for q in ctx.captured_queries[:40]),
            )
        return n, data

    def test_contractor_list_endpoints_query_budgets_and_stable_shape(self):
        self._login("perf-owner@example.com")
        paths = [
            ("/api/auth/me/", "GET /api/auth/me/"),
            ("/api/v1/staff/", "GET /api/v1/staff/"),
            ("/api/v1/sites/", "GET /api/v1/sites/"),
            ("/api/v1/entries/", "GET /api/v1/entries/"),
            ("/api/v1/items/", "GET /api/v1/items/"),
            ("/api/v1/notes/", "GET /api/v1/notes/"),
            ("/api/v1/reminders/", "GET /api/v1/reminders/"),
            ("/api/v1/activity/", "GET /api/v1/activity/"),
            ("/api/v1/notifications/", "GET /api/v1/notifications/"),
            ("/api/v1/media/", "GET /api/v1/media/"),
            ("/api/v1/wallet/", "GET /api/v1/wallet/"),
            ("/api/v1/billing/current/", "GET /api/v1/billing/current/"),
        ]
        first = {}
        for path, label in paths:
            n, data = self._get(path, label)
            first[label] = deepcopy(self.snapshots[label])
            # Staff must not scale with staff*assignments (classic N+1)
            if label == "GET /api/v1/staff/":
                self.assertLessEqual(n, 8, "staff list still looks like N+1 on site_ids")
            if label == "GET /api/v1/entries/":
                self.assertEqual(len(data), 80)

        # Re-fetch: shape must match (contract lock)
        for path, label in paths:
            _, data = self._get(path, label)
            self.assertEqual(
                self.snapshots[label]["shape"],
                first[label]["shape"],
                f"Response shape drift on {label}",
            )

    def test_admin_list_endpoints_query_budgets(self):
        self._login("perf-admin@example.com")
        for path, label in [
            ("/api/admin/overview/", "GET /api/admin/overview/"),
            ("/api/admin/contractors/", "GET /api/admin/contractors/"),
            ("/api/admin/sites/", "GET /api/admin/sites/"),
            ("/api/admin/staff/", "GET /api/admin/staff/"),
            ("/api/admin/payments/", "GET /api/admin/payments/"),
        ]:
            self._get(path, label)

    def test_staff_site_ids_match_with_and_without_prefetch(self):
        """Contract: site_ids content identical whether prefetch used or not."""
        self._login("perf-owner@example.com")
        from accounts.serializers import UserSerializer

        qs = User.objects.filter(workspace=self.ws).exclude(role=User.Role.OWNER)
        plain = UserSerializer(qs, many=True).data
        eager = UserSerializer(qs.prefetch_related("site_assignments"), many=True).data
        self.assertEqual(
            sorted((u["id"], tuple(sorted(u["site_ids"]))) for u in plain),
            sorted((u["id"], tuple(sorted(u["site_ids"]))) for u in eager),
        )
