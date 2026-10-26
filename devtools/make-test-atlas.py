#!/usr/bin/env python3
"""Dev only: builds a signed-distance-field atlas (graystroke.png + graystroke.json, contracts/font-atlas.schema.json)
from any font file, so the QML GameText component can be tried before the mod exports the game's real Graystroke atlas.
The output is made from the font you pass in (for example Economica Bold taken from your own game); never commit it.

  PYTHONPATH=<Barry Simulator>/Resources/site-packages <Barry Simulator>/MacOS/python devtools/make-test-atlas.py FONT OUT_DIR [--encoding sdf-alpha|sdf-red] [--skip "Q&"]

--skip leaves characters out of the atlas, to try the per-glyph fallback.
"""
import json
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QRawFont  # noqa: E402

POINT, PAD, SPREAD, SS = 48, 6, 8.0, 2      # atlas size of the font, SDF padding, distance range (atlas px), supersampling
INF = 1e9


def edt8(bitmap, w, h):
    """8SSEDT: distance from every pixel to the nearest set pixel of `bitmap` (list of bools)."""
    def run(inside):
        grid = [(0.0, 0.0) if b == inside else (INF, INF) for b in bitmap]
        d = lambda p: p[0] * p[0] + p[1] * p[1]
        def cmp(x, y, dx, dy):
            if 0 <= x + dx < w and 0 <= y + dy < h:
                o = grid[(y + dy) * w + (x + dx)]
                c = (o[0] + abs(dx), o[1] + abs(dy))
                i = y * w + x
                if d(c) < d(grid[i]):
                    grid[i] = c
        for y in range(h):
            for x in range(w):
                cmp(x, y, -1, 0); cmp(x, y, 0, -1); cmp(x, y, -1, -1); cmp(x, y, 1, -1)
            for x in range(w - 1, -1, -1):
                cmp(x, y, 1, 0)
        for y in range(h - 1, -1, -1):
            for x in range(w - 1, -1, -1):
                cmp(x, y, 1, 0); cmp(x, y, 0, 1); cmp(x, y, -1, 1); cmp(x, y, 1, 1)
            for x in range(w):
                cmp(x, y, -1, 0)
        return [math.sqrt(d(p)) for p in grid]
    return run(True), run(False)      # (distance to the nearest set pixel, distance to the nearest clear pixel)


def main():
    args = sys.argv[1:]
    enc = "sdf-alpha"
    skip = set()
    if "--encoding" in args:
        i = args.index("--encoding"); enc = args[i + 1]; del args[i:i + 2]
    if "--skip" in args:
        i = args.index("--skip"); skip = set(args[i + 1]); del args[i:i + 2]
    font_path, out = args
    os.makedirs(out, exist_ok=True)
    QGuiApplication(sys.argv[:1])
    fid = QFontDatabase.addApplicationFont(font_path)
    fam = QFontDatabase.applicationFontFamilies(fid)[0]
    font = QFont(fam); font.setPixelSize(POINT); font.setWeight(QFont.Bold)
    raw = QRawFont.fromFont(font)
    fm = QFontMetricsF(font)
    codes = [c for c in range(32, 127) if chr(c) not in skip]
    cells = []
    for c in codes:
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, chr(c))
        b = path.boundingRect()
        gw, gh = (math.ceil(b.width()) if b.width() > 0 else 0), (math.ceil(b.height()) if b.height() > 0 else 0)
        cells.append((c, path, b, gw, gh, raw.advancesForGlyphIndexes(raw.glyphIndexesForString(chr(c)))[0].x()))
    W = 512
    x = y = rowh = 0
    place = {}
    for c, path, b, gw, gh, adv in cells:
        cw, ch = gw + 2 * PAD, gh + 2 * PAD
        if x + cw > W:
            x, y, rowh = 0, y + rowh, 0
        place[c] = (x, y)
        x += cw; rowh = max(rowh, ch)
    H = 1
    while H < y + rowh:
        H *= 2
    atlas = QImage(W, H, QImage.Format_Grayscale8); atlas.fill(0)
    glyphs = []
    for c, path, b, gw, gh, adv in cells:
        px, py = place[c]
        if gw and gh:
            cw, ch = (gw + 2 * PAD) * SS, (gh + 2 * PAD) * SS
            img = QImage(cw, ch, QImage.Format_Grayscale8); img.fill(0)
            p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)
            p.scale(SS, SS); p.translate(PAD - b.left(), PAD - b.top()); p.fillPath(path, QColor(255, 255, 255)); p.end()
            bits = [(img.pixelColor(i % cw, i // cw).red() >= 128) for i in range(cw * ch)]
            tin, tout = edt8(bits, cw, ch)
            for iy in range(ch // SS):
                for ix in range(cw // SS):
                    i = (iy * SS + SS // 2) * cw + ix * SS + SS // 2
                    d = (tout[i] if bits[i] else -tin[i]) / SS      # + inside, - outside, in atlas px
                    v = max(0.0, min(1.0, 0.5 + d / SPREAD))
                    atlas.setPixel(px + ix, py + iy, int(round(v * 255)) * 0x10101 + 0xFF000000)
        glyphs.append({"unicode": c, "x": px + PAD, "y": py + PAD, "w": gw, "h": gh,
                       "bearingX": round(b.left(), 2) if gw else 0.0, "bearingY": round(-b.top(), 2) if gh else 0.0,
                       "advance": round(adv, 2)})
    if enc == "sdf-alpha":
        rgba = QImage(W, H, QImage.Format_ARGB32)
        for iy in range(H):
            for ix in range(W):
                v = atlas.pixelColor(ix, iy).red()
                rgba.setPixelColor(ix, iy, QColor(255, 255, 255, v))
        rgba.save(os.path.join(out, "graystroke.png"))
    else:
        atlas.save(os.path.join(out, "graystroke.png"))
    table = {"schema": 1, "modVersion": "dev", "build": 1, "name": "TEST SDF (from %s)" % fam, "family": "Graystroke Test",
             "atlas": {"file": "graystroke.png", "width": W, "height": H, "padding": PAD, "spread": SPREAD,
                       "pointSize": POINT, "encoding": enc},
             "face": {"lineHeight": round(fm.height(), 2), "ascent": round(fm.ascent(), 2), "descent": round(-fm.descent(), 2)},
             "glyphs": glyphs}
    with open(os.path.join(out, "graystroke.json"), "w") as f:
        json.dump(table, f)
    print("wrote", out, W, H, len(glyphs), "glyphs")


main()
