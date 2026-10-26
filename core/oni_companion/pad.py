"""Overlays, tools and Build (v1.3): the rules, with no layout. Stdlib only.

Everything comes from the game through the mod: the export lists the overlays, tools, build menu and per
building the unlock facts; live.json says what is active now, which buildings can be built and what the
colony has in stock. The core only combines them and decides what a button says and whether it is enabled.
Views (views/pad.py, views/buildings.py) turn the answers into Screens.
"""
import hashlib
import json

NOT_RUNNING = "The game is not running."
IN_MENU = "Load a colony in the game first."
NOT_AVAILABLE = "Not available in this game."
NOT_RESEARCHED = "Not researched yet."
NONE_MODE = "None"                 # overlay_set mode that switches the overlay off
EMERGENCY = "emergency"


def live_ok(availability):
    """availability: Controls.availability() -> (ok, reason, live). Returns (ok, reason text)."""
    ok, reason, _live = availability
    if ok:
        return True, None
    return False, IN_MENU if reason == "menu" else NOT_RUNNING


class Catalog:
    """The v1.3 lists of one loaded dataset (lookup.meta) with the lookups the views and validators need."""

    def __init__(self, lk):
        self.lk = lk
        m = lk.meta
        self.overlays = [o for o in m.get("overlays") or [] if isinstance(o, dict)]
        self.tools = [t for t in m.get("padTools") or [] if isinstance(t, dict)]
        self.menu = [g for g in m.get("buildMenu") or [] if isinstance(g, dict)]
        self._ov = {o["id"]: o for o in self.overlays}
        self._tl = {t["id"]: t for t in self.tools}

    def overlay(self, ident):
        return self._ov.get(ident)

    def tool(self, ident):
        return self._tl.get(ident)

    def dlc_reason(self, item):
        d = item.get("dlc") or []
        return "Needs %s." % " or ".join(self.lk.dlc_name(x) for x in d) if d else NOT_AVAILABLE

    def item_state(self, item):
        """(enabled, reason) of an overlay or tool by what the export says about the game being played."""
        if item.get("available") is False:
            return False, self.dlc_reason(item)
        return True, None

    # ---- buildings
    def building(self, ident):
        return self.lk.get("building", ident)

    def menu_groups(self):
        """[(group dict, [building entries])] in the game's build-menu order. Buildings the look-up does not know
        or hides (deprecated, developer) are left out. Without a build menu in the export: one group per
        building category, by name (the export then has no order of its own)."""
        kinds = self.lk.kinds.get("building", {})
        out = []
        if self.menu:
            for g in self.menu:
                rows = [kinds[b] for b in g.get("buildings") or [] if b in kinds and not kinds[b].get("hidden")]
                if rows:
                    out.append((g, rows))
            return out
        cats = {}
        for e in kinds.values():
            if e.get("source") == "mod-export" and not e.get("hidden") and e.get("category") not in (None, "Uncategorized"):
                cats.setdefault(e["category"], []).append(e)
        for cat in sorted(cats, key=str.lower):
            out.append(({"id": cat, "name": cat}, sorted(cats[cat], key=lambda e: (e.get("name") or e["id"]).lower())))
        return out


def research_done(live):
    """Set of completed tech ids over every world of a live.json dict, or None when it does not say."""
    if not isinstance(live, dict):
        return None
    out, seen = set(), False
    for w in live.get("worlds") or []:
        r = w.get("research") if isinstance(w, dict) else None
        if isinstance(r, dict) and isinstance(r.get("completed"), list):
            seen = True
            out.update(x for x in r["completed"] if isinstance(x, str))
    return out if seen else None


def unlock_state(cat, building, live):
    """(unlocked bool, reason text or None) for one building, by the game's own facts.
    Order of trust: live `unlockedBuildings` (the game's rule, refreshed when research finishes), then the
    completed research in live.json against the building's tech, then the export's snapshot."""
    lk = cat.lk
    if building.get("dlcActive") is False:
        return False, cat.dlc_reason(building)
    ids = live.get("unlockedBuildings") if isinstance(live, dict) else None
    tech = building.get("tech")
    if isinstance(ids, list):
        ok = building["id"] in ids
    else:
        done = research_done(live)
        if done is not None:
            ok = not tech or tech in done
        elif "unlocked" in building:
            ok = bool(building["unlocked"])
        else:
            ok = not tech
    if ok:
        return True, None
    name = None
    lr = building.get("lockReason")
    if isinstance(lr, dict):
        name = lr.get("techName")
        tech = tech or lr.get("techId")
    if not name and tech:
        name = lk.name("tech", tech)
    return False, ("Needs research: %s" % name) if name else NOT_RESEARCHED


def build_button(cat, building, live, avail):
    """The Build action of one building: (enabled, reason). avail = live_ok(...) of the game."""
    ok, why = avail
    if not ok:
        return False, why
    unlocked, reason = unlock_state(cat, building, live)
    return (True, None) if unlocked else (False, reason)


# ---- material picker data
def world_stock(live):
    """{element id: kg} of the active world in live.json, or None when the mod does not send stock."""
    if not isinstance(live, dict):
        return None
    wid = live.get("activeWorldId")
    worlds = [w for w in live.get("worlds") or [] if isinstance(w, dict)]
    pick = [w for w in worlds if w.get("id") == wid] or worlds[:1]
    if pick and isinstance(pick[0].get("stock"), dict):
        return {k: v for k, v in pick[0]["stock"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return None


def _n(x):
    """Display number: a whole number as int, else rounded to 2 places."""
    r = round(float(x), 2)
    return int(r) if r == int(r) else r


def slots_of(building):
    return [m for m in building.get("materials") or [] if isinstance(m, dict)]


def picker_slots(cat, building, stock, art_for=None):
    """The picker's slots (blocks.schema PickerSlot dicts). Candidates come from the export in the game's order;
    `haveKg` from the active world's stock. A candidate missing from the stock list (not discovered) is left out, like
    the game's picker; one listed with 0 or too little is shown greyed. When stock is unknown every candidate is
    listed with haveKg 0 and `enabled` true, so the player can still choose (the game decides).
    The pre-selection is the candidate with the most stock that is enabled (the game's default when no earlier
    choice exists); the first listed when stock is unknown; nothing when no candidate is affordable."""
    lk = cat.lk
    out = []
    for m in slots_of(building):
        need = _n(m.get("kg") or 0)
        cands = [c for c in (m.get("candidates") or []) if isinstance(c, str)]
        opts = []
        for c in cands:
            have = None if stock is None else _n(stock.get(c, 0) or 0)
            if stock is not None and c not in stock:
                continue                      # absent from the stock list = not discovered: the game does not offer it
            opts.append({"id": c, "name": lk.name("element", c), "needKg": need,
                         "haveKg": have if have is not None else 0,
                         "enabled": True if have is None else have >= need, "selected": False,
                         "_art": ("element", c)})     # art/decorate.py turns it into `art` (and drops it when there is none)
        best = None
        for o in opts:
            if o["enabled"] and (best is None or (stock is not None and o["haveKg"] > best["haveKg"])):
                best = o
        if best:
            best["selected"] = True
        label = m.get("label") or " or ".join(lk.name_any(t, ("element",)) for t in (m.get("tags") or []))
        slot = {"label": label, "needKg": need, "options": opts}
        if not opts:
            slot["empty"] = "Nothing to build this with has been found yet."
        out.append(slot)
    return out


def validate_materials(cat, building, materials, stock):
    """Raises ValueError(plain text) for a material list the game would not accept."""
    slots = slots_of(building)
    if len(materials) > len(slots):
        raise ValueError("This building has %d material slot%s." % (len(slots), "" if len(slots) == 1 else "s"))
    for i, mat in enumerate(materials):
        cands = slots[i].get("candidates") or []
        if cands and mat not in cands:
            raise ValueError("%s can't be used for %s." % (cat.lk.name("element", mat), slots[i].get("label") or "this slot"))
        if stock is not None and float(stock.get(mat, 0) or 0) < float(slots[i].get("kg") or 0):
            raise ValueError("Not enough %s." % cat.lk.name("element", mat))


# ---- change detection for events
class PadWatch:
    """Compares the parts of live.json the pad and the Build buttons show, so the service can name the events
    `pad` (active overlay, active tool, priority) and `build` (what can be built, game running) only when they
    changed. Event driven: called once per live.json change."""

    def __init__(self, read_live, fresh):
        self.read_live = read_live
        self.fresh = fresh
        self._pad = None
        self._build = None

    @staticmethod
    def _h(obj):
        return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

    def changed(self):
        live = self.read_live()
        if not isinstance(live, dict):
            live = {}
        pad = self._h([live.get("activeOverlay"), live.get("activeTool"), live.get("priority"), bool(self.fresh(live))])
        done = research_done(live)
        build = self._h([live.get("unlockedBuildings"), sorted(done) if done is not None else None,
                         bool(self.fresh(live))])
        names = []
        if pad != self._pad:
            names.append("pad")
        if build != self._build:
            names.append("build")
        self._pad, self._build = pad, build
        return tuple(names)
