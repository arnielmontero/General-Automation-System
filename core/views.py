from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from . import audit
from .models import AuditLog, User
from .odoo import OdooAuthError, OdooClient, OdooError
from .permissions import admin_required

Section = AuditLog.Section


@login_not_required
def health(request):
    return HttpResponse("ok", content_type="text/plain")


@login_not_required
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    email = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        if not email or not password:
            messages.error(request, "Enter your Odoo email and password.")
        else:
            try:
                user = authenticate(request, username=email, password=password)
            except OdooAuthError as exc:
                audit.log(request, Section.AUTH, "Login failed", target=email, comment=str(exc))
                messages.error(request, str(exc))
                user = None
            except OdooError as exc:
                messages.error(request, str(exc))
                user = None
            else:
                if user is None:
                    messages.error(request, "Your account is disabled in this system. Please contact an Admin.")
            if user is not None:
                login(request, user)
                request.session["odoo_session_id"] = user.odoo_session_id
                audit.log(request, Section.AUTH, "Logged in")
                if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}):
                    next_url = ""
                return redirect(next_url or "home")
    return render(request, "core/login.html", {"email": email, "next": next_url})


@require_POST
def logout_view(request):
    OdooClient(session_id=request.session.get("odoo_session_id")).logout()
    audit.log(request, Section.AUTH, "Logged out")
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("login")


def home(request):
    return redirect("mo_close:dashboard")


@admin_required
def users(request):
    q = request.GET.get("q", "").strip()
    people = User.objects.all()
    if q:
        people = people.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
    return render(request, "core/users.html", {"people": people, "q": q, "roles": User.Role.choices})


@admin_required
@require_POST
def user_update(request, pk):
    person = get_object_or_404(User, pk=pk)
    if person == request.user:
        messages.error(request, "You cannot change your own role or status.")
        return redirect("users")

    role = request.POST.get("role")
    if role and role in User.Role.values and role != person.role:
        old = person.get_role_display()
        person.role = role
        person.save(update_fields=["role"])
        audit.log(request, Section.USERS, "Role changed", target=person.username, old=old, new=person.get_role_display())
        messages.success(request, f"{person.display_name} is now {person.get_role_display()}.")

    active = request.POST.get("active")
    if active in ("0", "1") and (active == "1") != person.is_active:
        person.is_active = active == "1"
        person.save(update_fields=["is_active"])
        action = "User enabled" if person.is_active else "User disabled"
        audit.log(request, Section.USERS, action, target=person.username)
        messages.success(request, f"{action}: {person.display_name}.")
    return redirect("users")


@admin_required
def logs(request):
    entries = AuditLog.objects.select_related("user")
    section = request.GET.get("section", "")
    q = request.GET.get("q", "").strip()
    if section in Section.values:
        entries = entries.filter(section=section)
    if q:
        entries = entries.filter(
            Q(user_label__icontains=q)
            | Q(action__icontains=q)
            | Q(record_label__icontains=q)
            | Q(target__icontains=q)
            | Q(comment__icontains=q)
        )
    page = Paginator(entries, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "core/logs.html",
        {
            "page": page,
            "sections": Section.choices,
            "section": section,
            "q": q,
            "query": urlencode({"section": section, "q": q}),
        },
    )
