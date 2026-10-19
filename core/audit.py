from .models import AuditLog

Section = AuditLog.Section


def _ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


def log(request, section, action, *, user=None, system="", record=None, target="", old="", new="", comment=""):
    """Write one audit entry. ``record`` is any object with ``pk`` and ``audit_label``."""
    if user is None and request is not None and request.user.is_authenticated:
        user = request.user
    return AuditLog.objects.create(
        user=user,
        user_label=(user.display_name if user else "")[:150],
        section=section,
        action=action[:200],
        system=system,
        record_id=record.pk if record is not None else None,
        record_label=(getattr(record, "audit_label", "") if record is not None else "")[:50],
        target=str(target)[:100],
        old_value=str(old)[:200],
        new_value=str(new)[:200],
        comment=comment,
        ip_address=_ip(request),
    )
