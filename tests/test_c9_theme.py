"""C9: core theme.py. GET /api/v1/theme: built-in fallback (= v1 QML colors), game theme validation.

Synthetic only: the test PNGs are generated here (solid squares), never game art.
"""
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import theme as T  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402

CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
QML_THEME = os.path.join(ROOT, "clients", "barry", "qml", "Theme.qml")
V = Validator(CONTRACTS)


def make_png(path, w, h):
    """A solid-color PNG written with stdlib only (synthetic test image)."""
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) +
              chunk(b"IEND", b""))


def mod_theme(build=100001, **over):
    colors = dict(T.BUILTIN_COLORS)
    doc = {"schema": 1, "modVersion": "0.2.0", "build": build, "writtenAt": "2026-01-01T12:00:00Z",
           "colors": colors, "slices": []}
    doc.update(over)
    return doc


def write_theme(comp, build, doc, pngs=()):
    d = os.path.join(comp, "theme", str(build))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "theme.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    for name, w, h in pngs:
        make_png(os.path.join(d, name), w, h)
    return d


def panel_slice(**over):
    s = {"name": "panel", "file": "panel.png", "width": 48, "height": 48,
         "insets": {"left": 6, "top": 6, "right": 6, "bottom": 6}}
    s.update(over)
    return s


def qml_colors():
    """v1 colors from Theme.qml: name -> #rrggbb."""
    with open(QML_THEME, encoding="utf-8") as f:
        return dict(re.findall(r'(?:readonly )?property color (\w+): "(#[0-9a-fA-F]{6})"', f.read()))


class BuiltinTheme(unittest.TestCase):
    def test_builtin_validates_against_schema(self):
        self.assertEqual(V.validate(T.builtin(), "theme.schema.json"), [])
        self.assertEqual(V.validate(T.reply(None), "theme.schema.json"), [])

    def test_builtin_colors_are_the_v1_qml_colors(self):
        q = qml_colors()
        self.assertEqual(BUILTIN_MAP["background"], q["bg"])
        self.assertEqual(BUILTIN_MAP["panel"], q["panel"])
        self.assertEqual(BUILTIN_MAP["header"], q["panelHi"])
        self.assertEqual(BUILTIN_MAP["border"], q["line"])
        self.assertEqual(BUILTIN_MAP["text"], q["text"])
        self.assertEqual(BUILTIN_MAP["textDim"], q["muted"])
        self.assertEqual(BUILTIN_MAP["positive"], q["good"])
        self.assertEqual(BUILTIN_MAP["negative"], q["bad"])
        self.assertEqual(BUILTIN_MAP["warning"], q["warn"])
        self.assertEqual(BUILTIN_MAP["info"], q["accent"])

    def test_builtin_shape(self):
        r = T.reply(None)
        self.assertEqual(r["source"], "builtin")
        self.assertEqual(r["slices"], [])
        self.assertNotIn("build", r)
        self.assertEqual(r["font"], {"family": "Noto Sans"})

    def test_missing_folder_is_builtin(self):
        self.assertEqual(T.reply(os.path.join(tempfile.gettempdir(), "no-such-companion-c9")), T.builtin())
        res = T.load("")
        self.assertEqual(res.reply["source"], "builtin")
        self.assertTrue(res.notes)


BUILTIN_MAP = T.BUILTIN_COLORS


class GameTheme(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c9-theme-")
        self.comp = os.path.join(self.tmp, "companion")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_synthetic_fixture_loads_and_validates(self):
        res = T.load(os.path.join(FIX, "companion"))
        self.assertEqual(res.reply["source"], "game")
        self.assertEqual(res.reply["build"], 100001)
        self.assertEqual(V.validate(res.reply, "theme.schema.json"), [])
        self.assertEqual({s["name"] for s in res.reply["slices"]}, {"panel", "header", "button", "buttonHover", "buttonPressed"})
        for s in res.reply["slices"]:
            self.assertEqual(s["art"], "/api/v1/art/ui/" + s["name"])
            self.assertTrue(os.path.isfile(res.image_path(s["name"])))

    def test_fixture_reply_matches_fixture_file(self):
        with open(os.path.join(FIX, "api", "theme.json"), encoding="utf-8") as f:
            fixed = json.load(f)
        self.assertEqual(T.reply(os.path.join(FIX, "companion")), fixed)

    def test_valid_game_theme(self):
        write_theme(self.comp, 100001, mod_theme(slices=[panel_slice()]), [("panel.png", 48, 48)])
        res = T.load(self.comp)
        self.assertEqual(res.reply["source"], "game")
        self.assertEqual(res.notes, [])
        self.assertEqual(res.reply["slices"][0]["art"], "/api/v1/art/ui/panel")
        self.assertEqual(V.validate(res.reply, "theme.schema.json"), [])

    def test_newest_valid_build_wins(self):
        write_theme(self.comp, 100001, mod_theme(100001, colors=dict(T.BUILTIN_COLORS, panel="#111111")))
        write_theme(self.comp, 100002, mod_theme(100002))
        self.assertEqual(T.load(self.comp).reply["build"], 100002)

    def test_broken_newest_falls_back_to_older(self):
        write_theme(self.comp, 100001, mod_theme(100001))
        write_theme(self.comp, 100002, mod_theme(100002, schema=2))
        res = T.load(self.comp)
        self.assertEqual(res.reply["build"], 100001)
        self.assertTrue(any("100002" in n for n in res.notes))

    def test_bad_json_is_builtin(self):
        d = os.path.join(self.comp, "theme", "100001")
        os.makedirs(d)
        with open(os.path.join(d, "theme.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(T.load(self.comp).reply["source"], "builtin")

    def test_bad_color_rejects_theme(self):
        bad = dict(T.BUILTIN_COLORS, panel="blue")
        write_theme(self.comp, 100001, mod_theme(colors=bad))
        res = T.load(self.comp)
        self.assertEqual(res.reply["source"], "builtin")
        self.assertIn("panel", " ".join(res.notes))

    def test_missing_required_color_rejects_theme(self):
        c = dict(T.BUILTIN_COLORS)
        del c["meterStress"]
        write_theme(self.comp, 100001, mod_theme(colors=c))
        self.assertEqual(T.load(self.comp).reply["source"], "builtin")

    def test_unknown_color_key_rejects_theme(self):
        write_theme(self.comp, 100001, mod_theme(colors=dict(T.BUILTIN_COLORS, sparkle="#ffffff")))
        self.assertEqual(T.load(self.comp).reply["source"], "builtin")

    def test_unknown_top_level_key_rejects_theme(self):
        write_theme(self.comp, 100001, mod_theme(extra=1))
        self.assertEqual(T.load(self.comp).reply["source"], "builtin")

    def test_optional_colors_fall_back_to_v1_tones(self):
        c = dict(T.BUILTIN_COLORS)
        del c["warning"]
        del c["info"]
        write_theme(self.comp, 100001, mod_theme(colors=c))
        r = T.load(self.comp).reply
        self.assertEqual(r["colors"]["warning"], T.BUILTIN_COLORS["warning"])
        self.assertEqual(r["colors"]["info"], T.BUILTIN_COLORS["info"])
        self.assertEqual(V.validate(r, "theme.schema.json"), [])

    def test_alpha_color_allowed(self):
        write_theme(self.comp, 100001, mod_theme(colors=dict(T.BUILTIN_COLORS, border="#505a6e80")))
        self.assertEqual(T.load(self.comp).reply["colors"]["border"], "#505a6e80")

    def test_png_size_mismatch_drops_only_that_slice(self):
        write_theme(self.comp, 100001,
                    mod_theme(slices=[panel_slice(), panel_slice(name="header", file="header.png", height=24,
                                                                  insets={"left": 4, "top": 4, "right": 4, "bottom": 4})]),
                    [("panel.png", 48, 48), ("header.png", 48, 20)])
        res = T.load(self.comp)
        self.assertEqual(res.reply["source"], "game")
        self.assertEqual([s["name"] for s in res.reply["slices"]], ["panel"])
        self.assertIsNone(res.image_path("header"))
        self.assertTrue(any("header" in n for n in res.notes))

    def test_missing_png_drops_slice(self):
        write_theme(self.comp, 100001, mod_theme(slices=[panel_slice()]))
        res = T.load(self.comp)
        self.assertEqual(res.reply["slices"], [])
        self.assertEqual(res.reply["source"], "game")

    def test_insets_larger_than_image_drop_slice(self):
        write_theme(self.comp, 100001,
                    mod_theme(slices=[panel_slice(insets={"left": 30, "top": 6, "right": 30, "bottom": 6})]),
                    [("panel.png", 48, 48)])
        self.assertEqual(T.load(self.comp).reply["slices"], [])

    def test_slice_name_must_be_allowed(self):
        write_theme(self.comp, 100001, mod_theme(slices=[panel_slice(name="cursor")]), [("panel.png", 48, 48)])
        self.assertEqual(T.load(self.comp).reply["slices"], [])

    def test_duplicate_slice_name_keeps_first(self):
        write_theme(self.comp, 100001, mod_theme(slices=[panel_slice(), panel_slice()]), [("panel.png", 48, 48)])
        self.assertEqual(len(T.load(self.comp).reply["slices"]), 1)

    def test_file_name_cannot_point_elsewhere(self):
        for bad in ("../theme.json", "sub/panel.png", "/etc/passwd.png", "panel.jpg", "pa nel.png"):
            write_theme(self.comp, 100001, mod_theme(slices=[panel_slice(file=bad)]))
            self.assertEqual(T.load(self.comp).reply["slices"], [], bad)

    def test_not_a_png_is_dropped(self):
        d = write_theme(self.comp, 100001, mod_theme(slices=[panel_slice()]))
        with open(os.path.join(d, "panel.png"), "wb") as f:
            f.write(b"GIF89a-not-png")
        self.assertEqual(T.load(self.comp).reply["slices"], [])

    def test_image_path_only_for_validated_slices(self):
        write_theme(self.comp, 100001, mod_theme(slices=[panel_slice()]), [("panel.png", 48, 48)])
        res = T.load(self.comp)
        self.assertTrue(res.image_path("panel").endswith(os.path.join("theme", "100001", "panel.png")))
        self.assertIsNone(res.image_path("button"))
        self.assertIsNone(res.image_path("../../etc"))

    def test_schema_negative_fixtures(self):
        self.assertTrue(V.validate({"schema": 1, "source": "game"}, "theme.schema.json"))
        bad_slice = {"name": "panel", "art": "/x", "width": 1, "height": 1, "insets": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "file": "x.png"}
        self.assertTrue(V.validate(dict(T.builtin(), slices=[bad_slice]), "theme.schema.json"))


class Served(unittest.TestCase):
    """GET /api/v1/theme through the route table, with a views object that uses this module."""

    def test_route_returns_reply(self):
        from oni_companion.server import routes
        from oni_companion.views.provider import Views

        class Ctx:
            cfg = None

        class Cfg:
            companion_dir = os.path.join(FIX, "companion")

        views = Views(Ctx(), lookup=object(), config=Cfg())
        out = routes.dispatch("GET", "/api/v1/theme", None, Ctx(), views)
        self.assertEqual(out["source"], "game")
        self.assertEqual(V.validate(out, "theme.schema.json"), [])

    def test_route_builtin_without_companion(self):
        from oni_companion.server import routes
        from oni_companion.views.provider import Views

        class Ctx:
            cfg = None

        class Cfg:
            companion_dir = ""

        views = Views(Ctx(), lookup=object(), config=Cfg())
        out = routes.dispatch("GET", "/api/v1/theme", None, Ctx(), views)
        self.assertEqual(out["source"], "builtin")


if __name__ == "__main__":
    unittest.main()


class Contrast(unittest.TestCase):
    """v1.2: every text token must read on the background it is drawn on."""

    def test_builtin_passes_every_pair(self):
        notes = []
        self.assertEqual(T.ensure_contrast(T.BUILTIN_COLORS, notes), T.BUILTIN_COLORS)
        self.assertEqual(notes, [])

    def test_failing_text_color_is_fixed_and_noted(self):
        colors = dict(T.BUILTIN_COLORS, sectionHeader="#B0B0B0", sectionHeaderText="#FFFFFF", tabBg="#B0B0B0", tabText="#808080")
        notes = []
        out = T.ensure_contrast(colors, notes)
        for fg, bg, need in T.CONTRAST_PAIRS:
            self.assertGreaterEqual(T.contrast_ratio(out[fg], out[bg], out["background"]), need, (fg, bg))
        self.assertEqual(out["sectionHeaderText"], "#000000")
        self.assertTrue(any("sectionHeaderText" in n for n in notes))

    def test_translucent_background_is_composited_over_the_page(self):
        self.assertGreater(T.contrast_ratio("#FFFFFF", "#373A4DCC", "#494949"), 7)
        self.assertLess(T.contrast_ratio("#000000", "#373A4DCC", "#494949"), 2)

    def test_game_theme_is_checked_on_load(self):
        tmp = tempfile.mkdtemp(prefix="c9-contrast-")
        try:
            comp = os.path.join(tmp, "companion")
            colors = dict(T.BUILTIN_COLORS, background="#494949", panel="#FFFFFF", text="#FFFFFF")   # white text on a white panel
            write_theme(comp, 100001, mod_theme(colors=colors))
            res = T.load(comp)
            self.assertEqual(res.reply["source"], "game")
            self.assertGreaterEqual(T.contrast_ratio(res.reply["colors"]["text"], "#FFFFFF"), 4.5)
            self.assertTrue(any(n.startswith("contrast:") for n in res.notes))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class V12Tokens(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c9-v12-")
        self.comp = os.path.join(self.tmp, "companion")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_old_theme_gets_game_derived_tokens(self):
        old = {k: v for k, v in T.BUILTIN_COLORS.items() if k not in T.OPTIONAL_COLORS or k in ("warning", "info")}
        old.update(buttonNormal="#3E4357", buttonHover="#585F7C", panel="#FFFFFF", textTitle="#FFFFFF", background="#494949")
        write_theme(self.comp, 100001, mod_theme(colors=old))
        c = T.load(self.comp).reply["colors"]
        self.assertEqual(c["sectionHeader"], "#3E4357")
        self.assertEqual(c["tabBg"], "#585F7C")
        self.assertEqual(c["alertBg"], "#3E4357CC")

    def test_new_tokens_slice_and_render_rev_validate(self):
        colors = dict(T.BUILTIN_COLORS, sectionHeader="#B0B0B0", tabBg="#B0B0B0", tabActiveBg="#FFFFFF", tabText="#000000",
                      tabTextActive="#000000", alertBg="#373A4DCC")
        sl = panel_slice(name="sectionHeader", file="sectionHeader.png")
        write_theme(self.comp, 100001, mod_theme(colors=colors, slices=[sl], renderRev=3), [("sectionHeader.png", 48, 48)])
        res = T.load(self.comp)
        self.assertEqual(res.reply["source"], "game")
        self.assertEqual([s["name"] for s in res.reply["slices"]], ["sectionHeader"])
        self.assertEqual(V.validate(res.reply, "theme.schema.json"), [])
        doc = mod_theme(colors=colors, renderRev=3)
        self.assertEqual(V.validate(doc, "theme.schema.json#/$defs/ModTheme"), [])

    def test_alerts_list_carries_the_variant_hint(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        from oni_companion.views import blocks as B
        b = B.list_block([{"title": "x"}], title="Alerts", variant="alerts")
        self.assertEqual(b["variant"], "alerts")
        self.assertNotIn("variant", B.list_block([{"title": "x"}]))
