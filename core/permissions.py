from functools import wraps

from django.core.exceptions import PermissionDenied

from .modules import label


def module_required(code):
    """Allow the view only for users whose role has this module ticked."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.can(code):
                raise PermissionDenied(f"Your role does not include “{label(code)}”.")
            return view(request, *args, **kwargs)

        wrapper.module_code = code
        return wrapper

    return decorator
