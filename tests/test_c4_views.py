"""Views (lane C4): every entry of every kind renders to a Screen that validates.

Two data sets: the synthetic mod export (always runs, rich numbers), and the user's real game files
(runs when ONI_REAL_DIR or ../steamos-work/oni exists; never committed, never required).
"""
import json
import os
import tempfile
import unittest

from tests.jsonschema_mini import Validator
from core.oni_companion import config as oni_config
from core.oni_companion.art import decorate
from core.oni_companion.colony import Colony
from core.oni_companion.gamedata import Dataset, KIND_LABELS, load_dataset, merge, modexport
from core.oni_companion.server.errors import ApiError
from core.oni_companion.views import blocks as B
from core.oni_companion.views import colony as colony_view
from core.oni_companion.views import entry as entry_view
from core.oni_companion.views import listing
from core.oni_companion.views.lookup import Lookup
from core.oni_companion.views.provider import Views, make_views

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
REAL = os.environ.get("ONI_REAL_DIR") or os.path.join(os.path.dirname(ROOT), "steamos-work", "oni")
HAVE_REAL = os.path.isfile(os.path.join(REAL, "OxygenNotIncluded_Data", "StreamingAssets", "strings", "strings_template.pot"))
AS_OF = "2026-10-25T12:00:00Z"
V = Validator(CONTRACTS)


def load_json(*parts):
    with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
        return json.load(f)


def synthetic_lookup():
    data, sha = modexport.load_export(os.path.join(FIX, "mod", "export.json"))
    exports = [{"path": "export.json", "name": "export.json", "sha1": sha, "data": data}]
    kinds = merge.merge({}, exports, [])
    meta = {"dlcInstalled": data["dlcIds"], "dlcExported": data["dlcIds"], "dlcMissingExport": [],
            "exportFiles": ["export.json"], "modVersion": data["modVersion"], "builtAt": AS_OF,
            "researchTypes": data.get("researchTypes") or [], "steamBuildId": "1"}
    return Lookup(Dataset(kinds, meta, "k", False, {}))


PROTON_USER = os.path.join(REAL, "proton-user")
HAVE_EXPORT = os.path.isdir(os.path.join(PROTON_USER, "companion", "export"))


def real_config(tmp, user=None):
    return oni_config.load(game_dir=REAL, user_dir=user or os.path.join(REAL, "user"), data_dir=tmp)


class Checks:
    """Shared assertions."""

    def assertScreen(self, scr, lk=None, what=""):
        decorate(scr, None)     # the builders' art hooks are resolved (here: removed) by the views layer
        errs = V.validate(scr, "screen.schema.json")
        self.assertEqual(errs, [], "%s: %s" % (what, errs[:3]))
        json.dumps(scr, allow_nan=False)
        for s in B.walk_strings(scr):
            self.assertNotIn("STRINGS.", s, what)
        if lk is not None:
            for r in B.walk_refs(scr):
                if r["kind"] in ("dupe", "alert"):      # resolved from the live colony, not from game data
                    continue
                self.assertIsNotNone(lk.get(r["kind"], r["id"]), "%s: dangling %r" % (what, r))


class SyntheticEntries(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = synthetic_lookup()

    def test_every_entry_of_every_kind(self):
        n = 0
        for kind, entries in self.lk.kinds.items():
            for e in entries.values():
                scr = entry_view.entry_screen(self.lk, kind, e)
                self.assertScreen(scr, self.lk, "%s/%s" % (kind, e["id"]))
                self.assertEqual(scr["title"], e["name"])
                self.assertTrue(any(b["type"] == "link" for b in scr["blocks"]), "wiki link")
                self.assertTrue(any(b["type"] == "chips" for b in scr["blocks"]), "dlc chips")
                n += 1
        self.assertGreater(n, 10)

    def test_every_kind_in_the_export_is_covered(self):
        have = {k for k, v in self.lk.kinds.items() if v}
        self.assertEqual(have & set(entry_view.BUILDERS), have)
        for k in ("building", "element", "critter", "plant", "geyser", "food", "medicine", "recipe",
                  "tech", "trait", "skill", "room"):
            self.assertIn(k, have, "synthetic export has no %s (kind untested)" % k)

    def test_dlc_chip_and_badge(self):
        scr = entry_view.entry_screen(self.lk, "building", self.lk.get("building", "SynthLamp"))
        labels = [c["label"] for b in scr["blocks"] if b["type"] == "chips" for c in b["chips"]]
        self.assertIn("Dlc Alpha", labels)
        base = entry_view.entry_screen(self.lk, "building", self.lk.get("building", "SynthWidgetMaker"))
        self.assertIn("Base game", [c["label"] for b in base["blocks"] if b["type"] == "chips" for c in b["chips"]])
        lst = listing.list_screen(self.lk, "building")
        badges = {i["title"]: i.get("badge") for b in lst["blocks"] for i in b["items"]}
        self.assertEqual(badges["Lamp"], "Dlc Alpha")

    def test_building_numbers_and_ports(self):
        scr = entry_view.entry_screen(self.lk, "building", self.lk.get("building", "SynthWidgetMaker"))
        stats = {r["label"]: r for b in scr["blocks"] if b["type"] == "stats" for r in b["rows"]}
        self.assertEqual(stats["Size"]["value"], "3 x 2")
        ports = [b for b in scr["blocks"] if b["type"] == "ports"]
        self.assertTrue(ports)
        self.assertTrue(any(p.get("element") for p in ports[0]["inputs"] + ports[0]["outputs"]))
        self.assertTrue(any(p.get("conduit") == "power" for p in ports[0]["inputs"]))

    def test_produced_and_used_by(self):
        found = False
        for e in self.lk.kinds["element"].values():
            scr = entry_view.entry_screen(self.lk, "element", e)
            titles = [b["title"] for b in scr["blocks"] if b["type"] == "group"]
            found = found or any(t.startswith(("Produced by", "Used by")) for t in titles)
        self.assertTrue(found, "no element has produced-by/used-by in the synthetic data")

    def test_element_phases_ladder(self):
        e = next(e for e in self.lk.kinds["element"].values() if e.get("highTransition") or e.get("lowTransition"))
        scr = entry_view.entry_screen(self.lk, "element", e)
        ph = [b for b in scr["blocks"] if b["type"] == "phases"][0]["states"]
        temps = [s.get("loC") for s in ph if s.get("loC") is not None]
        self.assertEqual(temps, sorted(temps))

    def test_building_without_export_says_no_numbers_yet(self):
        e = {"id": "X", "name": "Thing", "dlc": [], "source": "pot", "dlcKnown": False, "desc": "A thing."}
        scr = entry_view.entry_screen(self.lk, "building", e)
        self.assertTrue(any(b["type"] == "notice" and b["text"] == entry_view.NO_NUMBERS and "mod" not in b["text"].lower()
                            for b in scr["blocks"]))                 # pages other than Settings never mention the mod
        self.assertIn("DLC not known", [c["label"] for b in scr["blocks"] if b["type"] == "chips" for c in b["chips"]])
        self.assertEqual(scr["source"], "yaml")

    def test_lists_and_sorts(self):
        for kind in self.lk.kinds:
            if not self.lk.kinds[kind]:
                continue
            for sort in ("name", "dlc"):
                self.assertScreen(listing.list_screen(self.lk, kind, None, sort), self.lk, kind)
            self.assertScreen(listing.list_screen(self.lk, kind, "base"), self.lk, kind)
        scr = listing.list_screen(self.lk, "building", "DLC_ALPHA_ID")
        self.assertEqual([i["title"] for i in scr["blocks"][0]["items"]], ["Lamp"])
        empty = listing.list_screen(self.lk, "codex")
        self.assertScreen(empty, self.lk)


class ColonyViews(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = synthetic_lookup()

    def test_live_running(self):
        facts = dict(load_json("mod", "live-running.json"), source="mod-live", state="running", asOf=AS_OF)
        scr = colony_view.colony_screen(self.lk, facts)
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["title"], "Synth Colony")
        self.assertEqual(scr["refreshOn"], ["colony", "action"])      # v1.2: it has alerts, a dismiss refreshes it
        types = [b["type"] for b in B.walk_blocks(scr["blocks"])]
        for t in ("grid", "progress", "list", "table"):
            self.assertIn(t, types)

    def test_header_and_none(self):
        self.assertScreen(colony_view.colony_screen(self.lk, {"source": "header", "state": "saved", "colonyName": "A",
                                                              "cycle": 3, "asOf": AS_OF}))
        self.assertScreen(colony_view.colony_screen(self.lk, {"source": "none", "state": "saved"}))

    def test_menu_state_is_not_shown_as_live(self):
        # Colony falls back to the save when live says menu; a bare "saved" state with worlds renders too
        facts = dict(load_json("mod", "live-running.json"), source="save", state="saved", asOf=AS_OF)
        self.assertScreen(colony_view.colony_screen(self.lk, facts), self.lk)

    def test_many_worlds_switcher_shows_one_world(self):
        base = load_json("mod", "live-running.json")
        w2 = dict(base["worlds"][0], id=1, name="Moon")
        facts = dict(base, source="mod-live", state="running", asOf=AS_OF, activeWorldId=1,
                     worlds=[base["worlds"][0], w2])
        scr = colony_view.colony_screen(self.lk, facts)
        self.assertScreen(scr, self.lk)
        self.assertEqual(scr["worldSwitcher"]["active"], 1)
        self.assertEqual([w["name"] for w in scr["worldSwitcher"]["worlds"]], [base["worlds"][0]["name"], "Moon"])
        self.assertTrue(scr["subtitle"].endswith("Moon"))
        other = colony_view.colony_screen(self.lk, facts, world=0)
        self.assertEqual(other["worldSwitcher"]["active"], 0)


class FakeCtx:
    def __init__(self, live_path, save_dirs=()):
        self.colony = Colony(live_path, save_dirs)
        self.bus = None
        self.cfg = None


class ProviderSynthetic(unittest.TestCase, Checks):
    @classmethod
    def setUpClass(cls):
        cls.lk = synthetic_lookup()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.live = os.path.join(cls.tmp.name, "live.json")
        cls.views = Views(FakeCtx(cls.live), lookup=cls.lk)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def api(self, obj, name):
        errs = V.validate(obj, "api.schema.json#/$defs/" + name)
        self.assertEqual(errs, [], errs[:3])

    def test_replies_validate(self):
        v = self.views
        self.api(v.status(), "Status")
        self.api(v.search("lamp", None, 5), "Search")
        self.api(v.kinds(), "Kinds")
        self.api(v.tools(), "ToolList")
        self.api(v.raw("building", "SynthLamp"), "Raw")
        self.assertScreen(v.home(), self.lk)
        self.assertScreen(v.list_kind("building", None, "name"), self.lk)
        self.assertScreen(v.entry("building", "SynthLamp"), self.lk)
        self.assertScreen(v.colony(None), self.lk)

    def test_errors(self):
        v = self.views
        for call in (lambda: v.entry("building", "Nope"), lambda: v.entry("nonsense", "x"),
                     lambda: v.list_kind("nonsense", None, "name"), lambda: v.raw("tech", "Nope"),
                     lambda: v.tool_form("nope"), lambda: v.tool_run("nope", {})):
            with self.assertRaises(ApiError) as cm:
                call()
            self.assertEqual(cm.exception.code, "not_found")
        with self.assertRaises(ApiError) as cm:
            v.search("lamp", "nonsense", 5)
        self.assertEqual(cm.exception.code, "bad_request")

    def test_tools_run_on_the_dataset(self):
        v = self.views
        for t in v.tools()["tools"]:
            self.assertScreen(v.tool_form(t["id"]), self.lk)

    def test_colony_from_live_file(self):
        live = load_json("mod", "live-running.json")
        import datetime
        live["writtenAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(self.live, "w") as f:
            json.dump(live, f)
        scr = self.views.colony(None)
        self.assertEqual(scr["source"], "mod-live")
        self.assertEqual(scr["raw"]["cycle"], 12)
        self.assertScreen(scr, self.lk)
        with self.assertRaises(ApiError):
            self.views.colony("99")


class OverHttp(unittest.TestCase, Checks):
    """The real views behind the real server (token, routes), on the synthetic dataset."""

    def test_endpoints(self):
        from core.oni_companion.server.service import Service, ServiceConfig
        from tests.test_c3_server import TOKEN, http
        lk = synthetic_lookup()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "companion", "live"))
            cfg = ServiceConfig(user_dir=tmp, token=TOKEN, views_factory=lambda ctx: Views(ctx, lookup=lk))
            svc = Service(cfg).start()
            try:
                cases = [("/status", "api.schema.json#/$defs/Status"), ("/home", "screen.schema.json"),
                         ("/search?q=lamp", "api.schema.json#/$defs/Search"), ("/kinds", "api.schema.json#/$defs/Kinds"),
                         ("/list/building?sort=dlc", "screen.schema.json"),
                         ("/entry/building/SynthLamp", "screen.schema.json"),
                         ("/raw/building/SynthLamp", "api.schema.json#/$defs/Raw"),
                         ("/colony", "api.schema.json#/$defs/ColonyReply"), ("/tools", "api.schema.json#/$defs/ToolList")]
                for path, schema in cases:
                    st, body = http(svc, "/api/v1" + path)
                    self.assertEqual(st, 200, path)
                    self.assertEqual(V.validate(body, schema), [], path)
                for tid, vals in (("geyser-average", {}), ("heat", {"element": "SynthWidgetium"})):
                    st, body = http(svc, "/api/v1/tools/" + tid, "POST", body={"values": vals})
                    self.assertEqual(st, 200, tid)
                    self.assertScreen(body, lk)
                st, body = http(svc, "/api/v1/tools/heat", "POST", body={"values": {}})
                self.assertEqual(st, 400)
                self.assertEqual(http(svc, "/api/v1/entry/building/Nope")[0], 404)
            finally:
                svc.stop()


@unittest.skipUnless(HAVE_REAL, "real game files not present (steamos-work/oni)")
class RealData(unittest.TestCase, Checks):
    """The user's own game files: every entry of every kind renders with no STRINGS. keys and no schema error."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # game files only: an empty user folder, so no mod export is merged
        empty_user = os.path.join(cls.tmp.name, "user")
        os.makedirs(empty_user)
        cfg = real_config(cls.tmp.name, user=empty_user)
        cls.ds = load_dataset(cfg)
        cls.lk = Lookup(cls.ds, cfg.assets_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_entry_renders(self):
        n = 0
        for kind, entries in self.lk.kinds.items():
            for e in entries.values():
                scr = entry_view.entry_screen(self.lk, kind, e)
                self.assertScreen(scr, self.lk, "%s/%s" % (kind, e["id"]))
                n += 1
        self.assertGreater(n, 1000)
        print("\nC4: rendered %d real entries" % n)

    def test_lists_for_every_kind(self):
        for kind in self.lk.kinds:
            for sort in ("name", "dlc"):
                self.assertScreen(listing.list_screen(self.lk, kind, None, sort), self.lk, kind)

    def test_codex_text_has_no_raw_keys(self):
        for e in self.lk.kinds["codex"].values():
            self.assertNotIn("STRINGS.", e["name"])
            for p in e["paragraphs"]:
                self.assertNotIn("STRINGS.", p["text"])

    def test_dlc_names_come_from_the_game(self):
        self.assertTrue(all("_ID" not in self.lk.dlc_name(d) for d in self.ds.meta["dlcInstalled"]))
        print("\nC4: DLC names:", {d: self.lk.dlc_name(d) for d in self.ds.meta["dlcInstalled"]})

    def test_provider_and_home_without_mod(self):
        v = Views(FakeCtx(os.path.join(self.tmp.name, "none.json")), lookup=self.lk)
        home = v.home()
        self.assertScreen(home, self.lk)
        txt = repr(home)
        self.assertNotIn("Companion Link", txt)
        self.assertNotIn("mod", [w.lower().strip(".,") for w in txt.split()])
        self.assertEqual(home["title"], self.lk.codex_label)
        labels = [i["title"] for b in home["blocks"] if b["type"] == "list" for i in b["items"]]
        self.assertNotIn("Buildings", labels)
        self.assertIn("Tools", [b.get("text") for b in home["blocks"] if b["type"] == "heading"])
        self.assertScreen(v.entry("building", "ADVANCEDAPOTHECARY"), self.lk)
        self.assertScreen(v.entry("element", "Water"), self.lk)

    def test_search_speed(self):
        import time
        t = time.perf_counter()
        for q in ("water", "oxy", "bunker door", "coal"):
            self.lk.index.search(q, None, 20)
        self.assertLess((time.perf_counter() - t) / 4, 0.05)

    def test_colony_from_real_save(self):
        from core.oni_companion.save.colony_from_save import colony_from_save
        saves = []
        for root, _d, files in os.walk(os.path.join(REAL, "user", "cloud_save_files")):
            saves += [os.path.join(root, f) for f in files if f.endswith(".sav") and "auto_save" not in root]
        self.assertTrue(saves)
        for p in sorted(saves)[:4]:
            live = colony_from_save(p)["live"]
            facts = dict(live, source="save", state="saved", asOf=AS_OF)
            facts.pop("writtenAt", None)
            self.assertScreen(colony_view.colony_screen(self.lk, facts), self.lk, p)


@unittest.skipUnless(HAVE_REAL and HAVE_EXPORT, "real game files + real mod export not present (steamos-work/oni/proton-user)")
class RealExport(unittest.TestCase, Checks):
    """Real game files plus the real mod export and live.json, from the Proton prefix."""

    @classmethod
    def setUpClass(cls):
        import shutil
        cls.tmp = tempfile.TemporaryDirectory()
        cls.user = os.path.join(cls.tmp.name, "user")
        shutil.copytree(os.path.join(PROTON_USER, "companion"), os.path.join(cls.user, "companion"))
        cls.cfg = real_config(cls.tmp.name, cls.user)
        cls.ds = load_dataset(cls.cfg)
        cls.lk = Lookup(cls.ds, cls.cfg.assets_dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_export_and_live_match_their_contracts(self):
        from core.oni_companion import sources
        for p in sources.export_files(self.user):
            with open(p, encoding="utf-8") as f:
                self.assertEqual(V.validate(json.load(f), "mod-export.schema.json"), [], p)
        with open(sources.live_path(self.user), encoding="utf-8") as f:
            self.assertEqual(V.validate(json.load(f), "mod-live.schema.json"), [])

    def test_dlc_tags_come_from_the_export(self):
        counts = {}
        for kind in ("building", "geyser", "food", "medicine", "tech", "trait", "skill", "room"):
            rows = list(self.lk.kinds[kind].values())
            exp = [r for r in rows if r.get("source") == "mod-export"]
            unknown = [r for r in rows if r.get("dlcKnown") is False]
            self.assertTrue(all(r.get("source") == "pot" for r in unknown), kind)
            self.assertTrue(all("dlcKnown" not in r for r in exp), kind)
            names = {}
            for r in exp:
                names.setdefault(r["name"].lower(), r["id"])
            dup = [r["id"] for r in unknown if r["name"].lower() in names]
            self.assertEqual(dup, [], "%s: .pot entries that duplicate an export entry" % kind)
            counts[kind] = (len(exp), sum(1 for r in exp if r.get("dlc")), len(unknown))
        print("\nREAL export (kind: from export, with DLC tag, DLC unknown):", counts)

    def test_every_entry_and_list_renders(self):
        n = 0
        for kind, entries in self.lk.kinds.items():
            self.assertScreen(listing.list_screen(self.lk, kind, None, "dlc"), self.lk, kind)
            for e in entries.values():
                self.assertScreen(entry_view.entry_screen(self.lk, kind, e), self.lk, "%s/%s" % (kind, e["id"]))
                n += 1
        print("\nREAL export: %d entries rendered" % n)

    def test_service_endpoints_with_live_and_saves(self):
        import datetime
        from core.oni_companion.server.service import Service, ServiceConfig
        from core.oni_companion import sources
        from tests.test_c3_server import TOKEN, http
        lp = sources.live_path(self.user)
        with open(lp, encoding="utf-8") as f:
            live = json.load(f)
        live["writtenAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(lp, "w") as f:
            json.dump(live, f)
        saves = os.path.join(REAL, "user", "cloud_save_files")
        cfg = ServiceConfig(user_dir=self.user, save_dirs=[saves], game_dir=REAL, token=TOKEN,
                            views_factory=lambda ctx: Views(ctx, config=self.cfg))
        svc = Service(cfg).start()
        try:
            for path, schema in (("/status", "api.schema.json#/$defs/Status"), ("/home", "screen.schema.json"),
                                 ("/kinds", "api.schema.json#/$defs/Kinds"), ("/colony", "api.schema.json#/$defs/ColonyReply"),
                                 ("/search?q=geyser", "api.schema.json#/$defs/Search"),
                                 ("/tools", "api.schema.json#/$defs/ToolList")):
                st, body = http(svc, "/api/v1" + path)
                self.assertEqual(st, 200, path)
                self.assertEqual(V.validate(body, schema), [], path)
                if path == "/status":
                    self.assertTrue(body["mod"]["liveFresh"])
                    self.assertEqual(body["game"]["dlcMissingExport"], ["EXPANSION1_ID"])
                if path == "/colony":
                    self.assertEqual(body["source"], "mod-live")
                    self.assertScreen(body, self.lk)
            for t in svc.views.tools()["tools"]:
                self.assertScreen(svc.views.tool_form(t["id"]), self.lk)
        finally:
            svc.stop()

    def test_saved_colonies_name_their_skills(self):
        from core.oni_companion.save.colony_from_save import colony_from_save
        saves = []
        for root, _d, files in os.walk(os.path.join(REAL, "user", "cloud_save_files")):
            saves += [os.path.join(root, f) for f in files if f.endswith(".sav") and "auto_save" not in root]
        self.assertTrue(saves)
        for p in sorted(saves)[:4]:
            facts = dict(colony_from_save(p)["live"], source="save", state="saved", asOf=AS_OF)
            facts.pop("writtenAt", None)
            scr = colony_view.colony_screen(self.lk, facts)
            self.assertScreen(scr, self.lk, p)
            text = json.dumps(scr)
            for w in facts.get("worlds", []):
                for d in w.get("dupes", []):
                    for sid in d["skills"]:
                        self.assertNotEqual(self.lk.name("skill", sid), sid, sid)
            self.assertNotRegex(text, r'"(Building|Mining|Cooking)\d"')


if __name__ == "__main__":
    unittest.main()
