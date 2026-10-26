"""C8: the Resources Screen, its in-memory trends, the /resources route.

Synthetic data always runs. The real mirrored live.json (read only) and the real game files run when present.
"""
import copy
import json
import os
import shutil
import tempfile
import unittest

from core.oni_companion.colony import Colony, parse_iso
from core.oni_companion.server import routes
from core.oni_companion.server.errors import ApiError
from core.oni_companion.views import blocks as B
from core.oni_companion.views import resources as R
from core.oni_companion.views.provider import Views
from tests.test_c4_views import (Checks, FIX, HAVE_EXPORT, HAVE_REAL, PROTON_USER, REAL, V, real_config,
                                 synthetic_lookup, load_json)
from core.oni_companion.gamedata import load_dataset
from core.oni_companion.views.lookup import Lookup

MIRROR_LIVE = os.path.expanduser("~/Library/Application Support/oni-companion/nova-user/companion/live/live.json")


def v2_facts(**over):
    live = load_json("mod", "live-running-v2.json")
    out = {k: live[k] for k in ("colonyName", "cycle", "timeOfDay", "paused", "speed", "activeWorldId", "worlds")}
    out.update(source="mod-live", state="running", asOf=live["writtenAt"])
    out.update(over)
    return out


def at(facts, cycle, tod, **amounts):
    """Copy of facts at a game time, with some world 0 amounts changed."""
    f = copy.deepcopy(facts)
    f["cycle"], f["timeOfDay"] = cycle, tod
    for r in f["worlds"][0]["resources"]:
        if r["id"] in amounts:
            r["amount"] = amounts[r["id"]]
    return f


def rows_of(scr):
    out = {}
    for b in B.walk_blocks(scr["blocks"]):
        if b["type"] == "list":
            for it in b["items"]:
                out[it["title"]] = it
    return out


def group_titles(scr):
    return [b["title"] for b in scr["blocks"] if b["type"] == "group"]


class Synthetic(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = synthetic_lookup()

    def test_schema2_groups_in_game_order_with_totals(self):
        scr = R.resources_screen(self.lk, v2_facts(), R.ResourceHistory())
        self.assertScreen(scr, self.lk)
        self.assertEqual(group_titles(scr), ["Metal: 1,500.5 kg", "Food: 28,800 kcal", "Critters: 4"])
        self.assertEqual(scr["source"], "mod-live")
        self.assertEqual(scr["refreshOn"], ["colony"])
        self.assertEqual(scr["filter"], {"placeholder": "Filter resources"})
        self.assertEqual(scr["worldSwitcher"], {"active": 0, "worlds": [{"id": 0, "name": "Home Asteroid"}]})
        rows = rows_of(scr)
        self.assertEqual(rows["Synth Widgetium"]["badge"], "1,200.5 kg")
        self.assertEqual(rows["Synth Widgetium"]["ref"], {"kind": "element", "id": "SynthWidgetium"})
        self.assertEqual(rows["Synth Bar"]["badge"], "12 (28,800 kcal)")
        self.assertEqual(rows["Synth Beast"]["badge"], "4")
        self.assertEqual(rows["Synth Beast"]["ref"], {"kind": "critter", "id": "SynthBeast"})
        self.assertNotIn("ref", rows["Synth Ore"])           # not in the look-up: shown, not tappable
        self.assertIsNone(rows["Synth Ore"].get("subtitle"))  # first start: no trend yet

    def test_game_order_is_kept_not_sorted(self):
        f = v2_facts()
        f["worlds"][0]["resources"] = [
            {"id": "SynthBar", "name": "Zed", "category": "Food", "amount": 1, "unit": "units"},
            {"id": "SynthOre", "name": "Ant", "category": "Zzz", "amount": 2, "unit": "kg"},
            {"id": "SynthWidgetium", "name": "Mid", "category": "Aaa", "amount": 3, "unit": "kg"}]
        scr = R.resources_screen(self.lk, f, None)
        self.assertEqual([t.split(":")[0] for t in group_titles(scr)], ["Food", "Zzz", "Aaa"])

    def test_schema1_map_fallback(self):
        live = load_json("mod", "live-running.json")
        facts = {k: live[k] for k in ("colonyName", "cycle", "timeOfDay", "paused", "speed", "activeWorldId", "worlds")}
        facts.update(source="mod-live", asOf=live["writtenAt"])
        scr = R.resources_screen(self.lk, facts, R.ResourceHistory())
        self.assertScreen(scr, self.lk)
        self.assertEqual(group_titles(scr), ["Minerals: 1,200.5 kg", "Food: 12,000 kcal", "Critters: 4"])
        rows = rows_of(scr)
        self.assertEqual(rows["Synth Bar"]["badge"], "12 (12,000 kcal)")

    def test_schema1_drops_unknown_tags(self):
        facts = v2_facts()
        facts["worlds"][0]["resources"] = {"SynthWidgetium": 5, "Pickupable": 99999, "Reachable": 5}
        scr = R.resources_screen(self.lk, facts, None)
        self.assertEqual(list(rows_of(scr)), ["Widgetium", "Synth Beast"])

    def test_filter(self):
        scr = R.resources_screen(self.lk, v2_facts(), None, q="BAR")
        self.assertEqual(list(rows_of(scr)), ["Synth Bar"])
        self.assertEqual(len(group_titles(scr)), 1)
        self.assertTrue(group_titles(scr)[0].startswith("Food:"))      # the category total stays whole
        none = R.resources_screen(self.lk, v2_facts(), None, q="zzzz")
        self.assertEqual([b["type"] for b in none["blocks"]], ["notice"])
        self.assertScreen(none, self.lk)

    def test_world_switcher_and_choice(self):
        f = v2_facts()
        w2 = copy.deepcopy(f["worlds"][0])
        w2["id"], w2["name"] = 1, "Far Asteroid"
        w2["resources"] = [{"id": "SynthOre", "name": "Synth Ore", "category": "Metal", "amount": 7, "unit": "kg"}]
        f["worlds"].append(w2)
        scr = R.resources_screen(self.lk, f, None)
        self.assertEqual(scr["subtitle"], "Home Asteroid")
        self.assertEqual([w["id"] for w in scr["worldSwitcher"]["worlds"]], [0, 1])
        far = R.resources_screen(self.lk, f, None, world="1")
        self.assertEqual(far["subtitle"], "Far Asteroid")
        self.assertEqual(far["worldSwitcher"]["active"], 1)
        self.assertEqual(list(rows_of(far)), ["Synth Ore"])
        with self.assertRaises(KeyError):
            R.resources_screen(self.lk, f, None, world="9")
        f["activeWorldId"] = 1
        self.assertEqual(R.resources_screen(self.lk, f, None)["subtitle"], "Far Asteroid")

    def test_art_hook(self):
        seen = []

        def art(kind, ident):
            seen.append((kind, ident))
            return "/api/v1/art/%s/%s" % (kind, ident) if ident != "SynthOre" else None
        scr = R.resources_screen(self.lk, v2_facts(), None, art=art)
        self.assertScreen(scr, self.lk)
        rows = rows_of(scr)
        self.assertEqual(rows["Synth Widgetium"]["art"], "/api/v1/art/element/SynthWidgetium")
        self.assertEqual(rows["Synth Widgetium"]["ref"]["art"], "/api/v1/art/element/SynthWidgetium")
        self.assertEqual(rows["Synth Bar"]["art"], "/api/v1/art/food/SynthBar")
        self.assertEqual(rows["Synth Beast"]["art"], "/api/v1/art/critter/SynthBeast")
        self.assertNotIn("art", rows["Synth Ore"])
        self.assertIn(("item", "SynthOre"), seen)

    def test_sources_without_live(self):
        none = R.resources_screen(self.lk, {"source": "none", "state": "saved"}, None)
        self.assertScreen(none, self.lk)
        hdr = R.resources_screen(self.lk, {"source": "header", "state": "saved", "colonyName": "X", "cycle": 5}, None)
        self.assertScreen(hdr, self.lk)
        self.assertEqual(hdr["source"], "header")
        f = v2_facts()
        f["source"], f["state"] = "save", "saved"
        f["worlds"][0]["resources"] = {"SynthWidgetium": 10.5, "SynthBar": 3}
        scr = R.resources_screen(self.lk, f, R.ResourceHistory())
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["source"], "save")
        self.assertFalse([b for b in scr["blocks"] if b["type"] == "notice"])
        self.assertIsNone(rows_of(scr)["Widgetium"].get("subtitle"))


class Trends(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = synthetic_lookup()

    def sub(self, hist, facts, name="Synth Widgetium"):
        return rows_of(R.resources_screen(self.lk, facts, hist))[name]

    def test_first_start_has_no_trend_then_a_cycle_later_it_does(self):
        h = R.ResourceHistory()
        base = v2_facts()
        t0 = at(base, 12, 0.0, SynthWidgetium=1000, SynthBar=10)
        self.assertIsNone(self.sub(h, t0).get("subtitle"))
        h.record(t0)
        self.assertIsNone(self.sub(h, t0).get("subtitle"))                    # one snapshot: no span
        for i in range(1, 12):                                                # every ~50 game seconds
            h.record(at(base, 12, i / 12.0, SynthWidgetium=1000 + 3 * i, SynthBar=10))
        t1 = at(base, 13, 0.0, SynthWidgetium=1040, SynthBar=9)
        it = self.sub(h, t1)
        self.assertEqual(it["subtitle"], "+40 kg since last cycle")
        self.assertEqual(it["tone"], "good")
        bar = self.sub(h, t1, "Synth Bar")
        self.assertEqual(bar["subtitle"], "-2,400 kcal since last cycle")   # one unit fewer, 2400 kcal each
        self.assertEqual(bar["tone"], "warn")

    def test_short_history_says_how_long(self):
        h = R.ResourceHistory()
        base = v2_facts()
        h.record(at(base, 12, 0.0, SynthWidgetium=100))
        now = at(base, 12, 0.3, SynthWidgetium=90)          # 180 game seconds later
        it = self.sub(h, now)
        self.assertEqual(it["subtitle"], "-10 kg in 3 min")
        self.assertEqual(it["tone"], "warn")
        h2 = R.ResourceHistory()
        h2.record(at(base, 12, 0.0, SynthWidgetium=100))
        self.assertIsNone(self.sub(h2, at(base, 12, 0.02, SynthWidgetium=90)).get("subtitle"))   # 12 s: too short

    def test_no_change_and_new_item(self):
        h = R.ResourceHistory()
        base = v2_facts()
        h.record(at(base, 12, 0.0, SynthWidgetium=100))
        now = at(base, 12, 0.5, SynthWidgetium=100.2)
        self.assertEqual(self.sub(h, now)["subtitle"], "No change")
        # an item that was not there at the start counts from zero
        h3 = R.ResourceHistory()
        early = at(base, 12, 0.0)
        early["worlds"][0]["resources"] = [r for r in early["worlds"][0]["resources"] if r["id"] != "SynthOre"]
        h3.record(early)
        self.assertEqual(self.sub(h3, at(base, 12, 0.5), "Synth Ore")["subtitle"], "+300 kg in 5 min")

    def test_critter_counts_trend(self):
        h = R.ResourceHistory()
        base = v2_facts()
        h.record(at(base, 12, 0.0))
        now = at(base, 12, 0.5, SynthBeast=6)
        self.assertEqual(self.sub(h, now, "Synth Beast")["subtitle"], "+2 in 5 min")

    def test_history_thins_prunes_and_resets(self):
        h = R.ResourceHistory()
        base = v2_facts()
        h.record(at(base, 12, 0.0))
        self.assertFalse(h.record(at(base, 12, 0.003)))      # 1.8 s later: thinned out
        self.assertTrue(h.record(at(base, 12, 0.01)))        # 6 s later
        for i in range(1, 40):                               # 40 snapshots 60 s apart
            h.record(at(base, 12 + i // 10, (i % 10) / 10.0))
        n = len(h._snaps[0])
        self.assertLessEqual(n, int(R.WINDOW_S / R.STEP_S) + 1)
        self.assertGreaterEqual(h._snaps[0][0][0], h._last_gt - R.WINDOW_S)
        # loading an older save: game time jumps back, the history starts over
        h.record(at(base, 3, 0.5))
        self.assertEqual(len(h._snaps[0]), 1)
        # another colony: starts over too
        h.record(at(base, 3, 0.9, ))
        other = at(base, 3, 0.95)
        other["colonyName"] = "Other"
        h.record(other)
        self.assertEqual(len(h._snaps[0]), 1)

    def test_only_live_is_recorded_and_nothing_is_saved(self):
        h = R.ResourceHistory()
        f = v2_facts(source="save")
        self.assertFalse(h.record(f))
        self.assertEqual(h._snaps, {})
        self.assertFalse(h.record({"source": "mod-live", "worlds": []}))     # no game time
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                h.record(v2_facts())
                self.assertEqual(os.listdir(d), [])
            finally:
                os.chdir(cwd)

    def test_baseline_by_world(self):
        h = R.ResourceHistory()
        f = v2_facts()
        w2 = copy.deepcopy(f["worlds"][0])
        w2["id"], w2["name"] = 1, "Far"
        f["worlds"].append(w2)
        h.record(f)
        g = copy.deepcopy(f)
        g["timeOfDay"] = f["timeOfDay"] + 0.2
        gt = R.game_time(g)
        self.assertIsNotNone(h.baseline(0, gt))
        self.assertIsNotNone(h.baseline(1, gt))
        self.assertIsNone(h.baseline(7, gt))


class Route(unittest.TestCase, Checks):
    """Views.resources and GET /resources through the router, with a live file written to a temp folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = os.path.join(self.tmp.name, "live.json")
        shutil.copy(os.path.join(FIX, "mod", "live-running-v2.json"), self.live)
        self.colony = Colony(self.live, clock=lambda: parse_iso("2026-01-01T12:00:05Z"))

        class Ctx:
            pass
        self.ctx = Ctx()
        self.ctx.colony = self.colony
        self.lk = synthetic_lookup()
        self.views = Views(self.ctx, lookup=self.lk)

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, target):
        return routes.dispatch("GET", target, None, self.ctx, self.views)

    def test_schema2_live_is_read_and_served(self):
        scr = self.get("/api/v1/resources")
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["source"], "mod-live")
        self.assertEqual(len(group_titles(scr)), 3)

    def test_query_parameters(self):
        scr = self.get("/api/v1/resources?q=beast&world=0")
        self.assertEqual(list(rows_of(scr)), ["Synth Beast"])
        with self.assertRaises(ApiError) as cm:
            self.get("/api/v1/resources?world=5")
        self.assertEqual(cm.exception.code, "not_found")
        self.assertEqual(len(group_titles(self.get("/api/v1/resources?world="))), 3)

    def test_no_colony(self):
        os.remove(self.live)
        scr = self.get("/api/v1/resources")
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["source"], "none")

    def test_history_listener_records_on_colony_events(self):
        import time
        from core.oni_companion.server.events import EventBus
        self.ctx.bus = EventBus()
        t = self.views.start_history()
        try:
            time.sleep(0.2)
            self.ctx.bus.publish("colony")
            for _ in range(50):
                if self.views.history._snaps:
                    break
                time.sleep(0.05)
            self.assertIn(0, self.views.history._snaps)
        finally:
            self.ctx.bus.close()
            t.join(2)
        self.assertFalse(t.is_alive())

    def test_response_validates_against_the_example_shape(self):
        mine, ex = self.get("/api/v1/resources"), load_json("screens", "resources.json")
        self.assertEqual(set(ex) - set(mine), set())


@unittest.skipUnless(os.path.isfile(MIRROR_LIVE), "no mirrored live.json (read only test)")
class RealLive(unittest.TestCase, Checks):
    """The real Nova live.json (schema 1 today), read only, with the synthetic look-up and the real one."""

    @classmethod
    def setUpClass(cls):
        with open(MIRROR_LIVE, encoding="utf-8") as f:
            cls.written = json.load(f)["writtenAt"]
        cls.colony = Colony(MIRROR_LIVE, clock=lambda: parse_iso(cls.written))
        cls.facts = cls.colony.facts()

    def test_live_file_is_read(self):
        self.assertEqual(self.facts["source"], "mod-live")
        self.assertTrue(self.facts["worlds"])

    def test_with_the_synthetic_lookup_every_id_is_dropped_cleanly(self):
        scr = R.resources_screen(synthetic_lookup(), self.facts, R.ResourceHistory())
        self.assertScreen(scr)

    @unittest.skipUnless(HAVE_REAL and HAVE_EXPORT, "real game files + mod export not present")
    def test_with_the_real_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "user")
            shutil.copytree(os.path.join(PROTON_USER, "companion"), os.path.join(user, "companion"))
            cfg = real_config(tmp, user)
            lk = Lookup(load_dataset(cfg), cfg.assets_dir)
            hist = R.ResourceHistory()
            hist.record(self.facts)
            scr = R.resources_screen(lk, self.facts, hist)
            self.assertScreen(scr, lk)
            rows = rows_of(scr)
            raw = self.facts["worlds"][0]["resources"]
            print("\nREAL live.json: %d map entries -> %d rows in groups %s" % (len(raw), len(rows), group_titles(scr)))
            self.assertGreater(len(rows), 20)
            self.assertNotIn("Pickupable", [r.lower() for r in map(str.title, rows)])
            # an amount from the file shows up unchanged
            e = lk.get("element", "Oxygen")
            if isinstance(raw, list):   # live schema 2 (mod 0.2.0+): a categorized list
                ox = next(r for r in raw if r.get("id") == "Oxygen")
                self.assertEqual(rows[e["name"]]["badge"], R.amount_text(ox))
            else:                       # live schema 1: tag -> kg map
                self.assertEqual(rows[e["name"]]["badge"], R.amount_text({"unit": "kg", "amount": raw["Oxygen"]}))
            for it in rows.values():
                self.assertIsNone(it.get("subtitle"))
            self.assertEqual(scr["worldSwitcher"]["active"], self.facts["activeWorldId"])


if __name__ == "__main__":
    unittest.main()
