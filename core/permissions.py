from functools import wraps

from django.core.exceptions import PermissionDenied


def checker_required(view):
    """Checker / Supervisor or Admin."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_checker:
            raise PermissionDenied("Only a Checker / Supervisor can do this.")
        return view(request, *args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied("Only an Admin can do this.")
        return view(request, *args, **kwargs)

    return wrapper
