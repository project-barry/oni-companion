"""The core's own copy of the game's art, fonts and theme (plan 4.3 item 4). Stdlib only.

One art pack per game build + DLC set, kept in the core's data folder, not per ONI user folder. The Linux and the
Windows (Proton) version of the game each have their own user folder and their own mod output, but they draw the same
pictures. Finished art from any folder is copied in; the screens serve from here, so switching versions needs no new
sync, and the sync "needed" logic asks this store whether a finished pack exists.

Layout under <data>/shared:
  art/<build>-<dlc key>/manifest.json   merged manifest, same format as the mod's (contracts/mod-art-manifest)
  art/<build>-<dlc key>/<build>/<kind>/<name>.png
  art/<build>-<dlc key>/pack.json        {build, dlcIds, finishedAt}: a finished sync for that build + DLC set
  fonts/<build>/graystroke.{json,png}    the layout of companion/fonts
  theme/<build>/theme.json + PNGs        the layout of companion/theme
Reads only the ONI folders named to it; writes only inside its own folder. Nothing from the game is shipped: the files
here are what the user's own game drew on the user's own device.
"""
import json
import logging
import os
import re
import shutil
import threading

from .art.store import ArtStore, MAX_PNG

log = logging.getLogger("oni_companion.shared")

_DLC_ID = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_BUILD_DIR = re.compile(r"^[0-9]{1,10}$")
_FLAT_FILE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
MAX_FILE = 8 * 1024 * 1024


def dlc_key(dlc_ids):
    ids = sorted(set(dlc_ids or []))
    for i in ids:
        if not isinstance(i, str) or not _DLC_ID.match(i):
            raise ValueError("bad dlc id")
    return "+".join(ids) if ids else "base"


def pack_key(build, dlc_ids):
    if isinstance(build, bool) or not isinstance(build, int) or build < 0:
        raise ValueError("bad build")
    return "%d-%s" % (build, dlc_key(dlc_ids))


def _read_json(path):
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read(4 * 1024 * 1024).decode("utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _inside(root, full):
    try:
        r = os.path.realpath(root)
        return os.path.commonpath([r, os.path.realpath(full)]) == r
    except ValueError:
        return False


def _copy_if_different(src, dst):
    """Copy src to dst (atomically) unless dst already has the same size and modification time. True if copied."""
    try:
        s = os.stat(src)
    except OSError:
        return False
    try:
        d = os.stat(dst)
        if d.st_size == s.st_size and d.st_mtime_ns == s.st_mtime_ns:
            return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)
    return True


class SharedStore:
    def __init__(self, root):
        self.root = root
        self._lock = threading.Lock()       # one import at a time

    # ---- paths
    def art_dir(self, build, dlc_ids):
        try:
            return os.path.join(self.root, "art", pack_key(build, dlc_ids))
        except ValueError:
            return None

    def fonts_root(self):
        return os.path.join(self.root, "fonts")

    def theme_root(self):
        return os.path.join(self.root, "theme")

    def has_theme(self):
        try:
            return any(_BUILD_DIR.match(n) and os.path.isfile(os.path.join(self.theme_root(), n, "theme.json"))
                       for n in os.listdir(self.theme_root()))
        except OSError:
            return False

    # ---- finished packs
    def packs(self):
        out = []
        base = os.path.join(self.root, "art")
        try:
            names = os.listdir(base)
        except OSError:
            return out
        for n in names:
            d = _read_json(os.path.join(base, n, "pack.json"))
            if d and isinstance(d.get("build"), int) and isinstance(d.get("dlcIds"), list):
                out.append({"build": d["build"], "dlcIds": sorted(x for x in d["dlcIds"] if isinstance(x, str)),
                            "finishedAt": d.get("finishedAt")})
        return out

    def has_pack(self, build, dlc_ids):
        try:
            return os.path.isfile(os.path.join(self.root, "art", pack_key(build, dlc_ids), "pack.json"))
        except ValueError:
            return False

    def latest_pack(self, build):
        """A finished pack for this build (another DLC set) if there is one, else the newest build's."""
        packs = self.packs()
        same = [p for p in packs if p["build"] == build]
        if same:
            return same[0]
        return max(packs, key=lambda p: p["build"]) if packs else None

    # ---- import from an ONI user folder
    def import_folder(self, user_dir):
        """Copies finished art, fonts, theme and the "sync finished" fact from <user_dir>/companion. Never raises on
        bad files. Returns {"art": [keys changed], "fonts": bool, "theme": bool, "pack": bool}."""
        res = {"art": [], "fonts": False, "theme": False, "pack": False}
        if not user_dir:
            return res
        cdir = os.path.join(user_dir, "companion")
        with self._lock:
            for name, fn in (("art", self._import_art), ("fonts", self._import_fonts),
                             ("theme", self._import_theme), ("pack", self._import_pack)):
                try:
                    res[name] = fn(cdir)
                except Exception:
                    log.exception("shared %s import from %s failed", name, user_dir)
        return res

    def _import_art(self, cdir):
        art_dir = os.path.join(cdir, "art")
        m = _read_json(os.path.join(art_dir, "manifest.json"))
        if not m or m.get("schema") != 1 or not isinstance(m.get("files"), list):
            return []
        try:
            key = pack_key(m.get("build"), m.get("dlcIds"))
        except ValueError:
            return []
        kdir = os.path.join(self.root, "art", key)
        mpath = os.path.join(kdir, "manifest.json")
        have = _read_json(mpath) or {}
        rr_in = m.get("renderRev") if isinstance(m.get("renderRev"), int) and not isinstance(m.get("renderRev"), bool) else 1
        rr_have = have.get("renderRev") if isinstance(have.get("renderRev"), int) else 1
        if have and rr_in < rr_have:
            return []                                   # drawn by an older renderer than what we hold
        entries = {}
        if have and rr_in == rr_have:
            for f in have.get("files") or []:
                if isinstance(f, dict) and isinstance(f.get("path"), str):
                    entries[f["path"]] = f
        elif have:                                      # a newer renderer: its images replace all of ours
            shutil.rmtree(os.path.join(kdir, str(m["build"])), ignore_errors=True)
        copied = False
        for f in m["files"]:
            e = ArtStore._valid(f)
            if not e or not e["path"].startswith("%d/" % m["build"]):
                continue
            src = os.path.join(art_dir, *e["path"].split("/"))
            dst = os.path.join(kdir, *e["path"].split("/"))
            if not _inside(art_dir, src) or not os.path.isfile(src):
                continue
            try:
                if os.stat(src).st_size != e["size"] or e["size"] > MAX_PNG:
                    continue
                copied = _copy_if_different(src, dst) or copied
            except OSError:
                continue
            entries[e["path"]] = f
        doc = {k: m[k] for k in ("schema", "modVersion", "build", "dlcIds", "writtenAt", "onDemand", "renderRev")
               if k in m}
        doc["files"] = [entries[p] for p in sorted(entries)]
        if doc != have:
            _write_json(mpath, doc)
            return [key]
        return [key] if copied else []

    def _import_tree(self, src_dir, dst_dir, last="theme.json"):
        """Flat copy of the regular files of one build folder; `last` goes last so a reader never sees a half copy."""
        try:
            names = sorted(os.listdir(src_dir), key=lambda n: n == last)
        except OSError:
            return False
        changed = False
        for n in names:
            src = os.path.join(src_dir, n)
            if not _FLAT_FILE.match(n) or n.endswith(".tmp") or not os.path.isfile(src) or os.path.islink(src):
                continue
            try:
                if os.stat(src).st_size > MAX_FILE:
                    continue
                changed = _copy_if_different(src, os.path.join(dst_dir, n)) or changed
            except OSError:
                continue
        return changed

    def _import_fonts(self, cdir):
        root = os.path.join(cdir, "fonts")
        try:
            builds = [n for n in os.listdir(root) if _BUILD_DIR.match(n)]
        except OSError:
            return False
        changed = False
        for b in builds:
            d = os.path.join(root, b)
            if os.path.isfile(os.path.join(d, "graystroke.json")) and os.path.isfile(os.path.join(d, "graystroke.png")):
                changed = self._import_tree(d, os.path.join(self.fonts_root(), b), last="graystroke.json") or changed
        return changed

    def _import_theme(self, cdir):
        root = os.path.join(cdir, "theme")
        try:
            builds = [n for n in os.listdir(root) if _BUILD_DIR.match(n)]
        except OSError:
            return False
        changed = False
        for b in builds:
            if os.path.isfile(os.path.join(root, b, "theme.json")):
                changed = self._import_tree(os.path.join(root, b), os.path.join(self.theme_root(), b)) or changed
        return changed

    def _import_pack(self, cdir):
        st = _read_json(os.path.join(cdir, "sync", "status.json"))
        if not st or st.get("state") != "done" or not isinstance(st.get("dlcIds"), list):
            return False
        try:
            key = pack_key(st.get("build"), st["dlcIds"])
        except ValueError:
            return False
        p = os.path.join(self.root, "art", key, "pack.json")
        if os.path.isfile(p):
            return False
        _write_json(p, {"build": st["build"], "dlcIds": sorted(st["dlcIds"]),
                        "finishedAt": st.get("updatedAt") if isinstance(st.get("updatedAt"), str) else None})
        return True
