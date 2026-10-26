"""C10: Colony overview, warning badges, duplicant page, onOpen, settings and their persistence."""
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import colony as colony_mod  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.settings import Settings, SettingsError  # noqa: E402
from oni_companion.views import colony as cv  # noqa: E402
from oni_companion.views.provider import Views  # noqa: E402
from tests.test_c4_views import AS_OF, FIX, Checks, load_json, synthetic_lookup  # noqa: E402

TOKEN = "c10-token"
SYNTH = synthetic_lookup


def facts_v2(**over):
    d = dict(load_json("mod", "live-running-v2.json"), source="mod-live", state="running", asOf=AS_OF)
    d.update(over)
    return d


def dupe(id_, name="X", **kw):
    d = {"id": id_, "name": name, "stress": 10, "health": {"value": 100, "max": 100},
         "calories": {"value": 3000, "max": 4000}, "breath": {"value": 100, "max": 100},
         "statusItems": [], "diseases": []}
    d.update(kw)
    return d


def si(id_, name, sev):
    return {"id": id_, "name": name, "severity": sev}


def labels(b):
    return [(x["level"], x["label"]) for x in b]


class BadgeMapping(unittest.TestCase):
    def test_game_status_items_map_to_levels(self):
        d = dupe("a", statusItems=[
            si("Cozy", "Cozy", "good"),
            si("Hungry", "Hungry", "minorBad"),
            si("Suffocating", "Suffocating", "bad"),
            si("Stressed", "Stressed", "bad"),
            si("Starving", "Starving", "bad"),
            si("Hot", "Too Hot", "minorBad"),
            si("Cold", "Freezing", "bad"),
            si("Weird", "Weird Thing", "bad"),
            si("Neutral", "Looking around", "neutral")])
        b = cv.status_badges(d)
        self.assertEqual(labels(b), [
            ("danger", "Suffocating"), ("danger", "Starving"),
            ("warn", "Stressed"), ("warn", "Too hot"), ("warn", "Too cold"), ("warn", "Weird Thing"),
            ("info", "Hungry")])

    def test_good_and_neutral_make_no_badge(self):
        d = dupe("a", statusItems=[si("Cozy", "Cozy", "good"), si("N", "Idle", "neutral")])
        self.assertEqual(cv.status_badges(d), [])

    def test_incapacitated_is_danger_and_diseases_are_sick_once(self):
        d = dupe("a", statusItems=[si("Incapacitated", "Incapacitated", "bad"), si("Sick", "Sick", "bad")],
                 diseases=[{"id": "SlimeLung", "name": "Slimelung"}, {"id": "FoodSick", "name": "Food Poisoning"}])
        self.assertEqual(labels(cv.status_badges(d)), [("danger", "Incapacitated"), ("warn", "Sick")])

    def test_diseases_alone_make_sick(self):
        d = dupe("a", diseases=[{"id": "x", "name": "Slimelung"}])
        self.assertEqual(labels(cv.status_badges(d)), [("warn", "Sick")])

    def test_status_items_win_over_the_table(self):
        # stress 99 would be "critical" by the table, but the game's own list says nothing is wrong
        d = dupe("a", stress=99)
        badges, est = cv.badges_for(d, cv.LIMITS)
        self.assertEqual((badges, est), ([], False))

    def test_fallback_table_is_marked_estimated(self):
        d = dupe("a", stress=99, calories={"value": 100, "max": 4000})
        del d["statusItems"], d["diseases"]
        badges, est = cv.badges_for(d, cv.LIMITS)
        self.assertTrue(est)
        self.assertEqual(labels(badges), [("danger", "Stress critical"), ("danger", "Starving")])

    def test_fallback_limits_come_from_export_constants(self):
        d = dupe("a", stress=40)
        del d["statusItems"], d["diseases"]
        self.assertEqual(cv.badges_for(d, cv.limits_for(None))[0], [])
        lim = cv.limits_for({"dupeLimits": {"stressWarn": 30, "bogus": 1, "stressDanger": "x"}})
        self.assertEqual(lim["stressWarn"], 30)
        self.assertEqual(lim["stressDanger"], cv.LIMITS["stressDanger"])
        self.assertNotIn("bogus", lim)
        self.assertEqual(labels(cv.badges_for(d, lim)[0]), [("warn", "Stressed")])
        self.assertEqual(cv.LIMITS["stressWarn"], 60)            # the table itself is never changed


class Overview(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = SYNTH()

    def test_cards_are_short_and_sorted(self):
        scr = cv.colony_screen(self.lk, facts_v2())
        self.assertScreen(scr, self.lk)
        grid = [b for b in scr["blocks"] if b["type"] == "grid"][0]
        names = [c["title"] for c in grid["cards"]]
        self.assertEqual(names, ["Bo", "Ada"])                   # Bo has a danger badge: first
        bo, ada = grid["cards"]
        self.assertEqual([m["label"] for m in bo["meters"]], ["Stress", "Health", "Calories"])
        self.assertNotIn("stats", bo)
        self.assertEqual(bo["ref"], {"kind": "dupe", "id": "d2"})
        self.assertEqual(labels(bo["badges"])[0], ("danger", "Suffocating"))
        self.assertEqual(bo["tone"], "bad")
        self.assertEqual(labels(ada["badges"]), [("info", "Hungry")])
        self.assertNotIn("art", bo)                              # no art hook: no art

    def test_healthy_card_has_no_badges_key(self):
        f = facts_v2()
        f["worlds"][0]["dupes"] = [dupe("h1", "Hale")]
        card = [b for b in cv.colony_screen(self.lk, f)["blocks"] if b["type"] == "grid"][0]["cards"][0]
        self.assertNotIn("badges", card)
        self.assertEqual(card["tone"], "good")

    def test_rest_keep_the_games_order(self):
        f = facts_v2()
        f["worlds"][0]["dupes"] = [dupe("1", "A"), dupe("2", "B", statusItems=[si("S", "Suffocating", "bad")]),
                                   dupe("3", "C", statusItems=[si("H", "Hungry", "minorBad")]),
                                   dupe("4", "D", statusItems=[si("S", "Starving", "bad")]), dupe("5", "E")]
        grid = [b for b in cv.colony_screen(self.lk, f)["blocks"] if b["type"] == "grid"][0]
        self.assertEqual([c["title"] for c in grid["cards"]], ["B", "D", "A", "C", "E"])

    def test_many_badges_are_capped(self):
        f = facts_v2()
        f["worlds"][0]["dupes"] = [dupe("1", "A", statusItems=[si("x%d" % i, "Bad%d" % i, "bad") for i in range(7)])]
        card = [b for b in cv.colony_screen(self.lk, f)["blocks"] if b["type"] == "grid"][0]["cards"][0]
        self.assertEqual(len(card["badges"]), cv.MAX_BADGES)
        self.assertEqual(card["badges"][-1], {"level": "info", "label": "+4 more"})

    def test_schema_1_live_uses_estimates_without_a_notice(self):
        f = dict(load_json("mod", "live-running.json"), source="mod-live", state="running", asOf=AS_OF)
        f["worlds"][0]["dupes"][0]["stress"] = 95
        scr = cv.colony_screen(self.lk, f)
        self.assertScreen(scr, self.lk)
        self.assertFalse([b for b in scr["blocks"] if b["type"] == "notice" and "estimated" in (b.get("text") or "")])
        card = [b for b in scr["blocks"] if b["type"] == "grid"][0]["cards"][0]
        self.assertEqual(labels(card["badges"]), [("danger", "Stress critical")])

    def test_header_alerts_first_and_worst_first(self):
        f = facts_v2()
        f["worlds"][0]["alerts"] = [{"id": "i", "level": "info", "text": "FYI", "count": 1},
                                    {"id": "b", "level": "bad", "text": "Low air", "count": 2}]
        scr = cv.colony_screen(self.lk, f)
        types = [b["type"] for b in scr["blocks"]]
        self.assertEqual(types[0], "stats")
        self.assertLess(types.index("list"), types.index("grid"))
        alerts = scr["blocks"][types.index("list")]
        self.assertEqual([i["title"] for i in alerts["items"]], ["Low air", "FYI"])
        rows = {r["label"]: r["value"] for r in scr["blocks"][0]["rows"]}
        self.assertEqual((rows["Cycle"], rows["Time of day"], rows["Speed"]), (12, "42%", "2x"))

    def test_art_hook_fills_card_and_ref(self):
        art = lambda d: "/api/v1/art/dupe/%s" % d["id"]            # noqa: E731
        scr = cv.colony_screen(self.lk, facts_v2(), art_dupe=art)
        self.assertScreen(scr, self.lk)
        card = [b for b in scr["blocks"] if b["type"] == "grid"][0]["cards"][0]
        self.assertEqual(card["art"], "/api/v1/art/dupe/d2")
        self.assertEqual(card["ref"]["art"], "/api/v1/art/dupe/d2")

    def test_v2_resource_list_does_not_break_the_colony(self):
        scr = cv.colony_screen(self.lk, facts_v2())
        self.assertNotIn("Resources", json.dumps(scr["blocks"]).replace("Resources tab", ""))


class DupePage(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = SYNTH()

    def page(self, id_="d1", zoom=False, **kw):
        return cv.dupe_screen(self.lk, facts_v2(), id_, zoom, **kw)

    def focus(self, scr):
        for b in scr["blocks"]:
            for it in b.get("items") or []:
                for a in it.get("actions") or []:
                    return a
        return None

    def test_complete_page_validates(self):
        scr = self.page("d2", art_dupe=lambda d: "/api/v1/art/dupe/%s" % d["id"])
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["title"], "Bo")
        self.assertEqual(scr["blocks"][0]["type"], "image")
        text = json.dumps(scr)
        for want in ("Stamina", "Body temperature", "38.6 C", "Bladder", "Breath", "Suffocating", "Slimelung",
                     "Quick", "Digging"):
            self.assertIn(want, text)
        st = [b for b in scr["blocks"] if b.get("title") == "Status"][0]["blocks"]
        self.assertEqual([i["title"] for i in st[0]["items"]], ["Suffocating", "Stressed"])
        self.assertEqual(st[1]["items"][0]["title"], "Slimelung")

    def test_page_without_art_has_no_image(self):
        self.assertNotIn("image", [b["type"] for b in self.page()["blocks"]])

    def test_show_in_game_always_present(self):
        for zoom in (False, True):
            for id_ in ("d1", "d2"):
                a = self.focus(self.page(id_, zoom))
                self.assertEqual(a["id"], "focus")
                self.assertEqual(a["label"], "Show in game")
                self.assertEqual(a["args"], {"target": {"kind": "dupe", "id": id_}, "select": True})

    def test_on_open_only_when_the_setting_is_on(self):
        self.assertNotIn("onOpen", self.page("d1", False))
        on = self.page("d1", True)
        self.assertEqual(on["onOpen"], [{"action": "focus", "args": {"target": {"kind": "dupe", "id": "d1"}, "select": True}}])
        self.assertScreen(on, self.lk)

    def test_unknown_dupe_is_none(self):
        self.assertIsNone(self.page("nope"))

    def test_estimated_page(self):
        f = dict(load_json("mod", "live-running.json"), source="mod-live", state="running", asOf=AS_OF)
        f["worlds"][0]["dupes"][0]["stress"] = 95
        scr = cv.dupe_screen(self.lk, f, "d1")
        self.assertScreen(scr, self.lk)
        self.assertIn("estimated", json.dumps(scr))

    def test_from_a_save_the_button_says_what_it_needs(self):
        f = facts_v2(source="save")
        scr = cv.dupe_screen(self.lk, f, "d1")
        self.assertIn("Needs the game running", json.dumps(scr))
        self.assertEqual(self.focus(scr)["id"], "focus")


class SettingsStore(unittest.TestCase):
    def test_defaults_and_kept_after_restart(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "data", "settings.json")
            s = Settings(p)
            self.assertIs(s.get("zoomToDupeOnSelect"), False)
            s.update({"zoomToDupeOnSelect": True})
            self.assertIs(Settings(p).get("zoomToDupeOnSelect"), True)       # a new process
            with open(p) as f:
                self.assertEqual(json.load(f), {"schema": 1, "zoomToDupeOnSelect": True})
            self.assertEqual(os.listdir(os.path.dirname(p)), ["settings.json"])   # no temp file left

    def test_bad_value_saves_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "settings.json")
            s = Settings(p)
            for bad in ("yes", 1, None):
                with self.assertRaises(SettingsError) as cm:
                    s.update({"zoomToDupeOnSelect": bad})
                self.assertIn("zoomToDupeOnSelect", str(cm.exception))
            self.assertFalse(os.path.exists(p))
            with self.assertRaises(SettingsError):
                s.update([])

    def test_unknown_keys_ignored_in_post_and_kept_in_file(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "settings.json")
            with open(p, "w") as f:
                json.dump({"schema": 1, "futureThing": [1, 2]}, f)
            s = Settings(p)
            s.update({"zoomToDupeOnSelect": True, "other": 5})
            with open(p) as f:
                self.assertEqual(json.load(f), {"schema": 1, "zoomToDupeOnSelect": True, "futureThing": [1, 2]})

    def test_damaged_file_means_defaults(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "settings.json")
            for text in ("{not json", "[1]", json.dumps({"schema": 1, "zoomToDupeOnSelect": "maybe"})):
                with open(p, "w") as f:
                    f.write(text)
                self.assertIs(Settings(p).get("zoomToDupeOnSelect"), False)

    def test_on_change_runs_after_save(self):
        hits = []
        s = Settings(None, lambda: hits.append(1))
        s.update({"zoomToDupeOnSelect": True})
        self.assertEqual(hits, [1])
        self.assertIs(s.get("zoomToDupeOnSelect"), True)


def http(svc, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d/api/v1%s" % (svc.port, path), data=data, method=method,
                                 headers={"X-Oni-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        finally:
            e.close()


class Endpoints(unittest.TestCase, Checks):
    """The whole path: HTTP, routes, views, settings file, event bus, live file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user = os.path.join(self.tmp.name, "user")
        self.data = os.path.join(self.tmp.name, "data")
        live = load_json("mod", "live-running-v2.json")
        live["writtenAt"] = colony_mod.iso(time.time())
        os.makedirs(os.path.join(self.user, "companion", "live"))
        with open(os.path.join(self.user, "companion", "live", "live.json"), "w") as f:
            json.dump(live, f)
        self.lk = SYNTH()
        self.services = []

    def tearDown(self):
        for s in self.services:
            s.stop()
        self.tmp.cleanup()

    def start(self):
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, data_dir=self.data,
                            views_factory=lambda ctx: Views(ctx, lookup=self.lk))
        svc = Service(cfg).start()
        self.services.append(svc)
        return svc

    def form_default(self, scr):
        return [b for b in scr["blocks"] if b["type"] == "form"][0]["fields"][0]["default"]

    def test_settings_get_post_event_and_restart(self):
        svc = self.start()
        st, scr = http(svc, "/settings")
        self.assertEqual(st, 200)
        self.assertScreen(scr)
        form = scr["blocks"][0]
        self.assertEqual((form["type"], form["endpoint"], form["tool"]), ("form", "/settings", "settings"))
        self.assertEqual(scr["refreshOn"], ["settings"])
        self.assertIs(self.form_default(scr), False)
        text = json.dumps(scr)
        for want in ("Game found", "Companion Link mod", "Data cache", "About", "Zoom to duplicant when selected"):
            self.assertIn(want, text)
        seq = http(svc, "/events?since=0")[1]["seq"]
        st, saved = http(svc, "/settings", "POST", {"values": {"zoomToDupeOnSelect": True}})
        self.assertEqual(st, 200)
        self.assertScreen(saved)
        self.assertIs(self.form_default(saved), True)
        st, ev = http(svc, "/events?since=%d&timeout=3" % seq)
        self.assertIn("settings", ev["changed"])
        self.assertIs(self.form_default(http(svc, "/settings")[1]), True)
        # restart: a new service on the same data folder
        svc2 = self.start()
        self.assertIs(self.form_default(http(svc2, "/settings")[1]), True)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "settings.json")))

    def test_settings_bad_requests(self):
        svc = self.start()
        for body in ({"values": {"zoomToDupeOnSelect": "yes"}}, {"values": 3}, {"nope": 1}, [1]):
            st, err = http(svc, "/settings", "POST", body)
            self.assertEqual((st, err["error"]["code"]), (400, "bad_request"), body)
        self.assertIn("zoomToDupeOnSelect", http(svc, "/settings", "POST", {"values": {"zoomToDupeOnSelect": 0}})[1]["error"]["message"])
        self.assertIs(self.form_default(http(svc, "/settings")[1]), False)
        # unknown setting names in values are ignored
        self.assertEqual(http(svc, "/settings", "POST", {"values": {"mystery": 1}})[0], 200)

    def test_dupe_page_on_open_follows_the_setting(self):
        svc = self.start()
        st, off = http(svc, "/entry/dupe/d1")
        self.assertEqual(st, 200)
        self.assertScreen(off, self.lk)
        self.assertNotIn("onOpen", off)
        http(svc, "/settings", "POST", {"values": {"zoomToDupeOnSelect": True}})
        on = http(svc, "/entry/dupe/d1")[1]
        self.assertEqual(on["onOpen"][0]["action"], "focus")
        self.assertEqual(on["onOpen"][0]["args"]["target"], {"kind": "dupe", "id": "d1"})
        http(svc, "/settings", "POST", {"values": {"zoomToDupeOnSelect": False}})
        self.assertNotIn("onOpen", http(svc, "/entry/dupe/d1")[1])

    def test_colony_cards_open_real_pages(self):
        svc = self.start()
        st, scr = http(svc, "/colony")
        self.assertEqual(st, 200)
        self.assertScreen(scr, self.lk)
        grid = [b for b in scr["blocks"] if b["type"] == "grid"][0]
        for c in grid["cards"]:
            self.assertEqual(http(svc, "/entry/dupe/" + c["ref"]["id"])[0], 200)
        st, err = http(svc, "/entry/dupe/missing")
        self.assertEqual((st, err["error"]["code"]), (404, "not_found"))
        self.assertEqual(http(svc, "/colony?world=0")[0], 200)
        self.assertEqual(http(svc, "/colony?world=9")[0], 404)

    def test_dupe_is_not_a_search_or_list_kind(self):
        svc = self.start()
        self.assertEqual(http(svc, "/list/dupe")[0], 404)
        self.assertEqual(http(svc, "/raw/dupe/d1")[0], 404)


class Fixtures(unittest.TestCase, Checks):
    def test_core_shapes_match_the_contract_examples(self):
        lk = SYNTH()
        scr = cv.dupe_screen(lk, facts_v2(), "d1", True)
        ex = load_json("screens", "dupe-page-onopen.json")
        self.assertEqual(scr["onOpen"], ex["onOpen"])
        self.assertEqual(scr["nav"], ex["nav"])
        self.assertEqual([b["type"] for b in scr["blocks"] if b["type"] in ("list", "table")][:1], ["list"])


if __name__ == "__main__":
    unittest.main()
