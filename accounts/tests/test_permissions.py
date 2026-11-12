from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, Workspace, default_permissions
from accounts.permissions import sanitize_permissions
from jobsites.models import Site, SiteAssignment, SiteStatusEvent
from ledger.models import Attachment, Entry, Item


class SanitizePermissionsTests(TestCase):
    def test_edit_entries_pulls_parents(self):
        p = sanitize_permissions({"editEntries": True})
        self.assertTrue(p["editEntries"])
        self.assertTrue(p["createEntries"])
        self.assertTrue(p["viewSite"])

    def test_reports_requires_financials(self):
        p = sanitize_permissions({"reports": True})
        self.assertTrue(p["reports"])
        self.assertTrue(p["viewFinancials"])
        self.assertTrue(p["viewSite"])

    def test_unknown_keys_dropped(self):
        p = sanitize_permissions({"viewSite": True, "hackAdmin": True})
        self.assertTrue(p["viewSite"])
        self.assertNotIn("hackAdmin", p)


class PermissionEnforcementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ws = Workspace.objects.create(
            business_name="Perm Co",
            owner_name="Owner",
            phone="9000000000",
            email="owner-perm@example.com",
        )
        self.owner = User.objects.create_user(
            username="owner-perm@example.com",
            email="owner-perm@example.com",
            password="pass1234",
            workspace=self.ws,
            role=User.Role.OWNER,
            permissions=default_permissions("owner"),
            first_name="Owner",
            email_verified=True,
        )
        perms = default_permissions("staff")
        perms["viewFinancials"] = False
        perms["editEntries"] = False
        perms["manageItems"] = False
        perms["manageStaffSites"] = False
        perms["reports"] = False
        self.staff = User.objects.create_user(
            username="staff-perm@example.com",
            email="staff-perm@example.com",
            password="pass1234",
            workspace=self.ws,
            role=User.Role.STAFF,
            permissions=perms,
            first_name="Staff",
            email_verified=True,
        )
        today = timezone.localdate()
        self.site = Site.objects.create(
            workspace=self.ws,
            name="Site P1",
            primary_phone="9111111111",
            status=Site.Status.ACTIVE,
            start_date=today,
        )
        SiteStatusEvent.objects.create(site=self.site, status=Site.Status.ACTIVE, by=self.owner)
        SiteAssignment.objects.create(site=self.site, user=self.staff)
        self.item = Item.objects.create(
            workspace=self.ws, type=Item.Type.OTHER, name="Tea", normalized="tea"
        )
        self.entry = Entry.objects.create(
            workspace=self.ws,
            site=self.site,
            type=Entry.Type.OTHER,
            item=self.item,
            description="Tea",
            total_paise=12345,
            date=today,
            created_by=self.owner,
        )

    def _login(self, email):
        res = self.client.post(
            "/api/auth/login/",
            {"identifier": email, "password": "pass1234"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['tokens']['access']}")

    def test_staff_entries_redact_money(self):
        self._login("staff-perm@example.com")
        res = self.client.get("/api/v1/entries/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertIsNone(res.data[0]["total_paise"])
        self.assertIsNone(res.data[0]["unit_price_paise"])

    def test_staff_cannot_read_site_totals(self):
        self._login("staff-perm@example.com")
        res = self.client.get(f"/api/v1/sites/{self.site.id}/totals/")
        self.assertEqual(res.status_code, 403)

    def test_staff_cannot_create_site(self):
        self._login("staff-perm@example.com")
        res = self.client.post(
            "/api/v1/sites/",
            {"name": "Hack", "primary_phone": "9000000001"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_staff_cannot_edit_entry_without_perm(self):
        self._login("staff-perm@example.com")
        res = self.client.patch(
            f"/api/v1/entries/{self.entry.id}/",
            {"total_paise": 1, "date": str(self.entry.date), "site_id": str(self.site.id), "type": "other", "item_id": str(self.item.id)},
            format="json",
        )
        self.assertEqual(res.status_code, 403)

    def test_staff_without_view_site_blocked(self):
        self.staff.permissions = {**self.staff.permissions, "viewSite": False}
        self.staff.save(update_fields=["permissions"])
        self._login("staff-perm@example.com")
        self.assertEqual(self.client.get("/api/v1/sites/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/entries/").status_code, 403)

    def test_owner_sees_money(self):
        self._login("owner-perm@example.com")
        res = self.client.get("/api/v1/entries/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data[0]["total_paise"], 12345)

    def test_staff_create_sanitizes_related_perms(self):
        self._login("owner-perm@example.com")
        res = self.client.post(
            "/api/v1/staff/",
            {
                "name": "New Staff",
                "email": "new-staff@example.com",
                "phone": "9222222222",
                "role": "staff",
                "active": True,
                "site_ids": [str(self.site.id)],
                "permissions": {"editEntries": True},
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        created = User.objects.get(email="new-staff@example.com")
        self.assertTrue(created.permissions["editEntries"])
        self.assertTrue(created.permissions["createEntries"])
        self.assertTrue(created.permissions["viewSite"])

    def test_bills_hidden_without_financials(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        Attachment.objects.create(
            workspace=self.ws,
            site=self.site,
            kind=Attachment.Kind.BILL,
            name="bill.pdf",
            size_bytes=10,
            file=SimpleUploadedFile("bill.pdf", b"pdf"),
            date=timezone.localdate(),
            created_by=self.owner,
        )
        Attachment.objects.create(
            workspace=self.ws,
            site=self.site,
            kind=Attachment.Kind.PHOTO,
            name="photo.jpg",
            size_bytes=10,
            file=SimpleUploadedFile("photo.jpg", b"jpg"),
            date=timezone.localdate(),
            created_by=self.owner,
        )
        self._login("staff-perm@example.com")
        res = self.client.get("/api/v1/media/")
        self.assertEqual(res.status_code, 200)
        kinds = [a["kind"] for a in res.data]
        self.assertIn("photo", kinds)
        self.assertNotIn("bill", kinds)
