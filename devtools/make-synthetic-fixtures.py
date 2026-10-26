#!/usr/bin/env python3
"""Generates the v1.1 synthetic fixtures: placeholder PNGs (solid shapes, no game art),
the art manifest with real sizes and hashes, a synthetic theme, commands and acks.
stdlib only. Run from anywhere: python3 devtools/make-synthetic-fixtures.py"""
import hashlib
import json
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "fixtures", "synthetic", "companion")
OUT12 = os.path.join(ROOT, "fixtures", "synthetic", "companion-v12")
BUILD = 100001
STAMP = "2026-01-01T12:00:00Z"


def png(w, h, pixel):
    """pixel(x, y) -> (r, g, b, a)."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(pixel(x, y))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def shape(kind, size, rgb):
    c = (size - 1) / 2.0

    def px(x, y):
        dx, dy = x - c, y - c
        r = size * 0.42
        if kind == "circle":
            inside = dx * dx + dy * dy <= r * r
        elif kind == "diamond":
            inside = abs(dx) + abs(dy) <= r
        else:
            inside = abs(dx) <= r and abs(dy) <= r
        return rgb + (255,) if inside else (0, 0, 0, 0)
    return png(size, size, px)


def slice_img(w, h, border, fill, edge):
    def px(x, y):
        on = x < border or y < border or x >= w - border or y >= h - border
        return (edge if on else fill) + (255,)
    return png(w, h, px)


def write(path, data, out=None):
    full = os.path.join(out or OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)
    return data


def wjson(path, obj, out=None):
    write(path, json.dumps(obj, indent=2) + "\n", out)


def synth_font():
    """A tiny valid TrueType file (two empty glyphs, 'A' mapped): lets the core's sfnt and name-table
    checks run on a font that is not from any game. Family 'Synth Sans'."""
    def u16(*v):
        return struct.pack(">%dH" % len(v), *v)

    def name_table():
        recs = [(1, "Synth Sans"), (2, "Regular"), (4, "Synth Sans Regular"), (6, "SynthSans-Regular")]
        strings, rows, off = b"", b"", 0
        for nid, text in recs:
            raw = text.encode("utf-16-be")
            rows += struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(raw), off)
            strings += raw
            off += len(raw)
        return struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs)) + rows + strings

    cmap_sub = (u16(4, 32, 0, 4, 4, 1, 0) + u16(0x41, 0xFFFF) + u16(0) + u16(0x41, 0xFFFF)
                + u16((1 - 0x41) & 0xFFFF, 1) + u16(0, 0))
    tables = {
        "cmap": u16(0, 1) + struct.pack(">HHI", 3, 1, 12) + cmap_sub,
        "head": struct.pack(">iiIIHHqqhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0, 1000, 0, 0,
                            0, 0, 0, 0, 0, 8, 2, 0, 0),
        "hhea": struct.pack(">ihhhHhhhhhhhhhhhH", 0x00010000, 800, -200, 0, 500, 0, 0, 0, 1, 0, 0,
                            0, 0, 0, 0, 0, 2),
        "hmtx": struct.pack(">HhHh", 500, 0, 500, 0),
        "loca": u16(0, 0, 0),
        "glyf": b"",
        "maxp": struct.pack(">IH", 0x00010000, 2) + u16(0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0),
        "name": name_table(),
        "post": struct.pack(">IiHHIIIII", 0x00030000, 0, 0xFF9C, 50, 0, 0, 0, 0, 0),
    }
    tags = sorted(tables)
    n = len(tags)
    out = struct.pack(">IHHHH", 0x00010000, n, 128, 3, n * 16 - 128)
    off = 12 + 16 * n
    body, rows, head_at = b"", b"", None
    for t in tags:
        data = tables[t]
        padded = data + b"\0" * (-len(data) % 4)
        total = sum(struct.unpack(">%dI" % (len(padded) // 4), padded)) & 0xFFFFFFFF if padded else 0
        rows += t.encode() + struct.pack(">III", total, off + len(body), len(data))
        if t == "head":
            head_at = off + len(body)
        body += padded
    blob = bytearray(out + rows + body)
    whole = bytes(blob) + b"\0" * (-len(blob) % 4)
    adj = (0xB1B0AFBA - sum(struct.unpack(">%dI" % (len(whole) // 4), whole))) & 0xFFFFFFFF
    blob[head_at + 8:head_at + 12] = struct.pack(">I", adj)
    return bytes(blob)


def main():
    files = []
    art = [
        ("building", "SynthWidget", "square", 128, (200, 120, 40)),
        ("element", "SynthWidgetium", "diamond", 128, (90, 160, 220)),
        ("critter", "SynthBeast", "circle", 128, (120, 200, 120)),
        ("plant", "SynthPlant", "circle", 128, (60, 160, 90)),
        ("food", "SynthBar", "square", 128, (210, 180, 90)),
        ("item", "SynthTag", "diamond", 128, (170, 90, 200)),
        ("dupe", "d1", "circle", 256, (220, 120, 140)),
        ("dupe", "d2", "circle", 256, (140, 120, 220)),
    ]
    hashes = {"d1": "ab12cd34", "d2": "0f0f0f0f"}
    for kind, id_, shp, size, rgb in art:
        h = hashes.get(id_)
        rel = "%d/%s/%s%s.png" % (BUILD, kind, id_, "-" + h if h else "")
        data = write("art/" + rel, shape(shp, size, rgb))
        e = {"kind": kind, "id": id_, "path": rel}
        if h:
            e["appearanceHash"] = h
        e.update(size=len(data), sha256=hashlib.sha256(data).hexdigest(), width=size, height=size)
        files.append(e)
    wjson("art/manifest.json", {
        "schema": 1, "modVersion": "0.2.0", "build": BUILD, "dlcIds": ["DLC_ALPHA_ID"],
        "writtenAt": STAMP, "catalogComplete": True,
        "stats": {"totalMs": 850.5, "worstFrameMs": 3.2, "count": len(files)},
        "files": files})

    slices = []
    spec = [("panel", 48, 48, 6, (30, 36, 48), (80, 90, 110)),
            ("header", 48, 24, 4, (50, 60, 80), (110, 120, 140)),
            ("button", 32, 24, 3, (60, 70, 90), (120, 130, 150)),
            ("buttonHover", 32, 24, 3, (75, 85, 110), (140, 150, 170)),
            ("buttonPressed", 32, 24, 3, (40, 48, 64), (100, 110, 130))]
    for name, w, h, b, fill, edge in spec:
        write("theme/%d/%s.png" % (BUILD, name), slice_img(w, h, b, fill, edge))
        slices.append({"name": name, "file": name, "width": w, "height": h,
                       "insets": {"left": b, "top": b, "right": b, "bottom": b}})
    for s in slices:
        s["file"] += ".png"
    colors = {
        "background": "#10151c", "panel": "#1e2430", "header": "#323c50", "border": "#505a6e",
        "buttonNormal": "#3c4659", "buttonHover": "#4b556e", "buttonPressed": "#283040",
        "text": "#e6e9ef", "textDim": "#98a2b3", "textTitle": "#ffffff",
        "positive": "#4cc38a", "negative": "#ef5b5b", "warning": "#e8b44a", "info": "#5aa9ff",
        "progressFill": "#4cc38a", "progressTrack": "#283040",
        "meterStress": "#e8b44a", "meterHealth": "#ef5b5b", "meterCalories": "#5aa9ff"}
    icons = []
    for name, shp, rgb in [("speedPause", "square", (230, 230, 240)), ("speedPlay", "diamond", (230, 230, 240)),
                           ("speed1", "circle", (200, 200, 90)), ("speed2", "circle", (230, 190, 70)),
                           ("speed3", "circle", (240, 150, 60))]:
        write("theme/%d/%s.png" % (BUILD, name), shape(shp, 24, rgb), OUT12)
        icons.append({"name": name, "file": name + ".png", "width": 24, "height": 24})
    wjson("theme/%d/theme.json" % BUILD, {
        "schema": 1, "modVersion": "0.2.0", "build": BUILD, "writtenAt": STAMP,
        "colors": colors, "slices": slices})
    # v1.2 theme (icons) lives apart so a v1.1 core is not fed fields it does not know
    for name, w, h, b, fill, edge in spec:
        write("theme/%d/%s.png" % (BUILD, name), slice_img(w, h, b, fill, edge), OUT12)
    wjson("theme/%d/theme.json" % BUILD, {
        "schema": 1, "modVersion": "0.3.0", "renderRev": 2, "build": BUILD, "writtenAt": STAMP,
        "colors": colors, "slices": slices, "icons": icons}, OUT12)

    wjson("commands/cmd-5.json", {"schema": 1, "seq": 5, "createdAt": STAMP, "type": "focus",
                                  "target": {"kind": "dupe", "id": "d1"}, "select": True})
    wjson("commands/cmd-7.json", {"schema": 1, "seq": 7, "createdAt": STAMP, "type": "art_request",
                                  "target": {"kind": "building", "id": "SynthWidget"}})
    wjson("acks/ack-7.json", {"schema": 1, "seq": 7, "state": "done", "message": "Drawn", "ackedAt": STAMP})
    wjson("acks/ack-8.json", {"schema": 1, "seq": 8, "state": "failed", "message": "Unknown id", "ackedAt": STAMP})
    wjson("commands/cmd-9.json", {"schema": 1, "seq": 9, "createdAt": STAMP, "type": "alert_activate",
                                  "alertId": "a1", "link": 0})
    wjson("commands/cmd-10.json", {"schema": 1, "seq": 10, "createdAt": STAMP, "type": "alert_dismiss",
                                   "alertId": "a3"})
    wjson("commands/cmd-11.json", {"schema": 1, "seq": 11, "createdAt": STAMP, "type": "set_speed",
                                   "state": "play", "speed": 2})
    wjson("commands/cmd-12.json", {"schema": 1, "seq": 12, "createdAt": STAMP, "type": "set_speed",
                                   "state": "pause"})
    wjson("commands/cmd-13.json", {"schema": 1, "seq": 13, "createdAt": STAMP, "type": "sync_assets",
                                   "scope": "missing"})
    wjson("acks/ack-9.json", {"schema": 1, "seq": 9, "state": "done", "ackedAt": STAMP})
    wjson("acks/ack-10.json", {"schema": 1, "seq": 10, "state": "failed", "message": "Alert is gone",
                               "ackedAt": STAMP})
    wjson("acks/ack-11.json", {"schema": 1, "seq": 11, "state": "done", "ackedAt": STAMP})
    wjson("acks/ack-13.json", {"schema": 1, "seq": 13, "state": "done", "message": "Started", "ackedAt": STAMP})

    stages = lambda a, b, c: [{"name": "art", "state": a}, {"name": "theme", "state": b}, {"name": "fonts", "state": c}]
    wjson("sync/status.json", {
        "schema": 1, "modVersion": "0.3.0", "state": "running", "scope": "missing", "build": BUILD,
        "dlcIds": ["DLC_ALPHA_ID"], "done": 312, "total": 1033, "current": "building: SynthWidget",
        "errors": 0, "stages": stages("running", "pending", "pending"), "gamePausedBySync": True,
        "startedAt": STAMP, "updatedAt": STAMP, "elapsedMs": 41250})
    wjson("sync/status-done.json", {
        "schema": 1, "modVersion": "0.3.0", "state": "done", "scope": "full", "build": BUILD,
        "dlcIds": ["DLC_ALPHA_ID"], "done": 1033, "total": 1033, "current": None, "errors": 2,
        "lastError": "item: SynthTag has no image", "stages": stages("done", "done", "done"),
        "gamePausedBySync": False, "startedAt": STAMP, "updatedAt": STAMP, "elapsedMs": 138800,
        "worstFrameMs": 61.5})

    write("fonts/%d/SynthSans.ttf" % BUILD, synth_font())
    atlas = write("fonts/%d/graystroke.png" % BUILD,
                  png(64, 64, lambda x, y: (255, 255, 255, 255 if (x // 8 + y // 8) % 2 == 0 else 0)))
    wjson("fonts/%d/graystroke.json" % BUILD, {
        "schema": 1, "modVersion": "0.3.0", "build": BUILD, "name": "SYNTH DISPLAY SDF", "family": "Synth Display",
        "atlas": {"file": "graystroke.png", "width": 64, "height": 64, "padding": 4, "spread": 5.0,
                  "pointSize": 36, "encoding": "sdf-alpha"},
        "face": {"lineHeight": 44.0, "ascent": 34.0, "descent": -10.0, "scale": 1.0, "tabWidth": 20.0},
        "glyphs": [
            {"unicode": 32, "x": 0, "y": 0, "w": 0, "h": 0, "bearingX": 0.0, "bearingY": 0.0, "advance": 12.0},
            {"unicode": 65, "x": 4, "y": 4, "w": 24, "h": 28, "bearingX": 1.0, "bearingY": 28.0, "advance": 26.0},
            {"unicode": 66, "x": 32, "y": 4, "w": 22, "h": 28, "bearingX": 2.0, "bearingY": 28.0, "advance": 24.0}],
        "kerning": [{"first": 65, "second": 66, "x": -1.5}]})
    wjson("acks/ack-5.json", {"schema": 1, "seq": 5, "state": "done", "ackedAt": STAMP})
    wjson("acks/ack-6.json", {"schema": 1, "seq": 6, "state": "failed",
                              "message": "Duplicant not found", "ackedAt": STAMP})


if __name__ == "__main__":
    main()
