from functools import cached_property

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from .modules import ALL_CODES


class Role(models.Model):
    """A named set of modules. Admins create roles and tick their modules; each user has one role."""

    ADMIN = "Admin"

    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=200, blank=True)
    modules = models.JSONField(default=list, blank=True)
    full_access = models.BooleanField(
        default=False, help_text="Always has every module, including modules added later (Admin)."
    )
    is_system = models.BooleanField(default=False, help_text="Built-in role; cannot be deleted.")
    is_default = models.BooleanField(default=False, help_text="Given to people on their first login.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-full_access", "name"]

    def __str__(self):
        return self.name

    @property
    def module_codes(self):
        return set(ALL_CODES) if self.full_access else {c for c in self.modules if c in ALL_CODES}

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first()

    @classmethod
    def admin(cls):
        return cls.objects.filter(full_access=True).order_by("id").first()


class User(AbstractUser):
    """A person who logs in with their Odoo account. The role is managed inside this system."""

    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users")
    odoo_uid = models.PositiveIntegerField(null=True, blank=True, unique=True)
    last_odoo_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["first_name", "username"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def role_name(self):
        return self.role.name if self.role else "No role"

    @cached_property
    def modules(self):
        """Module codes this user may use (from their role)."""
        if not self.is_active or self.role is None:
            return frozenset()
        return frozenset(self.role.module_codes)

    def can(self, code):
        return code in self.modules

    @property
    def has_full_access(self):
        return bool(self.role and self.role.full_access)


class AuditLog(models.Model):
    """Everything that happens in the system, by whom and when."""

    class Section(models.TextChoices):
        AUTH = "auth", "Login"
        RECORD = "record", "Records"
        GENERATE = "generate", "Generate / Refresh from Odoo"
        MARK = "mark", "Mark done"
        SYSTEM_CHECK = "system_check", "System check"
        CONFIRMATION = "confirmation", "Final confirmation"
        EXPORT = "export", "Export"
        USERS = "users", "Users"
        ROLES = "roles", "Roles & Permissions"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    user_label = models.CharField(max_length=150, blank=True)
    section = models.CharField(max_length=20, choices=Section.choices, db_index=True)
    action = models.CharField(max_length=200)
    system = models.CharField(max_length=30, blank=True, db_index=True)
    record_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    record_label = models.CharField(max_length=50, blank=True)
    target = models.CharField(max_length=100, blank=True)
    old_value = models.CharField(max_length=200, blank=True)
    new_value = models.CharField(max_length=200, blank=True)
    comment = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_label} {self.action}"
