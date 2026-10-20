import re
from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.odoo import MO_STATES, PICKING_STATES

SYSTEM = "mo_close"


def norm_code(code):
    """Product code compared without spaces, dashes or case (PDF vs Odoo formatting)."""
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def so_digits(so):
    """'S08027' → '8027' (the number without the S and leading zeros)."""
    return str(int(so[1:])) if so[1:].isdigit() else so


def so_source_pattern(so):
    """Finds the SO number in an MO Source however it was typed. The correct form is 'S0…' (S08027);
    SO8027, So8027, SS08027, S8027, O8027, 08027, 'SO# 08027' and a bare 8027 are auto-corrected to it — but
    never S080271, PO8027, a number that is part of a date / time (10/16/2026, 2026-08-07), or a bare number in
    parentheses, which in SAWO Sources is the customer code (UKRAINE(4300), Sauna Europe (11500))."""
    sep = r"[\s#.:-]*"
    number = re.escape(so_digits(so))
    prefixed = r"(?<![A-Za-z0-9])(?:S{1,2}" + sep + r"[O0]?|[O0])" + sep + r"0*" + number + r"(?!\d)"
    bare = r"(?<![A-Za-z0-9/.:(-])0*" + number + r"(?![\d/)]|[.:-]\d)"
    return re.compile(prefixed + "|" + bare, re.IGNORECASE)


def so_source_fix(so, source):
    """The wrong spelling of the SO in an MO Source ('SO8027'), or '' when it is written correctly."""
    found = [m.group(0) for m in so_source_pattern(so).finditer(source or "")]
    if not found or so in found:
        return ""
    return found[0]


class PackingList(models.Model):
    """One record per Sales Order, created from an uploaded packing list PDF (Step 1)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SAVED = "saved", "Saved"
        GENERATED = "generated", "In progress"
        CLOSED = "closed", "Closed"

    so_number = models.CharField("SO", max_length=20, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)

    # Header information from the PDF
    sold_to = models.TextField(blank=True)
    tel = models.CharField("Tel. No.", max_length=100, blank=True)
    fax = models.CharField("Fax No.", max_length=100, blank=True)
    attn = models.CharField("ATTN", max_length=200, blank=True)
    doc_date_text = models.CharField("Date", max_length=50, blank=True)
    doc_date = models.DateField(null=True, blank=True)
    invoice_no = models.CharField("Invoice No.", max_length=50, blank=True)
    container_no = models.CharField("Container No.", max_length=200, blank=True)
    seal_no = models.CharField("Seal No.", max_length=100, blank=True)
    destination = models.CharField(max_length=100, blank=True)

    # Grand total row from the PDF
    total_packages = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_net_weight = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    total_gross_weight = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    total_cbm = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    total_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    pdf = models.FileField(upload_to="packing_lists/%Y/%m/")
    pdf_name = models.CharField(max_length=255, blank=True)
    parse_warnings = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    saved_at = models.DateTimeField(null=True, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.so_number

    @property
    def audit_label(self):
        return self.so_number

    @property
    def sold_to_name(self):
        return self.sold_to.splitlines()[0] if self.sold_to else ""

    def grouped_lines(self):
        """Packing lines grouped by External Code with Qty summed (as shown on the record)."""
        groups = OrderedDict()
        for line in self.lines.all():
            key = norm_code(line.external_code) or f"__line{line.pk}"
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    "code": line.external_code,
                    "norm": norm_code(line.external_code),
                    "description": line.description,
                    "um": line.um,
                    "qty": Decimal("0"),
                    "rows": 0,
                }
            g["qty"] += line.qty or 0
            g["rows"] += 1
        return list(groups.values())

    def all_rows(self):
        """Every tracked row (MOs and their transfers)."""
        rows = []
        for mo in self.mos.all():
            rows.append(mo)
            rows.extend(mo.transfers.all())
        return rows

    def update_status(self, save=True):
        """In progress ↔ Closed: closed when every MO and transfer row has final confirmation."""
        if self.status not in (self.Status.GENERATED, self.Status.CLOSED):
            return
        rows = self.all_rows()
        if rows and all(r.final_confirmed for r in rows):
            if self.status != self.Status.CLOSED:
                self.status, self.closed_at = self.Status.CLOSED, timezone.now()
        else:
            self.status, self.closed_at = self.Status.GENERATED, None
        if save:
            self.save(update_fields=["status", "closed_at"])


class PackingLine(models.Model):
    """One row of the packing list table, saved as printed."""

    packing_list = models.ForeignKey(PackingList, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    external_code = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=500, blank=True)
    um = models.CharField("UM", max_length=20, blank=True)
    packages = models.DecimalField("Number of Packages", max_digits=12, decimal_places=2, null=True, blank=True)
    net_weight = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    gross_weight = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    cbm = models.DecimalField("CBM", max_digits=12, decimal_places=3, null=True, blank=True)
    qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["line_no"]


class TrackedRow(models.Model):
    """Odoo item followed until done: user marks done → system checks Odoo → Checker confirms (Step 3)."""

    class SystemStatus(models.TextChoices):
        NONE = "", "Not checked"
        CONFIRMED = "confirmed", "Done in Odoo"
        NOT_DONE = "not_done", "Not done in Odoo"
        ERROR = "error", "Could not check"

    odoo_id = models.PositiveIntegerField()
    reference = models.CharField(max_length=100)
    state = models.CharField("Odoo state", max_length=20, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    user_done = models.BooleanField(default=False)
    user_done_at = models.DateTimeField(null=True, blank=True)
    user_done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    system_status = models.CharField(max_length=10, choices=SystemStatus.choices, blank=True, default="")
    system_checked_at = models.DateTimeField(null=True, blank=True)
    system_odoo_state = models.CharField(max_length=20, blank=True)

    final_confirmed = models.BooleanField(default=False)
    final_confirmed_at = models.DateTimeField(null=True, blank=True)
    final_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    final_comment = models.TextField(blank=True)

    STATE_LABELS = {}
    KIND = ""

    class Meta:
        abstract = True

    @property
    def state_label(self):
        return self.STATE_LABELS.get(self.state, self.state or "—")

    @property
    def system_state_label(self):
        return self.STATE_LABELS.get(self.system_odoo_state, self.system_odoo_state)

    @property
    def is_odoo_done(self):
        return self.state == "done"

    @property
    def tracking_stage(self):
        if self.final_confirmed:
            return "confirmed"
        if self.user_done:
            return "waiting"
        return "open"


class MORecord(TrackedRow):
    """A Manufacturing Order of the SO (Step 2): matched to a packing line, or — when its product is not on
    the packing list — a component / sub-assembly made for the SO (fg_* then hold the MO's product)."""

    packing_list = models.ForeignKey(PackingList, on_delete=models.CASCADE, related_name="mos")
    on_packing_list = models.BooleanField(default=True)
    fg_code = models.CharField("FG Code", max_length=100)
    fg_description = models.CharField("FG", max_length=500, blank=True)
    qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    product_qty = models.DecimalField("MO Qty", max_digits=12, decimal_places=2, null=True, blank=True)
    product_label = models.CharField(max_length=500, blank=True)
    origin = models.CharField("Source", max_length=500, blank=True)

    STATE_LABELS = MO_STATES
    KIND = "mo"

    class Meta:
        ordering = ["-on_packing_list", "fg_code", "reference"]
        constraints = [models.UniqueConstraint(fields=["packing_list", "odoo_id"], name="uniq_mo_per_record")]

    def __str__(self):
        return self.reference

    @property
    def source_fix(self):
        """Fix flag: the SO is written wrong in the Odoo Source (e.g. 'SO8027' instead of 'S08027')."""
        return so_source_fix(self.packing_list.so_number, self.origin)


class TransferRecord(TrackedRow):
    """A transfer (PC / SFP …) of a matched MO that was not Done when generated (Step 2)."""

    mo = models.ForeignKey(MORecord, on_delete=models.CASCADE, related_name="transfers")
    type_code = models.CharField(max_length=20, blank=True)
    type_name = models.CharField(max_length=200, blank=True)
    scheduled_date = models.DateTimeField(null=True, blank=True)

    STATE_LABELS = PICKING_STATES
    KIND = "transfer"

    class Meta:
        ordering = ["reference"]
        constraints = [models.UniqueConstraint(fields=["mo", "odoo_id"], name="uniq_transfer_per_mo")]

    def __str__(self):
        return self.reference

    @property
    def packing_list(self):
        return self.mo.packing_list
