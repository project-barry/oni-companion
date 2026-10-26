"""Resources Screen (GET /resources): what the colony has, grouped like the game's Resources panel.

Sources, in the order Colony.facts() picks them:
  mod-live  schema 2: a categorized list (the game's own categories and order, never re-sorted here);
            schema 1: an id -> kg map. The map has no categories and also holds tags such as
            "Pickupable", so only ids the look-up knows as an element, food or medicine are shown,
            grouped by the core's own rules (marked in the code as the fallback grouping).
  save      the save parser's totals (a map), (no notice). No trends.
Trends come from ResourceHistory: snapshots kept in memory only, in game time, never saved.
"""
import threading
import time
from collections import deque

from . import blocks as B

CYCLE_S = 600.0
STEP_S = 5.0            # keep one snapshot per 5 game seconds
WINDOW_S = 900.0        # and about 1.5 cycles of them
MIN_SPAN_S = 30.0       # below this span a trend is noise: no trend line
FLAT_EPS = 0.5          # kg or kcal change below this counts as no change

NO_COLONY = "No colony found. Start Oxygen Not Included and load a save."
HEADER_ONLY = "Only the save header could be read, so there are no resource totals yet."
EMPTY = "No resources found in this world."

# Fallback grouping for schema 1 and save data (the game's own categories come with schema 2).
FALLBACK_ORDER = ["Metal", "Minerals", "Liquids", "Gases", "Food", "Medicine", "Critters"]
FALLBACK_KINDS = ("element", "food", "medicine")


def game_time(facts):
    cyc, tod = facts.get("cycle"), facts.get("timeOfDay")
    if isinstance(cyc, bool) or not isinstance(cyc, (int, float)) or isinstance(tod, bool) or not isinstance(tod, (int, float)):
        return None
    return cyc * CYCLE_S + tod * CYCLE_S


def _live_worlds(facts):
    return facts.get("worlds") or []


class ResourceHistory:
    """In-memory snapshots per world: {resource id: amount}, stamped with game time (seconds).
    Only live data is recorded. A colony change or a jump back in game time (loading an older save)
    starts over. Thread safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._snaps = {}        # world id -> deque[(gt, {id: amount})]
        self._colony = None
        self._last_gt = None

    def clear(self):
        with self._lock:
            self._snaps.clear()
            self._colony = None
            self._last_gt = None

    def record(self, facts):
        """Add a snapshot from Colony.facts() output. Ignores anything that is not live."""
        if facts.get("source") != "mod-live":
            return False
        gt = game_time(facts)
        if gt is None:
            return False
        amounts = {}
        for w in _live_worlds(facts):
            amounts[w.get("id")] = {r["id"]: r["amount"] for r in normalize(None, w.get("resources"), (), raw=True)}
            for c in w.get("critters") or []:
                amounts[w.get("id")].setdefault("critter:" + str(c.get("id")), c.get("count", 0))
        with self._lock:
            if facts.get("colonyName") != self._colony or (self._last_gt is not None and gt < self._last_gt - 1):
                self._snaps.clear()
                self._last_gt = None
            self._colony = facts.get("colonyName")
            if self._last_gt is not None and gt - self._last_gt < STEP_S:
                return False
            self._last_gt = gt
            for wid, cur in amounts.items():
                dq = self._snaps.setdefault(wid, deque())
                dq.append((gt, cur))
                while dq and dq[0][0] < gt - WINDOW_S:
                    dq.popleft()
            return True

    def baseline(self, world_id, now_gt):
        """(snapshot amounts, span seconds) from about one cycle ago, or the oldest if the history is
        younger. None when there is nothing at least MIN_SPAN_S old."""
        with self._lock:
            dq = self._snaps.get(world_id)
            if not dq:
                return None
            target = now_gt - CYCLE_S
            pick = None
            for gt, amts in dq:
                if gt <= target:
                    pick = (gt, amts)
                else:
                    break
            if pick is None:
                pick = dq[0]
            span = now_gt - pick[0]
            if span < MIN_SPAN_S:
                return None
            return pick[1], span


# ---- rows
def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else 0


def normalize(lk, res, critters, raw=False):
    """Rows {id, name, category, amount, unit, kcal} from schema 2 (list) or schema 1 / save (map).
    raw=True skips the look-up and keeps every id (used by the history, which needs only amounts)."""
    rows = []
    if isinstance(res, list):
        for r in res:
            if not isinstance(r, dict) or "id" not in r:
                continue
            row = {"id": str(r["id"]), "name": r.get("name") or str(r["id"]), "category": r.get("category") or "Other",
                   "amount": max(0.0, _num(r.get("amount"))), "unit": r.get("unit") or "units"}
            if isinstance(r.get("kcal"), (int, float)) and not isinstance(r.get("kcal"), bool):
                row["kcal"] = r["kcal"]
            rows.append(row)
        return rows
    if not isinstance(res, dict):
        return rows
    for rid, amount in res.items():
        amount = max(0.0, _num(amount))
        if raw:
            rows.append({"id": str(rid), "amount": amount})
            continue
        row = _fallback_row(lk, str(rid), amount)
        if row:
            rows.append(row)
    return rows


def _fallback_row(lk, rid, amount):
    """Map entry -> row, or None for ids the look-up does not know (tags like Pickupable)."""
    if lk is None:
        return None
    ref = lk.ref_any(rid, FALLBACK_KINDS)
    if not ref:
        return None
    e = lk.get(ref["kind"], ref["id"])
    name = e.get("name") or ref["id"]
    if ref["kind"] == "food":
        row = {"id": ref["id"], "name": name, "category": "Food", "amount": amount, "unit": "units"}
        if isinstance(e.get("kcal"), (int, float)) and e["kcal"] > 0:
            row["kcal"] = e["kcal"]
        return row
    if ref["kind"] == "medicine":
        return {"id": ref["id"], "name": name, "category": "Medicine", "amount": amount, "unit": "units"}
    state = e.get("state")
    tags = set(e.get("tags") or [])
    if state == "liquid":
        cat = "Liquids"
    elif state == "gas":
        cat = "Gases"
    elif "Metal" in tags or "RefinedMetal" in tags:
        cat = "Metal"
    else:
        cat = "Minerals"
    return {"id": ref["id"], "name": name, "category": cat, "amount": amount, "unit": "kg"}


def critter_rows(lk, critters):
    rows = []
    for c in critters or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        n = int(_num(c.get("count")))
        rows.append({"id": str(c["id"]), "name": lk.name("critter", c["id"]), "category": "Critters",
                     "amount": float(n), "unit": "units", "_critter": True})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


# ---- formatting
def _fmt(x, places=1):
    if abs(x) < 10 and places:
        places = 2 if abs(x) % 1 else 0
    s = ("{:,.%df}" % places).format(round(x, places))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def amount_text(row):
    unit = row["unit"]
    if unit == "kg":
        return "%s kg" % _fmt(row["amount"])
    if unit == "kcal":
        return "%s kcal" % _fmt(row["amount"], 0)
    n = _fmt(row["amount"], 0)
    kcal = row.get("kcal")
    if kcal:
        return "%s (%s kcal)" % (n, _fmt(row["amount"] * kcal, 0))
    return n


def display_unit(row):
    """(multiplier from amount, unit label) for trends: foods with energy trend in kcal."""
    if row["unit"] == "units" and row.get("kcal"):
        return row["kcal"], "kcal"
    return 1.0, row["unit"]


def group_total(rows):
    kg = sum(r["amount"] for r in rows if r["unit"] == "kg")
    kcal = sum(r["amount"] if r["unit"] == "kcal" else r["amount"] * r["kcal"] for r in rows
               if r["unit"] == "kcal" or (r["unit"] == "units" and r.get("kcal")))
    units = sum(r["amount"] for r in rows if r["unit"] == "units" and not r.get("kcal"))
    parts = []
    if kg or any(r["unit"] == "kg" for r in rows):
        parts.append("%s kg" % _fmt(kg))
    if kcal or any(r["unit"] == "kcal" or r.get("kcal") for r in rows):
        parts.append("%s kcal" % _fmt(kcal, 0))
    if not parts:                       # a group of plain counts (critters, medicine, seeds)
        parts.append(_fmt(units, 0))
    return ", ".join(parts)


def span_text(span):
    if span >= CYCLE_S - 10:
        return "since last cycle"
    if span >= 90:
        return "in %d min" % round(span / 60)
    return "in %d s" % round(span)


def trend(row, base, span, world_has_base):
    """(subtitle, tone) for one row."""
    if base is None:
        return None, None                        # no trend yet (paused, or not 30 s of history): no line at all
    key = ("critter:" + row["id"]) if row.get("_critter") else row["id"]
    before = base.get(key, 0.0) if world_has_base else 0.0
    mult, unit = display_unit(row)
    delta = (row["amount"] - before) * mult
    if abs(delta) < (FLAT_EPS if unit != "units" else 0.5):
        return "No change", None
    sign = "+" if delta > 0 else "-"
    mag = _fmt(abs(delta), 0 if unit == "kcal" else 1)
    suffix = (" " + unit) if unit != "units" else ""
    return "%s%s%s %s" % (sign, mag, suffix, span_text(span)), ("good" if delta > 0 else "warn")


# ---- the Screen
ART_KIND = {"element": "element", "food": "food", "medicine": "item", "critter": "critter"}


def _row_item(lk, row, art, base, span, has_base):
    kinds = ("element", "food", "medicine", "critter")
    if row.get("_critter") or row["category"].lower().startswith("critter"):
        kinds = ("critter",) + kinds
    elif row["category"].lower() == "food":
        kinds = ("food",) + kinds
    kind = next((k for k in kinds if lk.get(k, row["id"])), None)
    ref = lk.ref(kind, row["id"]) if kind else None
    art_path = None
    if art:
        # the look-up's kind first, then every art kind the mod renders (the look-up lists eggs with their critter,
        # the art pack files them as egg)
        rest = ["element", "food", "critter", "item", "plant", "seed", "egg", "medicine"]
        order = ([ART_KIND.get(kind, "item")] if kind else []) + rest
        art_path = next((u for u in (art(k, row["id"]) for k in order) if u), None)
    if ref and art_path:
        ref = dict(ref, art=art_path)
    sub, tone = trend(row, base, span, has_base)
    it = B.item(row["name"], ref, subtitle=sub, badge=amount_text(row), tone=tone)
    if art_path:
        it["art"] = art_path
    return it


def resources_screen(lk, facts, history=None, world=None, q=None, art=None):
    """facts: Colony.facts() output (all worlds). world: world id (str or int) or None for the active one.
    art: optional callable (artKind, id) -> '/api/v1/art/...' or None. Raises KeyError for an unknown world."""
    src = facts.get("source", "none")
    as_of = facts.get("asOf")
    if src == "none":
        return B.screen("Resources", [B.notice("info", NO_COLONY)], source="none", back="home", refresh_on=["colony"])
    if src == "header" or not facts.get("worlds"):
        return B.screen("Resources", [B.notice("info", HEADER_ONLY)], subtitle=facts.get("colonyName"),
                        source=src, as_of=as_of, back="home", refresh_on=["colony"])
    worlds = facts["worlds"]
    if world is not None:
        w = next((x for x in worlds if str(x.get("id")) == str(world)), None)
        if w is None:
            raise KeyError(world)
    else:
        active = facts.get("activeWorldId")
        w = next((x for x in worlds if str(x.get("id")) == str(active)), worlds[0])
    wid = w.get("id")
    live = src == "mod-live"
    res = w.get("resources")
    rows = normalize(lk, res, w.get("critters"))
    if not isinstance(res, list):                # schema 1 and the save have no critter rows in the map
        rows += critter_rows(lk, w.get("critters"))
        order = {c: i for i, c in enumerate(FALLBACK_ORDER)}
        rows.sort(key=lambda r: (order.get(r["category"], 99), r["name"].lower()))
    base, span, has_base = None, 0.0, False
    if live and history is not None:
        gt = game_time(facts)
        got = history.baseline(wid, gt) if gt is not None else None
        if got:
            base, span = got
            has_base = True
    needle = (q or "").strip().lower()
    cats, order_cat = {}, []
    for r in rows:
        if r["category"] not in cats:
            cats[r["category"]] = []
            order_cat.append(r["category"])
        cats[r["category"]].append(r)
    blocks = []
    shown = 0
    for cat in order_cat:
        allrows = cats[cat]
        vis = [r for r in allrows if not needle or needle in r["name"].lower() or needle in cat.lower()]
        if not vis:
            continue
        items = [_row_item(lk, r, art, base, span, has_base) for r in vis]
        shown += len(items)
        collapsed = None if needle or len(blocks) - (1 if src == "save" else 0) < 3 else True
        tot = group_total(allrows)
        blocks.append(B.group("%s: %s" % (cat, tot) if tot else cat, [B.list_block(items)], collapsed=collapsed))
    if not shown:
        blocks.append(B.notice("info", "Nothing matches that filter." if needle and rows else EMPTY))
    scr = B.screen("Resources", blocks, subtitle=w.get("name") or None, source=src, as_of=as_of, back="home",
                   refresh_on=["colony"])
    scr["filter"] = {"placeholder": "Filter resources"}
    ws = [{"id": x["id"], "name": x.get("name") or "World %s" % x["id"]} for x in worlds if isinstance(x.get("id"), int)]
    if ws and isinstance(wid, int):
        scr["worldSwitcher"] = {"active": wid, "worlds": ws}
    return scr
