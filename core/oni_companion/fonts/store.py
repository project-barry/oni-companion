"""Fonts read at run time from the user's own game (nothing is shipped, nothing is committed).

Sources, all read-only:
  - Noto Sans (body): <game>/OxygenNotIncluded_Data/StreamingAssets/fonts/NotoSansUI-Regular.ttf
  - Economica x4 and League Spartan Bold: embedded font data inside <game>/OxygenNotIncluded_Data/sharedassets0.assets,
    found through the file's object table (unity.py) and checked as sfnt fonts (sfnt.py)
  - Graystroke (header): the TextMeshPro SDF atlas the mod exports to <ONI user folder>/companion/fonts/<build>/
    (graystroke.png + graystroke.json, contracts/font-atlas.schema.json); checked here, served as it is

Extracted fonts are cached under <data folder>/fonts/<key>/ and reused until the game files change
(size + modification time of the two source files). A damaged cache is extracted again. The request
never names a path: GET /fonts/<name> serves only names this store lists.
"""
import hashlib
import json
import logging
import os
import shutil
import struct
import tempfile
import threading

from . import sfnt, unity

log = logging.getLogger("oni_companion.fonts")

SCHEMA = 1
CACHE_DIR = "fonts"
NOTO_FILE = "NotoSansUI-Regular.ttf"
ASSETS_FILE = "sharedassets0.assets"
ATLAS_NAME = "graystroke"
MAX_ATLAS_JSON = 8 * 1024 * 1024
MAX_ATLAS_PNG = 32 * 1024 * 1024
MAX_FONT = 20 * 1024 * 1024
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
SAFE_NAME = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")

# Embedded fonts the core takes from the asset file, by the game's asset name -> the roles the game uses it for.
EMBEDDED = {
    "Economica-Regular-OTF": [],
    "Economica-Bold-OTF": [],
    "Economica-Italic-OTF": [],
    "Economica-BoldItalic-OTF": [],
    "LeagueSpartan-Bold": [],
}
LICENSE = {"Economica": "SIL OFL 1.1", "League Spartan": "SIL OFL 1.1", "Noto Sans": "SIL OFL 1.1"}


def _license(family):
    for k, v in LICENSE.items():
        if family.startswith(k):
            return v
    return ""


class FontFile:
    """A served font file (ttf/otf, atlas PNG or atlas JSON) ready to send; same shape as art.Png."""

    def __init__(self, data, content_type, etag):
        self.data, self.content_type, self.etag = data, content_type, etag


def safe_name(name):
    return isinstance(name, str) and 0 < len(name) <= 80 and set(name) <= SAFE_NAME and name[0] != "."


def _stat(path):
    try:
        st = os.stat(path)
        return [st.st_size, int(st.st_mtime)]
    except OSError:
        return None


def _read_limited(path, limit):
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file too large")
    return data


def _atomic_write(path, data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def extension(info):
    return ".otf" if info["format"] == "opentype-cff" else ".ttf"


def extract_embedded(assets_path):
    """{asset name: (font bytes, sfnt info)} for the EMBEDDED fonts that are present and valid, plus a list of notes.
    Never raises on a bad file: returns what it could validate."""
    found, notes = {}, []
    try:
        with open(assets_path, "rb") as f:
            sf = unity.SerializedFile(f)
            for obj in sf.fonts():
                try:
                    raw = sf.read(obj)
                    name, data = unity.font_from_object(raw, sf.little)
                except unity.UnityError as e:
                    notes.append("font object %d: %s" % (obj.path_id, e))
                    continue
                if name not in EMBEDDED or not data:
                    continue
                try:
                    info = sfnt.check(data)
                except sfnt.FontError as e:
                    notes.append("%s: %s" % (name, e))
                    continue
                found[name] = (data, info)
    except (OSError, unity.UnityError, struct.error) as e:
        notes.append("%s: %s" % (ASSETS_FILE, e))
    return found, notes


def _file_name(asset_name, info):
    base = asset_name.replace("-OTF", "")
    return base + extension(info)


def validate_atlas(json_path, png_path):
    """The mod's Graystroke export: (table dict) or raises ValueError. Checks the parts a front end relies on."""
    doc = json.loads(_read_limited(json_path, MAX_ATLAS_JSON).decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != 1:
        raise ValueError("atlas table: schema must be 1")
    for k in ("name", "family", "atlas", "face", "glyphs", "build"):
        if k not in doc:
            raise ValueError("atlas table: %s is missing" % k)
    at, face, glyphs = doc["atlas"], doc["face"], doc["glyphs"]
    if not isinstance(at, dict) or not isinstance(face, dict) or not isinstance(glyphs, list) or not glyphs:
        raise ValueError("atlas table: bad shape")
    w, h = at.get("width"), at.get("height")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in (w, h)):
        raise ValueError("atlas table: bad size")
    if at.get("file") != os.path.basename(png_path):
        raise ValueError("atlas table: file name does not match")
    for k in ("padding", "spread", "pointSize"):
        if not isinstance(at.get(k), (int, float)) or isinstance(at.get(k), bool) or at[k] < 0:
            raise ValueError("atlas table: atlas.%s" % k)
    if at["pointSize"] < 1:
        raise ValueError("atlas table: pointSize")
    for k in ("lineHeight", "ascent", "descent"):
        if not isinstance(face.get(k), (int, float)) or isinstance(face.get(k), bool):
            raise ValueError("atlas table: face.%s" % k)
    for g in glyphs:
        if not isinstance(g, dict):
            raise ValueError("atlas table: bad glyph")
        for k in ("unicode", "x", "y", "w", "h"):
            if not isinstance(g.get(k), int) or isinstance(g.get(k), bool) or g[k] < 0:
                raise ValueError("atlas table: glyph %s" % k)
        for k in ("bearingX", "bearingY", "advance"):
            if not isinstance(g.get(k), (int, float)) or isinstance(g.get(k), bool):
                raise ValueError("atlas table: glyph %s" % k)
        if g["x"] + g["w"] > w or g["y"] + g["h"] > h:
            raise ValueError("atlas table: glyph %d lies outside the atlas" % g["unicode"])
    with open(png_path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        raise ValueError("atlas image is not a PNG")
    if struct.unpack(">II", head[16:24]) != (w, h):
        raise ValueError("atlas image size differs from the table")
    if os.path.getsize(png_path) > MAX_ATLAS_PNG:
        raise ValueError("atlas image too large")
    return doc


class FontStore:
    """One per service. `game_dir` may be empty; `companion_dir` is <ONI user folder>/companion."""

    def __init__(self, game_dir, data_dir, companion_dir, build_id=None):
        self.game_dir = game_dir or ""
        self.data_dir = data_dir
        self.companion_dir = companion_dir
        self.build_id = build_id          # callable -> Steam build id (int) or None; fingerprint is used otherwise
        self._lock = threading.Lock()
        self._memo = None                  # (fingerprint, entries)
        self.notes = []

    # ---- sources
    def _paths(self):
        g = self.game_dir
        data = os.path.join(g, "OxygenNotIncluded_Data") if g else ""
        return (os.path.join(data, "StreamingAssets", "fonts", NOTO_FILE) if data else "",
                os.path.join(data, ASSETS_FILE) if data else "")

    def _atlas_paths(self):
        """Newest build folder under companion/fonts holding a graystroke pair that validates."""
        root = os.path.join(self.companion_dir, "fonts") if self.companion_dir else ""
        try:
            builds = sorted((n for n in os.listdir(root) if n.isdigit()), key=int, reverse=True)
        except OSError:
            return None
        for b in builds:
            j = os.path.join(root, b, ATLAS_NAME + ".json")
            p = os.path.join(root, b, ATLAS_NAME + ".png")
            if os.path.isfile(j) and os.path.isfile(p):
                return b, j, p
        return None

    def _fingerprint(self):
        noto, assets = self._paths()
        atlas = self._atlas_paths()
        return [_stat(noto) if noto else None, _stat(assets) if assets else None,
                [atlas[0], _stat(atlas[1]), _stat(atlas[2])] if atlas else None]

    def _cache_key(self):
        _noto, assets = self._paths()
        bid = None
        if self.build_id:
            try:
                bid = self.build_id()
            except Exception:
                bid = None
        if bid:
            return "b%d" % bid
        st = _stat(assets) if assets else None
        return "f%d-%d" % tuple(st) if st else "none"

    # ---- extraction + cache
    def _extract(self):
        """Fill the cache folder for the current game files. Returns the entries (served files + facts)."""
        noto, assets = self._paths()
        key = self._cache_key()
        cdir = os.path.join(self.data_dir, CACHE_DIR, key)
        meta_path = os.path.join(cdir, "fonts.json")
        want = [_stat(noto) if noto else None, _stat(assets) if assets else None]
        entries = None
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("schema") == SCHEMA and meta.get("source") == want and self._cache_ok(cdir, meta):
                entries = meta["fonts"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if entries is None:
            entries = self._extract_fresh(cdir, noto, assets, want)
        out = []
        for e in entries:
            out.append(dict(e, path=os.path.join(cdir, e["name"])))
        return out

    @staticmethod
    def _cache_ok(cdir, meta):
        for e in meta.get("fonts", []):
            if not safe_name(e.get("name")):
                return False
            p = os.path.join(cdir, e["name"])
            try:
                if os.path.getsize(p) != e["size"]:
                    return False
            except OSError:
                return False
        return True

    def _extract_fresh(self, cdir, noto, assets, want):
        notes, fonts = [], []
        os.makedirs(os.path.dirname(cdir), exist_ok=True)
        tmp = tempfile.mkdtemp(dir=os.path.dirname(cdir), prefix=".tmp-")
        try:
            def put(file_name, data, info, roles, family=None, style=None):
                _atomic_write(os.path.join(tmp, file_name), data)
                fonts.append({"name": file_name, "family": family or info["family"],
                              "style": style or sfnt.style_key(info["style"]), "kind": "ttf", "size": len(data),
                              "roles": roles, "license": _license(info["family"]), "sha256": hashlib.sha256(data).hexdigest()})
            if noto and os.path.isfile(noto):
                try:
                    data = _read_limited(noto, MAX_FONT)
                    info = sfnt.check(data)
                    put(NOTO_FILE, data, info, ["body"])
                except (OSError, ValueError, sfnt.FontError) as e:
                    notes.append("%s: %s" % (NOTO_FILE, e))
            if assets and os.path.isfile(assets):
                found, more = extract_embedded(assets)
                notes += more
                for asset_name in sorted(found):
                    data, info = found[asset_name]
                    fam = info["family"]
                    put(_file_name(asset_name, info), data, info, [], family=fam)
            meta = {"schema": SCHEMA, "source": want, "fonts": fonts, "notes": notes}
            _atomic_write(os.path.join(tmp, "fonts.json"), json.dumps(meta, indent=1).encode())
            if os.path.isdir(cdir):
                shutil.rmtree(cdir, ignore_errors=True)
            os.replace(tmp, cdir)
            tmp = None
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        self.notes = notes
        return fonts

    # ---- public
    def ensure(self):
        """Extract (or reuse the cache) and return (entries, changed). `changed` is True when the set of served
        fonts differs from the last call. Cheap when nothing changed: two stat calls and one directory listing."""
        with self._lock:
            fp = self._fingerprint()
            if self._memo and self._memo[0] == fp:
                return self._memo[1], False
            failed = False
            try:
                entries = self._extract()
            except OSError as e:
                log.warning("font extraction failed: %s", e)
                entries = []
                failed = True
            entries += self._atlas_entries()
            old = [(e["name"], e["size"]) for e in (self._memo[1] if self._memo else [])]
            # a failed extraction (full disk, permissions) is not remembered: the next call tries again
            self._memo = None if failed else (fp, entries)
            return entries, old != [(e["name"], e["size"]) for e in entries]

    def _atlas_entries(self):
        found = self._atlas_paths()
        if not found:
            return []
        _b, j, p = found
        try:
            doc = validate_atlas(j, p)
        except (OSError, ValueError) as e:
            self.notes.append("graystroke: %s" % e)
            return []
        fam = doc["family"]
        return [
            {"name": ATLAS_NAME + ".png", "family": fam, "kind": "sdfAtlasImage", "size": os.path.getsize(p),
             "roles": ["header", "title"], "path": p, "style": "regular"},
            {"name": ATLAS_NAME + ".json", "family": fam, "kind": "sdfAtlasTable", "size": os.path.getsize(j),
             "roles": ["header", "title"], "path": j, "style": "regular"},
        ]

    def font_list(self):
        """The FontList reply (contracts/api.schema.json#/$defs/FontList)."""
        entries, _ = self.ensure()
        out = []
        for e in entries:
            row = {"name": e["name"], "family": e["family"], "kind": e["kind"],
                   "url": "/api/v1/fonts/" + e["name"], "size": e["size"]}
            if e.get("style"):
                row["style"] = e["style"]
            if e.get("roles"):
                row["roles"] = list(e["roles"])
            if e.get("license"):
                row["license"] = e["license"]
            out.append(row)
        reply = {"fonts": out}
        build = self._atlas_build()
        if build is not None:
            reply["build"] = build
        return reply

    def _atlas_build(self):
        found = self._atlas_paths()
        return int(found[0]) if found else None

    def file(self, name):
        """A FontFile for a listed font name, else None. Re-checks the cached file on the way out."""
        if not safe_name(name):
            return None
        entries, _ = self.ensure()
        for e in entries:
            if e["name"] != name:
                continue
            try:
                data = _read_limited(e["path"], MAX_ATLAS_PNG if e["kind"] != "ttf" else MAX_FONT)
            except (OSError, ValueError):
                return None
            ctype = ("image/png" if e["kind"] == "sdfAtlasImage" else "application/json" if e["kind"] == "sdfAtlasTable"
                     else "font/otf" if name.endswith(".otf") else "font/ttf")
            return FontFile(data, ctype, '"%s"' % hashlib.sha1(data).hexdigest()[:16])
        return None

    def roles(self):
        """theme.font.roles: body / header / title with the /fonts entry that provides them and the fallbacks."""
        entries, _ = self.ensure()
        by = {e["name"]: e for e in entries}

        def role(font_name, family, fallback):
            r = {"family": family}
            if font_name in by:
                r["font"] = font_name
                r["family"] = by[font_name]["family"]
            r["fallback"] = fallback
            return r

        noto = role(NOTO_FILE, "Noto Sans", ["Noto Sans"])
        if NOTO_FILE not in by:
            noto["family"] = "Noto Sans"
        if ATLAS_NAME + ".json" in by:
            head = role(ATLAS_NAME + ".json", "Graystroke", ["Economica", "Noto Sans"])
        elif any(n.startswith("Economica-Bold.") for n in by):
            head = role(next(n for n in sorted(by) if n.startswith("Economica-Bold.")), "Economica", ["Noto Sans"])
        else:
            head = role("", "Graystroke", ["Economica", "Noto Sans"])
        return {"body": noto, "header": head, "title": dict(head)}
