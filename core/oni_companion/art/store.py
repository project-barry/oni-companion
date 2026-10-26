"""Reads companion/art/manifest.json and finds the PNG for (kind, id).

Rules (contracts/api.md, "Art"):
- Only files listed in the manifest are served. The request never makes a path: the id is only compared
  with manifest ids, and the manifest path must match <build>/<kind>/<name>.png and stay inside art/.
- A missing manifest, entry or file means "no art" (None here, 404 at the route).
- dupe/<id>: the entry whose appearanceHash equals the duplicant's current hash in live.json, else the newest.
Event driven: the manifest and live.json are re-read only when their size/mtime/inode change.
"""
import json
import os
import re
import threading
import zlib

ART_KINDS = ("building", "element", "critter", "plant", "seed", "egg", "food", "medicine", "item", "dupe")
BASE = "/api/v1/art"
MAX_PNG = 8 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PATH_RE = re.compile(r"^[0-9]+/[a-z]+/[^/\\]+\.png$")
_HASH_RE = re.compile(r"^[0-9a-f]{8}$")

# Which art kinds may stand in for a Ref kind, best first.
REF_ART = {
    "element": ("element", "item"), "building": ("building",), "critter": ("critter",),
    "plant": ("plant",), "food": ("food", "item"), "medicine": ("medicine", "item"), "dupe": ("dupe",),
}


class Png:
    """A PNG ready to send."""
    content_type = "image/png"

    def __init__(self, data, etag):
        self.data, self.etag = data, etag


def art_url(kind, ident):
    # ids are the game's own; keep the URL one path segment per part
    from urllib.parse import quote
    return "%s/%s/%s" % (BASE, kind, quote(ident, safe=""))


def _sig(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _load_json(path):
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read().decode("utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


class ArtStore:
    def __init__(self, companion_dir, live_path=None):
        self.art_dir = os.path.join(companion_dir, "art") if companion_dir else None
        self.manifest_path = os.path.join(self.art_dir, "manifest.json") if self.art_dir else None
        self.live_path = live_path
        self.ui_lookup = None       # optional hook for the theme lane: callable(id) -> absolute PNG path or None
        self._lock = threading.Lock()
        self._msig = None
        self._index = {}            # (kind, id) -> [entry, ...] in manifest order
        self._lower = {}            # (kind, id.lower()) -> [ids]
        self._lsig = None
        self._hashes = {}           # dupe id -> appearanceHash
        self._on_demand = False     # the manifest says the mod draws catalog art on request
        self.on_miss = None         # optional callable(kind, id): an art GET found no image (queues an art_request)

    def retarget(self, art_dir, live_path=None):
        """Serve from another art folder (the core's shared copy, or the active ONI folder's own)."""
        with self._lock:
            self.art_dir = art_dir or None
            self.manifest_path = os.path.join(art_dir, "manifest.json") if art_dir else None
            if live_path is not None:
                self.live_path = live_path
            self._msig = self._lsig = None
            self._index, self._lower, self._hashes = {}, {}, {}
            self._on_demand = False

    # ---- manifest
    def _refresh(self):
        if not self.manifest_path:
            return
        sig = _sig(self.manifest_path)
        with self._lock:
            if sig == self._msig:
                return
        index, lower = {}, {}
        m = _load_json(self.manifest_path) if sig else None
        on_demand = bool(m and m.get("onDemand") is True)
        if m and m.get("schema") == 1 and isinstance(m.get("files"), list):
            for f in m["files"]:
                e = self._valid(f)
                if e:
                    index.setdefault((e["kind"], e["id"]), []).append(e)
            for (k, i) in index:
                lower.setdefault((k, i.lower()), []).append(i)
        with self._lock:
            self._msig, self._index, self._lower = sig, index, lower
            self._on_demand = on_demand

    @staticmethod
    def _valid(f):
        if not isinstance(f, dict):
            return None
        kind, ident, path, size = f.get("kind"), f.get("id"), f.get("path"), f.get("size")
        if kind not in ART_KINDS or not isinstance(ident, str) or not ident:
            return None
        if not isinstance(path, str) or not _PATH_RE.match(path) or ".." in path.split("/"):
            return None
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_PNG:
            return None
        h = f.get("appearanceHash")
        if h is not None and not (isinstance(h, str) and _HASH_RE.match(h)):
            return None
        sha = f.get("sha256")
        return {"kind": kind, "id": ident, "path": path, "size": size, "hash": h,
                "sha": sha if isinstance(sha, str) else ""}

    def _file(self, e):
        """Absolute path of a manifest entry if the file exists with the listed size and stays inside art/."""
        full = os.path.join(self.art_dir, *e["path"].split("/"))
        try:
            st = os.stat(full)
            root = os.path.realpath(self.art_dir)
            if os.path.commonpath([root, os.path.realpath(full)]) != root:
                return None
        except (OSError, ValueError):
            return None
        if not os.path.isfile(full) or st.st_size != e["size"]:
            return None
        return full

    # ---- live.json (only the duplicant hashes)
    def _live_hashes(self):
        if not self.live_path:
            return {}
        sig = _sig(self.live_path)
        with self._lock:
            if sig == self._lsig:
                return self._hashes
        hashes = {}
        d = _load_json(self.live_path) if sig else None
        if d:
            for w in d.get("worlds") or []:
                for u in (w.get("dupes") or []) if isinstance(w, dict) else []:
                    if isinstance(u, dict) and isinstance(u.get("id"), str) and isinstance(u.get("appearanceHash"), str):
                        hashes[u["id"]] = u["appearanceHash"]
        with self._lock:
            self._lsig, self._hashes = sig, hashes
        return hashes

    # ---- lookup
    def _entry(self, kind, ident):
        """-> (entry, absolute path) or None."""
        if kind not in ART_KINDS or not self.art_dir or not isinstance(ident, str) or not ident:
            return None
        self._refresh()
        with self._lock:
            ids = [ident] if (kind, ident) in self._index else self._lower.get((kind, ident.lower()), [])
            cands = [e for i in ids[:1] for e in self._index.get((kind, i), [])]
        if not cands:
            return None
        if kind == "dupe":
            want = self._live_hashes().get(cands[0]["id"])
            exact = [e for e in cands if want and e["hash"] == want]
            cands = exact or cands
        found = []
        for n, e in enumerate(cands):
            full = self._file(e)
            if full:
                try:
                    found.append((os.stat(full).st_mtime_ns, n, e, full))
                except OSError:
                    pass
        if not found:
            return None
        _m, _n, e, full = max(found, key=lambda t: (t[0], t[1]))
        return e, full

    def has(self, kind, ident):
        return self._entry(kind, ident) is not None

    def on_demand(self):
        """True when the mod draws catalog art only on request (manifest `onDemand`)."""
        if not self.art_dir:
            return False
        self._refresh()
        with self._lock:
            return self._on_demand

    def url_for(self, kind, ident, pending=False):
        """URL path for an art kind + id, or None when there is no art. pending=True: when the image is not drawn yet but the
        mod draws on demand, still the URL (the GET answers 404 and asks the mod; the app shows its glyph until then)."""
        hit = self._entry(kind, ident)
        if hit:
            return art_url(kind, hit[0]["id"])
        if pending and kind != "dupe" and kind in ART_KINDS and isinstance(ident, str) and ident and self.on_demand():
            return art_url(kind, ident)
        return None

    def url_for_ref(self, ref_kind, ident):
        """URL path for a Ref kind (element, building, ...) or None."""
        kinds = REF_ART.get(ref_kind, ())
        for k in kinds:
            u = self.url_for(k, ident)
            if u:
                return u
        for k in kinds:                  # none drawn yet: the first kind the mod can draw
            u = self.url_for(k, ident, pending=True)
            if u:
                return u
        return None

    def read(self, kind, ident):
        """Png for GET /art/<kind>/<id>, or None (the route answers 404)."""
        if kind == "ui":
            hook = self.ui_lookup
            full = hook(ident) if hook else None
            return self._read_file(full, "") if full else None
        hit = self._entry(kind, ident)
        if hit:
            return self._read_file(hit[1], hit[0]["sha"])
        hook = self.on_miss
        if hook and kind != "dupe":
            try:
                hook(kind, ident)
            except Exception:           # a request problem never changes the answer
                pass
        return None

    @staticmethod
    def _read_file(full, sha):
        try:
            with open(full, "rb") as f:
                data = f.read(MAX_PNG + 1)
        except OSError:
            return None
        if len(data) > MAX_PNG or not data.startswith(PNG_MAGIC):
            return None
        return Png(data, '"%s"' % (sha[:32] if sha else "c%08x" % zlib.crc32(data)))
