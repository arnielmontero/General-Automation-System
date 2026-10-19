"""Roles & Permissions: roles with ticked modules, users get a role from a dropdown."""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, Role, User
from core.modules import ALL_CODES


class RolesAndPermissionsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create(username="admin@sawo.com", first_name="Ada", role=Role.admin())
        self.client.force_login(self.admin)

    def make_user(self, role, username="person@sawo.com"):
        return User.objects.create(username=username, first_name="Pat", role=role)

    def test_built_in_roles(self):
        self.assertEqual(
            {r.name: (r.full_access, r.is_default) for r in Role.objects.all()},
            {"Admin": (True, False), "Checker / Supervisor": (False, False), "User": (False, True)},
        )
        self.assertEqual(Role.admin().module_codes, set(ALL_CODES))
        user_role = Role.objects.get(name="User")
        self.assertNotIn("mo_close.confirm", user_role.module_codes)
        self.assertNotIn("admin.users", user_role.module_codes)
        self.assertIn("mo_close.confirm", Role.objects.get(name="Checker / Supervisor").module_codes)

    def test_create_role_with_checkmarks(self):
        resp = self.client.post(reverse("role_new"), {
            "name": "Warehouse", "description": "Ticks transfers",
            "modules": ["mo_close.records", "mo_close.mark_done", "not.a.module"],
        })
        self.assertEqual(resp.status_code, 200)  # unknown module rejected
        resp = self.client.post(reverse("role_new"), {
            "name": "Warehouse", "description": "Ticks transfers", "modules": ["mo_close.mark_done", "mo_close.records"],
        })
        self.assertRedirects(resp, reverse("roles"))
        role = Role.objects.get(name="Warehouse")
        self.assertEqual(role.modules, ["mo_close.records", "mo_close.mark_done"])
        self.assertTrue(AuditLog.objects.filter(section="roles", action="Role created", target="Warehouse").exists())
        self.assertContains(self.client.get(reverse("roles")), "Warehouse")

        resp = self.client.post(reverse("role_new"), {"name": "warehouse", "modules": []})
        self.assertContains(resp, "already exists")

    def test_edit_role_logs_changes(self):
        role = Role.objects.create(name="Viewer", modules=["mo_close.records"])
        self.client.post(reverse("role_edit", args=[role.pk]), {"name": "Viewer", "modules": ["mo_close.records", "mo_close.progress"]})
        role.refresh_from_db()
        self.assertEqual(role.modules, ["mo_close.records", "mo_close.progress"])
        log = AuditLog.objects.get(action="Role modules changed")
        self.assertEqual(log.new_value, "+ Progress")

    def test_limited_role_access(self):
        role = Role.objects.create(name="Viewer", modules=["mo_close.records", "mo_close.mark_done"])
        self.client.force_login(self.make_user(role))
        self.assertRedirects(self.client.get(reverse("home")), reverse("mo_close:records"))
        self.assertEqual(self.client.get(reverse("mo_close:records")).status_code, 200)
        for name in ("mo_close:dashboard", "mo_close:record_new", "mo_close:progress", "users", "roles", "logs"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        page = self.client.get(reverse("mo_close:records")).content.decode()
        self.assertNotIn(reverse("mo_close:record_new"), page)  # no New Record menu / button
        self.assertNotIn(reverse("roles"), page)

    def test_role_without_modules(self):
        self.client.force_login(self.make_user(Role.objects.create(name="Nothing")))
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Your role has no modules yet", status_code=403)

    def test_assign_role_from_dropdown(self):
        person = self.make_user(Role.default())
        checker = Role.objects.get(name="Checker / Supervisor")
        self.client.post(reverse("user_update", args=[person.pk]), {"role": checker.pk, "active": "1"})
        person.refresh_from_db()
        self.assertEqual(person.role, checker)
        log = AuditLog.objects.get(action="Role changed")
        self.assertEqual((log.old_value, log.new_value), ("User", "Checker / Supervisor"))
        self.assertContains(self.client.get(reverse("users")), f'<option value="{checker.pk}" selected>')

    def test_only_full_access_can_give_admin(self):
        manager = Role.objects.create(name="Manager", modules=["admin.users", "admin.roles"])
        self.client.force_login(self.make_user(manager, "manager@sawo.com"))
        person = self.make_user(Role.default())
        self.client.post(reverse("user_update", args=[person.pk]), {"role": Role.admin().pk, "active": "1"})
        person.refresh_from_db()
        self.assertEqual(person.role, Role.default())
        self.client.post(reverse("user_update", args=[self.admin.pk]), {"role": Role.default().pk, "active": "0"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.has_full_access and self.admin.is_active)
        self.assertRedirects(self.client.get(reverse("role_edit", args=[Role.admin().pk])), reverse("roles"))

    def test_cannot_change_own_role(self):
        self.client.post(reverse("user_update", args=[self.admin.pk]), {"role": Role.default().pk})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.has_full_access)

    def test_delete_rules(self):
        built_in = Role.objects.get(name="Checker / Supervisor")
        self.client.post(reverse("role_delete", args=[built_in.pk]))
        self.assertTrue(Role.objects.filter(pk=built_in.pk).exists())

        used = Role.objects.create(name="Used", modules=["mo_close.records"])
        self.make_user(used)
        self.client.post(reverse("role_delete", args=[used.pk]))
        self.assertTrue(Role.objects.filter(pk=used.pk).exists())

        unused = Role.objects.create(name="Unused")
        self.client.post(reverse("role_delete", args=[unused.pk]))
        self.assertFalse(Role.objects.filter(pk=unused.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action="Role deleted", target="Unused").exists())

    def test_single_default_role(self):
        self.client.post(reverse("role_new"), {"name": "Starter", "is_default": "on", "modules": ["mo_close.records"]})
        self.assertEqual(list(Role.objects.filter(is_default=True).values_list("name", flat=True)), ["Starter"])

    @mock.patch("core.backends.OdooClient")
    def test_first_login_gets_default_role(self, client_cls):
        self.client.logout()
        starter = Role.objects.create(name="Starter", modules=["mo_close.records"])
        Role.objects.update(is_default=False)
        Role.objects.filter(pk=starter.pk).update(is_default=True)
        client_cls.return_value.authenticate.return_value = {"uid": 99, "username": "new@sawo.com", "name": "New Person"}
        client_cls.return_value.session_id = "sid"
        with self.settings(ADMIN_ODOO_LOGINS=[]):
            self.client.post(reverse("login"), {"email": "new@sawo.com", "password": "x"})
        self.assertEqual(User.objects.get(odoo_uid=99).role, starter)
