"""C14: building page against the real export (Airborne Critter Trap, Electrolyzer, Door, sensor, Wire Bridge),
Settings DLC notice, dupe status text. Real-data tests run only when fixtures/real holds the game and an export."""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.oni_companion import config  # noqa: E402
from core.oni_companion.gamedata import load_dataset  # noqa: E402
from core.oni_companion.views import buildings as bv  # noqa: E402
from core.oni_companion.views import entry as entry_view  # noqa: E402
from core.oni_companion.views import settings_view  # noqa: E402
from core.oni_companion.views.lookup import Lookup  # noqa: E402

REAL = os.path.join(ROOT, "fixtures", "real")
HAVE = bool(glob.glob(os.path.join(REAL, "user", "companion", "export", "gamedata-*.json"))) and \
    os.path.isdir(os.path.join(REAL, "OxygenNotIncluded_Data"))


def walk(n):
    if isinstance(n, dict):
        yield n
        for v in n.values():
            yield from walk(v)
    elif isinstance(n, list):
        for v in n:
            yield from walk(v)


def texts(n):
    return [s.get("text", "") for b in walk(n) for s in b.get("spans", []) if isinstance(s, dict)]


class Signals(unittest.TestCase):
    def test_game_text_naming_the_signal_is_not_prefixed_twice(self):
        e = {"id": "X", "ports": [{"kind": "logic", "direction": "in", "name": "Open/Close",
                                   "greenText": "Green Signal: Open", "redText": "Red Signal: Close and lock"}]}
        grp = bv.automation_blocks(e)[0]
        self.assertEqual(texts(grp), ["Open/Close", "Green Signal: Open", "Red Signal: Close and lock"])
        colors = [s.get("color") for b in walk(grp) for s in b.get("spans", [])]
        self.assertEqual(colors, [None, "positive", "negative"])

    def test_plain_text_gets_the_signal_label(self):
        e = {"id": "X", "ports": [{"kind": "logic", "direction": "out", "name": "Status",
                                   "greenText": "A critter is inside.", "redText": "Empty."}]}
        self.assertEqual(texts(bv.automation_blocks(e)[0])[1:], ["Green signal: A critter is inside.", "Red signal: Empty."])

    def test_unnamed_port_without_strings_is_hidden(self):
        self.assertEqual(bv.automation_blocks({"id": "X", "ports": [{"kind": "logic", "direction": "in"}]}), [])


class Settings(unittest.TestCase):
    def test_notice_has_names_and_no_mod_talk(self):
        st = {"game": {"dlcMissingExport": ["EXPANSION1_ID"], "found": True}, "mod": {}, "cache": {}, "colony": {}}
        scr = settings_view.settings_screen({}, st, lambda d: "Spaced Out!")
        n = [b for b in scr["blocks"] if b.get("type") == "notice"][0]
        self.assertIn("Spaced Out!", n["text"])
        self.assertNotIn("EXPANSION1_ID", json.dumps(scr))
        self.assertNotIn("mod", (n["title"] + n["text"]).lower())


@unittest.skipUnless(HAVE, "fixtures/real missing")
class RealPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="c14real")
        cfg = config.load(env={"HOME": cls.tmp}, game_dir=REAL, user_dir=os.path.join(REAL, "user"), data_dir=cls.tmp)
        cls.lk = Lookup(load_dataset(cfg), cfg.assets_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def page(self, bid):
        return entry_view.entry_screen(self.lk, "building", self.lk.get("building", bid))

    def titles(self, scr):
        return [b.get("title") for b in scr["blocks"] if b.get("type") in ("group", "ports")]

    def test_airborne_critter_trap(self):
        scr = self.page("CreatureAirTrap")
        flat = json.dumps(scr)
        self.assertNotIn("Flow", self.titles(scr))
        self.assertNotIn("Logic in", flat)
        self.assertNotIn("20000", flat)
        grp = [b for b in scr["blocks"] if b.get("title") == "Research"][0]
        it = grp["blocks"][0]["items"][0]
        self.assertEqual((it["title"], it["ref"]), ("Animal Control", {"kind": "tech", "id": "AnimalControl"}))
        self.assertEqual(it["subtitle"], "35 Novice Research, 30 Advanced Research")

    def test_electrolyzer_flow_names_the_elements_once(self):
        flow = [b for b in self.page("Electrolyzer")["blocks"] if b.get("title") == "Flow"][0]
        self.assertEqual([(p["label"], p["rate"], p["unit"]) for p in flow["inputs"]],
                         [("Water", 1000, "g/s"), ("Power in", 120, "W")])
        self.assertEqual([p["label"] for p in flow["outputs"]], ["Oxygen", "Hydrogen Gas"])

    def test_door_uses_the_games_strings_for_its_automation_port(self):
        scr = self.page("Door")
        grp = [b for b in scr["blocks"] if b.get("title") == "Automation"][0]
        self.assertEqual(texts(grp), ["Open/Close", "Green Signal: Open", "Red Signal: Close and lock"])

    def test_germ_sensor(self):
        grp = [b for b in self.page("LogicDiseaseSensor")["blocks"] if b.get("title") == "Automation"][0]
        self.assertEqual(texts(grp)[0], "Germ Count")
        self.assertEqual(texts(grp)[2], "Otherwise, sends a Red Signal")

    def test_wire_bridge_has_no_flow_or_automation(self):
        t = self.titles(self.page("WireBridge"))
        self.assertNotIn("Flow", t)
        self.assertNotIn("Automation", t)

    def test_dlc_names_are_the_games(self):
        self.assertEqual(self.lk.dlc_name("EXPANSION1_ID"), "Spaced Out!")


@unittest.skipUnless(HAVE, "fixtures/real missing")
class DupeStatusText(unittest.TestCase):
    def test_status_names_pass_through_as_the_game_wrote_them(self):
        """The game's BreathingO2 text is GetFormattedMass(0 - averageRate) of a positive accumulator, so its own
        text carries the minus (decompiled: DuplicantStatusItems, OxygenBreather). The page shows it unchanged."""
        from core.oni_companion.views import colony as cv
        d = {"id": 1, "name": "Ruby", "statusItems": [{"id": "BreathingO2", "name": "Inhaling -83.9 g/s O2", "severity": "neutral"}]}
        blocks = cv._status_blocks(d, False, [])
        self.assertEqual(blocks[0]["items"][0]["title"], "Inhaling -83.9 g/s O2")


if __name__ == "__main__":
    unittest.main()
