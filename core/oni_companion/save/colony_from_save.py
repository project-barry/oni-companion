"""Colony facts from an ONI save file.

colony_from_save(path) returns a dict:

    {
      "source":  "save" | "header",   # "header" = body unreadable, header facts only
      "asOf":    ISO time (file modification time),
      "level":   "full" | "header",
      "warnings": [str, ...],
      "header":  {build, saveVersion, cycle, colonyName, ...},
      "live":    dict shaped like contracts/mod-live.schema.json (schema 1),
      "research": {"completed": [...], "inProgress": [...], "points": {...},
                   "activeTech": str|None},
      "deadDupes": [name, ...],
    }

`live` is what the mod would have written, so the colony views can use one
code path for both sources. A save holds no pause state, speed, alerts or
current task, so the live block says paused=True, speed=1, alerts=[] and
chore=None; the real values come from the mod when it is running.

Fallback: an unknown major version, a damaged body or a layout this reader
does not know gives level "header" (cycle, colony name, DLC, dupe count) and
a warning instead of an exception. Only a file that is not a save at all
raises SaveFormatError.
"""

import datetime
import os
import re
import struct

from .header import SaveFormatError, parse_header
from .kserial import KSerialError, Reader, read_body, split_save

KNOWN_MAJOR = 7
TESTED_MINOR = 38  # newest save version checked against real files

CYCLE_SECONDS = 600.0

# The save stores current amounts only. These maxima are the game's normal
# ones (assumed, not read from the file): health and breath 100 and
# calories 4,000 kcal. Traits and equipment can change them in game.
HEALTH_MAX = 100.0
BREATH_MAX = 100.0
CALORIES_MAX_KCAL = 4000.0
CALORIES_PER_KCAL = 1000.0  # the save counts calories, the UI shows kcal

_DEATH_STATE = re.compile(rb"DeathMonitor\+Instance\xff\xff\xff\xff(.{4})", re.S)


def sdbm_lower(text):
    """The game's string hash (Hash.SDBMLower), signed 32-bit."""
    h = 0
    for ch in text.lower():
        h = (ord(ch) + (h << 6) + (h << 16) - h) & 0xFFFFFFFF
    return h - (1 << 32) if h >= (1 << 31) else h


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _header_summary(h):
    return {
        "build": h.build,
        "saveVersion": list(h.save_version),
        "cycle": h.cycle,
        "colonyName": h.colony_name,
        "colonyGuid": h.colony_guid,
        "clusterId": h.cluster_id,
        "dlcIds": h.dlc_ids,
        "dupeCount": h.dupe_count,
        "isAutoSave": h.is_autosave,
    }


def _live_from_header(h, written_at):
    live = {
        "schema": 1, "seq": 1, "state": "running", "writtenAt": written_at,
        "modVersion": "save",
        "build": h.build, "dlcIds": h.dlc_ids,
        "colonyName": h.colony_name, "colonyGuid": h.colony_guid,
        "cycle": h.cycle, "timeOfDay": 0.0, "paused": True, "speed": 1,
        "activeWorldId": 0, "worlds": [],
    }
    return live


def pretty_world_name(key):
    """'STRINGS.WORLDS.SANDSTONE_DEFAULT.NAME' -> 'Sandstone Default' (fallback only)."""
    if not key:
        return "Colony"
    parts = key.split(".")
    core = parts[-2] if len(parts) >= 3 and parts[-1] == "NAME" else parts[-1]
    return core.replace("_", " ").title()


def colony_from_save(source, strings=None):
    """Build the colony dict from a save path or the raw bytes of a save.

    strings: optional {STRINGS key: English text}; used to name worlds.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        mtime = None
    else:
        with open(source, "rb") as fh:
            data = fh.read()
        mtime = os.path.getmtime(source)
    written = _iso(mtime) if mtime is not None else _iso(0)
    header = parse_header(data)  # raises SaveFormatError: not a save at all
    out = {
        "source": "header", "level": "header", "asOf": written, "warnings": [],
        "header": _header_summary(header),
        "live": _live_from_header(header, written),
        "research": {"completed": [], "inProgress": [], "points": {}, "activeTech": None},
        "deadDupes": [],
    }
    major, minor = header.save_version
    if major != KNOWN_MAJOR:
        out["warnings"].append("save version %d.%d is not understood; header facts only" % (major, minor))
        return out
    if minor > TESTED_MINOR:
        out["warnings"].append("save version %d.%d is newer than tested (%d.%d)" % (major, minor, KNOWN_MAJOR, TESTED_MINOR))
    try:
        _, templates, body = split_save(data)
        sb = read_body(templates, body)
        _fill_from_body(out, header, sb, written, strings or {})
    except (KSerialError, SaveFormatError, struct.error, KeyError, IndexError, ValueError) as exc:
        out["warnings"].append("save body not readable (%s); header facts only" % exc)
        out["source"], out["level"] = "header", "header"
        out["live"] = _live_from_header(header, written)
        out["research"] = {"completed": [], "inProgress": [], "points": {}, "activeTech": None}
        out["deadDupes"] = []
    return out


# ---- body ---------------------------------------------------------------------

def _data(sb, obj, name, lenient=False):
    raw = obj.behavior(name)
    tpl = sb.templates.get(name)
    if raw is None or tpl is None:
        return None, b""
    return sb.parser.template_data(raw, tpl, lenient)


def _amounts(extra):
    """MinionModifiers extra data: [count] then (name, byteLength, float) rows."""
    r = Reader(extra)
    out = {}
    for _ in range(r.i32()):
        name = r.string()
        n = r.i32()
        raw = r.take(n)
        if n == 4:
            out[name] = struct.unpack("<f", raw)[0]
    return out


def _is_dead(sb, minion):
    raw = minion.behavior("StateMachineController")
    if raw is None:
        return None
    tpl = sb.templates.get("StateMachineController")
    _, extra = sb.parser.template_data(raw, tpl) if tpl else (None, raw)
    m = _DEATH_STATE.search(extra)
    if not m:
        return None
    try:
        r = Reader(extra, m.start(1))
        state = r.string()
    except KSerialError:
        return None
    return bool(state) and ".dead" in state


def _worlds(sb):
    out = []
    for objs in sb.game_objects.values():
        for o in objs:
            if o.behavior("WorldContainer") is None:
                continue
            f, _ = _data(sb, o, "WorldContainer", lenient=True)
            if f and "id" in f and "worldOffset" in f and "worldSize" in f:
                out.append(f)
    out.sort(key=lambda f: f["id"])
    return out


def _world_of(worlds, position):
    x, y = int(position[0]), int(position[1])
    for w in worlds:
        ox, oy = w["worldOffset"]
        sx, sy = w["worldSize"]
        if ox <= x < ox + sx and oy <= y < oy + sy:
            return w["id"]
    return None


def _fill_from_body(out, header, sb, written, strings):
    save_game = (sb.game_objects.get("SaveGame") or [None])[0]
    if save_game is None:
        raise KSerialError("SaveGame object missing")

    live = out["live"]
    clock, _ = _data(sb, save_game, "GameClock")
    if clock:
        live["cycle"] = int(clock["cycle"]) + 1
        live["timeOfDay"] = max(0.0, min(1.0, float(clock["timeSinceStartOfCycle"]) / CYCLE_SECONDS))
    cm, _ = _data(sb, save_game, "ClusterManager")

    world_rows = _worlds(sb)
    if not world_rows:
        out["warnings"].append("no world records found; using one world")
        world_rows = [{"id": 0, "worldOffset": (0, 0), "worldSize": (1 << 20, 1 << 20),
                       "worldName": "", "worldType": "", "isStartWorld": True}]
    worlds = {}
    for w in world_rows:
        name = w.get("overrideName") or strings.get(w.get("worldType") or "") or pretty_world_name(w.get("worldType") or w.get("worldName"))
        worlds[w["id"]] = {
            "id": w["id"], "name": name, "isStarter": bool(w.get("isStartWorld")),
            "dupes": [], "resources": {}, "critters": [], "alerts": [],
            "research": {"queue": []},
        }
    first = world_rows[0]["id"]
    live["activeWorldId"] = (cm or {}).get("activeWorldIdx", first)
    if live["activeWorldId"] not in worlds:
        live["activeWorldId"] = first

    # duplicants
    dead = []
    for m in sb.game_objects.get("Minion", []):
        ident, _ = _data(sb, m, "MinionIdentity")
        name = (ident or {}).get("name") or "?"
        if _is_dead(sb, m):
            dead.append(name)
            continue
        mods, extra = _data(sb, m, "MinionModifiers")
        am = _amounts(extra) if extra else {}
        traits, _ = _data(sb, m, "Klei.AI.Traits")
        resume, _ = _data(sb, m, "MinionResume")
        prefab, _ = _data(sb, m, "KPrefabID")
        role = (resume or {}).get("currentRole")
        mastered = sorted(k for k, v in ((resume or {}).get("MasteryBySkillID") or {}).items() if v)
        dupe = {
            "id": str((prefab or {}).get("InstanceID", name)),
            "name": name,
            "stress": max(0.0, min(100.0, am.get("Stress", 0.0))),
            "health": {"value": am.get("HitPoints", 0.0), "max": max(HEALTH_MAX, am.get("HitPoints", 0.0))},
            "calories": {"value": am.get("Calories", 0.0) / CALORIES_PER_KCAL, "max": CALORIES_MAX_KCAL},
            "breath": {"value": am.get("Breath", 0.0), "max": BREATH_MAX},
            "chore": None,
            "skills": mastered,
            "traits": list((traits or {}).get("TraitIds") or []),
            "assignedSkill": role if role and role != "NoRole" else None,
        }
        if "Bladder" in am:
            dupe["bladder"] = max(0.0, min(100.0, am["Bladder"]))
        wid = _world_of(world_rows, m.position)
        worlds[wid if wid in worlds else first]["dupes"].append(dupe)
    out["deadDupes"] = dead

    # resources and critters
    crit = {}
    for prefab, objs in sb.game_objects.items():
        for o in objs:
            if o.behavior("CreatureBrain") is not None:
                wid = _world_of(world_rows, o.position)
                wid = wid if wid in worlds else first
                row = crit.setdefault((wid, prefab), {"count": 0, "eggs": 0})
                row["count"] += 1
                continue
            if prefab == "Minion" or o.behavior("Pickupable") is None or o.behavior("PrimaryElement") is None:
                continue
            f, _ = _data(sb, o, "PrimaryElement")
            if not f:
                continue
            wid = _world_of(world_rows, o.position)
            wid = wid if wid in worlds else first
            if prefab.endswith("Egg") and len(prefab) > 3:
                row = crit.setdefault((wid, prefab[:-3]), {"count": 0, "eggs": 0})
                row["eggs"] += 1
            res = worlds[wid]["resources"]
            res[prefab] = res.get(prefab, 0.0) + max(0.0, float(f["Units"]))
    for (wid, prefab), row in sorted(crit.items()):
        entry = {"id": prefab, "count": row["count"]}
        if row["eggs"]:
            entry["eggs"] = row["eggs"]
        worlds[wid]["critters"].append(entry)
    for w in worlds.values():
        w["resources"] = {k: round(v, 3) for k, v in sorted(w["resources"].items())}

    # research (colony wide: the save has one research state)
    res, _ = _data(sb, save_game, "Research")
    summary = out["research"]
    if res:
        sd = res.get("saveData") or {}
        summary["activeTech"] = sd.get("activeResearchId") or None
        summary["points"] = dict((res.get("globalPointInventory") or {}).get("PointsByTypeID") or {})
        for t in sd.get("techs") or []:
            pts = dict(zip(t.get("inventoryIDs") or [], t.get("inventoryValues") or []))
            if t.get("complete"):
                summary["completed"].append(t["techId"])
            elif any(v > 0 for v in pts.values()):
                summary["inProgress"].append({"tech": t["techId"], "points": pts})
    for w in worlds.values():
        r = w["research"]
        r["completed"] = list(summary["completed"])
        r["queue"] = [{"tech": p["tech"], "points": p["points"], "cost": {}} for p in summary["inProgress"]
                      if p["tech"] == summary["activeTech"]]
        r["current"] = r["queue"][0] if r["queue"] else None

    live["worlds"] = [worlds[k] for k in sorted(worlds)]
    out["source"], out["level"] = "save", "full"
