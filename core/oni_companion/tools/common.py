"""Shared helpers for the calculators (tools).

Every tool is a pure function of its form values and a game-data object shaped
like `contracts/mod-export.schema.json` (the merged union of export files, as
plain dicts and lists). No numbers are written into this package except unit
conversions, which are definitions, not game data.

stdlib only (Python >= 3.11).
"""

from __future__ import annotations

import copy
import math
from collections import namedtuple
from datetime import datetime, timezone

# A number from a form: the value as typed, and the unit id it was typed in.
Num = namedtuple("Num", "value unit")

# Unit ids for form fields, as (id, label) pairs for the `units` list.
MASS_UNITS = [("kg", "kg"), ("g", "g")]
MASS_TO_KG = {"kg": 1.0, "g": 0.001}
RATE_UNITS = [("g/s", "g/s"), ("kg/s", "kg/s")]
RATE_TO_KG_S = {"g/s": 0.001, "kg/s": 1.0}
TEMP_UNITS = [("C", "C"), ("F", "F"), ("K", "K")]


class ToolError(Exception):
    """A bad form value. The API maps it to 400 bad_request; `message` names the field."""

    def __init__(self, field, message, label=None):
        # `field` is the form field's name; the text a person reads names it by its label.
        super().__init__("%s: %s" % (label or field, message))
        self.field = field
        self.detail = message
        self.message = "%s: %s" % (label or field, message)


class UnknownTool(Exception):
    """No tool has that id. The API maps it to 404 not_found."""


class DataProblem(Exception):
    """Needed game data is missing or inconsistent. The Screen says so; no number is invented."""


_MISSING = object()


# ---------------------------------------------------------------- data access

def index_by_id(data, key):
    """Dict id -> entry for one list of the export (e.g. "elements")."""
    out = {}
    for item in data.get(key) or []:
        out[item["id"]] = item
    return out


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def round_num(x, places=2):
    """Display rounding. Keeps the number a float (JSON number)."""
    return round(float(x), places)


def fmt_num(x):
    """Short text for a number in a range label, e.g. 120 -> '120', 99.5 -> '99.5'."""
    return "%g" % round(float(x), 2)


def temp_to_c(num):
    """Typed temperature -> Celsius. Rounded to hide float noise (373.15 K is exactly 100 C)."""
    if num.unit == "C":
        v = num.value
    elif num.unit == "F":
        v = (num.value - 32.0) * 5.0 / 9.0
    elif num.unit == "K":
        v = num.value - 273.15
    else:
        raise ToolError("temperature", "pick C, F or K")
    return round(v, 9)


# -------------------------------------------------------------- form fields

def number_field(name, label, default, *, units=None, default_unit=None, unit=None,
                 min=None, max=None, step=None):
    """A number field: a unit choice (`units`) or one fixed unit (`unit`), or none."""
    f = {"kind": "number", "name": name, "label": label, "default": default}
    if units is not None:
        f["units"] = [{"id": uid, "label": ulabel} for uid, ulabel in units]
        f["defaultUnit"] = default_unit or units[0][0]
    elif unit is not None:
        f["unit"] = unit
    if min is not None:
        f["min"] = min
    if max is not None:
        f["max"] = max
    if step is not None:
        f["step"] = step
    return f


def element_field(name, label, *, default=None, filter="any"):
    f = {"kind": "element", "name": name, "label": label, "filter": filter}
    if default is not None:
        f["default"] = default
    return f


def choice_field(name, label, options, *, default=None):
    """`options` is a list of (value, label). Default is the first option."""
    opts = [{"value": v, "label": lab} for v, lab in options]
    f = {"kind": "choice", "name": name, "label": label, "options": opts}
    f["default"] = default if default is not None else opts[0]["value"]
    return f


def toggle_field(name, label, default=False):
    return {"kind": "toggle", "name": name, "label": label, "default": default}


def _parse_number(f, raw, name):
    fixed_unit = f.get("unit")
    typed_unit = None
    if isinstance(raw, dict):
        if "value" not in raw:
            raise ToolError(name, "type a number")
        val = raw["value"]
        typed_unit = raw.get("unit")
    else:
        val = raw
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
        raise ToolError(name, "type a number")
    if "units" in f:
        ids = [u["id"] for u in f["units"]]
        unit = typed_unit if typed_unit is not None else f.get("defaultUnit", ids[0])
        if unit not in ids:
            raise ToolError(name, "pick one of the units: %s" % ", ".join(ids))
    else:
        if typed_unit is not None and fixed_unit is not None and typed_unit != fixed_unit:
            raise ToolError(name, "the unit is %s" % fixed_unit)
        unit = fixed_unit
    if "min" in f and val < f["min"]:
        raise ToolError(name, "use %s or more" % fmt_num(f["min"]))
    if "max" in f and val > f["max"]:
        raise ToolError(name, "use %s or less" % fmt_num(f["max"]))
    return Num(float(val), unit)


def _parse_one(f, raw, data):
    name = f["name"]
    kind = f["kind"]
    if kind == "number":
        return _parse_number(f, raw, name)
    if kind == "element":
        if not isinstance(raw, str) or raw == "":
            raise ToolError(name, "choose an element")
        els = index_by_id(data, "elements")
        if raw not in els:
            raise ToolError(name, "that element is not in the game")
        want = f.get("filter", "any")
        if want != "any" and els[raw]["state"] != want:
            raise ToolError(name, "choose a %s element" % want)
        return raw
    if kind == "choice":
        values = [o["value"] for o in f["options"]]
        if not isinstance(raw, str) or raw not in values:
            raise ToolError(name, "pick one of the listed choices")
        return raw
    if kind == "toggle":
        if not isinstance(raw, bool):
            raise ToolError(name, "choose on or off")
        return raw
    raise ToolError(name, "unknown field kind %r" % kind)


def parse_values(fields, values, data):
    """Form values -> {name: parsed}. Missing values take the field default.

    Number fields give Num(value, unit); element fields give the id; choice fields
    give the option value; toggles give a bool. Raises ToolError naming the field.
    """
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ToolError("values", "send the form values as an object")
    out = {}
    for f in fields:
        name = f["name"]
        raw = values.get(name, _MISSING)
        if raw is _MISSING or raw is None or (f["kind"] == "element" and raw == ""):
            if "default" not in f:
                raise ToolError(name, "needs a value", label=f.get("label"))
            # A default for a unit field is a plain number; its unit is defaultUnit.
            raw = f["default"]
        try:
            out[name] = _parse_one(f, raw, data)
        except ToolError as e:
            raise ToolError(name, e.detail, label=f.get("label"))
    return out


def prefilled_fields(fields, parsed):
    """Copies of the form fields with the submitted values as their defaults."""
    out = []
    for f in fields:
        g = copy.deepcopy(f)
        p = parsed[f["name"]]
        if f["kind"] == "number":
            g["default"] = p.value
            if "units" in g:
                g["defaultUnit"] = p.unit
        else:
            g["default"] = p
        out.append(g)
    return out


# ------------------------------------------------------------- block builders

def stat(label, value, unit=None, hint=None, ref=None, tone=None):
    row = {"label": label, "value": value}
    if unit is not None:
        row["unit"] = unit
    if hint is not None:
        row["hint"] = hint
    if ref is not None:
        row["ref"] = ref
    if tone is not None:
        row["tone"] = tone
    return row


def stats_block(rows, title=None):
    b = {"type": "stats", "rows": rows}
    if title is not None:
        b["title"] = title
    return b


def notice(level, text, title=None):
    b = {"type": "notice", "level": level, "text": text}
    if title is not None:
        b["title"] = title
    return b


def text_block(text):
    return {"type": "text", "spans": [{"type": "plain", "text": text}]}


def element_ref(eid):
    return {"kind": "element", "id": eid}


def form_block(tool_id, fields, submit_label):
    return {"type": "form", "tool": tool_id, "submitLabel": submit_label, "fields": fields}


# ----------------------------------------------------------------- the tool

class Tool:
    """One calculator. `fields(data)` gives form fields; `run(parsed, data)` gives blocks."""

    def __init__(self, tool_id, title, summary, fields, run, submit_label="Calculate"):
        self.id = tool_id
        self.title = title
        self.summary = summary
        self.fields = fields
        self.run = run
        self.submit_label = submit_label
