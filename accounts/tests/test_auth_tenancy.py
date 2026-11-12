from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, Workspace, default_permissions
from billing.services import site_charge, staff_charge, storage_charge, tax_on, Pricing
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from ledger.models import Entry


def make_pricing():
    return Pricing(
        site_per_month=10900,
        free_sites=3,
        staff_per_month=2900,
        free_staff=1,
        free_storage_mb=250,
        storage_block_mb=250,
        storage_block_price=500,
        days_per_month=30,
    )


class BillingMathTests(TestCase):
    def test_site_and_staff_free_allowances(self):
        p = make_pricing()
        self.assertEqual(site_charge(3, p)["amount"], 0)
        self.assertEqual(site_charge(5, p)["amount"], 2 * 10900)
        self.assertEqual(staff_charge(1, p)["amount"], 0)
        self.assertEqual(staff_charge(3, p)["amount"], 2 * 2900)

    def test_storage_blocks(self):
        p = make_pricing()
        self.assertEqual(storage_charge(250, p)["blocks"], 0)
        self.assertEqual(storage_charge(251, p)["blocks"], 1)
        self.assertEqual(storage_charge(751, p)["blocks"], 3)

    def test_tax_rounding(self):
        self.assertEqual(tax_on(10000, 18), 1800)


class AuthTenancyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ws_a = Workspace.objects.create(
            business_name="A Builders",
            owner_name="Owner A",
            phone="9876543210",
            email="a@example.com",
        )
        self.ws_b = Workspace.objects.create(
            business_name="B Builders",
            owner_name="Owner B",
            phone="9876543211",
            email="b@example.com",
        )
        self.owner_a = User.objects.create_user(
            username="a@example.com",
            email="a@example.com",
            password="pass1234",
            workspace=self.ws_a,
            role=User.Role.OWNER,
            permissions=default_permissions("owner"),
            first_name="Owner",
            last_name="A",
            email_verified=True,
        )
        self.owner_b = User.objects.create_user(
            username="b@example.com",
            email="b@example.com",
            password="pass1234",
            workspace=self.ws_b,
            role=User.Role.OWNER,
            permissions=default_permissions("owner"),
            first_name="Owner",
            last_name="B",
            email_verified=True,
        )
        self.staff_a = User.objects.create_user(
            username="staff-a@example.com",
            email="staff-a@example.com",
            password="pass1234",
            workspace=self.ws_a,
            role=User.Role.STAFF,
            permissions=default_permissions("staff"),
            first_name="Staff",
            last_name="A",
            email_verified=True,
        )
        today = timezone.localdate()
        self.site_a = Site.objects.create(
            workspace=self.ws_a,
            name="Site A1",
            primary_phone="9999999999",
            status=Site.Status.ACTIVE,
            start_date=today,
        )
        SiteStatusEvent.objects.create(site=self.site_a, status=Site.Status.ACTIVE, by=self.owner_a)
        self.site_b = Site.objects.create(
            workspace=self.ws_b,
            name="Site B1",
            primary_phone="8888888888",
            status=Site.Status.ACTIVE,
            start_date=today,
        )
        SiteAssignment.objects.create(site=self.site_a, user=self.staff_a)
        Entry.objects.create(
            workspace=self.ws_a,
            site=self.site_a,
            type=Entry.Type.OTHER,
            description="Tea",
            total_paise=10000,
            date=today,
            created_by=self.owner_a,
        )
        Entry.objects.create(
            workspace=self.ws_b,
            site=self.site_b,
            type=Entry.Type.OTHER,
            description="Secret",
            total_paise=99900,
            date=today,
            created_by=self.owner_b,
        )

    def _login(self, email):
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": email, "password": "pass1234"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        token = res.data["tokens"]["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return res.data

    def test_login_and_me(self):
        data = self._login("a@example.com")
        self.assertEqual(data["user"]["role"], "owner")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["workspace"]["business_name"], "A Builders")

    def test_unverified_owner_cannot_login(self):
        self.owner_a.email_verified = False
        self.owner_a.save(update_fields=["email_verified"])
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": "a@example.com", "password": "pass1234"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data.get("code"), "email_unverified")

    def test_tenant_isolation_sites(self):
        self._login("a@example.com")
        res = self.client.get("/api/v1/sites/")
        names = [s["name"] for s in res.data]
        self.assertIn("Site A1", names)
        self.assertNotIn("Site B1", names)

    def test_tenant_isolation_entries(self):
        self._login("a@example.com")
        res = self.client.get("/api/v1/entries/")
        descs = [e["description"] for e in res.data]
        self.assertIn("Tea", descs)
        self.assertNotIn("Secret", descs)

    def test_staff_cannot_view_financials_nav_data_still_scoped(self):
        self._login("staff-a@example.com")
        res = self.client.get("/api/v1/sites/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)

    def test_staff_cannot_manage_sites(self):
        self._login("staff-a@example.com")
        res = self.client.post(
            "/api/v1/sites/",
            {"name": "Hack", "primary_phone": "9000000000"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_platform_admin_only_admin_api(self):
        admin = User.objects.create_user(
            username="admin@test.com",
            email="admin@test.com",
            password="pass1234",
            is_platform_admin=True,
            is_staff=True,
            first_name="Admin",
            email_verified=True,
        )
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": "admin@test.com", "password": "pass1234"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['tokens']['access']}")
        overview = self.client.get("/api/admin/overview/")
        self.assertEqual(overview.status_code, 200)
        sites = self.client.get("/api/v1/sites/")
        self.assertEqual(sites.status_code, 403)
