"""Buildings (v1.3): the Buildings tab (GET /buildings), the Build button and material picker of a building
page, and the Automation and Research sections of a building page.

The groups, their order and their names are the game's own build menu (export `buildMenu`). A building's
Build button is enabled by the game's own unlock rule (pad.unlock_state) AND by having enough of some material for
every slot (the same check as the picker, user request 2026-10-25); it says why when it is not.
Pages other than Settings never mention the mod.
"""
from .. import pad as P
from . import blocks as B

NO_MENU = "The build menu is not available yet. See Settings."


def build_action(cat, building, live, avail, materials=None, stock=None, slots=None):
    """The Build button of one building (Action dict): unlocked, and some material affordable in every slot.
    `slots` (picker slots) are computed here unless the caller already has them."""
    ok, reason = P.build_button(cat, building, live, avail)
    a = B.action("build_select", "Build", {"buildingId": building["id"]})
    if not ok:
        a["enabled"] = False
        a["reason"] = reason
        return a
    if slots is None and avail[0] and any(m.get("candidates") for m in P.slots_of(building)):
        slots = P.picker_slots(cat, building, stock if stock is not None else P.world_stock(live))
    for sl in slots or []:
        if not any(o.get("selected") for o in sl["options"]):
            a["enabled"] = False
            a["reason"] = ("Not enough %s." % sl["options"][0]["name"]) if len(sl["options"]) == 1 else \
                ("Not enough %s." % sl["label"]) if sl["options"] else ("No %s found yet." % sl["label"]) if sl.get("label") \
                else sl.get("empty") or "Not enough material."
            break
    return a


def buildings_screen(cat, live, avail):
    lk = cat.lk
    groups = cat.menu_groups()
    if not groups:
        return B.screen("Buildings", [B.notice("info", NO_MENU)], source="none", refresh_on=["gamedata", "status"])
    bl = []
    total = 0
    stock = P.world_stock(live) if avail[0] else None
    for i, (g, rows) in enumerate(groups):
        items = []
        for e in rows:
            act = build_action(cat, e, live, avail, stock=stock)
            sub = act.get("reason") if act.get("enabled") is False and avail[0] else None
            items.append(B.item(e.get("name") or e["id"], B.ref("building", e["id"]), subtitle=sub,
                                badge=lk.dlc_badge(e), art_key=None))
            items[-1]["actions"] = [act]
        total += len(items)
        bl.append(B.group("%s (%d)" % (g.get("name") or g["id"], len(items)), [B.list_block(items)], collapsed=i > 0))
    src = "mod-export" if lk.meta.get("exportFiles") else "yaml"
    scr = B.screen("Buildings", bl, subtitle="%d buildings" % total, source=src, as_of=lk.as_of,
                   refresh_on=["build", "gamedata", "status"])
    scr["filter"] = {"placeholder": "Search buildings"}
    return scr


def in_menu(cat, building_id):
    return any(building_id in (g.get("buildings") or []) for g in cat.menu)


def build_blocks(cat, building, live, avail):
    """The Build button, with the material picker when the building has material slots the game lets the player
    choose. Empty when the building is not in the build menu."""
    if not in_menu(cat, building["id"]):
        return []
    stock = P.world_stock(live) if avail[0] else None
    slots = P.picker_slots(cat, building, stock) if any(m.get("candidates") for m in P.slots_of(building)) else []
    act = build_action(cat, building, live, avail, stock=stock, slots=slots)
    if slots:
        pk = {"type": "picker", "title": "Build with", "slots": slots, "action": act}
        return [pk]
    return [B.list_block([_row(building, act)])]


def _row(building, act):
    it = B.item(building.get("name") or building["id"], subtitle=act.get("reason") if act.get("enabled") is False else None)
    it["actions"] = [act]
    return it


# ---- Automation
SIGNAL_WORDS = {"positive": "green signal", "negative": "red signal"}


def _signal_text(label, txt, color):
    """The game's text as is when it already names the signal ("Green Signal: Open"); else "Green signal: ..."."""
    if SIGNAL_WORDS[color] in txt.lower():
        s = B.plain(txt)
    else:
        s = B.plain("%s: %s" % (label, txt))
    s["color"] = color
    return s


def automation_blocks(e, lk=None):
    """Group 'Automation': one entry per logic port the game names, with what a green and a red signal mean.
    The export carries the texts; for an older export a building with one port and one set of the game's own
    strings uses those. Hidden when there is nothing to say; a port without texts is not listed."""
    ports = [dict(p) for p in e.get("ports") or [] if p.get("kind") == "logic"]
    if len(ports) == 1 and not any(ports[0].get(k) for k in ("name", "description", "greenText", "redText")) and lk:
        texts = lk.logic_texts(e["id"])
        if len(texts) == 1:
            ports[0].update(name=texts[0][0], greenText=texts[0][1], redText=texts[0][2])
    blocks = []
    for p in ports:
        name, desc = p.get("name"), p.get("description")
        green, red = p.get("greenText"), p.get("redText")
        if not (name or desc or green or red):
            continue
        direction = "Input" if p.get("direction") == "in" else "Output"
        spans = [B.bold(name or "Automation %s" % direction.lower())]
        if desc:
            spans.append(B.plain("\n" + desc))
        blocks.append(B.text(*spans))
        for label, txt, color in (("Green signal", green, "positive"), ("Red signal", red, "negative")):
            if txt:
                blocks.append(B.text(_signal_text(label, txt, color)))
    return [B.group("Automation", blocks)] if blocks else []


# ---- Research
def _cost_text(lk, tech):
    parts = []
    order = list(lk.research_types)          # the game's own order of research types
    for rt, pts in sorted((tech.get("cost") or {}).items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0])):
        if isinstance(pts, (int, float)) and pts:
            parts.append("%s %s" % (B.num(pts), lk.research_types.get(rt, rt)))
    return ", ".join(parts)


def research_blocks(lk, e, tech_ids):
    """Group 'Research': the tech's display name, linked to its entry, with its cost. Hidden when there is none."""
    items = []
    for tid in tech_ids:
        t = lk.get("tech", tid)
        if t:
            items.append(B.item(t.get("name") or t["id"], B.ref("tech", t["id"]), subtitle=_cost_text(lk, t) or None,
                                badge=lk.dlc_badge(t)))
    lr = e.get("lockReason")
    if not items and isinstance(lr, dict) and lr.get("techName"):
        items.append(B.item(lr["techName"], subtitle=_cost_text(lk, lr) or None))
    return [B.group("Research", [B.list_block(items)])] if items else []
