"""Reads an Odoo-printed SAWO packing list PDF.

Splits it into the header **information** (Sold To, Date, Invoice No., …) and the **list data**
(External Code, Description, UM, Number of Packages, Net/Gross Weight, CBM, Qty) plus the Grand Total row.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

# Header labels as printed; the value is the text to the right of the label.
HEADER_LABELS = {
    "sold_to": ("Sold", "To:"),
    "tel": ("Tel.", "No.:"),
    "fax": ("Fax", "No.:"),
    "attn": ("ATTN:",),
    "date": ("Date:",),
    "invoice_no": ("Invoice", "No.:"),
    "container_no": ("Container", "No.:"),
    "seal_no": ("Seal", "No.:"),
    "destination": ("Destination:",),
}

# Table header text (whitespace-collapsed, lower case) → field.
COLUMNS = {
    "external code": "external_code",
    "description": "description",
    "um": "um",
    "number of packages": "packages",
    "net weight": "net_weight",
    "gross weight": "gross_weight",
    "cbm": "cbm",
    "qty": "qty",
}
NUMERIC = ("packages", "net_weight", "gross_weight", "cbm", "qty")
COLUMN_ORDER = list(COLUMNS.values())

# Fallback when no ruled table is found: one row per text line.
ROW_RE = re.compile(
    r"^(?P<external_code>\S+)\s+(?P<description>.+?)\s+(?P<um>\S+)\s+(?P<packages>[\d.,]+)\s+"
    r"(?P<net_weight>[\d.,]+)\s+(?P<gross_weight>[\d.,]+)\s+(?P<cbm>[\d.,]+)\s+(?P<qty>[\d.,]+)$"
)
TOTAL_RE = re.compile(
    r"Grand\s+Total:?\s+(?P<packages>[\d.,]+)\s+(?P<net_weight>[\d.,]+)\s+(?P<gross_weight>[\d.,]+)\s+"
    r"(?P<cbm>[\d.,]+)\s+(?P<qty>[\d.,]+)"
)


class PackingListParseError(Exception):
    pass


@dataclass
class ParsedPackingList:
    header: dict = field(default_factory=dict)
    lines: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def to_decimal(text):
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(text):
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_packing_list(file_obj):
    try:
        pdf = pdfplumber.open(file_obj)
    except Exception as exc:  # pdfminer raises many types for broken files
        raise PackingListParseError("This file could not be opened as a PDF.") from exc

    with pdf:
        if not pdf.pages:
            raise PackingListParseError("The PDF has no pages.")
        result = ParsedPackingList()
        result.header = _parse_header(pdf.pages[0])
        result.lines, result.totals = _parse_table(pdf.pages)

    if not result.lines:
        raise PackingListParseError(
            "No packing list rows were found. Please upload the packing list PDF printed from Odoo."
        )
    _check_totals(result)
    return result


# --- header --------------------------------------------------------------------------------


def _words(page):
    words = page.extract_words(x_tolerance=1.5, y_tolerance=3, keep_blank_chars=False)
    for w in words:
        w["mid"] = (w["top"] + w["bottom"]) / 2
    return sorted(words, key=lambda w: (round(w["top"]), w["x0"]))


def _find_label(words, tokens):
    for i, w in enumerate(words):
        if w["text"] != tokens[0]:
            continue
        seq = words[i : i + len(tokens)]
        if len(seq) == len(tokens) and all(
            s["text"] == t and abs(s["mid"] - w["mid"]) < 2 for s, t in zip(seq, tokens)
        ):
            return {"x0": seq[0]["x0"], "x1": seq[-1]["x1"], "top": w["top"], "mid": w["mid"]}
    return None


def _join_lines(words):
    lines = []
    for w in sorted(words, key=lambda w: (w["mid"], w["x0"])):
        if lines and abs(lines[-1][0]["mid"] - w["mid"]) < 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(" ".join(x["text"] for x in sorted(line, key=lambda x: x["x0"])) for line in lines)


def _parse_header(page):
    words = _words(page)
    half = page.width / 2
    labels = {key: _find_label(words, tokens) for key, tokens in HEADER_LABELS.items()}
    # The table starts at its "External Code" header; nothing below it belongs to the header.
    table_top = (_find_label(words, ("External", "Code")) or {"top": page.height})["top"]

    header = {}
    for key, label in labels.items():
        if label is None:
            header[key] = ""
            continue
        limit = half if label["x0"] < half else page.width
        if key == "sold_to":
            bottom = labels["tel"]["top"] - 1 if labels.get("tel") else label["top"] + 60
            picked = [
                w for w in words
                if w["x0"] > label["x1"] and w["x1"] <= limit and label["top"] - 4 <= w["top"] < bottom
            ]
            header[key] = _join_lines(picked)
        else:
            picked = [
                w for w in words
                if w["x0"] > label["x1"] and w["x1"] <= limit and abs(w["mid"] - label["mid"]) <= 5
                and w["top"] < table_top
            ]
            header[key] = " ".join(w["text"] for w in sorted(picked, key=lambda w: w["x0"]))
    return header


# --- table ---------------------------------------------------------------------------------


def _clean(cell):
    return " ".join((cell or "").split())


def _clean_code(cell):
    # Long codes wrap inside the cell ("SCA-90NS-DRF-BL-\nP-C"): join the pieces without spaces.
    return "".join(part.strip() for part in (cell or "").splitlines())


def _parse_table(pages):
    lines, totals = [], {}
    columns = None
    for page in pages:
        for table in page.extract_tables():
            for row in table:
                cells = [c if c is not None else "" for c in row]
                header_cols = _header_columns(cells)
                if header_cols:
                    columns = header_cols
                    continue
                if columns is None or len(cells) != len(columns):
                    continue
                record = {}
                for name, cell in zip(columns, cells):
                    if name:
                        record[name] = _clean_code(cell) if name == "external_code" else _clean(cell)
                if any("grand total" in _clean(c).lower() for c in cells):
                    totals = {k: to_decimal(record.get(k)) for k in NUMERIC}
                    continue
                if not record.get("external_code") and not record.get("description"):
                    continue
                lines.append(_typed(record))

    if not lines:
        lines, totals = _parse_text(pages)
    for i, line in enumerate(lines, start=1):
        line["line_no"] = i
    return lines, totals


def _header_columns(cells):
    names = [COLUMNS.get(_clean(c).lower()) for c in cells]
    if "external_code" in names and "qty" in names:
        return names
    return None


def _typed(record):
    line = {name: record.get(name, "") for name in ("external_code", "description", "um")}
    for name in NUMERIC:
        line[name] = to_decimal(record.get(name))
    return line


def _parse_text(pages):
    lines, totals = [], {}
    for page in pages:
        for text_line in (page.extract_text() or "").splitlines():
            text_line = text_line.strip()
            total = TOTAL_RE.search(text_line)
            if total:
                totals = {k: to_decimal(v) for k, v in total.groupdict().items()}
                continue
            match = ROW_RE.match(text_line)
            if match:
                lines.append(_typed(match.groupdict()))
    return lines, totals


def _check_totals(result):
    totals = result.totals
    if not totals:
        result.warnings.append("No Grand Total row found in the PDF; totals could not be verified.")
        return
    for key, label in (("qty", "Qty"), ("packages", "Number of Packages")):
        expected = totals.get(key)
        if expected is None:
            continue
        actual = sum((line[key] or 0) for line in result.lines)
        if actual != expected:
            result.warnings.append(
                f"Sum of {label} on the rows ({actual:g}) does not match the Grand Total ({expected:g})."
            )
