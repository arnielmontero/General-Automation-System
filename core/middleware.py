from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .odoo import OdooSessionExpired


class OdooSessionMiddleware:
    """When the user's Odoo session has expired, log them out of this system too and send them to login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, OdooSessionExpired):
            return None
        logout(request)
        messages.warning(request, str(exception))
        login_url = reverse("login")
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = login_url
            return response
        return redirect(f"{login_url}?next={request.path}")
