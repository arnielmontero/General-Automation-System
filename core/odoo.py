"""Minimal read-only Odoo JSON-RPC client.

Uses the same endpoints as the Odoo web UI. Each user works with their own Odoo session
(obtained at login), so the system sees exactly what that user can see in Odoo.
"""

import itertools
import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)
_ids = itertools.count(1)


class OdooError(Exception):
    """Any problem talking to Odoo. The message is safe to show to users."""


class OdooConnectionError(OdooError):
    pass


class OdooAuthError(OdooError):
    pass


class OdooSessionExpired(OdooError):
    pass


class OdooAccessError(OdooError):
    pass


# Odoo selection values → labels shown in the Odoo UI.
MO_STATES = {
    "draft": "Draft",
    "confirmed": "Confirmed",
    "progress": "In Progress",
    "to_close": "To Close",
    "done": "Done",
    "cancel": "Cancelled",
}
PICKING_STATES = {
    "draft": "Draft",
    "waiting": "Waiting Another Operation",
    "confirmed": "Waiting",
    "assigned": "Ready",
    "done": "Done",
    "cancel": "Cancelled",
}


class OdooClient:
    def __init__(self, session_id=None, base_url=None, db=None, timeout=None):
        self.base_url = (base_url or settings.ODOO_URL).rstrip("/")
        self.db = db or settings.ODOO_DB
        self.timeout = timeout or settings.ODOO_TIMEOUT
        self.session_id = session_id

    # --- transport -------------------------------------------------------------------------
    def _post(self, path, params):
        payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": next(_ids)}
        cookies = {"session_id": self.session_id} if self.session_id else None
        try:
            resp = requests.post(self.base_url + path, json=payload, cookies=cookies, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("Odoo request %s failed: %s", path, exc)
            raise OdooConnectionError("Cannot reach Odoo. Please try again in a moment.") from exc
        except ValueError as exc:
            raise OdooConnectionError("Odoo returned an unexpected response.") from exc

        if data.get("error"):
            self._raise(data["error"])
        new_sid = resp.cookies.get("session_id")
        if new_sid:
            self.session_id = new_sid
        return data.get("result")

    @staticmethod
    def _raise(error):
        data = error.get("data") or {}
        name = data.get("name") or ""
        message = data.get("message") or error.get("message") or "Odoo error"
        if "SessionExpired" in name or error.get("code") == 100:
            raise OdooSessionExpired("Your Odoo session has expired. Please log in again.")
        if "AccessDenied" in name:
            raise OdooAuthError("Wrong email or password.")
        if "AccessError" in name:
            raise OdooAccessError(f"Odoo denied access: {message}")
        raise OdooError(f"Odoo error: {message}")

    # --- session ---------------------------------------------------------------------------
    def authenticate(self, login, password):
        """Log in with an Odoo email + password. Returns Odoo's session info (uid, name, username…)."""
        result = self._post(
            "/web/session/authenticate",
            {"db": self.db, "login": login, "password": password},
        )
        if not result or not result.get("uid"):
            # Odoo returns uid=None when the account needs two-step verification.
            raise OdooAuthError(
                "This Odoo account uses two-step verification, which this system does not support. "
                "Please ask your Odoo administrator."
            )
        return result

    def logout(self):
        if not self.session_id:
            return
        try:
            self._post("/web/session/destroy", {})
        except OdooError:
            pass

    # --- ORM -------------------------------------------------------------------------------
    def call_kw(self, model, method, args=None, kwargs=None):
        return self._post(
            f"/web/dataset/call_kw/{model}/{method}",
            {"model": model, "method": method, "args": args or [], "kwargs": kwargs or {}},
        )

    def search_read(self, model, domain, fields, order=None, limit=None):
        kwargs = {"fields": fields}
        if order:
            kwargs["order"] = order
        if limit:
            kwargs["limit"] = limit
        return self.call_kw(model, "search_read", [domain], kwargs)

    def read(self, model, ids, fields):
        if not ids:
            return []
        return self.call_kw(model, "read", [list(ids), fields])

    def search_count(self, model, domain):
        return self.call_kw(model, "search_count", [domain])


def client_for(request):
    """Odoo client using the logged-in user's Odoo session."""
    return OdooClient(session_id=request.session.get("odoo_session_id"))
