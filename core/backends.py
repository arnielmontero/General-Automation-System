from django.conf import settings
from django.utils import timezone

from .models import Role, User
from .odoo import OdooClient


class OdooBackend:
    """Authenticates against Odoo with the user's own email + password.

    The password is only passed through to Odoo and never stored. On success the Odoo session id
    is attached to the user object (``user.odoo_session_id``) so the login view can keep it in the
    server-side session. Raises ``OdooError`` subclasses so the login page can show the reason.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        client = OdooClient()
        info = client.authenticate(username.strip(), password)

        login = (info.get("username") or username).strip().lower()
        user = User.objects.filter(odoo_uid=info["uid"]).first() or User.objects.filter(username=login).first()
        if user is None:
            user = User(username=login, odoo_uid=info["uid"], role=Role.default())
            user.set_unusable_password()

        user.username = login
        user.odoo_uid = info["uid"]
        if "@" in login:
            user.email = login
        name = (info.get("name") or "").strip()
        if name:
            first, _, last = name.partition(" ")
            user.first_name, user.last_name = first[:150], last[:150]
        if login in settings.ADMIN_ODOO_LOGINS:
            user.role = Role.admin() or user.role
        user.last_odoo_login = timezone.now()
        user.save()

        user.odoo_session_id = client.session_id
        return user if user.is_active else None

    def get_user(self, user_id):
        user = User.objects.select_related("role").filter(pk=user_id).first()
        return user if user and user.is_active else None
