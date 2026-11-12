"""API integration coverage for auth, contractor CRUD, isolation, and admin gates."""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, Workspace, default_permissions
from jobsites.models import Site, SiteStatusEvent
from ledger.models import Item


class ApiFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ws = Workspace.objects.create(
            business_name="Flow Co",
            owner_name="Owner Flow",
            phone="9111111111",
            email="flow-owner@example.com",
        )
        self.owner = User.objects.create_user(
            username="flow-owner@example.com",
            email="flow-owner@example.com",
            password="pass1234",
            workspace=self.ws,
            role=User.Role.OWNER,
            permissions=default_permissions("owner"),
            first_name="Owner",
            email_verified=True,
        )
        self.staff = User.objects.create_user(
            username="flow-staff@example.com",
            email="flow-staff@example.com",
            password="pass1234",
            workspace=self.ws,
            role=User.Role.STAFF,
            permissions=default_permissions("staff"),
            first_name="Staff",
            email_verified=True,
        )
        self.admin = User.objects.create_user(
            username="flow-admin@example.com",
            email="flow-admin@example.com",
            password="pass1234",
            is_platform_admin=True,
            is_staff=True,
            first_name="Admin",
            email_verified=True,
        )
        today = timezone.localdate()
        self.site = Site.objects.create(
            workspace=self.ws,
            name="Flow Site",
            primary_phone="9222222222",
            status=Site.Status.ACTIVE,
            start_date=today,
        )
        SiteStatusEvent.objects.create(site=self.site, status=Site.Status.ACTIVE, by=self.owner)
        self.item = Item.objects.create(
            workspace=self.ws, type=Item.Type.OTHER, name="Tea", normalized="tea"
        )

    def _login(self, email, password="pass1234"):
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": email, "password": password},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['tokens']['access']}")
        return res.data

    def test_auth_config_public(self):
        res = self.client.get("/api/auth/config/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("googleEnabled", res.data)
        self.assertIn("otpExpiryMinutes", res.data)

    def test_login_validation_and_refresh(self):
        res = self.client.post("/api/auth/login/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        data = self._login("flow-owner@example.com")
        refresh = data["tokens"]["refresh"]
        self.client.credentials()
        rotated = self.client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(rotated.status_code, 200)
        self.assertIn("access", rotated.data)
        self.assertIn("refresh", rotated.data)

    def test_owner_site_item_entry_note_reminder_flow(self):
        self._login("flow-owner@example.com")
        site = self.client.post(
            "/api/v1/sites/",
            {"name": "New Site", "primary_phone": "9333333333"},
            format="json",
        )
        self.assertEqual(site.status_code, 201, site.content)
        item = self.client.post(
            "/api/v1/items/",
            {"type": "materials", "name": "Cement"},
            format="json",
        )
        self.assertEqual(item.status_code, 201, item.content)
        item_id = item.data["item"]["id"]
        entry = self.client.post(
            "/api/v1/entries/",
            {
                "site_id": site.data["id"],
                "type": "materials",
                "item_id": item_id,
                "quantity": "2",
                "unit_price_paise": 10000,
                "total_paise": 20000,
                "date": str(timezone.localdate()),
            },
            format="json",
        )
        self.assertEqual(entry.status_code, 201, entry.content)
        self.assertEqual(entry.data["description"], "Cement")
        note = self.client.post(
            "/api/v1/notes/",
            {"title": "Call client", "body": "Tomorrow"},
            format="json",
        )
        self.assertEqual(note.status_code, 201, note.content)
        rem = self.client.post(
            "/api/v1/reminders/",
            {"title": "Follow up", "due_at": "2026-12-01T10:00:00+05:30"},
            format="json",
        )
        self.assertEqual(rem.status_code, 201, rem.content)
        wallet = self.client.get("/api/v1/wallet/")
        self.assertEqual(wallet.status_code, 200)
        drive = self.client.get("/api/v1/drive/")
        self.assertEqual(drive.status_code, 200)

    def test_site_address_max_length(self):
        self._login("flow-owner@example.com")
        res = self.client.post(
            "/api/v1/sites/",
            {"name": "Long", "primary_phone": "9444444444", "address": "A" * 401},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_site_name_rejects_angle_brackets(self):
        self._login("flow-owner@example.com")
        res = self.client.post(
            "/api/v1/sites/",
            {"name": "<script>x</script>", "primary_phone": "9444444444"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_staff_blocked_from_sites_and_billing(self):
        self._login("flow-staff@example.com")
        res = self.client.post(
            "/api/v1/sites/",
            {"name": "Nope", "primary_phone": "9555555555"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
        bill = self.client.get("/api/v1/billing/current/")
        self.assertEqual(bill.status_code, 403)
        admin_api = self.client.get("/api/admin/overview/")
        self.assertEqual(admin_api.status_code, 403)

    def test_admin_overview_and_contractor_gate(self):
        self._login("flow-admin@example.com")
        overview = self.client.get("/api/admin/overview/")
        self.assertEqual(overview.status_code, 200)
        contractors = self.client.get("/api/admin/contractors/")
        self.assertEqual(contractors.status_code, 200)
        sites = self.client.get("/api/v1/sites/")
        self.assertEqual(sites.status_code, 403)

    def test_password_forgot_no_email_leak(self):
        missing = self.client.post(
            "/api/auth/password/forgot/",
            {"email": "missing@example.com"},
            format="json",
        )
        existing = self.client.post(
            "/api/auth/password/forgot/",
            {"email": "flow-owner@example.com"},
            format="json",
        )
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.data.get("ok"), existing.data.get("ok"))

    def test_unauthenticated_protected_routes(self):
        self.assertEqual(self.client.get("/api/v1/sites/").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/overview/").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
