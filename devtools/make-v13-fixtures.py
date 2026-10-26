#!/usr/bin/env python3
"""Generates the v1.3 synthetic fixtures: a made-up export and live file (overlays, tools, build menu, materials,
ports with signal texts, unlock facts), the Screens and replies the core builds from them, commands and acks.
Made-up content only (ids start with Synth, placeholder names, no Klei text or numbers). stdlib only.

The Screens are built by the real core from the made-up files, so the fixtures cannot drift from the code:
run `python3 devtools/make-v13-fixtures.py` after changing the views, then the contract tests validate them.
"""
import copy
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "fixtures", "synthetic")

import core.oni_companion.server  # noqa: E402,F401  (import order)
from core.oni_companion import config as oni_config                      # noqa: E402
from core.oni_companion import modstate                                  # noqa: E402
from core.oni_companion.actions import ActionService                     # noqa: E402
from core.oni_companion.colony import Colony, parse_iso                  # noqa: E402
from core.oni_companion.controls import Controls                         # noqa: E402
from core.oni_companion.gamedata import Dataset, load_dataset, merge, modexport   # noqa: E402
from core.oni_companion.views.lookup import Lookup                       # noqa: E402
from core.oni_companion.views.provider import Views                      # noqa: E402

AS_OF = "2026-01-01T12:00:00Z"


SANITIZE = []          # [(real temp path, stable fake path)]: no machine paths in a fixture


def wjson(rel, obj):
    path = os.path.join(FIX, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    for real, fake in SANITIZE:
        text = text.replace(real, fake)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


def fake_user(user):
    SANITIZE.append((os.path.realpath(user), "/home/synth/Klei/OxygenNotIncluded"))
    SANITIZE.append((user, "/home/synth/Klei/OxygenNotIncluded"))


def make_export():
    base = json.load(open(os.path.join(FIX, "mod", "export.json"), encoding="utf-8"))
    d = copy.deepcopy(base)
    d["modVersion"] = "0.4.0"
    d["contract"] = 3
    d["requiresCore"] = {"min": "1.3.0"}
    d["constants"] = {"dupeO2KgPerS": 0.1, "toolNumbers": {"dupeCo2KgPerS": 0.02}}
    d["dlcNames"] = {"DLC_ALPHA_ID": "Synth Alpha Pack", "DLC_BETA_ID": "Synth Beta Pack"}
    d["elements"] += [
        {"id": "SynthMetalA", "name": "Metal A", "dlc": [], "state": "solid", "tags": ["SynthMetal"]},
        {"id": "SynthMetalB", "name": "Metal B", "dlc": [], "state": "solid", "tags": ["SynthMetal"]},
        {"id": "SynthMetalC", "name": "Metal C", "dlc": [], "state": "solid", "tags": ["SynthMetal"]},
        {"id": "SynthPlastic", "name": "Plastic", "dlc": [], "state": "solid", "tags": ["SynthPlastic"]},
    ]
    d["overlays"] = [
        {"id": "SynthOxygen", "name": "Oxygen Overlay", "hotkey": "F1", "icon": "overlay_oxygen", "dlc": [], "available": True},
        {"id": "SynthPower", "name": "Power Overlay", "hotkey": "F2", "icon": "overlay_power", "dlc": [], "available": True},
        {"id": "SynthRadiation", "name": "Radiation Overlay", "hotkey": "F3", "icon": "overlay_radiation",
         "dlc": ["DLC_BETA_ID"], "available": False},
    ]
    d["tools"] = [
        {"id": "SynthDig", "name": "Dig", "hotkey": "G", "icon": "tool_dig", "dlc": [], "available": True, "usesPriority": True},
        {"id": "SynthCancel", "name": "Cancel", "hotkey": "Z", "icon": "tool_cancel", "dlc": [], "available": True},
        {"id": "SynthMop", "name": "Mop", "hotkey": "M", "dlc": [], "available": True, "usesPriority": True},
        {"id": "SynthHarvest", "name": "Harvest", "hotkey": "H", "dlc": ["DLC_BETA_ID"], "available": False, "usesPriority": True},
    ]
    d["techs"] = [
        {"id": "SynthWidgetry", "name": "Widgetry", "dlc": [], "cost": {"synth_basic": 15}, "requires": [],
         "unlocks": [{"kind": "building", "id": "SynthWidgetMaker"}]},
        {"id": "SynthSensing", "name": "Sensing", "dlc": [], "cost": {"synth_basic": 30, "synth_adv": 10}, "requires": [],
         "unlocks": [{"kind": "building", "id": "SynthTrap"}]},
    ]
    wm = d["buildings"][0]
    wm.update(category="SynthIndustry", unlocked=False, dlcActive=True,
              lockReason={"techId": "SynthWidgetry", "techName": "Widgetry", "cost": {"synth_basic": 15}})
    wm["materials"] = [{"tags": ["SynthMetal"], "kg": 200, "label": "Metal",
                        "candidates": ["SynthMetalA", "SynthMetalB", "SynthMetalC"]}]
    lamp = d["buildings"][1]
    lamp.update(category="SynthBase", unlocked=True, dlcActive=True)
    d["buildings"] += [
        {"id": "SynthTrap", "name": "Critter Trap", "dlc": [], "desc": "Made-up.", "effect": "Catches made-up critters.",
         "category": "SynthAutomation", "size": {"w": 1, "h": 2}, "hp": 30, "buildTimeS": 10,
         "materials": [{"tags": ["SynthMetal"], "kg": 100, "label": "Metal", "candidates": ["SynthMetalA", "SynthMetalB", "SynthMetalC"]},
                       {"tags": ["SynthPlastic"], "kg": 50, "label": "Plastic", "candidates": ["SynthPlastic"]}],
         "ports": [{"kind": "logic", "direction": "out", "name": "Trap Status", "description": "Reports whether a critter is inside.",
                    "greenText": "Sends a green signal when a critter is inside.", "redText": "Sends a red signal when the trap is empty."},
                   {"kind": "logic", "direction": "in", "name": "Trap Control", "greenText": "Arms the trap.", "redText": "Disarms the trap."}],
         "storage": {"capacityKg": 20000}, "tech": "SynthSensing", "unlocked": True, "dlcActive": True},
        {"id": "SynthPump", "name": "Gas Pump", "dlc": [], "category": "SynthIndustry", "size": {"w": 2, "h": 2},
         "materials": [{"tags": ["SynthMetal"], "kg": 60, "label": "Metal", "candidates": ["SynthMetalA", "SynthMetalB"]}],
         "power": {"usesW": 240},
         "ports": [{"kind": "gas", "direction": "in", "maxKgPerS": 0.5}, {"kind": "gas", "direction": "out", "maxKgPerS": 0.5},
                   {"kind": "power", "direction": "in", "maxW": 240}],
         "tech": None, "unlocked": True, "dlcActive": True},
        {"id": "SynthWireBridge", "name": "Wire Bridge", "dlc": [], "category": "SynthBase", "size": {"w": 3, "h": 1},
         "tech": None, "unlocked": True, "dlcActive": True},
        {"id": "SynthBetaGizmo", "name": "Beta Gizmo", "dlc": ["DLC_BETA_ID"], "category": "SynthIndustry",
         "size": {"w": 1, "h": 1}, "tech": None, "unlocked": False, "dlcActive": False},
    ]
    d["buildMenu"] = [
        {"id": "SynthBase", "name": "Base", "icon": "menu_base", "hotkey": "1", "dlc": [], "buildings": ["SynthLamp", "SynthWireBridge"]},
        {"id": "SynthAutomation", "name": "Automation", "icon": "menu_automation", "hotkey": "2", "dlc": [], "buildings": ["SynthTrap"]},
        {"id": "SynthIndustry", "name": "Refinement", "icon": "menu_industry", "hotkey": "3", "dlc": [],
         "buildings": ["SynthWidgetMaker", "SynthPump", "SynthBetaGizmo"],
         "subgroups": [{"id": "SynthIndustryMain", "name": "Machines", "buildings": ["SynthWidgetMaker", "SynthPump"]}]},
    ]
    return d


def make_live():
    d = json.load(open(os.path.join(FIX, "mod", "live-running-v2.json"), encoding="utf-8"))
    d.update(seq=21, modVersion="0.4.0", contract=3, requiresCore={"min": "1.3.0"}, activeOverlay="SynthOxygen",
             activeTool="SynthDig", priority=5, paused=False, speed=2,
             unlockedBuildings=["SynthLamp", "SynthWireBridge", "SynthTrap", "SynthPump"])
    w = d["worlds"][0]
    w["stock"] = {"SynthMetalA": 1240.0, "SynthMetalB": 80.0, "SynthMetalC": 0.0, "SynthPlastic": 30.0}
    w["research"] = {"current": None, "queue": [], "completed": ["SynthSensing"]}
    return d


def lookup_from(data, name="export.json", sha="0"):
    """A Lookup over one made-up export dict, with the v1.3 meta the dataset builder would add."""
    ex = [{"path": name, "name": name, "sha1": sha, "data": data}]
    kinds = merge.merge({}, ex, [])
    meta = {"dlcInstalled": data["dlcIds"], "dlcExported": data["dlcIds"], "dlcMissingExport": [],
            "exportFiles": [name], "modVersion": data["modVersion"], "builtAt": AS_OF,
            "researchTypes": data.get("researchTypes") or [], "steamBuildId": "1",
            "constants": data.get("constants") or {}, "dlcNames": data.get("dlcNames") or {},
            "overlays": data.get("overlays") or [], "padTools": data.get("tools") or [],
            "buildMenu": data.get("buildMenu") or [], "modContract": data.get("contract"),
            "modRequiresCore": data.get("requiresCore"), "dlcActive": data["dlcIds"]}
    return Lookup(Dataset(kinds, meta, "k", False, {}))


class Ctx:
    def __init__(self, cfg, colony, controls, actions, bundled):
        self.cfg, self.colony, self.controls, self.actions = cfg, colony, controls, actions
        self.bundled_mod = bundled
        self.bus = None
        self.settings = None


def make_views(tmp, export, live, bundled=None):
    """A Views over a made-up user folder in tmp. Returns (views, user_dir)."""
    user = os.path.join(tmp, "user")
    comp = os.path.join(user, "companion")
    os.makedirs(os.path.join(comp, "live"), exist_ok=True)
    os.makedirs(os.path.join(comp, "export"), exist_ok=True)
    if live is not None:
        with open(os.path.join(comp, "live", "live.json"), "w", encoding="utf-8") as f:
            json.dump(live, f)
    if export is not None:
        with open(os.path.join(comp, "export", "gamedata-100001-DLC_ALPHA_ID.json"), "w", encoding="utf-8") as f:
            json.dump(export, f)
    now = parse_iso(AS_OF) + 2
    colony = Colony(os.path.join(comp, "live", "live.json"), clock=lambda: now)
    actions = ActionService(comp, lambda *a: None, clock=lambda: now)
    controls = Controls(actions, colony, lambda *a: None, comp, clock=lambda: now)
    cfg = oni_config.Config(user_dir=user, data_dir=os.path.join(tmp, "data"))
    lk = None
    if export is not None:
        path = os.path.join(comp, "export", "gamedata-100001-DLC_ALPHA_ID.json")
        data, sha = modexport.load_export(path)
        lk = lookup_from(data, os.path.basename(path), sha)
    fake_user(user)
    return Views(Ctx(cfg, colony, controls, actions, bundled), lookup=lk, config=cfg), user


def status_with(user, bundled, live, export_present, tmp, fresh_clock):
    """Status.modState for a made-up folder state."""
    meta = {"exportFiles": ["x.json"] if export_present else [], "modVersion": None}
    col = Colony(os.path.join(user, "companion", "live", "live.json"), clock=lambda: fresh_clock)
    ms = modstate.ModState(user, lambda: meta, col.read_live, col.live_fresh, bundled)
    return ms.compute()


def main():
    export, live = make_export(), make_live()
    bundled = os.path.join(tempfile.mkdtemp(prefix="oni-v13-bundle-"), "OniCompanionLink")
    os.makedirs(bundled)
    for n, body in (("OniCompanionLink.dll", "x"), ("mod.yaml", "staticID: OniCompanionLink\n"),
                    ("mod_info.yaml", "version: 0.4.0\n")):
        open(os.path.join(bundled, n), "w").write(body)
    wjson("mod/export-v13.json", export)
    wjson("mod/live-running-v13.json", live)
    tmp = tempfile.mkdtemp(prefix="oni-v13-fx-")
    try:
        v, _user = make_views(tmp, export, live, bundled)
        wjson("api/tabs.json", v.tabs())
        wjson("screens/actions.json", v.pad())
        wjson("screens/buildings.json", v.buildings())
        wjson("screens/entry-building-v13.json", v.entry("building", "SynthTrap"))
        wjson("screens/entry-building-locked.json", v.entry("building", "SynthWidgetMaker"))
        wjson("screens/entry-building-ports.json", v.entry("building", "SynthPump"))
        wjson("screens/entry-building-plain.json", v.entry("building", "SynthWireBridge"))
        # the game is in the menu: every button greyed with the reason
        menu = copy.deepcopy(live)
        menu["state"] = "menu"
        v2, _ = make_views(os.path.join(tmp, "menu"), export, menu, bundled)
        wjson("screens/actions-menu.json", v2.pad())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # mod states over made-up folders
    now = parse_iso(AS_OF) + 2

    def folder(name, local=False, workshop=False, modsjson=None, live_=None, export_=False, version="0.4.0"):
        tmp2 = tempfile.mkdtemp(prefix="oni-v13-%s-" % name)
        user = os.path.join(tmp2, "user")
        fake_user(user)
        os.makedirs(os.path.join(user, "companion", "live"))
        if local:
            p = os.path.join(user, "mods", "Local", "OniCompanionLink")
            os.makedirs(p)
            open(os.path.join(p, "mod.yaml"), "w").write("staticID: OniCompanionLink\n")
            open(os.path.join(p, "mod_info.yaml"), "w").write("version: %s\n" % version)
        if workshop:
            p = os.path.join(user, "mods", "Steam", "100001")
            os.makedirs(p)
            open(os.path.join(p, "mod.yaml"), "w").write("staticID: OniCompanionLink\n")
            open(os.path.join(p, "mod_info.yaml"), "w").write("version: %s\n" % version)
        if modsjson is not None:
            os.makedirs(os.path.join(user, "mods"), exist_ok=True)
            json.dump({"version": 1, "mods": modsjson}, open(os.path.join(user, "mods", "mods.json"), "w"))
        if live_ is not None:
            json.dump(live_, open(os.path.join(user, "companion", "live", "live.json"), "w"))
        return user

    entry_on = [{"label": {"distribution_platform": 0, "id": "OniCompanionLink", "title": "ONI Companion Link"},
                 "enabledForDlc": [""], "staticID": "OniCompanionLink"}]
    entry_off = [dict(entry_on[0], enabledForDlc=[])]
    old = dict(live, modVersion="0.3.2")
    old.pop("requiresCore", None)
    cases = {
        "missing": folder("missing"),
        "disabled": folder("disabled", local=True, modsjson=entry_off),
        "no-live": folder("nolive", local=True, modsjson=entry_on),
        "version-mismatch": folder("old", local=True, modsjson=entry_on, live_=old, version="0.3.2"),
        "ok": folder("ok", local=True, modsjson=entry_on, live_=live),
    }
    base = json.load(open(os.path.join(FIX, "api", "status.json"), encoding="utf-8"))
    for name, user in cases.items():
        st = copy.deepcopy(base)
        st["modState"] = status_with(user, bundled, None, name != "missing", None, now)
        wjson("api/status-modstate-%s.json" % name, st)
        shutil.rmtree(os.path.dirname(user), ignore_errors=True)

    # Settings page with the mod section (missing mod: the install button)
    tmp3 = tempfile.mkdtemp(prefix="oni-v13-set-")
    try:
        v3, user3 = make_views(tmp3, export, None, bundled)
        scr = v3.settings()
        wjson("screens/settings-modstate.json", scr)
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    # POST /mod/install: the reply after copying the bundled mod into a made-up user folder
    tmp4 = tempfile.mkdtemp(prefix="oni-v13-inst-")
    try:
        v4, user4 = make_views(tmp4, export, None, bundled)
        reply = v4.mod_install({"confirm": True})
        wjson("api/mod-install-reply.json", reply)
    finally:
        shutil.rmtree(tmp4, ignore_errors=True)

    # request bodies and mod commands
    wjson("api/action-post-overlay-set.json", {"mode": "SynthPower"})
    wjson("api/action-post-tool-select.json", {"tool": "SynthDig", "priority": 7})
    wjson("api/action-post-build-select.json", {"buildingId": "SynthTrap", "materials": ["SynthMetalA", "SynthPlastic"]})
    wjson("api/mod-install-post.json", {"confirm": True})
    iso = "2026-01-01T12:00:01Z"
    wjson("companion/commands/cmd-14.json", {"schema": 1, "seq": 14, "createdAt": iso, "type": "overlay_set", "mode": "SynthPower"})
    wjson("companion/commands/cmd-15.json", {"schema": 1, "seq": 15, "createdAt": iso, "type": "tool_select", "tool": "SynthDig", "priority": "emergency"})
    wjson("companion/commands/cmd-16.json", {"schema": 1, "seq": 16, "createdAt": iso, "type": "build_select", "buildingId": "SynthTrap",
                                              "materials": ["SynthMetalA", "SynthPlastic"]})
    wjson("companion/acks/ack-14.json", {"schema": 1, "seq": 14, "state": "done", "ackedAt": "2026-01-01T12:00:02Z"})
    wjson("companion/acks/ack-15.json", {"schema": 1, "seq": 15, "state": "done", "ackedAt": "2026-01-01T12:00:02Z"})
    wjson("companion/acks/ack-16.json", {"schema": 1, "seq": 16, "state": "failed", "message": "Not researched yet",
                                          "ackedAt": "2026-01-01T12:00:02Z"})


if __name__ == "__main__":
    main()
