"""Roles become editable records with module checkmarks (replaces the fixed user / checker / admin choice)."""

import django.db.models.deletion
from django.db import migrations, models

USER_MODULES = [
    "mo_close.dashboard",
    "mo_close.records",
    "mo_close.create",
    "mo_close.generate",
    "mo_close.mark_done",
    "mo_close.progress",
    "mo_close.export",
]
BUILT_IN = [
    # (old value, name, description, modules, full_access, is_default)
    ("admin", "Admin", "Full access to every module", [], True, False),
    ("checker", "Checker / Supervisor", "Users' modules plus final confirmation", USER_MODULES + ["mo_close.confirm"], False, False),
    ("user", "User", "Create records, generate from Odoo, mark done", USER_MODULES, False, True),
]


def create_roles_and_assign(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    User = apps.get_model("core", "User")
    by_old = {}
    for old, name, description, modules, full_access, is_default in BUILT_IN:
        by_old[old] = Role.objects.create(
            name=name,
            description=description,
            modules=modules,
            full_access=full_access,
            is_system=True,
            is_default=is_default,
        )
    for user in User.objects.all():
        user.role_ref = by_old.get(user.role, by_old["user"])
        user.save(update_fields=["role_ref"])


def back_to_choices(apps, schema_editor):
    User = apps.get_model("core", "User")
    for user in User.objects.select_related("role_ref"):
        role = user.role_ref
        user.role = "admin" if role and role.full_access else ("checker" if role and "mo_close.confirm" in role.modules else "user")
        user.save(update_fields=["role"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=60, unique=True)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("modules", models.JSONField(blank=True, default=list)),
                ("full_access", models.BooleanField(default=False, help_text="Always has every module, including modules added later (Admin).")),
                ("is_system", models.BooleanField(default=False, help_text="Built-in role; cannot be deleted.")),
                ("is_default", models.BooleanField(default=False, help_text="Given to people on their first login.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-full_access", "name"]},
        ),
        migrations.AddField(
            model_name="user",
            name="role_ref",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="core.role"
            ),
        ),
        migrations.RunPython(create_roles_and_assign, back_to_choices),
        migrations.RemoveField(model_name="user", name="role"),
        migrations.RenameField(model_name="user", old_name="role_ref", new_name="role"),
        migrations.AlterField(
            model_name="auditlog",
            name="section",
            field=models.CharField(
                choices=[
                    ("auth", "Login"),
                    ("record", "Records"),
                    ("generate", "Generate / Refresh from Odoo"),
                    ("mark", "Mark done"),
                    ("system_check", "System check"),
                    ("confirmation", "Final confirmation"),
                    ("export", "Export"),
                    ("users", "Users"),
                    ("roles", "Roles & Permissions"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
