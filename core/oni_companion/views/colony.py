"""Colony Screen (GET /colony) and the duplicant page (GET /entry/dupe/<id>).

The overview is short: header, alerts, then one card per duplicant (portrait, three meters, warning
badges only when something is wrong). The page behind a card has everything. Warnings come from the
game's own status items on each duplicant. Only when the mod gave none (live schema 1, a save) does
the fixed table LIMITS apply, and then every warning is labeled "estimated".
"""
import re

from . import alerts as alert_view
from . import blocks as B

NO_COLONY = "No colony found. Start Oxygen Not Included and load a save."
HEADER_ONLY = "Only the save header could be read: name and cycle. Details appear while the game runs."
NO_DUPE = "Not available."

# ---- the one table of fallback limits. Used ONLY when a duplicant has no statusItems.
# Stress is in percent; the others are fractions of the meter's max. Every number is an estimate.
# The mod export may replace any of them: constants["dupeLimits"] = {"stressWarn": 60, ...}.
LIMITS = {
    "stressWarn": 60, "stressDanger": 90,
    "healthWarn": 0.5, "healthDanger": 0.25,
    "caloriesWarn": 0.4, "caloriesDanger": 0.1,
    "breathWarn": 0.5, "breathDanger": 0.25,
}

# ---- how the game's status items become badges (matching on words of the item id and name)
RANK = {"danger": 0, "warn": 1, "info": 2}
SEVERITY_RANK = {"bad": 0, "minorBad": 1, "neutral": 2, "good": 3}
SEVERITY_BADGE = {"bad": "bad", "minorBad": "minor", "good": "good"}
SEVERITY_TONE = {"bad": "bad", "minorBad": "warn", "good": "good"}
CRITICAL_WORDS = ("suffocat", "starv", "incapacitat", "dying", "death", "entomb")
SICK_WORDS = ("sick", "diseas", "infect")
STRESS_WORDS = ("stress",)
HOT_WORDS = ("hot", "overheat", "scald", "hyperthermi", "heatstroke")
COLD_WORDS = ("cold", "freez", "hypotherm", "chill", "frostbit")


def _num(v, default=0.0):
    """A finite number, else default (bad live.json values show 0, like Resources)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return default
    return v


def _dict(v):
    return v if isinstance(v, dict) else {}


def _dicts(v):
    """Only the dict rows of a list; anything else is dropped."""
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _meter_of(v):
    """A meter dict with numeric value and max."""
    m = _dict(v)
    return {"value": _num(m.get("value")), "max": _num(m.get("max"))}


def _words(*texts):
    out = []
    for t in texts:
        t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(t or ""))
        out += [w.lower() for w in re.findall(r"[A-Za-z]+", t)]
    return out


def _has(words, stems):
    return any(w.startswith(st) for w in words for st in stems)


def limits_for(constants):
    """LIMITS with any numeric override from the mod export's constants.dupeLimits."""
    out = dict(LIMITS)
    over = (constants or {}).get("dupeLimits")
    if isinstance(over, dict):
        for k, v in over.items():
            if k in out and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = v
    return out


def _sorted_badges(badges):
    return sorted(badges, key=lambda b: RANK[b["level"]])      # stable: ties keep the game's order


def status_badges(d):
    """Badges from the duplicant's own status items and diseases (worst first)."""
    out, seen = [], set()

    def add(level, label):
        if label not in seen:
            seen.add(label)
            out.append(B.badge_level(level, label))

    for s in _dicts(d.get("statusItems")):
        sev = s.get("severity")
        if sev not in ("bad", "minorBad"):
            continue
        name = s.get("name") or s.get("id") or "Problem"
        w = _words(s.get("id"), name)
        if _has(w, CRITICAL_WORDS):
            add("danger", name)
        elif _has(w, SICK_WORDS):
            add("warn", "Sick")
        elif _has(w, STRESS_WORDS):
            add("warn", "Stressed")
        elif _has(w, HOT_WORDS):
            add("warn", "Too hot")
        elif _has(w, COLD_WORDS):
            add("warn", "Too cold")
        else:
            add("warn" if sev == "bad" else "info", name)
    if d.get("diseases"):
        add("warn", "Sick")
    return _sorted_badges(out)


def _frac(m):
    m = _meter_of(m)
    mx = m["max"]
    return (m["value"] / mx) if mx else None


def estimated_badges(d, limits):
    """Fallback for a duplicant without statusItems. Fixed limits: ESTIMATES, not the game's word."""
    out = []
    stress = d.get("stress")
    if isinstance(stress, (int, float)):
        if stress >= limits["stressDanger"]:
            out.append(B.badge_level("danger", "Stress critical"))
        elif stress >= limits["stressWarn"]:
            out.append(B.badge_level("warn", "Stressed"))
    for key, label_danger, label_warn, lvl_warn in (
            ("health", "Health critical", "Low health", "warn"),
            ("calories", "Starving", "Hungry", "info"),
            ("breath", "Suffocating", "Low air", "warn")):
        f = _frac(d.get(key))
        if f is None:
            continue
        if f <= limits[key + "Danger"]:
            out.append(B.badge_level("danger", label_danger))
        elif f <= limits[key + "Warn"]:
            out.append(B.badge_level(lvl_warn, label_warn))
    return _sorted_badges(out)


def badges_for(d, limits):
    """(badges, estimated). The game's status items win; the table is the fallback."""
    if "statusItems" in d or "diseases" in d:
        return status_badges(d), False
    return estimated_badges(d, limits), True


def _tone_stress(v):
    return "bad" if v >= 80 else ("warn" if v >= 50 else "good")


def _tone_frac(v, mx):
    if not mx:
        return "neutral"
    f = v / mx
    return "good" if f >= 0.6 else ("warn" if f >= 0.3 else "bad")


def _names(lk, kind, ids, limit=8):
    names = [lk.name(kind, i) for i in ids]
    more = len(names) - limit
    return ", ".join(names[:limit]) + (" and %d more" % more if more > 0 else "")


def _dupe_ref(d, art):
    if d.get("id") in (None, ""):
        return None
    r = B.ref("dupe", str(d["id"]))
    if art:
        r["art"] = art
    return r


def _card_tone(badges):
    levels = {b["level"] for b in badges}
    return "bad" if "danger" in levels else ("warn" if "warn" in levels else "good")


MAX_BADGES = 4


def dupe_card(d, limits, art_dupe=None):
    """(card, estimated). Short: portrait, name, task, stress/health/calories, badges."""
    stress = float(_num(d.get("stress")))
    hp, cal = _meter_of(d.get("health")), _meter_of(d.get("calories"))
    meters = [
        B.meter("Stress", stress, 100, "%", _tone_stress(stress)),
        B.meter("Health", hp.get("value", 0), hp.get("max", 0), None, _tone_frac(hp.get("value", 0), hp.get("max", 0))),
        B.meter("Calories", cal.get("value", 0), cal.get("max", 0), "kcal", _tone_frac(cal.get("value", 0), cal.get("max", 0))),
    ]
    badges, est = badges_for(d, limits)
    shown = badges[:MAX_BADGES]
    if len(badges) > MAX_BADGES:
        shown = badges[:MAX_BADGES - 1] + [B.badge_level("info", "+%d more" % (len(badges) - MAX_BADGES + 1))]
    art = art_dupe(d) if art_dupe else None
    card = B.card(d.get("name") or "Duplicant", subtitle=d.get("chore") or "Idle", tone=_card_tone(badges),
                  meters=meters, art=art, badges=shown, ref=_dupe_ref(d, art))
    return card, est, any(b["level"] == "danger" for b in badges)


def dupe_cards(dupes, limits, art_dupe=None):
    """(cards, any_estimated). Cards with a danger badge first; the rest keep the game's order."""
    rows = []
    est_any = False
    for i, d in enumerate(dupes):
        card, est, danger = dupe_card(d, limits, art_dupe)
        est_any = est_any or est
        rows.append((0 if danger else 1, i, card))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows], est_any


def _research_blocks(lk, r):
    out = []
    cur = (r or {}).get("current")
    if cur:
        done = sum((cur.get("points") or {}).values())
        need = sum((cur.get("cost") or {}).values())
        out.append(B.progress("Researching: " + lk.name("tech", cur["tech"]), done, need, "pts"))
    queue = [q for q in (r or {}).get("queue") or [] if not cur or q.get("tech") != cur.get("tech")]
    items = [B.item(lk.name("tech", q["tech"]), lk.ref("tech", q["tech"]), badge="%g pts" % B.num(sum(q.get("cost", {}).values())))
             for q in queue if q.get("tech")]
    if items:
        out.append(B.list_block(items, title="Research queue"))
    if not cur and not items:
        out.append(B.text("Nothing is being researched."))
    done_n = len((r or {}).get("completed") or [])
    if done_n:
        out.append(B.stats([B.stat("Researched", done_n, "techs")]))
    return out


def world_blocks(lk, w, limits=None, art_dupe=None, alert_ctx=None):
    """Blocks for one world. Returns (blocks, any_estimated)."""
    bl, est = [], False
    dupes = w.get("dupes") or []
    dismissing, has_ui = alert_ctx or ((), None)
    bl.append(B.list_block(alert_view.alert_items(w.get("alerts") or [], dismissing, has_ui), title="Alerts", empty="No alerts.", variant="alerts"))
    if dupes:
        cards, est = dupe_cards(dupes, limits or LIMITS, art_dupe)      # est: warnings from fixed limits (not shown to the user)
        bl.append(B.grid(cards, "Duplicants (%d)" % len(dupes)))
    else:
        bl.append(B.list_block([], title="Duplicants", empty="No duplicants in this world."))
    bl += _research_blocks(lk, w.get("research"))
    res_map = w.get("resources")
    if isinstance(res_map, dict) and res_map:        # live schema 1 and saves; schema 2 lists move to the Resources tab
        res = sorted(res_map.items(), key=lambda kv: (-kv[1], kv[0]))
        rows = []
        for k, kg in res[:40]:
            r = lk.ref_any(k, ("element", "food", "medicine"))
            rows.append([B.cell(lk.name_any(k, ("element", "food", "medicine")), r), B.num(kg, 1)])
        inner = [B.table(["Resource", "kg"], rows)]
        if len(res) > 40:
            inner.append(B.text("%d more not shown." % (len(res) - 40)))
        bl.append(B.group("Resources (%d)" % len(res), inner, collapsed=True))
    crit = w.get("critters") or []
    if crit:
        rows = []
        for c in crit:
            r = lk.ref("critter", c["id"])
            rows.append([B.cell(lk.name("critter", c["id"]), r), c.get("count", 0), c.get("tame", 0), c.get("eggs", 0)])
        bl.append(B.group("Critters", [B.table(["Critter", "Count", "Tame", "Eggs"], rows)], collapsed=True))
    pw = w.get("power") or []
    if pw:
        rows = []
        for c in pw:
            over = c.get("overloaded")
            rows.append(["Circuit %s" % c["id"], B.num(c["generatedW"], 0), B.num(c["consumedW"], 0),
                         B.cell("Overloaded", tone="bad") if over else "OK"])
        bl.append(B.group("Power", [B.table(["Circuit", "Made W", "Used W", "State"], rows)], collapsed=True))
    return bl, est


def _state_text(f):
    if f.get("paused"):
        return "Paused"
    sp = f.get("speed")
    return "%dx" % sp if isinstance(sp, int) else "Running"


def _shown_world(worlds, requested, active):
    """The one world the overview shows: the requested one, else the active one, else the first."""
    for want in (requested, active):
        if want is not None:
            for w in worlds:
                if str(w.get("id")) == str(want):
                    return w
    return worlds[0]


def colony_screen(lk, facts, world=None, constants=None, art_dupe=None, alert_ctx=None):
    """facts: the unfiltered Colony.facts(). world: requested world id or None (= the active world)."""
    src = facts.get("source", "none")
    as_of = facts.get("asOf")
    name = facts.get("colonyName") or "Colony"
    if src == "none":
        return B.screen("Colony", [B.notice("info", NO_COLONY)], source="none", as_of=None, back="home",
                        refresh_on=["colony"])
    rows = []
    if facts.get("cycle") is not None:
        rows.append(B.stat("Cycle", facts["cycle"]))
    if facts.get("timeOfDay") is not None:
        rows.append(B.stat("Time of day", "%g%%" % B.num(facts["timeOfDay"] * 100, 0)))
    if src in ("mod-live", "save") and facts.get("speed") is not None:
        rows.append(B.stat("Speed", _state_text(facts)))
    worlds = facts.get("worlds") or []
    bl = []
    if rows:
        bl.append(B.stats(rows))
    sub = "Cycle %s" % facts["cycle"] if facts.get("cycle") is not None else None
    if src == "header":
        bl.append(B.notice("info", HEADER_ONLY))
    switcher = None
    if worlds:
        w = _shown_world(worlds, world, facts.get("activeWorldId"))
        wb, _est = world_blocks(lk, w, limits_for(constants), art_dupe, alert_ctx)
        bl += wb
        sub = (sub + ", " if sub else "") + (w.get("name") or "")
        if len(worlds) > 1 and isinstance(w.get("id"), int):
            switcher = {"active": w["id"], "worlds": [
                {"id": x["id"], "name": x.get("name") or "World %s" % x["id"]}
                for x in worlds if isinstance(x.get("id"), int)]}
    return B.screen(name, bl, subtitle=sub or None, source=src, as_of=as_of, back="home",
                    refresh_on=["colony", "action"] if any(x.get("alerts") for x in worlds) else ["colony"],
                    world_switcher=switcher)


# ---- the duplicant page
def find_dupe(facts, dupe_id):
    for w in facts.get("worlds") or []:
        for d in w.get("dupes") or []:
            if str(d.get("id")) == str(dupe_id):
                return d, w
    return None, None


def _ratio(m, unit=None, places=0):
    m = _meter_of(m)
    fmt = "{:,.%df}" % places
    s = fmt.format(m.get("value", 0))
    if m.get("max"):
        s += " / " + fmt.format(m["max"])
    return s + (" " + unit if unit else "")


def _status_blocks(d, est, badges):
    if est:
        items = [B.item(b["label"], badge="estimated",
                        tone={"danger": "bad", "warn": "warn", "info": "info"}[b["level"]]) for b in badges]
        return [B.list_block(items, empty="Nothing wrong (estimated).")]
    sitems = sorted(_dicts(d.get("statusItems")), key=lambda s: SEVERITY_RANK.get(s.get("severity"), 2))
    items = [B.item(s.get("name") or s.get("id"), badge=SEVERITY_BADGE.get(s.get("severity")),
                    tone=SEVERITY_TONE.get(s.get("severity"))) for s in sitems]
    dis = [B.item(x.get("name") or x.get("id"), tone="bad") for x in _dicts(d.get("diseases"))]
    return [B.list_block(items, empty="Nothing wrong."), B.list_block(dis, title="Diseases", empty="Healthy.")]


def dupe_screen(lk, facts, dupe_id, zoom_on_select=False, constants=None, art_dupe=None):
    """The complete page for one live duplicant, or None when the id is unknown."""
    d, w = find_dupe(facts, dupe_id)
    if d is None:
        return None
    limits = limits_for(constants)
    badges, est = badges_for(d, limits)
    art = art_dupe(d) if art_dupe else None
    name = d.get("name") or "Duplicant"
    args = {"target": {"kind": "dupe", "id": str(d.get("id"))}, "select": True}
    live = facts.get("source") == "mod-live"
    bl = []
    if art:
        bl.append(B.image(art, caption=name, size="large"))
    bl.append(B.list_block([{
        "title": "Show in game",
        "subtitle": "Moves the game camera once" if live else "Needs the game running",
        "actions": [B.action("focus", "Show in game", args)]}]))
    stress = float(_num(d.get("stress")))
    hp, cal, br = _meter_of(d.get("health")), _meter_of(d.get("calories")), _meter_of(d.get("breath"))
    mrows = [
        B.stat("Stress", "%g%%" % B.num(stress, 0), tone=_tone_stress(stress)),
        B.stat("Health", _ratio(hp), tone=_tone_frac(hp.get("value", 0), hp.get("max", 0))),
        B.stat("Calories", _ratio(cal, "kcal"), tone=_tone_frac(cal.get("value", 0), cal.get("max", 0))),
    ]
    if d.get("breath") and isinstance(d.get("breath"), dict):
        mrows.append(B.stat("Breath", _ratio(br)))
    if d.get("bladder") is not None:
        mrows.append(B.stat("Bladder", "%g%%" % B.num(_num(d["bladder"]), 0)))
    if isinstance(d.get("stamina"), dict) and d["stamina"]:
        mrows.append(B.stat("Stamina", _ratio(d["stamina"])))
    if d.get("bodyTempC") is not None:
        mrows.append(B.stat("Body temperature", "%.1f C" % _num(d["bodyTempC"])))
    bl.append(B.group("Meters", [B.stats(mrows)]))
    bl.append(B.group("Status", _status_blocks(d, est, badges)))
    traits = [t for t in d.get("traits") or [] if isinstance(t, str)] if isinstance(d.get("traits"), list) else []
    skills = [t for t in d.get("skills") or [] if isinstance(t, str)] if isinstance(d.get("skills"), list) else []
    if traits:
        bl.append(B.heading("Traits", 2))
        bl.append(B.chips([B.chip(lk.name("trait", t), "category", lk.ref("trait", t)) for t in traits]))
    if skills:
        bl.append(B.heading("Skills", 2))
        bl.append(B.chips([B.chip(lk.name("skill", t), None, lk.ref("skill", t)) for t in skills]))
    attrs = _dicts(d.get("attributes"))
    if attrs:
        bl.append(B.table(["Attribute", "Value"], [[a.get("name") or a.get("id"), B.num(a.get("value"), 1)] for a in attrs],
                          title="Attributes"))
    m = _dict(d.get("morale"))
    if m:
        mv, mr = _num(m.get("value")), _num(m.get("required"))
        # the game's names: Morale, and Morale Need ("how high Morale must be kept to prevent them from gaining Stress")
        bl.append(B.stats([B.stat("Morale", B.num(mv, 1), tone="good" if mv >= mr else "warn",
                                  hint="Below the need: gaining stress" if mv < mr else None),
                           B.stat("Morale Need", B.num(mr, 1), hint="Keep Morale at least this high to prevent Stress")],
                          title="Morale"))
    on_open = [{"action": "focus", "args": args}] if zoom_on_select else None
    return B.screen(name, bl, subtitle=d.get("chore") or "Idle", source=facts.get("source"), as_of=facts.get("asOf"),
                    back="home", refresh_on=["colony"], on_open=on_open)
