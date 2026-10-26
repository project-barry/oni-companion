"""Entry Screens: one per kind (contracts/api.md GET /entry/<kind>/<id>)."""
import re
from urllib.parse import quote

from . import blocks as B
from . import buildings as buildings_view
from . import fmt
from .lookup import ITEM_KINDS, SINGULAR

WIKI = "https://oxygennotincluded.wiki.gg/wiki/"
NEED_MOD = "Numbers appear once a game has run."
NO_NUMBERS = "No numbers for this yet. Start a game once and they appear here."
MAX_REL = 50

ROLE_TEXT = {
    "converter": "Building", "recipe": "Recipe", "diet": "Critter diet", "drop": "Critter drop",
    "irrigation": "Plant irrigation", "fertilizer": "Plant fertilizer", "yield": "Plant yield",
    "geyser": "Geyser", "transition": "Phase change", "material": "Building material",
}


def _words(tag):
    """'EmitsLight' -> 'Emits Light'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tag)


def wiki_url(name):
    return WIKI + quote(name.strip().replace(" ", "_"), safe="_-,.()'!")


# ---- shared pieces
def dlc_chips(lk, e):
    if e.get("dlcKnown") is False:
        return [B.chip("DLC not known", "dlc")]
    out = [B.chip(lk.dlc_name(d), "dlc") for d in e.get("dlc") or []]
    if not out and not e.get("dlcAny"):
        out.append(B.chip("Base game", "dlc"))
    for d in e.get("dlcAny") or []:
        out.append(B.chip("Any of: " + lk.dlc_name(d), "dlc"))
    return out


def text_blocks(*texts):
    out = []
    for t in texts:
        for p in fmt.paragraphs(t):
            out.append(B.text(p))
    return out


def amount_ref(lk, a):
    if a.get("element"):
        return lk.ref_any(a["element"])
    return None


def amount_label(lk, a):
    if a.get("element"):
        return lk.name_any(a["element"])
    return str(a.get("tag") or "Item")


def port_from_amount(lk, a, note=None, scale=1.0, unit="kg"):
    """Port label is the item name; the element Ref makes it tappable."""
    temp = "At %s" % fmt.c(a["tempC"]) if a.get("tempC") is not None else None
    n = "; ".join(x for x in (note, temp) if x) or None
    return B.port(amount_label(lk, a), element=amount_ref(lk, a), rate=(a.get("kg") or 0) * scale, unit=unit, note=n)


def ports_from_amounts(lk, ins, outs, scale=1.0, unit="kg", title=None):
    pin = [port_from_amount(lk, a, None, scale, unit) for a in ins or []]
    pout = [port_from_amount(lk, a, None, scale, unit) for a in outs or []]
    return B.ports(pin, pout, title=title)


def relation_blocks(lk, kind, e):
    out = []
    for which, title in (("produced", "Produced by"), ("used", "Used by")):
        rows = lk.item_relations(which, kind, e["id"])
        if not rows:
            continue
        items = []
        for r in rows[:MAX_REL]:
            sub = ROLE_TEXT.get(r["role"], r["role"].title())
            if r.get("viaTag"):
                sub += ", by tag " + r["viaTag"]
            badge = ("%g kg" % B.num(r["kg"], 3)) if r.get("kg") else lk.dlc_badge(r)
            items.append(B.item(r["name"], B.ref(r["kind"], r["id"]), sub, badge))
        inner = [B.list_block(items)]
        if len(rows) > MAX_REL:
            inner.append(B.text("%d more not shown." % (len(rows) - MAX_REL)))
        out.append(B.group("%s (%d)" % (title, len(rows)), inner, collapsed=len(rows) > 8))
    return out


def ref_list(lk, kind, ids, title, collapsed=None):
    items = []
    for i in ids:
        r = lk.ref(kind, i)
        if r:
            items.append(B.item(lk.name(kind, i), r, badge=lk.dlc_badge(lk.get(kind, i))))
    return B.group(title, [B.list_block(items)], collapsed=collapsed) if items else None


def guide_block(lk, kind, e):
    """Link to the codex entry that has the same id, if there is one."""
    if kind == "codex":
        return None
    for cid in (e["id"], e["id"].replace("_", "")):
        r = lk.ref("codex", cid)
        if r:
            return B.list_block([B.item(lk.name("codex", r["id"]), r, "Guide")], title="In the codex")
    return None


# ---- per kind
def build_element(lk, e):
    bl = [B.chips(dlc_chips(lk, e) + [B.chip((e.get("state") or "solid").capitalize(), "state")]
                  + [B.chip(_words(t), "category") for t in (e.get("tags") or [])[:6]])]
    bl += text_blocks(e.get("desc"))
    rows = []
    for key, label, unit in (("specificHeat", "Specific heat", "DTU/g/K"),
                             ("thermalConductivity", "Thermal conductivity", "W/m/K"),
                             ("molarMass", "Molar mass", None), ("maxMass", "Max mass per tile", "kg"),
                             ("hardness", "Hardness", None)):
        if isinstance(e.get(key), (int, float)):
            rows.append(B.stat(label, B.num(e[key], 3), unit))
    if rows:
        bl.append(B.stats(rows, "Properties"))
    lo, hi = e.get("lowTransition"), e.get("highTransition")
    if lo or hi:
        states = []

        def tgt_state(t):
            te = lk.get("element", t["target"])
            return (te or {}).get("state") or "solid", lk.name("element", t["target"]), lk.ref("element", t["target"])
        if lo:
            s, n, r = tgt_state(lo)
            states.append(B.phase_state(s, n, "below %s" % fmt.c(lo["tempC"]), None, lo["tempC"], r))
        st = e.get("state") or "solid"
        states.append(B.phase_state(st, e["name"], fmt.c_range(lo["tempC"] if lo else None, hi["tempC"] if hi else None),
                                    lo["tempC"] if lo else None, hi["tempC"] if hi else None))
        if hi:
            s, n, r = tgt_state(hi)
            states.append(B.phase_state(s, n, "above %s" % fmt.c(hi["tempC"]), hi["tempC"], None, r))
        bl.append(B.phases(states, "State changes"))
    return bl


def build_menu_name(cat):
    """The game's build-menu tab of a building, as a plain name ("Uncategorized" = in no tab)."""
    return "None (not buildable from a menu)" if cat == "Uncategorized" else str(cat)


def build_building(lk, e, bctx=None):
    bl = [B.chips(dlc_chips(lk, e))]      # the build-menu category is a stat, not a chip next to "Base game"
    bl += text_blocks(e.get("desc"), e.get("effect"))
    if e.get("source") != "mod-export":
        bl.append(B.notice("info", NO_NUMBERS))
        return bl
    if bctx:                               # v1.3: the Build button, with the material picker
        bl += buildings_view.build_blocks(bctx["cat"], e, bctx["live"], bctx["avail"])
    rows = []
    if e.get("category"):
        menu_name = None
        for g in (bctx["cat"].menu if bctx else []):
            if g.get("id") == e["category"] and g.get("name"):
                menu_name = g["name"]
        rows.append(B.stat("Build menu", menu_name or build_menu_name(e["category"])))
    sz = e.get("size")
    if sz:
        rows.append(B.stat("Size", "%d x %d" % (sz["w"], sz["h"]), "tiles"))
    if e.get("hp") is not None:
        rows.append(B.stat("Hit points", B.num(e["hp"])))
    if e.get("buildTimeS") is not None:
        rows.append(B.stat("Build time", B.num(e["buildTimeS"], 1), "s"))
    for key, label in (("decor", "Decor"), ("noise", "Noise")):
        d = e.get(key)
        if d:
            rows.append(B.stat(label, "%+g" % B.num(d["value"], 1), None, "Radius %g tiles" % B.num(d["radius"], 1)))
    pw = e.get("power") or {}
    if pw.get("usesW") is not None:
        rows.append(B.stat("Power use", B.num(pw["usesW"]), "W", "While running"))
    if pw.get("generatesW") is not None:
        rows.append(B.stat("Power made", B.num(pw["generatesW"]), "W"))
    ht = e.get("heat") or {}
    if ht.get("exhaustKDtuPerS") is not None:
        rows.append(B.stat("Heat to the air", B.num(ht["exhaustKDtuPerS"], 3), "kDTU/s"))
    if ht.get("selfKDtuPerS") is not None:
        rows.append(B.stat("Self heat", B.num(ht["selfKDtuPerS"], 3), "kDTU/s"))
    if e.get("overheatC") is not None:
        rows.append(B.stat("Overheats at", B.num(e["overheatC"], 1), "C"))
    # The default storage capacity is an internal number the game's building card does not present as a stat.
    if rows:
        bl.append(B.stats(rows, "Basics"))
    mats = e.get("materials") or []
    if mats and not any(b.get("type") == "picker" for b in bl):        # the picker shows the same amounts
        trows = []
        for m in mats:
            tags = m.get("tags") or []
            r = lk.ref_any(tags[0], ("element",)) if len(tags) == 1 else None
            label = " or ".join(lk.name_any(t, ("element",)) for t in tags)
            trows.append([B.cell(label, r), B.num(m.get("kg"), 2)])
        bl.append(B.table(["Material", "kg"], trows, "Build with"))
    ins, outs = [], []
    for conv in e.get("converters") or []:
        for a in conv.get("inputs") or []:
            ins.append(port_from_amount(lk, a, None, 1000.0, "g/s"))
        for a in conv.get("outputs") or []:
            outs.append(port_from_amount(lk, a, None, 1000.0, "g/s"))
    have_power = False
    covered = set()                        # (conduit kind, direction) a converter already names with an element
    for conv in e.get("converters") or []:
        for dirn, amts in (("in", conv.get("inputs")), ("out", conv.get("outputs"))):
            for a in amts or []:
                st = (lk.get("element", a.get("element")) or {}).get("state") if a.get("element") else None
                if st:
                    covered.add((st, dirn))
    for p in e.get("ports") or []:
        kind, d = p["kind"], p["direction"]
        if kind == "logic":
            continue                       # automation ports have their own section
        if (kind, d) in covered:
            continue                       # "Water 1000 g/s" says more than "Liquid in 1000 g/s"
        label = "%s %s" % (kind.capitalize(), "in" if d == "in" else "out")
        if kind == "power":
            have_power = True
            rate, unit = p.get("maxW"), "W"
        elif kind == "logic":
            rate, unit = None, None
        else:
            rate = None if p.get("maxKgPerS") is None else p["maxKgPerS"] * 1000.0
            unit = "g/s"
        (ins if d == "in" else outs).append(B.port(label, rate=rate, unit=unit, conduit=kind,
                                                    note="Max rate" if rate is not None else None))
    if not have_power:
        if pw.get("usesW"):
            ins.append(B.port("Power", rate=pw["usesW"], unit="W", conduit="power"))
        if pw.get("generatesW"):
            outs.append(B.port("Power", rate=pw["generatesW"], unit="W", conduit="power"))
    if ins or outs:
        bl.append(B.ports(ins, outs, "Flow"))
    bl += buildings_view.automation_blocks(e, lk)
    techs = lk.reverse()["unlocked_by"].get(("building", e["id"].upper()), [])
    bl += buildings_view.research_blocks(lk, e, techs)
    g = ref_list(lk, "recipe", lk.reverse()["recipes_at"].get(e["id"].upper(), []), "Makes", collapsed=True)
    if g:
        bl.append(g)
    return bl


def _temp_stats(e, rows):
    t = e.get("temperatureC") or {}
    if "idealLo" in t or "idealHi" in t:
        rows.append(B.stat("Ideal temperature", fmt.c_range(t.get("idealLo"), t.get("idealHi"))))
    if "lethalLo" in t or "lethalHi" in t:
        rows.append(B.stat("Dies outside", fmt.c_range(t.get("lethalLo"), t.get("lethalHi")), None, None, None, "bad"))


def build_critter(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"))
    rows = []
    if e.get("lifespanCycles") is not None:
        rows.append(B.stat("Lifespan", B.num(e["lifespanCycles"], 1), "cycles"))
    _temp_stats(e, rows)
    egg = e.get("egg") or {}
    if egg.get("id"):
        rows.append(B.stat("Egg", lk.name_any(egg["id"]), None,
                           "Hatches in %g cycles" % B.num(egg["incubationCycles"], 1) if egg.get("incubationCycles") is not None else None,
                           lk.ref_any(egg["id"])))
    if rows:
        bl.append(B.stats(rows, "Basics"))
    diets = e.get("diets") or []
    for i, d in enumerate(diets, 1):
        pb = ports_from_amounts(lk, d.get("consumes"), d.get("produces"), unit="kg/cycle",
                                title="Diet %d" % i if len(diets) > 1 else "Diet")
        if d.get("caloriesPerCycle") is not None:
            pb["inputs"].append(B.port("Calories", rate=d["caloriesPerCycle"], unit="kcal/cycle"))
        bl.append(pb)
    if e.get("drops"):
        bl.append(B.ports([], [port_from_amount(lk, a, None, 1.0, "kg") for a in e["drops"]], "Drops when it dies"))
    g = ref_list(lk, "critter", e.get("morphs") or [], "Morphs", collapsed=True)
    if g:
        bl.append(g)
    return bl


def build_plant(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"))
    rows = []
    if e.get("growthCycles") is not None:
        rows.append(B.stat("Grows in", B.num(e["growthCycles"], 2), "cycles"))
    _temp_stats(e, rows)
    pr = fmt.minmax(e.get("pressureKg"))
    if pr:
        rows.append(B.stat("Air pressure", pr, "kg"))
    if e.get("lightLux") is not None:
        rows.append(B.stat("Light", B.num(e["lightLux"]), "lux"))
    atm = e.get("atmosphere")
    if atm is not None:
        rows.append(B.stat("Air", ", ".join(lk.name_any(a) for a in atm) if atm else "Any"))
    if rows:
        bl.append(B.stats(rows, "Basics"))
    ins = [port_from_amount(lk, a, "Irrigation", 1.0, "kg") for a in e.get("irrigation") or []]
    ins += [port_from_amount(lk, a, "Fertilizer", 1.0, "kg") for a in e.get("fertilizer") or []]
    outs = [port_from_amount(lk, a, None, 1.0, "kg") for a in e.get("yield") or []]
    if ins or outs:
        bl.append(B.ports(ins, outs, "Needs and yield"))
    return bl


def build_geyser(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"))
    rows = []
    if e.get("element"):
        rows.append(B.stat("Spits", lk.name_any(e["element"]), None, None, lk.ref_any(e["element"])))
    if e.get("tempC") is not None:
        rows.append(B.stat("Temperature", B.num(e["tempC"], 1), "C"))
    rate = fmt.minmax(e.get("rateKgPerS"), 1000.0, 1)
    if rate:
        rows.append(B.stat("Output while erupting", rate, "g/s"))
    it = fmt.minmax(e.get("eruptionIterationS"), 1.0, 0)
    if it:
        rows.append(B.stat("One cycle of erupt and rest", it, "s"))
    fr = e.get("eruptDurationFraction")
    if fr:
        rows.append(B.stat("Erupting share", fmt.minmax(fr, 100.0, 0), "%"))
    for key, label in (("activeCycles", "Active for"), ("dormantCycles", "Dormant for")):
        v = fmt.minmax(e.get(key), 1.0, 1)
        if v:
            rows.append(B.stat(label, v, "cycles"))
    af = fmt.minmax(e.get("activeFractionOfYear"), 100.0, 0)
    if af:
        rows.append(B.stat("Active share of the year", af, "%"))
    if rows:
        bl.append(B.stats(rows, "Basics"))
    elif e.get("source") != "mod-export":
        bl.append(B.notice("info", NO_NUMBERS))
    return bl


def build_food(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"))
    if e.get("kcal") is None:
        bl.append(B.notice("info", NO_NUMBERS))
        return bl
    rows = [B.stat("Calories", B.num(e["kcal"], 1), "kcal")]
    if e.get("quality") is not None:
        rows.append(B.stat("Quality", e["quality"]))
    rows.append(B.stat("Spoils in", fmt.seconds(e.get("spoilTimeS"))))
    bl.append(B.stats(rows, "Basics"))
    if e.get("effects"):
        bl.append(B.list_block([B.item(str(x)) for x in e["effects"]], title="Effects"))
    return bl


def build_medicine(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"), e.get("effect"))
    if e.get("cures"):
        bl.append(B.list_block([B.item(str(x)) for x in e["cures"]], title="Cures"))
    return bl


def build_recipe(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    rows = []
    fab = e.get("fabricator")
    if fab:
        rows.append(B.stat("Made at", lk.name("building", fab), None, None, lk.ref("building", fab)))
    if e.get("timeS") is not None:
        rows.append(B.stat("Time", B.num(e["timeS"], 1), "s"))
    if rows:
        bl.append(B.stats(rows, "Basics"))
    bl.append(ports_from_amounts(lk, e.get("inputs"), e.get("outputs"), title="Recipe"))
    return bl


def build_tech(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"))
    cost = e.get("cost") or {}
    if cost:
        bl.append(B.table(["Research type", "Points"],
                          [[lk.research_types.get(k, k), B.num(v)] for k, v in sorted(cost.items())], "Cost"))
    g = ref_list(lk, "tech", e.get("requires") or [], "Needs first")
    if g:
        bl.append(g)
    g = ref_list(lk, "tech", lk.reverse()["required_by"].get(e["id"].upper(), []), "Leads to", collapsed=True)
    if g:
        bl.append(g)
    unl = []
    for u in e.get("unlocks") or []:
        r = lk.ref(u.get("kind"), u.get("id")) if isinstance(u, dict) else None
        if r:
            unl.append(B.item(lk.name(r["kind"], r["id"]), r, SINGULAR.get(r["kind"], r["kind"]),
                              lk.dlc_badge(lk.get(r["kind"], r["id"]))))
    if unl:
        bl.append(B.group("Unlocks (%d)" % len(unl), [B.list_block(unl)], collapsed=len(unl) > 8))
    return bl


def build_trait(lk, e):
    chips_ = dlc_chips(lk, e)
    if e.get("kind"):
        chips_.append(B.chip(str(e["kind"]).capitalize(), "category"))
    return [B.chips(chips_)] + text_blocks(e.get("desc"))


def build_skill(lk, e):
    bl = [B.chips(dlc_chips(lk, e) + ([B.chip(str(e["group"]), "category")] if e.get("group") else []))]
    bl += text_blocks(e.get("desc"))
    if e.get("tier") is not None:
        bl.append(B.stats([B.stat("Tier", e["tier"])]))
    g = ref_list(lk, "skill", e.get("requires") or [], "Needs first")
    if g:
        bl.append(g)
    if e.get("unlocks"):
        bl.append(B.list_block([B.item(str(x)) for x in e["unlocks"]], title="Unlocks"))
    return bl


def build_room(lk, e):
    bl = [B.chips(dlc_chips(lk, e))]
    bl += text_blocks(e.get("desc"), e.get("effect"))
    sr = e.get("sizeRange") or {}
    if sr:
        bl.append(B.stats([B.stat("Size", fmt.minmax({"min": sr.get("minTiles"), "max": sr.get("maxTiles")}, 1, 0), "tiles")]))
    if e.get("requirements"):
        bl.append(B.list_block([B.item(str(x)) for x in e["requirements"]], title="Needs"))
    if e.get("effects"):
        bl.append(B.list_block([B.item(str(x)) for x in e["effects"]], title="Effects"))
    return bl


def build_codex(lk, e):
    chips_ = dlc_chips(lk, e)
    if e.get("category"):
        chips_.append(B.chip(str(e["category"]), "category"))
    bl = [B.chips(chips_)]
    paras = e.get("paragraphs") or []
    skip_title = bool(paras) and paras[0].get("style") == "Title" and paras[0].get("text") == e["name"]
    for i, p in enumerate(paras):
        t = p.get("text") or ""
        if not t:
            continue
        st = p.get("style")
        if st == "Title":
            if i == 0 and skip_title:
                continue
            bl.append(B.heading(t, 2))
        elif st == "Subtitle":
            bl.append(B.heading(t, 3))
        elif st == "Warning":
            bl.append(B.notice("warn", t))
        else:
            bl.append(B.text(t))
    items = []
    for lid in e.get("links") or []:
        r = None
        for k in ("codex",) + tuple(ITEM_KINDS) + ("tech", "trait", "skill", "room", "geyser"):
            r = lk.ref(k, lid)
            if r:
                break
        if r and r != B.ref("codex", e["id"]):
            items.append(B.item(lk.name(r["kind"], r["id"]), r, SINGULAR.get(r["kind"], r["kind"])))
    if items:
        bl.append(B.group("Related (%d)" % len(items), [B.list_block(items)], collapsed=len(items) > 6))
    if e.get("parent"):
        pr = lk.ref("codex", e["parent"])
        if pr:
            bl.append(B.list_block([B.item(lk.name("codex", pr["id"]), pr)], title="Part of"))
    return bl


BUILDERS = {
    "element": build_element, "building": build_building, "critter": build_critter, "plant": build_plant,
    "geyser": build_geyser, "food": build_food, "medicine": build_medicine, "recipe": build_recipe,
    "tech": build_tech, "trait": build_trait, "skill": build_skill, "room": build_room, "codex": build_codex,
}
REL_KINDS = ("element", "food", "medicine", "building", "plant", "critter")


def _has_build_action(b):
    if b.get("type") == "picker":
        return True
    return b.get("type") == "list" and any(a.get("id") == "build_select" for i in b.get("items") or [] for a in i.get("actions") or [])


def entry_screen(lk, kind, e, bctx=None):
    """bctx (buildings only, v1.3): {cat, live, avail} for the Build button and the material picker."""
    bl = BUILDERS[kind](lk, e, bctx) if kind == "building" else BUILDERS[kind](lk, e)
    if kind in REL_KINDS:
        bl += relation_blocks(lk, kind, e)
    g = guide_block(lk, kind, e)
    if g:
        bl.append(g)
    name = e.get("name") or e["id"]
    bl.append(B.link("Open on the ONI wiki", wiki_url(name)))
    src = "mod-export" if e.get("source") == "mod-export" else "yaml"
    refresh = ["gamedata"]
    if bctx and any(_has_build_action(b) for b in bl):
        refresh += ["build"] + (["colony"] if any(b.get("type") == "picker" for b in bl) else [])
    return B.screen(name, bl, subtitle=SINGULAR.get(kind, kind.title()), source=src, as_of=lk.as_of,
                    back="home", refresh_on=refresh)
