from decimal import Decimal

from django import template
from django.utils.html import format_html

register = template.Library()

MO_TONES = {"confirmed": "blue", "progress": "orange", "to_close": "purple", "done": "green"}
PICKING_TONES = {"waiting": "orange", "confirmed": "yellow", "assigned": "blue", "done": "green"}
RECORD_TONES = {"draft": "gray", "saved": "blue", "generated": "orange", "closed": "green"}


def _pill(label, tone, icon=""):
    if icon:
        return format_html('<span class="pill tone-{}"><i class="bi bi-{}"></i> {}</span>', tone, icon, label)
    return format_html('<span class="pill tone-{}">{}</span>', tone, label)


@register.simple_tag
def state_pill(row):
    """Odoo state of an MO or transfer row, coloured like Odoo."""
    tones = MO_TONES if row.KIND == "mo" else PICKING_TONES
    return _pill(row.state_label, tones.get(row.state, "gray"))


@register.simple_tag
def record_pill(pl):
    return _pill(pl.get_status_display(), RECORD_TONES.get(pl.status, "gray"))


@register.simple_tag
def system_pill(row):
    status = row.system_status
    if status == "confirmed":
        return _pill("Done in Odoo", "green", "check-circle")
    if status == "not_done":
        return _pill(f"Odoo: {row.system_state_label or 'not done'}", "red", "x-circle")
    if status == "error":
        return _pill("Could not check", "gray", "exclamation-circle")
    return format_html('<span class="muted">—</span>')


@register.filter
def get_item(mapping, key):
    return mapping.get(key, "") if mapping else ""


@register.filter
def qty(value):
    """12.00 → 12, 2.50 → 2.5"""
    if value is None or value == "":
        return ""
    return format(Decimal(str(value)).normalize(), "f")
