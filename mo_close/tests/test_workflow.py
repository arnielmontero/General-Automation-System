"""Steps 1–3 end to end through the web views, with Odoo replaced by FakeOdoo."""

import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog, Role, User
from core.odoo import OdooAuthError
from mo_close.models import MORecord, PackingList, TransferRecord

from .fake_odoo import FakeOdoo

SAMPLE = Path(__file__).parent / "fixtures" / "packing_list_S04743.pdf"


def sample_upload(name="packing.pdf"):
    return SimpleUploadedFile(name, SAMPLE.read_bytes(), content_type="application/pdf")


class LoginTests(TestCase):
    def test_login_page(self):
        self.assertContains(self.client.get(reverse("login")), "Odoo email")

    def test_pages_require_login(self):
        resp = self.client.get(reverse("mo_close:records"))
        self.assertRedirects(resp, reverse("login") + "?next=" + reverse("mo_close:records"))

    @mock.patch("core.backends.OdooClient")
    def test_login_with_odoo_account(self, client_cls):
        odoo = client_cls.return_value
        odoo.authenticate.return_value = {"uid": 42, "username": "Jane@Sawo.com", "name": "Jane Cruz"}
        odoo.session_id = "sid-123"
        with self.settings(ADMIN_ODOO_LOGINS=["admin@sawo.com"]):
            resp = self.client.post(reverse("login"), {"email": "jane@sawo.com", "password": "secret"})
        self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False)
        user = User.objects.get(odoo_uid=42)
        self.assertEqual((user.username, user.first_name, user.last_name, user.role.name), ("jane@sawo.com", "Jane", "Cruz", "User"))
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.session["odoo_session_id"], "sid-123")

    @mock.patch("core.backends.OdooClient")
    def test_admin_login_from_env(self, client_cls):
        client_cls.return_value.authenticate.return_value = {"uid": 7, "username": "boss@sawo.com", "name": "Boss"}
        client_cls.return_value.session_id = "sid-7"
        with self.settings(ADMIN_ODOO_LOGINS=["boss@sawo.com"]):
            self.client.post(reverse("login"), {"email": "boss@sawo.com", "password": "x"})
        self.assertEqual(User.objects.get(odoo_uid=7).role.name, "Admin")

    @mock.patch("core.backends.OdooClient")
    def test_wrong_password(self, client_cls):
        client_cls.return_value.authenticate.side_effect = OdooAuthError("Wrong email or password.")
        resp = self.client.post(reverse("login"), {"email": "jane@sawo.com", "password": "bad"})
        self.assertContains(resp, "Wrong email or password.")
        self.assertTrue(AuditLog.objects.filter(action="Login failed").exists())


class WorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()  # uploaded PDFs never land in the real media volume
        cls.media_override = override_settings(MEDIA_ROOT=cls.media)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.odoo = FakeOdoo()
        patcher = mock.patch("mo_close.views.client_for", return_value=self.odoo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create(username="user@sawo.com", first_name="Ana", role=Role.objects.get(name="User"))
        self.checker = User.objects.create(username="checker@sawo.com", first_name="Ben", role=Role.objects.get(name="Checker / Supervisor"))
        self.client.force_login(self.user)

    # --- helpers ---
    def create_record(self, so="4743"):
        resp = self.client.post(reverse("mo_close:record_new"), {"so_number": so, "pdf": sample_upload()})
        pl = PackingList.objects.get(so_number="S04743")
        self.assertRedirects(resp, reverse("mo_close:record_preview", args=[pl.pk]))
        return pl

    def save_and_generate(self):
        pl = self.create_record()
        self.client.post(reverse("mo_close:record_preview", args=[pl.pk]), {"action": "save"})
        self.client.post(reverse("mo_close:record_generate", args=[pl.pk]))
        pl.refresh_from_db()
        return pl

    def act(self, row, action, **data):
        kind = "mo" if isinstance(row, MORecord) else "transfer"
        return self.client.post(
            reverse("mo_close:row_action", args=[kind, row.pk, action]), data, HTTP_HX_REQUEST="true"
        )

    # --- Step 1 ---
    def test_step1_upload_preview_save(self):
        pl = self.create_record()
        self.assertEqual(pl.status, PackingList.Status.DRAFT)
        self.assertEqual(pl.lines.count(), 23)
        self.assertEqual(pl.container_no, "PACK0000856")
        self.assertEqual(pl.parse_warnings, [])
        resp = self.client.get(reverse("mo_close:record_preview", args=[pl.pk]))
        self.assertContains(resp, "Wellzijn BV")
        groups = pl.grouped_lines()
        self.assertEqual([(g["code"], int(g["qty"])) for g in groups], [
            ("NRNS-60NS-BL-Z-C", 10), ("NRNS-90NS-BL-Z-C", 10), ("NRNF-105NS-BL-Z", 10),
            ("NRNF-120NS-BL-Z", 5), ("NRNF-150NS-BL-Z", 10),
        ])
        self.client.post(reverse("mo_close:record_preview", args=[pl.pk]), {"action": "save"})
        pl.refresh_from_db()
        self.assertEqual(pl.status, PackingList.Status.SAVED)
        self.assertContains(self.client.get(reverse("mo_close:records")), "S04743")

    def test_step1_duplicate_and_mismatch(self):
        self.create_record()
        resp = self.client.post(reverse("mo_close:record_new"), {"so_number": "S04743", "pdf": sample_upload()})
        self.assertContains(resp, "already exists")
        resp = self.client.post(reverse("mo_close:record_new"), {"so_number": "S05000", "pdf": sample_upload()})
        pl = PackingList.objects.get(so_number="S05000")
        self.assertIn("The PDF Invoice No. is S04743, but this record is for S05000.", pl.parse_warnings)
        self.assertIn("Sales Order S05000 was not found in Odoo.", pl.parse_warnings)

    def test_step1_cancel_draft(self):
        pl = self.create_record()
        self.client.post(reverse("mo_close:record_preview", args=[pl.pk]), {"action": "cancel"})
        self.assertFalse(PackingList.objects.exists())

    # --- Step 2 ---
    def test_step2_generate(self):
        pl = self.save_and_generate()
        self.assertEqual(pl.status, PackingList.Status.GENERATED)
        mos = {m.reference: m for m in pl.mos.all()}
        self.assertEqual(set(mos), {"PL3/MO/06873", "PL3/MO/07787"})  # other product / other SO / cancelled excluded
        mo = mos["PL3/MO/06873"]
        self.assertEqual((mo.fg_code, int(mo.qty), int(mo.product_qty), mo.state_label), ("NRNS-60NS-BL-Z-C", 10, 30, "Confirmed"))
        transfers = {t.reference: t.state_label for t in mo.transfers.all()}
        self.assertEqual(transfers, {"PL3/SFP/04631": "Waiting Another Operation", "PL3/PC/17852": "Ready"})  # Done skipped
        self.assertEqual(mos["PL3/MO/07787"].transfers.get().type_code, "PC")

        resp = self.client.get(reverse("mo_close:record_detail", args=[pl.pk]))
        self.assertContains(resp, "PL3/SFP/04631")
        self.assertContains(resp, "NRNF-105NS-BL-Z")  # in "No MO found"

    def test_step2_generate_again_keeps_tracking(self):
        pl = self.save_and_generate()
        mo = pl.mos.get(reference="PL3/MO/06873")
        self.act(mo, "mark")
        self.odoo.set_state("stock.picking", 201, "assigned")
        self.client.post(reverse("mo_close:record_generate", args=[pl.pk]))
        mo.refresh_from_db()
        self.assertTrue(mo.user_done)
        self.assertEqual(TransferRecord.objects.get(reference="PL3/SFP/04631").state, "assigned")
        self.assertEqual(MORecord.objects.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="Odoo state changed", target="PL3/SFP/04631").exists())

    # --- Step 3 ---
    def test_step3_mark_done_not_done_in_odoo_needs_comment(self):
        pl = self.save_and_generate()
        mo = pl.mos.get(reference="PL3/MO/06873")
        resp = self.act(mo, "mark")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Odoo: Confirmed")
        mo.refresh_from_db()
        self.assertTrue(mo.user_done)
        self.assertEqual(mo.user_done_by, self.user)
        self.assertEqual(mo.system_status, "not_done")

        # A plain user cannot confirm.
        resp = self.act(mo, "confirm", comment="ok")
        self.assertContains(resp, "Your role does not allow this.")
        mo.refresh_from_db()
        self.assertFalse(mo.final_confirmed)

        self.client.force_login(self.checker)
        resp = self.act(mo, "confirm")
        self.assertContains(resp, "a comment is required")
        self.act(mo, "confirm", comment="Checked physically in warehouse")
        mo.refresh_from_db()
        self.assertTrue(mo.final_confirmed)
        self.assertEqual(mo.final_confirmed_by, self.checker)
        log = AuditLog.objects.get(action="Final confirmation (override)")
        self.assertEqual(log.comment, "Checked physically in warehouse")

    def test_step3_done_in_odoo_then_record_closes(self):
        pl = self.save_and_generate()
        for model, ids in (("mrp.production", [1, 2]), ("stock.picking", [201, 202, 204])):
            for i in ids:
                self.odoo.set_state(model, i, "done")
        rows = pl.all_rows()
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.act(row, "mark")
        self.client.force_login(self.checker)
        for row in pl.all_rows():
            self.assertEqual(row.system_status, "confirmed")
            self.act(row, "confirm")
        pl.refresh_from_db()
        self.assertEqual(pl.status, PackingList.Status.CLOSED)

        row = pl.mos.first()
        self.act(row, "unconfirm")
        pl.refresh_from_db()
        self.assertEqual(pl.status, PackingList.Status.GENERATED)

    def test_step3_refresh_rechecks_marked_rows(self):
        pl = self.save_and_generate()
        tr = TransferRecord.objects.get(reference="PL3/PC/17852")
        self.act(tr, "mark")
        tr.refresh_from_db()
        self.assertEqual(tr.system_status, "not_done")
        self.odoo.set_state("stock.picking", 202, "done")
        self.client.post(reverse("mo_close:record_refresh", args=[pl.pk]))
        tr.refresh_from_db()
        self.assertEqual(tr.system_status, "confirmed")

    def test_unmark(self):
        pl = self.save_and_generate()
        mo = pl.mos.first()
        self.act(mo, "mark")
        self.act(mo, "unmark")
        mo.refresh_from_db()
        self.assertFalse(mo.user_done)
        self.assertEqual(mo.system_status, "")

    def test_session_expired_redirects_to_login(self):
        pl = self.save_and_generate()
        self.odoo.expired = True
        resp = self.act(pl.mos.first(), "mark")
        self.assertEqual(resp["HX-Redirect"], reverse("login"))

    # --- Reports / pages ---
    def test_exports_and_pages(self):
        pl = self.save_and_generate()
        self.act(pl.mos.first(), "mark")
        for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
            resp = self.client.get(reverse("mo_close:record_export", args=[pl.pk, fmt]))
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.content.startswith(magic))
            resp = self.client.get(reverse("mo_close:progress_export", args=[fmt]))
            self.assertTrue(resp.content.startswith(magic))
        for name in ("mo_close:dashboard", "mo_close:records", "mo_close:progress"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("mo_close:record_pdf", args=[pl.pk])).status_code, 200)

    def test_admin_pages(self):
        self.assertEqual(self.client.get(reverse("users")).status_code, 403)
        admin = User.objects.create(username="admin@sawo.com", role=Role.admin())
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("logs")).status_code, 200)
        checker_role = Role.objects.get(name="Checker / Supervisor")
        self.client.post(reverse("user_update", args=[self.user.pk]), {"role": checker_role.pk, "active": "1"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, checker_role)
