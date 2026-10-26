"""C1: game data, merge, cache, search. Synthetic tests always run; real-data tests need fixtures/real."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from oni_companion import config  # noqa: E402
from oni_companion.gamedata import cache, load_dataset, pot, yamlmini  # noqa: E402
from oni_companion.gamedata.pot import markup_links, strip_markup  # noqa: E402
from oni_companion.index import Index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYN_EXPORT = os.path.join(ROOT, "fixtures", "synthetic", "mod", "export.json")
REAL = os.path.join(ROOT, "fixtures", "real")
HAVE_REAL = os.path.isfile(os.path.join(REAL, "OxygenNotIncluded_Data", "StreamingAssets", "strings",
                                        "strings_template.pot"))

POT = r'''msgid ""
msgstr ""
"Application: Made Up"

#. STRINGS.BUILDINGS.PREFABS.SYNTHWIDGETMAKER.NAME
msgctxt "STRINGS.BUILDINGS.PREFABS.SYNTHWIDGETMAKER.NAME"
msgid "<link=\"SYNTHWIDGETMAKER\">Widget Maker (pot)</link>"
msgstr ""

msgctxt "STRINGS.BUILDINGS.PREFABS.SYNTHWIDGETMAKER.EFFECT"
msgid "Pot effect text that the export lacks."
msgstr ""

msgctxt "STRINGS.BUILDINGS.PREFABS.SYNTHONLYPOT.NAME"
msgid "Pot Only "
"Thing"
msgstr ""

msgctxt "STRINGS.ELEMENTS.SYNTHROCK.NAME"
msgid "Synth Rock"
msgstr ""

msgctxt "STRINGS.ELEMENTS.SYNTHROCK.DESC"
msgid "A \"made up\" rock.\nSecond line."
msgstr ""

msgctxt "STRINGS.CODEX.SYNTH.TITLE"
msgid "Synth Entry"
msgstr ""

msgctxt "STRINGS.CODEX.SYNTH.BODY"
msgid "Body with <link=\"SYNTHROCK\">a link</link> and <b>bold</b>."
msgstr ""

msgctxt "STRINGS.CODEX.EMPTYKEY.TITLE"
msgid ""
msgstr ""
'''

ELEMENTS_YAML = '''---
elements:
  - elementId: SynthRock # a comment
    specificHeatCapacity: 0.5
    thermalConductivity: 2
    highTemp: 400.15
    highTempTransitionTarget: SynthLiquid
    highTempTransitionOreId: SynthDust
    highTempTransitionOreMassConversion: 0.25
    lowTemp: 100
    lowTempTransitionTarget:
    molarMass: 10
    maxMass: 500
    tags:
    - SynthStone
    state: Solid
    localizationID: STRINGS.ELEMENTS.SYNTHROCK.NAME
    dlcId: ""
  - elementId: SynthDlcGas
    state: Gas
    tags: []
    localizationID: STRINGS.ELEMENTS.SYNTHDLCGAS.NAME
    dlcId: DLC_ALPHA_ID
'''

CODEX_YAML = '''id: "SynthEntry"
title: STRINGS.CODEX.SYNTH.TITLE
requiredDlcIds:
  - "DLC_ALPHA_ID"
contentContainers:
#-----
  - contentLayout: Vertical
    lockID:
    content:
      - !CodexText
          stringKey: STRINGS.CODEX.SYNTH.TITLE
          style: Title
      - !CodexDividerLine
          preferredWidth: -1
      - !CodexText
          stringKey: STRINGS.CODEX.SYNTH.BODY
          style: Body
      - !CodexText
          stringKey: STRINGS.CODEX.EMPTYKEY.TITLE
          style: Body
'''


def make_game(tmp, with_exports=()):
    game = os.path.join(tmp, "game")
    assets = os.path.join(game, "OxygenNotIncluded_Data", "StreamingAssets")
    for rel, text in (("strings/strings_template.pot", POT), ("elements/solid.yaml", ELEMENTS_YAML),
                      ("codex/Misc/entry.yaml", CODEX_YAML)):
        p = os.path.join(assets, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    for d in ("expansion1", "dlc2", "cosmetic1"):
        os.makedirs(os.path.join(assets, "dlc", d))
    with open(os.path.join(game, "appmanifest_457140.acf"), "w") as f:
        f.write('"AppState"\n{\n\t"appid"\t"457140"\n\t"installdir"\t"X"\n\t"buildid"\t"777"\n}\n')
    user = os.path.join(tmp, "user")
    exp = os.path.join(user, "companion", "export")
    os.makedirs(exp)
    for name, data in with_exports:
        with open(os.path.join(exp, name), "w") as f:
            json.dump(data, f)
    return config.load(env={"HOME": tmp}, game_dir=game, user_dir=user, data_dir=os.path.join(tmp, "data"))


def syn_export():
    with open(SYN_EXPORT, encoding="utf-8") as f:
        return json.load(f)


class TestParsers(unittest.TestCase):
    def test_pot(self):
        d = pot.parse_pot_text(POT)
        self.assertEqual(d["STRINGS.BUILDINGS.PREFABS.SYNTHONLYPOT.NAME"], "Pot Only Thing")
        self.assertEqual(d["STRINGS.ELEMENTS.SYNTHROCK.DESC"], 'A "made up" rock.\nSecond line.')
        self.assertNotIn("STRINGS.CODEX.EMPTYKEY.TITLE", d)  # empty msgid
        self.assertNotIn("", d)

    def test_markup(self):
        t = 'x <link="OXYGEN">Oxygen</link> <b>b</b><style="KKeyword">k</style> {Name}'
        self.assertEqual(strip_markup(t), "x Oxygen bk {Name}")
        self.assertEqual(markup_links(t), ["OXYGEN"])

    def test_yamlmini(self):
        doc = yamlmini.loads(ELEMENTS_YAML)
        self.assertEqual(doc["elements"][0]["elementId"], "SynthRock")
        self.assertEqual(doc["elements"][0]["tags"], ["SynthStone"])
        self.assertIsNone(doc["elements"][0]["lowTempTransitionTarget"])
        self.assertEqual(doc["elements"][0]["dlcId"], "")
        self.assertEqual(doc["elements"][1]["tags"], [])
        c = yamlmini.loads(CODEX_YAML)
        items = c["contentContainers"][0]["content"]
        self.assertEqual(items[0].tag, "!CodexText")
        self.assertEqual(items[0]["style"], "Title")
        self.assertEqual(c["requiredDlcIds"], ["DLC_ALPHA_ID"])

    def test_yaml_sequences_and_scalars(self):
        d = yamlmini.loads('a:\n  - 1\n  - "two # not comment"\n  - 3.5 # comment\nb: true\nc:\n- x: 1\n  y: 2\n- x: 3\n')
        self.assertEqual(d["a"], [1, "two # not comment", 3.5])
        self.assertIs(d["b"], True)
        self.assertEqual(d["c"], [{"x": 1, "y": 2}, {"x": 3}])


class TestSynthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c1test")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_fallback_only(self):
        cfg = make_game(self.tmp)
        ds = load_dataset(cfg)
        self.assertFalse(ds.from_cache)
        el = ds.kinds["element"]["SynthRock"]
        self.assertEqual(el["name"], "Synth Rock")
        self.assertEqual(el["highTransition"], {"tempC": 127.0, "target": "SynthLiquid",
                                                "secondary": "SynthDust", "targetKgRatio": 0.75})
        self.assertNotIn("lowTransition", el)
        self.assertEqual(ds.kinds["element"]["SynthDlcGas"]["dlc"], ["DLC_ALPHA_ID"])
        b = ds.kinds["building"]["SYNTHWIDGETMAKER"]
        self.assertEqual((b["name"], b["source"], b["dlcKnown"]), ("Widget Maker (pot)", "pot", False))
        cx = ds.kinds["codex"]["SynthEntry"]
        self.assertEqual(cx["dlc"], ["DLC_ALPHA_ID"])
        self.assertEqual(cx["links"], ["SYNTHROCK"])
        self.assertEqual([p["text"] for p in cx["paragraphs"]], ["Synth Entry", "Body with a link and bold."])
        self.assertEqual(ds.meta["dlcInstalled"], ["DLC2_ID", "EXPANSION1_ID"])
        self.assertEqual(ds.meta["dlcMissingExport"], ["DLC2_ID", "EXPANSION1_ID"])
        self.assertEqual(ds.meta["steamBuildId"], 777)
        self.assertIn("STRINGS.CODEX.EMPTYKEY.TITLE", ds.meta["unresolvedStrings"])

    def test_mod_export_wins_and_pot_fills(self):
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", syn_export())])
        ds = load_dataset(cfg)
        b = ds.kinds["building"]["SynthWidgetMaker"]
        self.assertEqual(b["source"], "mod-export")
        self.assertEqual(b["name"], "Widget Maker")  # export name, not the pot name
        self.assertNotIn("SYNTHWIDGETMAKER", ds.kinds["building"])  # pot row absorbed, matched ignoring case
        # the export lists every building of the loaded game, so a .pot-only building is not in this game
        self.assertNotIn("SYNTHONLYPOT", ds.kinds["building"])
        self.assertEqual(ds.kinds["building"]["SynthLamp"]["dlc"], ["DLC_ALPHA_ID"])
        self.assertEqual(ds.meta["dlcExported"], ["DLC_ALPHA_ID"])
        self.assertEqual(ds.meta["dlcMissingExport"], ["DLC2_ID", "EXPANSION1_ID"])
        self.assertEqual(ds.meta["build"], 100001)
        self.assertEqual(ds.meta["modVersion"], "0.1.0")
        for kind in ("critter", "plant", "geyser", "recipe", "tech", "trait", "skill", "room", "food", "medicine"):
            self.assertTrue(ds.kinds[kind], kind)

    def test_union_over_dlc_sets(self):
        wide = syn_export()
        narrow = json.loads(json.dumps(wide))
        narrow["dlcIds"] = []
        narrow["buildings"] = [b for b in narrow["buildings"] if b["id"] == "SynthWidgetMaker"]
        narrow["buildings"][0]["name"] = "Narrow Name"
        narrow["buildings"].append({"id": "SynthOnlyBase", "name": "Only Base", "dlc": [], "category": "c",
                                    "size": {"w": 1, "h": 1}})
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", wide), ("gamedata-100001-base.json", narrow)])
        ds = load_dataset(cfg)
        self.assertEqual(ds.kinds["building"]["SynthWidgetMaker"]["name"], "Widget Maker")  # widest set wins
        self.assertEqual(ds.kinds["building"]["SynthWidgetMaker"]["exportSets"], [["DLC_ALPHA_ID"], []])
        self.assertIn("SynthOnlyBase", ds.kinds["building"])
        self.assertEqual(ds.kinds["building"]["SynthLamp"]["dlc"], ["DLC_ALPHA_ID"])

    def test_newest_build_per_dlc_set(self):
        old = syn_export()
        new = json.loads(json.dumps(old))
        new["build"] = 100002
        new["buildings"][0]["name"] = "Newer"
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", old), ("gamedata-100002-DLC_ALPHA_ID.json", new)])
        ds = load_dataset(cfg)
        self.assertEqual(ds.kinds["building"]["SynthWidgetMaker"]["name"], "Newer")
        self.assertEqual(ds.meta["exportFiles"], ["gamedata-100002-DLC_ALPHA_ID.json"])

    def test_bad_export_reported_not_fatal(self):
        cfg = make_game(self.tmp)
        with open(os.path.join(cfg.user_dir, "companion", "export", "gamedata-1-base.json"), "w") as f:
            f.write("{nope")
        ds = load_dataset(cfg)
        self.assertEqual(len(ds.meta["exportErrors"]), 1)
        self.assertTrue(ds.kinds["element"])

    def test_cache_hit_and_invalidation(self):
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", syn_export())])
        a = load_dataset(cfg)
        b = load_dataset(cfg)
        self.assertFalse(a.from_cache)
        self.assertTrue(b.from_cache)
        self.assertEqual(a.kinds, b.kinds)
        self.assertEqual(a.key, b.key)
        # a changed export changes the key and rebuilds
        ex = syn_export()
        ex["buildings"][0]["name"] = "Changed"
        with open(os.path.join(cfg.user_dir, "companion", "export", "gamedata-100001-DLC_ALPHA_ID.json"), "w") as f:
            json.dump(ex, f)
        c = load_dataset(cfg)
        self.assertFalse(c.from_cache)
        self.assertNotEqual(c.key, a.key)
        self.assertEqual(c.kinds["building"]["SynthWidgetMaker"]["name"], "Changed")
        # corrupt cache file -> rebuild, no crash
        path = cache._path(cfg.cache_dir, c.key)
        with open(path, "w") as f:
            f.write("{")
        self.assertFalse(load_dataset(cfg).from_cache)
        self.assertTrue(load_dataset(cfg).from_cache)

    def test_cache_keeps_two(self):
        cfg = make_game(self.tmp)
        for i in range(4):
            cache.save(cfg.cache_dir, "k%d" % i, {"kinds": {}, "meta": {}})
            time.sleep(0.01)
        self.assertEqual(len([n for n in os.listdir(cfg.cache_dir) if n.endswith(".json")]), cache.KEEP)

    def test_missing_game_raises(self):
        cfg = config.load(env={"HOME": self.tmp}, game_dir=os.path.join(self.tmp, "none"),
                          user_dir=self.tmp, data_dir=self.tmp)
        with self.assertRaises(FileNotFoundError):
            load_dataset(cfg)

    def test_search(self):
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", syn_export())])
        ix = Index(load_dataset(cfg))
        r = ix.search("wid")
        names = [x["name"] for x in r["results"]]
        self.assertIn("Widget Maker", names)
        self.assertIn("Widgetium", names)
        self.assertEqual(ix.search("widget maker")["results"][0]["id"], "SynthWidgetMaker")
        self.assertEqual(ix.search("SynthLamp")["results"][0]["name"], "Lamp")  # by id
        self.assertEqual(ix.search("widgtium")["results"][0]["name"], "Widgetium")  # typo
        self.assertEqual(ix.search("synth", kind="element")["results"][0]["kind"], "element")
        self.assertEqual(ix.search("zzzzqq")["results"], [])
        self.assertEqual(ix.search("   ")["results"], [])
        self.assertEqual(len(ix.search("synth", limit=2)["results"]), 2)
        self.assertTrue(ix.search("synth", limit=2)["truncated"])
        first = ix.search("lamp")["results"][0]
        self.assertEqual(set(first), {"kind", "id", "name", "dlc", "subtitle"})
        self.assertEqual(first["dlc"], ["DLC_ALPHA_ID"])
        self.assertEqual(ix.get("building", "synthlamp")["id"], "SynthLamp")  # case-insensitive
        self.assertIsNone(ix.get("building", "SYNTHONLYPOT"))
        self.assertIsNone(ix.get("building", "nope"))
        counts = {c["kind"]: c["count"] for c in ix.kind_counts()}
        self.assertEqual(counts["element"], 5)  # 3 export + 2 yaml
        base = [r["id"] for r in ix.list_kind("building", dlc="base")]
        self.assertNotIn("SYNTHONLYPOT", base)   # DLC unknown (pot only): never claimed as base game
        self.assertIn("SynthWidgetMaker", base)
        self.assertEqual([r["id"] for r in ix.list_kind("building", dlc="DLC_ALPHA_ID")], ["SynthLamp"])

    def test_graph_from_synthetic_export(self):
        cfg = make_game(self.tmp, [("gamedata-100001-DLC_ALPHA_ID.json", syn_export())])
        ix = Index(load_dataset(cfg))
        ex = syn_export()
        # derive expectation from the fixture, not from constants
        want_users = {b["id"] for b in ex["buildings"] for c in b.get("converters", [])
                      for a in c["inputs"] if a.get("element") == "SynthWidgetium"}
        got = {r["id"] for r in ix.used_by("element", "SynthWidgetium") if r["kind"] == "building"}
        self.assertTrue(want_users <= got, (want_users, got))
        want_makers = {b["id"] for b in ex["buildings"] for c in b.get("converters", [])
                       for a in c["outputs"] if a.get("element") == "SynthWidgetium"}
        got = {r["id"] for r in ix.produced_by("element", "SynthWidgetium") if r["kind"] == "building"}
        self.assertTrue(want_makers <= got)
        self.assertEqual(ix.used_by("element", "NoSuchThing"), [])


@unittest.skipUnless(HAVE_REAL, "fixtures/real missing (run devtools/fetch-game-files.sh)")
class TestReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="c1real")
        # game files only: an empty user folder, so no mod export is merged
        empty_user = os.path.join(cls.tmp, "user")
        os.makedirs(empty_user)
        cls.cfg = config.load(env={"HOME": cls.tmp}, game_dir=REAL, user_dir=empty_user,
                              data_dir=cls.tmp)
        t = time.perf_counter()
        cls.cold = load_dataset(cls.cfg)
        cls.cold_s = time.perf_counter() - t
        t = time.perf_counter()
        cls.warm = load_dataset(cls.cfg)
        cls.warm_s = time.perf_counter() - t
        cls.ix = Index(cls.warm)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_timing(self):
        self.assertFalse(self.cold.from_cache)
        self.assertTrue(self.warm.from_cache)
        self.assertLess(self.cold_s, 10)
        self.assertLess(self.warm_s, 1)
        t = time.perf_counter()
        for q in ("oxygen", "coal gen", "algea", "steel", "carbon dio"):
            self.ix.search(q)
        self.assertLess((time.perf_counter() - t) / 5, 0.05)

    def test_all_codex_text_is_english(self):
        cx = self.cold.kinds["codex"]
        self.assertGreater(len(cx), 300)
        for e in cx.values():
            self.assertNotIn("STRINGS.", e["name"], e["id"])
            for p in e["paragraphs"]:
                self.assertNotIn("STRINGS.", p["text"], e["id"])
                self.assertNotIn("<link", p["text"], e["id"])
        # unresolved keys are reported (empty/missing in the game's own .pot), not shown
        for k in self.cold.meta["unresolvedStrings"]:
            self.assertTrue(k.startswith("STRINGS."))

    def test_all_elements(self):
        n = 0
        for fn in ("gas", "liquid", "solid", "special"):
            doc = yamlmini.load(os.path.join(REAL, "OxygenNotIncluded_Data", "StreamingAssets", "elements", fn + ".yaml"))
            n += len(doc["elements"])
        els = self.cold.kinds["element"]
        self.assertEqual(len(els), n)
        for e in els.values():
            self.assertNotIn("STRINGS.", e["name"])
            self.assertIn(e["state"], ("solid", "liquid", "gas", "vacuum"))
        self.assertEqual(els["Oxygen"]["state"], "gas")
        self.assertEqual(els["Oxygen"]["name"], "Oxygen")
        self.assertAlmostEqual(els["Water"]["highTransition"]["tempC"], 99.35, places=2)
        self.assertEqual(els["Water"]["highTransition"]["target"], "Steam")

    def test_dlc_tags_and_installed(self):
        self.assertIn("EXPANSION1_ID", self.cold.meta["dlcInstalled"])
        tags = {d for e in self.cold.kinds["codex"].values() for d in e["dlc"]}
        self.assertTrue({"EXPANSION1_ID", "DLC2_ID"} <= tags)
        self.assertTrue(any(e["dlc"] for e in self.cold.kinds["element"].values()))
        self.assertEqual(self.cold.meta["dlcMissingExport"], self.cold.meta["dlcInstalled"])  # no export yet

    def test_fallback_kinds(self):
        for k in ("building", "food", "tech", "trait", "skill", "room", "element", "codex"):
            self.assertGreater(len(self.cold.kinds[k]), 10, k)

    def test_search_real(self):
        self.assertEqual(self.ix.search("oxygen")["results"][0]["id"], "Oxygen")
        self.assertEqual(self.ix.search("algea")["results"][0]["name"], "Algae")
        names = [r["name"] for r in self.ix.search("coal gen")["results"]]
        self.assertIn("Coal Generator", names)


if __name__ == "__main__":
    unittest.main()
