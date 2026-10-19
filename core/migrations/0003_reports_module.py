"""Give the new Reports module to the built-in Checker / Supervisor and User roles (Admin has everything)."""

from django.db import migrations

CODE = "mo_close.reports"
ROLES = ["Checker / Supervisor", "User"]


def add(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    for role in Role.objects.filter(name__in=ROLES, is_system=True):
        if CODE not in role.modules:
            role.modules = [*role.modules, CODE]
            role.save(update_fields=["modules"])


def remove(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    for role in Role.objects.filter(name__in=ROLES, is_system=True):
        role.modules = [c for c in role.modules if c != CODE]
        role.save(update_fields=["modules"])


class Migration(migrations.Migration):
    dependencies = [("core", "0002_roles_and_permissions")]
    operations = [migrations.RunPython(add, remove)]
