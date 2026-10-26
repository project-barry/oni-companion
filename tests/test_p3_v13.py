"""P3 (v1.3): overlays, tools and Build in the core, the Buildings and Actions Screens, the material picker, the
building page sections, the mod state and its ask-first install, the tabs list, the new commands and events.

Everything runs on made-up data (devtools/make-v13-fixtures.py builds it); the real game is never touched.
"""
import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.oni_companion import colony as colony_mod  # noqa: E402
from core.oni_companion import modstate  # noqa: E402
from core.oni_companion.server.errors import ApiError  # noqa: E402
from core.oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from core.oni_companion.views.provider import Views  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402
from tests.test_c3_server import TOKEN, atomic_write, http  # noqa: E402

spec = importlib.util.spec_from_file_location("make_v13", os.path.join(ROOT, "devtools", "make-v13-fixtures.py"))
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
V = Validator(os.path.join(ROOT, "contracts"))


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def actions_of(scr):
    return [a for n in walk(scr) for a in (n.get("actions") or []) if isinstance(a, dict) and "id" in a]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-p3-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.export, self.live = mk.make_export(), mk.make_live()
        self.bundled = os.path.join(self.tmp, "bundle", "OniCompanionLink")
        os.makedirs(self.bundled)
        for n, body in (("OniCompanionLink.dll", "x"), ("mod.yaml", "staticID: OniCompanionLink\n"),
                        ("mod_info.yaml", "version: 0.4.0\n")):
            open(os.path.join(self.bundled, n), "w").write(body)

    def views(self, live=None, name="a", export=True):
        v, user = mk.make_views(os.path.join(self.tmp, name), self.export if export else None,
                                self.live if live is None else live, self.bundled)
        return v, user

    def ok(self, scr):
        self.assertEqual(V.validate(scr, "screen.schema.json"), [])
        self.assertEqual([s for s in _strings(scr) if "mod" in s.lower().split() and "Settings" not in scr.get("title", "")], [])


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


class ActionsScreen(Base):
    def test_grids_follow_the_game(self):
        v, _ = self.views()
        scr = v.pad()
        self.ok(scr)
        titles = [b["title"] for b in scr["blocks"] if b["type"] == "grid"]
        self.assertEqual(titles, ["Overlays", "Priority", "Tools"])
        ov = scr["blocks"][0]["cards"]
        self.assertEqual([c["title"] for c in ov], ["Oxygen Overlay", "Power Overlay", "Radiation Overlay"])   # the game's order
        by = {c["title"]: c["actions"][0] for c in ov}
        self.assertTrue(by["Oxygen Overlay"]["active"])                         # follows live activeOverlay
        self.assertEqual(by["Oxygen Overlay"]["args"], {"mode": "None"})        # the active one goes back to none
        self.assertEqual(by["Power Overlay"]["args"], {"mode": "SynthPower"})
        self.assertFalse(by["Radiation Overlay"]["enabled"])
        self.assertEqual(by["Radiation Overlay"]["reason"], "Needs Synth Beta Pack.")   # DLC by the game's name
        pri = scr["blocks"][1]
        self.assertEqual(pri["variant"], "priority")
        self.assertEqual([c["title"] for c in pri["cards"]], list("123456789") + ["!"])
        self.assertEqual([c["actions"][0]["args"]["priority"] for c in pri["cards"]][-1], "emergency")
        self.assertEqual([c["title"] for c in pri["cards"] if c["actions"][0].get("active")], ["5"])
        tools = {c["title"]: c["actions"][0] for c in scr["blocks"][2]["cards"]}
        self.assertEqual(list(tools), ["Dig", "Cancel", "Mop", "Harvest"])
        self.assertTrue(tools["Dig"]["active"])
        self.assertEqual(tools["Dig"]["args"], {"tool": "SynthDig"})
        self.assertFalse(tools["Harvest"]["enabled"])

    def test_emergency_priority_is_marked(self):
        live = copy.deepcopy(self.live)
        live["priority"] = "emergency"
        v, _ = self.views(live)
        pri = v.pad()["blocks"][1]["cards"]
        self.assertTrue(pri[-1]["actions"][0]["active"])
        self.assertFalse(any(c["actions"][0].get("active") for c in pri[:-1]))

    def test_menu_and_no_export(self):
        live = copy.deepcopy(self.live)
        live["state"] = "menu"
        v, _ = self.views(live)
        scr = v.pad()
        self.ok(scr)
        btns = actions_of(scr)
        self.assertTrue(btns and all(a["enabled"] is False and a.get("reason") for a in btns))
        self.assertFalse(any(a.get("active") for a in btns))
        self.assertIn("Load a colony", scr["blocks"][0]["text"])
        # a mod that sends no lists: one notice, no mod talk
        old = copy.deepcopy(self.export)
        for k in ("overlays", "tools", "buildMenu"):
            old.pop(k)
        self.export = old
        v, _ = self.views(name="b")
        scr = v.pad()
        self.assertEqual([b["type"] for b in scr["blocks"]], ["notice"])
        self.assertNotIn("mod", scr["blocks"][0]["text"].lower())


class BuildingsScreen(Base):
    def rows(self, scr):
        return {i["title"]: i for g in scr["blocks"] for b in g["blocks"] for i in b["items"]}

    def test_groups_in_menu_order_with_build_buttons(self):
        v, _ = self.views()
        scr = v.buildings()
        self.ok(scr)
        self.assertEqual([g["title"] for g in scr["blocks"]], ["Base (2)", "Automation (1)", "Refinement (3)"])
        rows = self.rows(scr)
        self.assertEqual(list(rows), ["Lamp", "Wire Bridge", "Critter Trap", "Widget Maker", "Gas Pump", "Beta Gizmo"])
        self.assertNotIn("enabled", rows["Lamp"]["actions"][0])                        # unlocked: enabled
        wm = rows["Widget Maker"]["actions"][0]
        self.assertEqual((wm["enabled"], wm["reason"]), (False, "Needs research: Widgetry"))
        self.assertEqual(rows["Beta Gizmo"]["actions"][0]["reason"], "Needs Synth Beta Pack.")
        self.assertEqual(rows["Critter Trap"]["actions"][0]["args"], {"buildingId": "SynthTrap"})
        self.assertIn("build", scr["refreshOn"])
        self.assertEqual(scr["filter"]["placeholder"], "Search buildings")

    def test_research_finishing_enables_the_button(self):
        live = copy.deepcopy(self.live)
        live["unlockedBuildings"].append("SynthWidgetMaker")
        v, _ = self.views(live)
        wm = self.rows(v.buildings())["Widget Maker"]["actions"][0]
        self.assertNotIn("enabled", wm)
        # without unlockedBuildings the completed research decides
        live = copy.deepcopy(self.live)
        del live["unlockedBuildings"]
        live["worlds"][0]["research"]["completed"] = ["SynthSensing", "SynthWidgetry"]
        v, _ = self.views(live, name="b")
        self.assertNotIn("enabled", self.rows(v.buildings())["Widget Maker"]["actions"][0])
        # ... and without live research the export's snapshot
        live = copy.deepcopy(self.live)
        del live["unlockedBuildings"]
        del live["worlds"][0]["research"]
        v, _ = self.views(live, name="c")
        self.assertEqual(self.rows(v.buildings())["Widget Maker"]["actions"][0]["reason"], "Needs research: Widgetry")

    def test_game_not_running_greys_everything(self):
        live = copy.deepcopy(self.live)
        live["state"] = "menu"
        v, _ = self.views(live)
        acts = actions_of(v.buildings())
        self.assertTrue(acts and all(a["enabled"] is False for a in acts))
        self.assertEqual({a["reason"] for a in acts}, {"Load a colony in the game first."})

    def test_without_the_list_it_says_so(self):
        self.export.pop("buildMenu")
        self.export["buildings"] = [dict(b, category="Uncategorized") for b in self.export["buildings"]]
        v, _ = self.views()
        scr = v.buildings()
        self.assertEqual([b["type"] for b in scr["blocks"]], ["notice"])
        self.assertNotIn("mod", scr["blocks"][0]["text"].lower())


class BuildingPage(Base):
    def page(self, bid, live=None, name="a"):
        v, _ = self.views(live, name)
        scr = v.entry("building", bid)
        self.ok(scr)
        return scr

    def test_picker_matches_the_stock(self):
        scr = self.page("SynthTrap")
        pk = [b for b in scr["blocks"] if b["type"] == "picker"][0]
        self.assertEqual([s["label"] for s in pk["slots"]], ["Metal", "Plastic"])
        metal = {o["id"]: o for o in pk["slots"][0]["options"]}
        self.assertEqual((metal["SynthMetalA"]["haveKg"], metal["SynthMetalA"]["needKg"]), (1240, 100))
        self.assertTrue(metal["SynthMetalA"]["enabled"] and metal["SynthMetalA"]["selected"])
        self.assertFalse(metal["SynthMetalB"]["enabled"])                    # 80 < 100: greyed like the game
        self.assertFalse(metal["SynthMetalC"]["enabled"])                    # none in stock, but discovered
        self.assertEqual(sum(o["selected"] for o in pk["slots"][0]["options"]), 1)
        self.assertEqual(pk["action"]["args"], {"buildingId": "SynthTrap"})
        plastic = pk["slots"][1]["options"]                                 # needs 50, stock 30: nothing affordable
        self.assertEqual(sum(o["selected"] for o in plastic), 0)
        self.assertEqual((pk["action"]["enabled"], pk["action"]["reason"]), (False, "Not enough Plastic."))
        self.assertIn("colony", scr["refreshOn"])

    def test_list_build_button_checks_materials_too(self):
        # user, 2026-10-25: the Buildings list showed an active Build for Plastic Ladder with no plastic
        v, _ = self.views(None, "a")
        scr = v.buildings()
        rows = {i["title"]: i for g in scr["blocks"] for b in g["blocks"] for i in b.get("items", [])}
        trap = [r for t, r in rows.items() if r.get("ref", {}).get("id") == "SynthTrap"][0]
        self.assertEqual((trap["actions"][0].get("enabled"), trap["actions"][0].get("reason")), (False, "Not enough Plastic."))
        self.assertEqual(trap.get("subtitle"), "Not enough Plastic.")

    def test_undiscovered_material_is_not_offered(self):
        live = copy.deepcopy(self.live)
        del live["worlds"][0]["stock"]["SynthMetalC"]
        scr = self.page("SynthTrap", live)
        pk = [b for b in scr["blocks"] if b["type"] == "picker"][0]
        self.assertEqual([o["id"] for o in pk["slots"][0]["options"]], ["SynthMetalA", "SynthMetalB"])

    def test_default_is_the_most_stock_that_is_enough(self):
        live = copy.deepcopy(self.live)
        live["worlds"][0]["stock"].update(SynthMetalB=5000.0, SynthMetalA=300.0)
        pk = [b for b in self.page("SynthTrap", live)["blocks"] if b["type"] == "picker"][0]
        self.assertEqual([o["id"] for o in pk["slots"][0]["options"] if o["selected"]], ["SynthMetalB"])

    def test_locked_building_button_is_greyed_with_the_reason(self):
        scr = self.page("SynthWidgetMaker")
        pk = [b for b in scr["blocks"] if b["type"] == "picker"][0]
        self.assertEqual((pk["action"]["enabled"], pk["action"]["reason"]), (False, "Needs research: Widgetry"))

    def test_plain_building_has_a_build_row(self):
        scr = self.page("SynthWireBridge")
        rows = [b for b in scr["blocks"] if b["type"] == "list"]
        self.assertEqual(rows[0]["items"][0]["actions"][0]["id"], "build_select")
        self.assertNotIn("picker", [b["type"] for b in scr["blocks"]])

    def test_automation_section_like_the_game(self):
        scr = self.page("SynthTrap")
        types = [(b["type"], b.get("title")) for b in scr["blocks"]]
        self.assertIn(("group", "Automation"), types)
        self.assertNotIn(("ports", "Flow"), types)                           # logic is not flow
        grp = [b for b in scr["blocks"] if b.get("title") == "Automation"][0]
        texts = [sp["text"] for b in grp["blocks"] for sp in b["spans"]]
        self.assertIn("Trap Status", texts)
        # a text that already names the signal is shown as the game wrote it; others get "Green signal: "
        self.assertIn("Sends a green signal when a critter is inside.", texts)
        self.assertIn("Sends a red signal when the trap is empty.", texts)
        self.assertIn("Green signal: Arms the trap.", texts)
        colors = [sp.get("color") for b in grp["blocks"] for sp in b["spans"] if sp.get("color")]
        self.assertEqual(colors, ["positive", "negative", "positive", "negative"])
        flat = json.dumps(scr)
        self.assertNotIn("Logic in", flat)
        self.assertNotIn("20000", flat)                                      # no default storage capacity
        self.assertNotIn('"Storage"', flat)

    def test_research_shows_the_tech_name_and_cost(self):
        scr = self.page("SynthTrap")
        grp = [b for b in scr["blocks"] if b.get("title") == "Research"][0]
        it = grp["blocks"][0]["items"][0]
        self.assertEqual((it["title"], it["ref"]), ("Sensing", {"kind": "tech", "id": "SynthSensing"}))
        self.assertEqual(it["subtitle"], "30 Basic Research, 10 Advanced Research")

    def test_flow_for_real_ports_and_none_for_a_plain_building(self):
        scr = self.page("SynthPump")
        flow = [b for b in scr["blocks"] if b.get("title") == "Flow"][0]
        self.assertEqual([p["label"] for p in flow["inputs"]], ["Gas in", "Power in"])
        self.assertEqual([p["label"] for p in flow["outputs"]], ["Gas out"])
        self.assertTrue(any(p.get("conduit") == "power" for p in flow["inputs"]))
        plain = self.page("SynthWireBridge", name="b")
        self.assertEqual([b["type"] for b in plain["blocks"] if b["type"] in ("ports", "group")], [])

    def test_text_without_signal_names_is_hidden(self):
        e = copy.deepcopy(self.export)
        for b in e["buildings"]:
            for p in b.get("ports") or []:
                for k in ("name", "description", "greenText", "redText"):
                    p.pop(k, None)
        self.export = e
        scr = self.page("SynthTrap")
        self.assertNotIn("Automation", [b.get("title") for b in scr["blocks"]])


class Commands(Base):
    def test_validation_against_the_game_lists(self):
        v, _ = self.views()
        v.validate_command("overlay_set", {"mode": "SynthPower"})
        v.validate_command("overlay_set", {"mode": "None"})
        for bad in ({"mode": "Nope"}, {"mode": "SynthRadiation"}):
            with self.assertRaises(ApiError):
                v.validate_command("overlay_set", bad)
        v.validate_command("tool_select", {"tool": "SynthDig", "priority": 3})
        v.validate_command("tool_select", {"priority": "emergency"})
        with self.assertRaises(ApiError):
            v.validate_command("tool_select", {"tool": "SynthHarvest"})
        v.validate_command("build_select", {"buildingId": "SynthTrap", "materials": ["SynthMetalA"]})
        with self.assertRaises(ApiError) as e:
            v.validate_command("build_select", {"buildingId": "SynthTrap", "materials": ["SynthMetalA", "SynthPlastic"]})
        self.assertEqual(e.exception.message, "Not enough Plastic.")
        with self.assertRaises(ApiError) as e:
            v.validate_command("build_select", {"buildingId": "SynthWidgetMaker"})
        self.assertEqual(e.exception.message, "Needs research: Widgetry")
        with self.assertRaises(ApiError) as e:
            v.validate_command("build_select", {"buildingId": "SynthTrap", "materials": ["SynthMetalB"]})
        self.assertEqual(e.exception.message, "Not enough Metal B.")
        with self.assertRaises(ApiError):
            v.validate_command("build_select", {"buildingId": "SynthTrap", "materials": ["SynthStoneX"]})
        with self.assertRaises(ApiError) as e:
            v.validate_command("build_select", {"buildingId": "Nope"})
        self.assertEqual(e.exception.code, "not_found")

    def test_parse_bodies(self):
        from core.oni_companion.actions import ActionService as A
        self.assertEqual(A.parse_pad("overlay_set", {"mode": "X"}), {"mode": "X"})
        self.assertEqual(A.parse_pad("tool_select", {"priority": 9}), {"priority": 9})
        for aid, bad in (("overlay_set", {}), ("overlay_set", {"mode": "a b"}), ("overlay_set", {"mode": "A", "x": 1}),
                         ("tool_select", {}), ("tool_select", {"priority": 10}), ("tool_select", {"priority": True}),
                         ("tool_select", {"tool": "../x"}), ("build_select", {}), ("build_select", {"buildingId": "A", "materials": "A"}),
                         ("build_select", {"buildingId": "A", "materials": ["a b"]})):
            with self.assertRaises(ApiError, msg=(aid, bad)):
                A.parse_pad(aid, bad)


class Live(Base):
    """The service end to end: HTTP, command files, events."""

    def start(self, live=None, install_dir=None):
        user = os.path.join(self.tmp, "svc", "user")
        comp = os.path.join(user, "companion")
        atomic_write(os.path.join(comp, "live", "live.json"), json.dumps(self._live(live)))
        atomic_write(os.path.join(comp, "export", "gamedata-100001-DLC_ALPHA_ID.json"), json.dumps(self.export))
        lk = mk.lookup_from(self.export)
        from core.oni_companion import config as oni_config
        cfg = oni_config.Config(user_dir=user, data_dir=os.path.join(self.tmp, "svc", "data"))
        scfg = ServiceConfig(user_dir=user, token=TOKEN, views_factory=lambda ctx: Views(ctx, lookup=lk, config=cfg))
        self.svc = Service(scfg)
        self.svc.ctx_bundled = self.bundled
        self.svc.bundled_mod = self.bundled           # the Views read it from the service object (ctx)
        self.svc.start()
        self.addCleanup(self.svc.stop)
        self.user, self.comp = user, comp
        return self.svc

    def _live(self, live=None):
        d = copy.deepcopy(self.live if live is None else live)
        d["writtenAt"] = colony_mod.iso(time.time())
        return d

    def test_tabs_pad_buildings_over_http(self):
        self.start()
        st, tabs = http(self.svc, "/api/v1/tabs")
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(tabs, "api.schema.json#/$defs/TabList"), [])
        self.assertEqual([t["id"] for t in tabs["tabs"]], ["colony", "resources", "buildings", "actions", "codex", "settings"])
        self.assertEqual([t["label"] for t in tabs["tabs"]][:3], ["Colony", "Resources", "Buildings"])
        for path in ("pad", "buildings"):
            st, scr = http(self.svc, "/api/v1/" + path)
            self.assertEqual(st, 200)
            self.assertEqual(V.validate(scr, "screen.schema.json"), [])

    def test_overlay_command_is_written_for_the_mod(self):
        self.start()
        st, sent = http(self.svc, "/api/v1/actions/overlay_set", "POST", body={"mode": "SynthPower"})
        self.assertEqual(st, 200, sent)
        with open(os.path.join(self.comp, "commands", "cmd-%d.json" % sent["seq"])) as f:
            cmd = json.load(f)
        self.assertEqual(V.validate(cmd, "mod-command.schema.json"), [])
        self.assertEqual((cmd["type"], cmd["mode"]), ("overlay_set", "SynthPower"))
        st, sent = http(self.svc, "/api/v1/actions/tool_select", "POST", body={"tool": "SynthDig", "priority": 4})
        with open(os.path.join(self.comp, "commands", "cmd-%d.json" % sent["seq"])) as f:
            cmd = json.load(f)
        self.assertEqual(V.validate(cmd, "mod-command.schema.json"), [])
        self.assertEqual((cmd["tool"], cmd["priority"]), ("SynthDig", 4))
        st, sent = http(self.svc, "/api/v1/actions/build_select", "POST",
                        body={"buildingId": "SynthTrap", "materials": ["SynthMetalA", "SynthPlastic"]})
        self.assertEqual(st, 400, sent)             # plastic: 30 kg < 50 kg needed: refused before the mod
        self.assertEqual(sent["error"]["message"], "Not enough Plastic.")
        st, sent = http(self.svc, "/api/v1/actions/build_select", "POST", body={"buildingId": "SynthTrap", "materials": ["SynthMetalA"]})
        self.assertEqual(st, 200, sent)
        with open(os.path.join(self.comp, "commands", "cmd-%d.json" % sent["seq"])) as f:
            cmd = json.load(f)
        self.assertEqual(V.validate(cmd, "mod-command.schema.json"), [])

    def test_refused_without_a_running_game_and_for_locked_buildings(self):
        live = copy.deepcopy(self.live)
        live["state"] = "menu"
        self.start(live)
        st, err = http(self.svc, "/api/v1/actions/overlay_set", "POST", body={"mode": "SynthPower"})
        self.assertEqual((st, err["error"]["code"]), (503, "unavailable"))
        self.assertFalse(os.path.isdir(os.path.join(self.comp, "commands")) and os.listdir(os.path.join(self.comp, "commands")))

    def test_locked_building_is_refused_with_the_reason(self):
        self.start()
        st, err = http(self.svc, "/api/v1/actions/build_select", "POST", body={"buildingId": "SynthWidgetMaker"})
        self.assertEqual((st, err["error"]["message"]), (400, "Needs research: Widgetry"))

    def test_pad_event_when_the_game_changes_the_overlay(self):
        self.start()
        _st, e0 = http(self.svc, "/api/v1/events?since=0")
        live = self._live()
        live["activeOverlay"] = "SynthPower"
        live["seq"] += 1
        atomic_write(os.path.join(self.comp, "live", "live.json"), json.dumps(live))
        st, ev = http(self.svc, "/api/v1/events?since=%d&timeout=5" % e0["seq"])
        self.assertIn("pad", ev["changed"])
        e1 = ev["seq"]
        st, scr = http(self.svc, "/api/v1/pad")
        active = [a["label"] for a in actions_of(scr) if a.get("active")]
        self.assertIn("Power Overlay", active)
        # the same state written again: no pad event
        live["seq"] += 1
        atomic_write(os.path.join(self.comp, "live", "live.json"), json.dumps(live))
        st, ev = http(self.svc, "/api/v1/events?since=%d&timeout=1" % e1)
        self.assertNotIn("pad", ev["changed"])

    def test_build_event_when_research_finishes(self):
        self.start()
        _st, e0 = http(self.svc, "/api/v1/events?since=0")
        live = self._live()
        live["unlockedBuildings"].append("SynthWidgetMaker")
        live["seq"] += 1
        atomic_write(os.path.join(self.comp, "live", "live.json"), json.dumps(live))
        st, ev = http(self.svc, "/api/v1/events?since=%d&timeout=5" % e0["seq"])
        self.assertIn("build", ev["changed"])
        st, scr = http(self.svc, "/api/v1/buildings")
        wm = [i for g in scr["blocks"] for b in g["blocks"] for i in b["items"] if i["title"] == "Widget Maker"][0]
        self.assertNotIn("enabled", wm["actions"][0])

    def test_status_carries_the_mod_state_and_install_asks_first(self):
        self.start()
        st, status = http(self.svc, "/api/v1/status")
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(status, "api.schema.json#/$defs/Status"), [])
        self.assertEqual(status["modState"]["state"], "ok")        # the mod wrote live data, so it is working
        # no confirm: refused
        st, err = http(self.svc, "/api/v1/mod/install", "POST", body={})
        self.assertEqual(st, 400)
        self.assertFalse(os.path.exists(os.path.join(self.user, "mods")))
        st, err = http(self.svc, "/api/v1/mod/install", "POST", body={"confirm": False})
        self.assertEqual(st, 400)
        self.assertFalse(os.path.exists(os.path.join(self.user, "mods")))
        st, rep = http(self.svc, "/api/v1/mod/install", "POST", body={"confirm": True})
        self.assertEqual(st, 200, rep)
        self.assertEqual(V.validate(rep, "api.schema.json#/$defs/ModInstallReply"), [])
        for n in modstate.BUNDLED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.user, "mods", "Local", "OniCompanionLink", n)), n)
        # again: the newest version is there
        st, err = http(self.svc, "/api/v1/mod/install", "POST", body={"confirm": True})
        self.assertEqual(st, 503)
        self.assertIn("already", err["error"]["message"])

    def test_install_action_from_the_settings_screen(self):
        live = None
        self.start(live)
        st, scr = http(self.svc, "/api/v1/settings")
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(scr, "screen.schema.json"), [])
        inst = [a for a in actions_of(scr) if a["id"] == "mod_install"]
        self.assertEqual(len(inst), 1)
        self.assertIn("?", inst[0]["confirm"])                                 # the front end asks first
        st, sent = http(self.svc, "/api/v1/actions/mod_install", "POST", body=inst[0]["args"])
        self.assertEqual(st, 200, sent)
        st, res = http(self.svc, "/api/v1/actions/%d" % sent["seq"])
        self.assertEqual(res["state"], "done")
        st, err = http(self.svc, "/api/v1/actions/mod_install", "POST", body={})
        self.assertEqual(st, 400)


class ModStates(Base):
    ON = [{"label": {"distribution_platform": 0, "id": "OniCompanionLink"}, "enabledForDlc": [""], "staticID": "OniCompanionLink"}]

    def folder(self, name, local=False, workshop=False, modsjson=None, live=None, version="0.4.0"):
        user = os.path.join(self.tmp, name, "user")
        os.makedirs(os.path.join(user, "companion", "live"))
        for flag, sub in ((local, ("Local", "OniCompanionLink")), (workshop, ("Steam", "100001"))):
            if flag:
                p = os.path.join(user, "mods", *sub)
                os.makedirs(p)
                open(os.path.join(p, "mod.yaml"), "w").write("staticID: OniCompanionLink\n")
                open(os.path.join(p, "mod_info.yaml"), "w").write("version: %s\n" % version)
        if modsjson is not None:
            os.makedirs(os.path.join(user, "mods"), exist_ok=True)
            json.dump({"version": 1, "mods": modsjson}, open(os.path.join(user, "mods", "mods.json"), "w"))
        if live is not None:
            json.dump(live, open(os.path.join(user, "companion", "live", "live.json"), "w"))
        return user

    def state(self, user, exported=False, meta=None):
        now = colony_mod.parse_iso(mk.AS_OF) + 2
        col = colony_mod.Colony(os.path.join(user, "companion", "live", "live.json"), clock=lambda: now)
        m = dict(meta or {})
        m["exportFiles"] = ["x.json"] if exported else []
        return modstate.ModState(user, lambda: m, col.read_live, col.live_fresh, self.bundled).compute()

    def test_each_state(self):
        st = self.state(self.folder("m"))
        self.assertEqual(st["state"], "missing")
        self.assertTrue(st["install"]["available"])
        self.assertTrue(any("Install the game mod" in s for s in st["steps"]))
        st = self.state(self.folder("d", local=True, modsjson=[dict(self.ON[0], enabledForDlc=[])]))
        self.assertEqual(st["state"], "disabled")
        self.assertTrue(any("Mods menu" in s for s in st["steps"]))
        st = self.state(self.folder("n", local=True))                 # installed, the game never listed it
        self.assertEqual(st["state"], "disabled")
        st = self.state(self.folder("n2", local=True, modsjson=self.ON), exported=True)
        self.assertEqual(st["state"], "no_live")
        self.assertTrue(any("Player.log" in s for s in st["steps"]))
        st = self.state(self.folder("ok", local=True, modsjson=self.ON, live=self.live))
        self.assertEqual((st["state"], st["steps"]), ("ok", []))
        old = dict(self.live, modVersion="0.3.2")
        st = self.state(self.folder("o", local=True, modsjson=self.ON, live=old, version="0.3.2"))
        self.assertEqual((st["state"], st["compat"]["problem"]), ("version_mismatch", "mod_too_old"))
        too_new = dict(self.live, requiresCore={"min": "9.0.0"})
        st = self.state(self.folder("t", local=True, modsjson=self.ON, live=too_new))
        self.assertEqual((st["state"], st["compat"]["problem"]), ("version_mismatch", "app_too_old"))
        capped = dict(self.live, requiresCore={"min": "1.0.0", "max": "1.2.9"})
        st = self.state(self.folder("c", local=True, modsjson=self.ON, live=capped))
        self.assertEqual(st["compat"]["problem"], "app_too_new")

    def test_spaced_out_decides_which_set_counts(self):
        so_only = [dict(self.ON[0], enabledForDlc=["EXPANSION1_ID"])]
        base_only = self.ON
        live_so = dict(self.live, dlcIds=["EXPANSION1_ID"], state="menu")
        self.assertEqual(self.state(self.folder("a", local=True, modsjson=base_only, live=live_so))["state"], "disabled")
        self.assertNotEqual(self.state(self.folder("b", local=True, modsjson=so_only, live=live_so))["state"], "disabled")
        live_base = dict(self.live, dlcIds=[], state="menu")
        self.assertEqual(self.state(self.folder("c", local=True, modsjson=so_only, live=live_base))["state"], "disabled")

    def test_workshop_copy_blocks_the_local_install(self):
        user = self.folder("w", workshop=True, modsjson=self.ON, live=self.live)
        st = self.state(user)
        self.assertEqual(st["copies"], ["workshop"])
        self.assertFalse(st["install"]["available"])
        self.assertIn("Workshop", st["install"]["reason"])
        ms = modstate.ModState(user, lambda: {}, lambda: None, lambda lv: False, self.bundled)
        with self.assertRaises(ValueError):
            ms.install()
        self.assertFalse(os.path.exists(os.path.join(user, "mods", "Local")))

    def test_update_over_an_older_local_copy_and_nothing_else_is_copied(self):
        user = self.folder("u", local=True, version="0.3.2")
        open(os.path.join(self.bundled, "extra.txt"), "w").write("never copied")
        ms = modstate.ModState(user, lambda: {}, lambda: None, lambda lv: False, self.bundled)
        self.assertTrue(ms._install_info(modstate.find_copies(user))["available"])
        target = ms.install()
        self.assertEqual(sorted(os.listdir(target)), sorted(modstate.BUNDLED_FILES))
        self.assertEqual(modstate._info_version(target), "0.4.0")
        self.assertFalse(ms._install_info(modstate.find_copies(user))["available"])

    def test_version_helpers(self):
        self.assertTrue(modstate.in_range("1.3.0", {"min": "1.3"}))
        self.assertFalse(modstate.in_range("1.2.9", {"min": "1.3"}))
        self.assertFalse(modstate.in_range("2.0", {"min": "1.0", "max": "1.9.9"}))
        self.assertIsNone(modstate.in_range("x", {"min": "1.0"}))

class Tabs(Base):
    def test_codex_label_is_the_games_word(self):
        v, _ = self.views()
        tabs = v.tabs()["tabs"]
        self.assertEqual([t["label"] for t in tabs][:4], ["Colony", "Resources", "Buildings", "Actions"])
        self.assertEqual(tabs[4]["id"], "codex")
        self.assertEqual(tabs[4]["label"], "Database")            # no game strings here: the game's word as fallback
        from core.oni_companion.views.lookup import codex_label
        self.assertEqual(codex_label({"STRINGS.UI.CODEX.TITLE": "DATABASE"}), "Database")
        self.assertEqual(codex_label({"STRINGS.UI.CODEX.TITLE": "<b>Archive</b>"}), "Archive")


class DlcNames(Base):
    def test_export_names_win(self):
        v, _ = self.views()
        self.assertEqual(v.lookup().dlc_name("DLC_BETA_ID"), "Synth Beta Pack")

    def test_settings_lists_dlc_by_name(self):
        v, _ = self.views()
        st = v.status()
        st["game"]["dlcMissingExport"] = ["DLC_BETA_ID"]
        from core.oni_companion.views import settings_view
        scr = settings_view.settings_screen({}, st, v._dlc_name)
        txt = json.dumps(scr)
        self.assertIn("Synth Beta Pack", txt)
        self.assertNotIn("DLC_BETA_ID", txt)


class ToolConstants(Base):
    def test_constants_reach_the_calculators(self):
        v, _ = self.views()
        data = v._tooldata(v.lookup())
        self.assertEqual(data["constants"]["dupeO2KgPerS"], 0.1)
        self.assertEqual(data["constants"]["toolNumbers"]["dupeCo2KgPerS"], 0.02)


if __name__ == "__main__":
    unittest.main()
