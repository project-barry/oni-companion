"""Regressions from the live test: card titles were white on the game's white panel, and portraits flashed their
placeholder on every live refresh. Synthetic data only."""
import glob
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
QML = os.path.join(ROOT, "clients", "barry", "qml")

from oni_companion import theme as T  # noqa: E402
from oni_companion.art.store import art_url  # noqa: E402

# The game's own colors (white panel, white title): the case that hid the names.
GAME = dict(T.BUILTIN_COLORS, panel="#FFFFFF", textTitle="#FFFFFF", text="#000000", textDim="#808080")


# Blocks whose text sits on a panel (FormBlock only uses a panel for its fields; its labels sit on the page).
PANEL_FILES = ("GridBlock.qml", "ListBlock.qml", "StatsBlock.qml", "TableBlock.qml", "PortsBlock.qml", "PhasesBlock.qml")


def read(name):
    with open(os.path.join(QML, name), encoding="utf-8") as f:
        return f.read()


class PanelText(unittest.TestCase):
    def test_game_theme_text_on_panel_reads(self):
        self.assertGreaterEqual(T.contrast_ratio(GAME["text"], GAME["panel"]), 4.5)
        self.assertLess(T.contrast_ratio(GAME["textTitle"], GAME["panel"]), 2.0)   # why titles must not use textTitle
        pairs = {(f, b) for f, b, _ in T.CONTRAST_PAIRS}
        self.assertIn(("text", "panel"), pairs)
        self.assertIn(("textDim", "panel"), pairs)

    def test_panel_files_never_draw_text_in_title_color(self):
        """Files that draw on theme.panel may use theme.text / muted, never the title color (white on the game's panel)."""
        for path in glob.glob(os.path.join(QML, "*.qml")):
            src = open(path, encoding="utf-8").read()
            if os.path.basename(path) in PANEL_FILES:
                self.assertFalse(re.search(r"color:\s*[\w.]*theme\.(title|pageText|buttonText)\b", src),
                                 os.path.basename(path))

    def test_card_title_uses_text_color(self):
        g = read("GridBlock.qml")
        i = g.index("card.modelData.title || \"\"", g.index("elide: Text.ElideRight"))
        self.assertIn("theme.text", g[i:i + 200])


class ArtStability(unittest.TestCase):
    def test_art_url_is_the_same_every_time(self):
        self.assertEqual(art_url("dupe", "464851"), art_url("dupe", "464851"))
        self.assertNotIn("?", art_url("dupe", "464851"))

    def test_lists_update_in_place(self):
        """Repeaters over cards, rows and blocks take a count, so a live refresh keeps the delegates (and portraits)."""
        for name in ("GridBlock.qml", "ListBlock.qml"):
            self.assertRegex(read(name), r"model:\s*c\.shown\.length")
        self.assertRegex(read("BlockView.qml"), r"model:\s*v\.blocks\.length")

    def test_art_keeps_last_picture(self):
        a = read("Art.qml")
        self.assertIn("last.source = source", a)
        self.assertRegex(a, r"last\.status !== Image\.Ready")


if __name__ == "__main__":
    unittest.main()
