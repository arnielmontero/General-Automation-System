from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_not_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from . import audit
from .forms import RoleForm
from .models import AuditLog, Role, User
from .modules import BY_CODE, grouped, label
from .odoo import OdooAuthError, OdooClient, OdooError
from .permissions import module_required

Section = AuditLog.Section

# Where to land after login: the first page the user's role allows.
LANDING_PAGES = [
    ("mo_close.dashboard", "mo_close:dashboard"),
    ("mo_close.records", "mo_close:records"),
    ("mo_close.progress", "mo_close:progress"),
    ("mo_close.reports", "mo_close:reports"),
    ("mo_close.create", "mo_close:record_new"),
    ("admin.users", "users"),
    ("admin.roles", "roles"),
    ("admin.logs", "logs"),
]


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
    for code, url_name in LANDING_PAGES:
        if request.user.can(code):
            return redirect(url_name)
    return render(request, "core/no_access.html", status=403)


# --- Users ----------------------------------------------------------------------------------------


@module_required("admin.users")
def users(request):
    q = request.GET.get("q", "").strip()
    people = User.objects.select_related("role")
    if q:
        people = people.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
    return render(request, "core/users.html", {"people": people, "q": q, "roles": Role.objects.all()})


@module_required("admin.users")
@require_POST
def user_update(request, pk):
    person = get_object_or_404(User.objects.select_related("role"), pk=pk)
    if person == request.user:
        messages.error(request, "You cannot change your own role or status.")
        return redirect("users")

    role_id = request.POST.get("role")
    if role_id and str(person.role_id) != role_id:
        role = Role.objects.filter(pk=role_id).first()
        if role is None:
            messages.error(request, "Unknown role.")
            return redirect("users")
        touches_full_access = role.full_access or person.has_full_access
        if touches_full_access and not request.user.has_full_access:
            messages.error(request, f"Only an {Role.ADMIN} can give or remove the {role.name if role.full_access else person.role_name} role.")
            return redirect("users")
        old = person.role_name
        person.role = role
        person.save(update_fields=["role"])
        audit.log(request, Section.USERS, "Role changed", target=person.username, old=old, new=role.name)
        messages.success(request, f"{person.display_name} is now {role.name}.")

    active = request.POST.get("active")
    if active in ("0", "1") and (active == "1") != person.is_active:
        if person.has_full_access and not request.user.has_full_access:
            messages.error(request, f"Only an {Role.ADMIN} can disable an {Role.ADMIN}.")
            return redirect("users")
        person.is_active = active == "1"
        person.save(update_fields=["is_active"])
        action = "User enabled" if person.is_active else "User disabled"
        audit.log(request, Section.USERS, action, target=person.username)
        messages.success(request, f"{action}: {person.display_name}.")
    return redirect("users")


# --- Roles & Permissions ----------------------------------------------------------------------------


@module_required("admin.roles")
def roles(request):
    all_roles = Role.objects.annotate(user_count=Count("users"))
    for role in all_roles:
        role.module_list = [BY_CODE[c] for c in BY_CODE if c in role.module_codes]
    return render(request, "core/roles.html", {"roles": all_roles, "module_total": len(BY_CODE)})


def _modules_text(codes):
    return ", ".join(label(c) for c in codes) or "none"


def _save_default(role):
    """Only one role is the default for new users."""
    if role.is_default:
        Role.objects.exclude(pk=role.pk).filter(is_default=True).update(is_default=False)


@module_required("admin.roles")
def role_edit(request, pk=None):
    role = get_object_or_404(Role, pk=pk) if pk else Role()
    if role.full_access and not request.user.has_full_access:
        messages.error(request, f"Only an {Role.ADMIN} can edit the {role.name} role.")
        return redirect("roles")
    old_name, old_modules, was_default = role.name, sorted(role.module_codes), role.is_default
    form = RoleForm(request.POST or None, instance=role, initial={"modules": role.modules})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            role = form.save(commit=False)
            if role.full_access:
                role.modules = []  # full access never depends on ticks
            if was_default and not role.is_default and not Role.objects.exclude(pk=role.pk).filter(is_default=True).exists():
                role.is_default = True  # there must always be a default role for new users
                messages.info(request, "A default role is required for new users; choose another role as default instead.")
            role.save()
            _save_default(role)
        if pk is None:
            audit.log(request, Section.ROLES, "Role created", target=role.name, new=_modules_text(role.modules))
            messages.success(request, f"Role {role.name} created.")
        else:
            if old_name != role.name:
                audit.log(request, Section.ROLES, "Role renamed", target=role.name, old=old_name, new=role.name)
            if sorted(role.module_codes) != old_modules:
                added = sorted(set(role.module_codes) - set(old_modules))
                removed = sorted(set(old_modules) - set(role.module_codes))
                audit.log(
                    request, Section.ROLES, "Role modules changed", target=role.name,
                    old=("− " + _modules_text(removed)) if removed else "",
                    new=("+ " + _modules_text(added)) if added else "",
                )
            messages.success(request, f"Role {role.name} saved.")
        return redirect("roles")
    return render(
        request,
        "core/role_form.html",
        {"form": form, "role": role, "groups": grouped(), "selected": set(form["modules"].value() or [])},
    )


@module_required("admin.roles")
@require_POST
def role_delete(request, pk):
    role = get_object_or_404(Role.objects.annotate(user_count=Count("users")), pk=pk)
    if role.is_system or role.full_access:
        messages.error(request, f"{role.name} is a built-in role and cannot be deleted.")
    elif role.is_default:
        messages.error(request, f"{role.name} is the default role for new users. Make another role the default first.")
    elif role.user_count:
        messages.error(request, f"{role.name} still has {role.user_count} user(s). Give them another role first.")
    else:
        audit.log(request, Section.ROLES, "Role deleted", target=role.name, old=_modules_text(role.modules))
        role.delete()
        messages.success(request, f"Role {role.name} deleted.")
    return redirect("roles")


# --- Logs ----------------------------------------------------------------------------------------


@module_required("admin.logs")
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
