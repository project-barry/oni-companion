"""Game skin for the front ends (v1.1 lane C9): GET /api/v1/theme.

The mod writes companion/theme/<build>/theme.json once per build (colors read from the game's own
UI style assets, 9-slice PNGs rendered on the user's device). This module reads the newest valid
one and returns a `Theme` reply (contracts/theme.schema.json). With no valid game theme it returns
the built-in dark theme, whose colors are the v1 colors of clients/barry/qml/Theme.qml.

Rules:
- A theme.json that fails the ModTheme contract is ignored as a whole (builtin is used) and the
  reason is kept in `notes`.
- A single slice that fails (bad PNG size, bad insets, missing file) is dropped; the others stay.
- Only files named by a validated slice are ever served. The request never names a path.
- Stdlib only. Reads are on request (no polling); a few KB of JSON and PNG headers per call.
"""
import json
import os
import re
import struct

SCHEMA = 1
FONT_FAMILY = "Noto Sans"
THEME_DIR = "theme"
ART_UI_PREFIX = "/api/v1/art/ui/"

# The v1 colors (clients/barry/qml/Theme.qml) mapped to the named tokens.
BUILTIN_COLORS = {
    "background": "#0e1218",     # Theme.bg
    "panel": "#18202a",          # Theme.panel
    "header": "#222c39",         # Theme.panelHi (header and tap-highlight)
    "border": "#2c3846",         # Theme.line
    "buttonNormal": "#222c39",   # panelHi, the v1 tap highlight
    "buttonHover": "#2c3846",    # line
    "buttonPressed": "#18202a",  # panel
    "text": "#eef0f4",           # Theme.text
    "textDim": "#9aa4b5",        # Theme.muted
    "textTitle": "#eef0f4",      # v1 headings use Theme.text
    "positive": "#4cc38a",       # Theme.good
    "negative": "#ef5b5b",       # Theme.bad
    "warning": "#e8b44a",        # Theme.warn
    "info": "#5aa9ff",           # Theme.accent
    "progressFill": "#4cc38a",   # v1 progress bars use the tone color (good)
    "progressTrack": "#2c3846",  # line
    "meterStress": "#e8b44a",    # warn
    "meterHealth": "#ef5b5b",    # bad
    "meterCalories": "#5aa9ff",  # accent
    # v1.2: how the game draws section bars, tabs and the alert list (builtin = the v1 look)
    "sectionHeader": "#222c39",      # panelHi
    "sectionHeaderText": "#eef0f4",  # text
    "tabBg": "#18202a",              # panel
    "tabActiveBg": "#18202a",        # panel (the v1 tab bar has no separate active fill)
    "tabText": "#9aa4b5",            # muted
    "tabTextActive": "#eef0f4",      # title
    "alertBg": "#18202a",            # panel
    "alertText": "#eef0f4",          # text
    "alertBadBg": "#18202a",         # panel
    "alertBadText": "#ef5b5b",       # bad
}
REQUIRED_COLORS = (
    "background", "panel", "header", "border", "buttonNormal", "buttonHover", "buttonPressed",
    "text", "textDim", "textTitle", "positive", "negative", "progressFill", "progressTrack",
    "meterStress", "meterHealth", "meterCalories",
)
OPTIONAL_COLORS = ("warning", "info", "sectionHeader", "sectionHeaderText", "tabBg", "tabActiveBg", "tabText",
                   "tabTextActive", "alertBg", "alertText", "alertBadBg", "alertBadText")
SLICE_NAMES = ("panel", "header", "button", "buttonHover", "buttonPressed", "tab", "tabActive", "sectionHeader")

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_FILE = re.compile(r"^[A-Za-z0-9_-]+\.png$")
_ICON_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class ThemeError(Exception):
    """A theme.json (or one slice of it) does not match the contract."""


class Resolved:
    """The result of one load: the reply dict, the served files and the notes."""

    def __init__(self, reply, files, notes):
        self.reply = reply      # Theme (theme.schema.json), ready for JSON
        self.files = files      # {slice name: absolute PNG path}, only for validated slices
        self.notes = notes      # why a game theme was not used, or which slices were dropped

    def image_path(self, name):
        """Absolute path of the PNG behind /api/v1/art/ui/<name>, or None."""
        return self.files.get(name)


def builtin():
    return {
        "schema": SCHEMA,
        "source": "builtin",
        "colors": dict(BUILTIN_COLORS),
        "font": {"family": FONT_FAMILY},
        "slices": [],
    }


def png_size(path):
    """(width, height) from the IHDR chunk, or None if the file is not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def _need(cond, msg):
    if not cond:
        raise ThemeError(msg)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _derived(c):
    """v1.2 tokens an older mod (before 0.2.3) did not write, built from the game colors it did write."""
    try:
        return {
            "sectionHeader": c["buttonNormal"], "sectionHeaderText": c["textTitle"],
            "tabBg": c["buttonHover"], "tabActiveBg": c["panel"], "tabText": c["text"], "tabTextActive": c["text"],
            "alertBg": c["buttonNormal"][:7] + "CC", "alertText": c["textTitle"],
            "alertBadBg": c["buttonNormal"][:7] + "CC", "alertBadText": c["negative"],
        }
    except (KeyError, TypeError):
        return {}


def _check_colors(colors):
    _need(isinstance(colors, dict), "colors must be an object")
    allowed = set(REQUIRED_COLORS) | set(OPTIONAL_COLORS)
    extra = set(colors) - allowed
    _need(not extra, "colors has unknown keys: %s" % ", ".join(sorted(extra)))
    for k in REQUIRED_COLORS:
        _need(k in colors, "colors.%s is missing" % k)
    for k, v in colors.items():
        _need(isinstance(v, str) and _COLOR.match(v), "colors.%s is not #RRGGBB or #RRGGBBAA" % k)
    out = dict(BUILTIN_COLORS)     # optional tokens fall back to the v1 tone colors
    out.update(_derived(colors))   # ... and the v1.2 tokens of a theme written by an older mod, to the game's own colors
    out.update(colors)
    return {k: out[k] for k in BUILTIN_COLORS}


# Text must read on what it is drawn on. (foreground token, background token, minimum contrast ratio, WCAG 2 formula).
# Secondary text (textDim) only needs the large-text ratio.
CONTRAST_PAIRS = (
    ("text", "panel", 4.5), ("textDim", "panel", 3.0),
    ("textTitle", "header", 4.5), ("textTitle", "background", 4.5), ("textTitle", "buttonNormal", 4.5), ("textDim", "background", 3.0),
    ("sectionHeaderText", "sectionHeader", 4.5),
    ("tabText", "tabBg", 4.5), ("tabTextActive", "tabActiveBg", 4.5),
    ("alertText", "alertBg", 4.5), ("alertBadText", "alertBadBg", 4.5),
)


def _rgba(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
    return r, g, b, a


def _over(fg, bg):
    """fg (r, g, b, a) composited over an opaque bg (r, g, b)."""
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))


def _lum(rgb):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast_ratio(fg_hex, bg_hex, page_hex="#000000"):
    """WCAG contrast of fg on bg; translucent colors are composited over the page color first."""
    page = _rgba(page_hex)[:3]
    bg = _over(_rgba(bg_hex), page)
    fg = _over(_rgba(fg_hex), bg)
    hi, lo = max(_lum(fg), _lum(bg)), min(_lum(fg), _lum(bg))
    return (hi + 0.05) / (lo + 0.05)


def _mix_hex(hexcolor, target, t):
    r, g, b, _a = _rgba(hexcolor)
    return "#%02X%02X%02X" % tuple(int(round(c + (target - c) * t)) for c in (r, g, b))


def ensure_contrast(colors, notes=None):
    """Returns colors with every text token in CONTRAST_PAIRS readable on its background. A failing text color is moved
    toward black or white (whichever needs the smaller move), so it keeps its hue; the move is noted."""
    out = dict(colors)
    page = out["background"]
    for fg, bg, need in CONTRAST_PAIRS:
        if fg not in out or bg not in out:
            continue
        ratio = contrast_ratio(out[fg], out[bg], page)
        if ratio >= need:
            continue
        best = None
        for target in (0, 255):
            for step in range(1, 21):
                cand = _mix_hex(out[fg], target, step / 20.0)
                if contrast_ratio(cand, out[bg], page) >= need:
                    if best is None or step < best[0]:
                        best = (step, cand)
                    break
        if best is not None and best[0] > 10:        # more than half way: a plain black or white reads better than a mid gray
            best = None
        if best is None:
            best = (0, "#000000" if contrast_ratio("#000000", out[bg], page) >= contrast_ratio("#FFFFFF", out[bg], page) else "#FFFFFF")
        if notes is not None:
            notes.append("contrast: %s on %s was %.1f:1 (need %.1f), changed %s to %s" % (fg, bg, ratio, need, out[fg], best[1]))
        out[fg] = best[1]
    return out


def _check_insets(ins, width, height):
    _need(isinstance(ins, dict), "insets must be an object")
    _need(set(ins) == {"left", "top", "right", "bottom"}, "insets need exactly left, top, right, bottom")
    for k, v in ins.items():
        _need(_is_int(v) and v >= 0, "insets.%s must be a whole number >= 0" % k)
    _need(ins["left"] + ins["right"] <= width and ins["top"] + ins["bottom"] <= height,
          "insets are larger than the image")
    return {k: ins[k] for k in ("left", "top", "right", "bottom")}


def _check_slice(s, theme_dir, seen):
    _need(isinstance(s, dict), "slice must be an object")
    _need(set(s) == {"name", "file", "width", "height", "insets"}, "slice has missing or unknown keys")
    _need(s["name"] in SLICE_NAMES, "slice name %r is not allowed" % (s["name"],))
    _need(s["name"] not in seen, "slice %s appears twice" % s["name"])
    _need(isinstance(s["file"], str) and _FILE.match(s["file"]), "slice file must be a plain *.png name")
    for k in ("width", "height"):
        _need(_is_int(s[k]) and s[k] >= 1, "slice %s must be a whole number >= 1" % k)
    path = os.path.join(theme_dir, s["file"])
    size = png_size(path)
    _need(size is not None, "slice %s: %s is not a readable PNG" % (s["name"], s["file"]))
    _need(size == (s["width"], s["height"]), "slice %s: PNG is %dx%d, theme says %dx%d"
          % (s["name"], size[0], size[1], s["width"], s["height"]))
    ins = _check_insets(s["insets"], s["width"], s["height"])
    return path, {"name": s["name"], "art": ART_UI_PREFIX + s["name"], "width": s["width"],
                  "height": s["height"], "insets": ins}


def _check_icon(i, theme_dir, seen):
    _need(isinstance(i, dict), "icon must be an object")
    _need({"name", "file", "width", "height"} <= set(i) <= {"name", "file", "activeFile", "width", "height"},
          "icon has missing or unknown keys")
    _need(isinstance(i["name"], str) and _ICON_NAME.match(i["name"]), "icon name %r is not allowed" % (i["name"],))
    _need(i["name"] not in seen, "%s appears twice" % i["name"])
    for k in ("width", "height"):
        _need(_is_int(i[k]) and i[k] >= 1, "icon %s must be a whole number >= 1" % k)
    got, out = {}, {"name": i["name"], "art": ART_UI_PREFIX + i["name"], "width": i["width"], "height": i["height"]}
    for key, name in (("file", i["name"]), ("activeFile", i["name"] + "Active")):
        if key not in i:
            continue
        _need(isinstance(i[key], str) and _FILE.match(i[key]), "icon %s: %s must be a plain *.png name" % (i["name"], key))
        path = os.path.join(theme_dir, i[key])
        _need(png_size(path) is not None, "icon %s: %s is not a readable PNG" % (i["name"], i[key]))
        got[name] = path
        if key == "activeFile":
            out["activeArt"] = ART_UI_PREFIX + name
    return got, out


def parse_mod_theme(doc, theme_dir):
    """Validate a ModTheme dict. Returns (colors, slices, icons, files, notes) or raises ThemeError.

    `slices` and `icons` are the reply form; `files` maps slice/icon name to its absolute PNG path. A slice or
    icon that fails is left out and its reason goes into `notes`; the top-level fields must all pass.
    """
    _need(isinstance(doc, dict), "theme.json must be an object")
    required = {"schema", "modVersion", "build", "writtenAt", "colors", "slices"}
    _need(required <= set(doc), "theme.json is missing: %s" % ", ".join(sorted(required - set(doc))))
    optional = {"renderRev", "icons"}
    _need(set(doc) - optional == required, "theme.json has unknown keys: %s" % ", ".join(sorted(set(doc) - required - optional)))
    _need("renderRev" not in doc or _is_int(doc["renderRev"]), "renderRev must be a whole number")
    _need(doc["schema"] == SCHEMA, "theme.json schema must be %d" % SCHEMA)
    _need(isinstance(doc["modVersion"], str), "modVersion must be a string")
    _need(_is_int(doc["build"]), "build must be a whole number")
    _need(isinstance(doc["writtenAt"], str) and _DATETIME.match(doc["writtenAt"]),
          "writtenAt must be a date-time")
    colors = _check_colors(doc["colors"])
    _need(isinstance(doc["slices"], list), "slices must be a list")
    slices, files, notes, seen = [], {}, [], set()
    colors = ensure_contrast(colors, notes)
    for s in doc["slices"]:
        try:
            path, out = _check_slice(s, theme_dir, seen)
        except ThemeError as e:
            notes.append("slice dropped: %s" % e)
            continue
        seen.add(out["name"])
        slices.append(out)
        files[out["name"]] = path
    icons = []
    raw = doc.get("icons", [])
    if not isinstance(raw, list):
        notes.append("icons dropped: icons must be a list")
        raw = []
    for i in raw:
        try:
            got, out = _check_icon(i, theme_dir, seen)
        except ThemeError as e:
            notes.append("icon dropped: %s" % e)
            continue
        seen.add(out["name"])
        icons.append(out)
        files.update(got)
    return colors, slices, icons, files, notes


def _build_dirs(theme_root):
    try:
        names = os.listdir(theme_root)
    except OSError:
        return []
    builds = [n for n in names if n.isdigit() and os.path.isdir(os.path.join(theme_root, n))]
    return sorted(builds, key=int, reverse=True)     # newest (highest) build first


def load(companion_dir):
    """Resolve the skin for one companion folder. Never raises on bad files."""
    if not companion_dir:
        return Resolved(builtin(), {}, ["no companion folder: built-in theme"])
    theme_root = os.path.join(companion_dir, THEME_DIR)
    notes = []
    for build in _build_dirs(theme_root):
        theme_dir = os.path.join(theme_root, build)
        json_path = os.path.join(theme_dir, "theme.json")
        try:
            with open(json_path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            notes.append("build %s: theme.json not readable (%s)" % (build, e.__class__.__name__))
            continue
        try:
            colors, slices, icons, files, slice_notes = parse_mod_theme(doc, theme_dir)
        except ThemeError as e:
            notes.append("build %s: %s" % (build, e))
            continue
        reply = {
            "schema": SCHEMA,
            "source": "game",
            "build": doc["build"],
            "colors": colors,
            "font": {"family": FONT_FAMILY},
            "slices": slices,
        }
        if icons:
            reply["icons"] = icons
        return Resolved(reply, files, notes + slice_notes)
    if not notes:
        notes.append("no game theme in %s: built-in theme" % theme_root)
    return Resolved(builtin(), {}, notes)


def reply(companion_dir):
    """The GET /api/v1/theme body."""
    return load(companion_dir).reply
