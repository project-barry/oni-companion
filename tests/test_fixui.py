"""Fixes from the first Simulator test: building lists, the build-menu label, the newest save's cycle."""
import os
import struct
import json
import tempfile
import unittest

from core.oni_companion.colony import Colony
from core.oni_companion.gamedata import Dataset, merge
from core.oni_companion.index import Index
from core.oni_companion.views import blocks as B
from core.oni_companion.views import entry as entry_view
from core.oni_companion.views import listing
from core.oni_companion.views.lookup import Lookup


def export(buildings):
    return {"name": "gamedata-1-X.json", "data": {"dlcIds": ["DLC2_ID"], "build": 1, "buildings": buildings}}


def pot(i, name, **kw):
    return dict({"id": i, "name": name, "dlc": [], "dlcKnown": False, "source": "pot"}, **kw)


class TestBuildingsFromExport(unittest.TestCase):
    def setUp(self):
        exp = export([{"id": "Tile", "name": "Tile", "category": "Base", "dlc": []},
                      {"id": "CritterCondo", "name": "Critter Condo", "category": "Food", "dlc": []},
                      {"id": "PropWall", "name": "Wall", "category": "Uncategorized", "dlc": []}])
        fb = {"building": [pot("TILE", "Tile"), pot("DEVHEATER", "Dev Heater"),
                           pot("STEAMTURBINE", "[DEPRECATED] Steam Turbine", effect="CANNOT BE BUILT"),
                           pot("BATTERYMODULE", "Battery Module")],
          "trait": [pot("ANXIOUS", "Anxious"), pot("OLDTRAIT", "[DEPRECATED] Old", desc="x")]}
        kinds = merge.merge(fb, [exp])
        self.ds = Dataset(kinds, {"builtAt": "2026-10-25T00:00:00Z", "exportFiles": ["x"]}, "k", False, {})
        self.ix = Index(self.ds)

    def test_only_export_buildings_are_listed(self):
        ids = [r["id"] for r in self.ix.list_kind("building")]
        self.assertEqual(sorted(ids), ["CritterCondo", "PropWall", "Tile"])
        self.assertEqual({c["kind"]: c["count"] for c in self.ix.kind_counts()}["building"], 3)
        self.assertEqual(self.ix.search("dev heater")["results"], [])

    def test_other_kinds_keep_the_pot_but_deprecated_is_hidden(self):
        self.assertEqual([r["id"] for r in self.ix.list_kind("trait")], ["ANXIOUS"])
        self.assertEqual(self.ix.search("old")["results"], [])
        # a hidden entry still resolves by id (old saves may name it)
        self.assertIsNotNone(self.ix.get("trait", "OLDTRAIT"))

    def test_no_export_keeps_the_pot_buildings(self):
        kinds = merge.merge({"building": [pot("DEVHEATER", "Dev Heater")]}, [])
        self.assertIn("DEVHEATER", kinds["building"])

    def test_subtitles_name_the_build_menu(self):
        sub = {r["id"]: self.ix.subtitle("building", r) for r in self.ix.list_kind("building")}
        self.assertEqual(sub["Tile"], "Build menu: Base")
        self.assertEqual(sub["CritterCondo"], "Build menu: Food")
        self.assertEqual(sub["PropWall"], "Not in a build menu")

    def test_building_page_has_one_dlc_chip_and_a_build_menu_stat(self):
        lk = Lookup(self.ds)
        scr = entry_view.entry_screen(lk, "building", lk.get("building", "Tile"))
        chips = [c for b in scr["blocks"] if b["type"] == "chips" for c in b["chips"]]
        self.assertEqual([c["label"] for c in chips], ["Base game"])
        stats = {r["label"]: r["value"] for b in scr["blocks"] if b["type"] == "stats" for r in b["rows"]}
        self.assertEqual(stats["Build menu"], "Base")
        lst = listing.list_screen(lk, "building")
        self.assertEqual(lst["subtitle"], "3 entries")


class TestNewestSaveCycle(unittest.TestCase):
    def test_header_cycle_wins_over_the_file_name(self):
        d = tempfile.mkdtemp(prefix="oni-save-")
        p = os.path.join(d, "Bunker Cycle 428.sav")
        hdr = json.dumps({"numberOfCycles": 419}).encode()
        with open(p, "wb") as f:
            f.write(struct.pack("<IIII", 1, len(hdr), 1, 1) + hdr + b"body")
        sv = Colony(None, [d]).newest_save()
        self.assertEqual(sv["cycle"], 420)
        self.assertEqual(sv["name"], "Bunker Cycle 428")      # the file name stays a separate field


if __name__ == "__main__":
    unittest.main()
