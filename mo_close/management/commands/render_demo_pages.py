"""Render the main pages with demo data to static HTML files (for design review), then roll back.

    python manage.py render_demo_pages /tmp/pages

Nothing is kept in the database: all demo data is created inside a transaction that is rolled back.
"""

from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from core.models import User
from mo_close.models import PackingList, TransferRecord
from mo_close.tests.fake_odoo import FakeOdoo

SAMPLE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "packing_list_S04743.pdf"


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Render demo pages to HTML for design review (no data is kept)."

    def add_arguments(self, parser):
        parser.add_argument("out_dir")

    @override_settings(ALLOWED_HOSTS=["*"])
    def handle(self, out_dir, **options):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        try:
            with transaction.atomic():
                self._render(out)
                raise Rollback
        except Rollback:
            pass
        self.stdout.write(self.style.SUCCESS(f"Pages written to {out} (demo data rolled back)."))

    def _render(self, out):
        odoo = FakeOdoo()
        user = User.objects.create(username="demo.user@sawo.com", first_name="Arniel", last_name="Montero",
                                   role=User.Role.CHECKER)
        client = Client()
        client.force_login(user)
        with mock.patch("mo_close.views.client_for", return_value=odoo):
            client.post(reverse("mo_close:record_new"), {
                "so_number": "S04743",
                "pdf": SimpleUploadedFile("Holland SSE13 Odoo Packing list SO # 4743.pdf", SAMPLE.read_bytes()),
            })
            pl = PackingList.objects.get(so_number="S04743")
            pages = {"preview": reverse("mo_close:record_preview", args=[pl.pk])}
            self._save(client, out, pages)

            client.post(pages["preview"], {"action": "save"})
            client.post(reverse("mo_close:record_generate", args=[pl.pk]))
            mo = pl.mos.get(reference="PL3/MO/06873")
            client.post(reverse("mo_close:row_action", args=["mo", mo.pk, "mark"]))
            odoo.set_state("stock.picking", 202, "done")
            tr = TransferRecord.objects.get(reference="PL3/PC/17852")
            client.post(reverse("mo_close:row_action", args=["transfer", tr.pk, "mark"]))
            client.post(reverse("mo_close:row_action", args=["transfer", tr.pk, "confirm"]))

            self._save(client, out, {
                "dashboard": reverse("mo_close:dashboard"),
                "records": reverse("mo_close:records"),
                "new": reverse("mo_close:record_new"),
                "detail": reverse("mo_close:record_detail", args=[pl.pk]),
                "progress": reverse("mo_close:progress"),
            })
            for fmt in ("xlsx", "pdf"):
                resp = client.get(reverse("mo_close:record_export", args=[pl.pk, fmt]))
                (out / f"export.{fmt}").write_bytes(resp.content)
            pl.pdf.delete(save=False)  # files are not part of the rolled-back transaction
        client.logout()
        self._save(client, out, {"login": reverse("login")})

    def _save(self, client, out, pages):
        for name, url in pages.items():
            html = client.get(url).content.decode()
            (out / f"{name}.html").write_text(html, encoding="utf-8")
