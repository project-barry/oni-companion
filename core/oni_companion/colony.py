"""One Colony model. Source order: mod live file > save > save header > none.

Every reply says which source it used (`source`) and when (`asOf`).
The result has the shape of api.schema.json ColonyReply.raw.
Thread safe; reads files only when they changed (mtime/size/inode key).
"""
import json
import os
import re
import struct
import threading
import time
from datetime import datetime, timezone

# A live file that says "running" is trusted this long after writtenAt. The mod
# writes only on change, so a paused game stays quiet: it gets a longer limit.
FRESH_SECONDS = 15
FRESH_SECONDS_PAUSED = 180       # mod 0.3.1+ rewrites live.json at least every 60 s while paused

_CYCLE_RE = re.compile(r"Cycle\s+(\d+)", re.I)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, AttributeError):
        return None


def read_save_header(path):
    """Header JSON of a .sav: <IIII> (build, header size, header version, compressed) + JSON.
    Returns a dict or None. (C2's save/header.py will replace this.)"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            if len(head) < 16:
                return None
            _build, size, _ver, _comp = struct.unpack("<IIII", head)
            if not 0 < size < 1 << 20:
                return None
            data = json.loads(f.read(size).decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeDecodeError, struct.error):
        return None


def _first(d, *keys):
    for k in keys:
        if isinstance(d.get(k), (int, float, str)) and not isinstance(d.get(k), bool):
            return d[k]
    return None


class Colony:
    """live_path: companion/live/live.json. save_dirs: folders searched recursively for *.sav.
    save_parser: optional callable(path) -> dict of ColonyReply.raw fields (C2 hooks in here);
    if it returns None or raises, the header is used."""

    def __init__(self, live_path, save_dirs=(), save_parser=None, clock=time.time):
        self.live_path = live_path
        self.save_dirs = [d for d in save_dirs if d]
        self.save_parser = save_parser
        self.clock = clock
        self._lock = threading.Lock()
        self._cache = {}     # key -> (sig, value)

    def retarget(self, live_path, save_dirs=None):
        """The active ONI folder changed (plan 4.3): read the new live file (and saves)."""
        with self._lock:
            self.live_path = live_path
            if save_dirs is not None:
                self.save_dirs = [d for d in save_dirs if d]
            self._cache = {}

    # ---- file helpers ----
    @staticmethod
    def _sig(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def _cached(self, key, path, loader):
        sig = self._sig(path)
        if sig is None:
            return None
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == (path, sig):
                return hit[1]
        val = loader(path)
        with self._lock:
            self._cache[key] = ((path, sig), val)
        return val

    def read_live(self):
        def load(p):
            try:
                with open(p, "rb") as f:
                    d = json.loads(f.read().decode("utf-8"))
                return d if isinstance(d, dict) and d.get("schema") in (1, 2) else None
            except (OSError, ValueError, UnicodeDecodeError):
                return None
        return self._cached("live", self.live_path, load)

    def live_fresh(self, live=None):
        live = live if live is not None else self.read_live()
        if not live or live.get("state") != "running":
            return False
        written = parse_iso(live.get("writtenAt", ""))
        if written is None:
            return False
        age = self.clock() - written
        return age <= (FRESH_SECONDS_PAUSED if live.get("paused") else FRESH_SECONDS)

    def newest_save(self):
        best = None
        for root in self.save_dirs:
            for dirpath, _dirs, files in os.walk(root):
                for n in files:
                    if n.endswith(".sav"):
                        p = os.path.join(dirpath, n)
                        try:
                            m = os.stat(p).st_mtime
                        except OSError:
                            continue
                        if best is None or m > best[0]:
                            best = (m, p)
        if best is None:
            return None
        m, p = best
        hdr = self._cached("hdr:" + p, p, read_save_header) or {}
        cyc = _first(hdr, "numberOfCycles", "cycles", "cycle")
        name = os.path.splitext(os.path.basename(p))[0]
        if isinstance(cyc, int) and not isinstance(cyc, bool) and "numberOfCycles" in hdr:
            cyc += 1                # header numberOfCycles is zero-based; the game shows +1
        if not isinstance(cyc, int):
            mt = _CYCLE_RE.search(name)
            cyc = int(mt.group(1)) if mt else None
        info = {"name": name, "modifiedAt": iso(m), "path": p, "mtime": m}
        if cyc is not None:
            info["cycle"] = cyc
        return info

    # ---- the model ----
    def facts(self, world=None):
        """ColonyReply.raw for the best available source."""
        live = self.read_live()
        if live and live.get("state") == "running" and self.live_fresh(live):
            out = {k: live[k] for k in ("colonyName", "cycle", "timeOfDay", "paused", "speed",
                                         "activeWorldId", "worlds") if k in live}
            out.update(source="mod-live", state="running", asOf=live["writtenAt"])
            return self._pick_world(out, world)
        sv = self.newest_save()
        if sv:
            parsed = None
            if self.save_parser:
                try:
                    parsed = self._cached("parse:" + sv["path"], sv["path"], self.save_parser)
                except Exception:
                    parsed = None
            if parsed:
                out = dict(parsed)
                out.update(source="save", state="saved", asOf=sv["modifiedAt"])
                out.setdefault("colonyName", self._name_from_path(sv))
                return self._pick_world(out, world)
            hdr = self._cached("hdr:" + sv["path"], sv["path"], read_save_header)
            if hdr is not None:
                out = {"source": "header", "state": "saved", "asOf": sv["modifiedAt"],
                       "colonyName": self._name_from_path(sv)}
                if "cycle" in sv:
                    out["cycle"] = sv["cycle"]
                return out
        return {"source": "none", "state": "saved"}

    @staticmethod
    def _name_from_path(sv):
        # cloud_save_files/<steamid>/<colony>/<file>.sav : the folder is the colony name
        folder = os.path.basename(os.path.dirname(sv["path"]))
        if folder and folder != "auto_save" and not folder.isdigit():
            return folder
        return _CYCLE_RE.split(sv["name"])[0].strip() or sv["name"]

    @staticmethod
    def _pick_world(out, world):
        if world is None or "worlds" not in out:
            return out
        picked = [w for w in out["worlds"] if str(w.get("id")) == str(world)]
        if not picked:
            raise KeyError(world)
        out = dict(out)
        out["worlds"] = picked
        return out

    def status_fields(self):
        """Pieces of api Status that depend on colony files: colony, newestSave, mod.liveFresh."""
        f = self.facts()
        col = {"source": f["source"]}
        for k_out, k_in in (("asOf", "asOf"), ("name", "colonyName"), ("cycle", "cycle")):
            if k_in in f:
                col[k_out] = f[k_in]
        sv = self.newest_save()
        newest = None
        if sv:
            newest = {"name": sv["name"], "modifiedAt": sv["modifiedAt"]}
            if "cycle" in sv:
                newest["cycle"] = sv["cycle"]
        live = self.read_live()
        return {"colony": col, "newestSave": newest, "liveFresh": self.live_fresh(live),
                "livePresent": live is not None}
