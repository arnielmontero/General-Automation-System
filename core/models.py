from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A person who logs in with their Odoo account. The role is managed inside this system."""

    class Role(models.TextChoices):
        USER = "user", "User"
        CHECKER = "checker", "Checker / Supervisor"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
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
    def is_checker(self):
        return self.role in (self.Role.CHECKER, self.Role.ADMIN)

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN


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
