"""Art & font sync (v1.2): GET /sync, POST /sync, the `sync` event.

A sync draws the user's own game art, the theme and the Graystroke atlas at run time (nothing from the game is shipped).
The mod does the work and writes companion/sync/status.json (mod-sync-status.schema.json) about every 250 ms; this module
turns that file into the `Sync` reply (api.schema.json) and adds what only the core knows:
- `needed` / `neededReason` / `suggestedScope`: no finished sync for the current game build + DLC set (no_pack), the build
  changed (new_build), or the DLC set changed (new_dlc; a "missing" sync is enough). The current build comes from
  live.json (its first bytes) or, in the menu, from the art manifest the mod writes at start. The DLC set comes from that
  manifest when its build matches: live.json's dlcIds are the SAVE's DLC (a base-game save lists none), while a pack is
  drawn for the game's active DLC content, which is what the manifest records.
- `canStart` / `reason`: false when the game is not running with the mod and a colony loaded.
- `fonts`: none | partial | ready (the mod's Graystroke export, plus the core's own TTF extraction when a hook says so).
POST /sync writes ONE `sync_assets` command. Until the mod's status file shows the new run (or its ack fails) the reply
shows state running with total 0, so a front end switches to the progress view at once.
Event driven: file events call `touched`; two one-shot timers settle "the mod never answered" and "the game stopped
answering mid-sync". Stdlib only. The core never writes anything but the command file.
"""
import calendar
import json
import logging
import os
import re
import threading
import time

from . import cause as cause_mod


log = logging.getLogger("oni_companion.sync")

FRESH_SECONDS = 15                # live.json limits, the same as actions.py
FRESH_SECONDS_PAUSED = 180       # mod 0.3.1+ rewrites live.json at least every 60 s while paused
STALE_SECONDS = 20.0         # a running status older than this: the game stopped answering
PENDING_SECONDS = 12.0       # a sent command the mod never showed
SCOPES = ("full", "missing")
STATES = ("idle", "running", "done", "failed")
MAX_FILE = 64 * 1024
UNAVAILABLE_TEXT = "Start Oxygen Not Included to sync."      # kept for older callers; POST /sync now queues instead
_HEAD = 4096
_RX_STATE = re.compile(r'"state"\s*:\s*"([a-z]+)"')
_RX_WRITTEN = re.compile(r'"writtenAt"\s*:\s*"([^"]+)"')
_RX_BUILD = re.compile(r'"build"\s*:\s*(\d+)')
_RX_DLC = re.compile(r'"dlcIds"\s*:\s*\[([^\]]*)\]')
_RX_PAUSED = re.compile(r'"paused"\s*:\s*(true|false)')
_RX_SCHEMA = re.compile(r'"schema"\s*:\s*(\d+)')


def _parse_iso(s):
    try:
        return calendar.timegm(time.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, AttributeError, TypeError):
        return None


def ApiError(code, message):
    """The route error; imported late because the server package imports this module."""
    from .server.errors import ApiError as E
    return E(code, message)


def _sig(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _load_json(path, limit=MAX_FILE):
    try:
        with open(path, "rb") as f:
            raw = f.read(limit + 1)
        if len(raw) > limit:
            return None
        d = json.loads(raw.decode("utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _dlc_list(text):
    return sorted(x for x in re.findall(r'"([^"]*)"', text or ""))


class SyncService:
    def __init__(self, companion_dir, actions, publish, clock=time.time):
        self.companion_dir = companion_dir
        self.actions = actions
        self.publish = publish                  # publish("sync")
        self.clock = clock
        d = os.path.abspath(companion_dir) if companion_dir else ""
        self.status_path = os.path.join(d, "sync", "status.json") if d else None
        self.live_path = os.path.join(d, "live", "live.json") if d else None
        self.manifest_path = os.path.join(d, "art", "manifest.json") if d else None
        self.fonts_dir = os.path.join(d, "fonts") if d else None
        self.explainer = None                   # cause.Explainer: the real cause for a front end (message)
        self.shared = None                      # shared.SharedStore: the core's one copy of art, fonts and theme per build + DLC set
        self.ttf_hook = None                    # optional callable(build) -> True when the core extracted the game's TTF fonts
        self._lock = threading.Lock()
        self._pending = None                    # {"seq", "scope", "sentAt"} while a sent command has not shown up
        self._failed = None                     # (message, time) of a command the mod refused or never answered, shown until a newer status
        self._queued = None                     # {"scope"} of a sync asked for while the game could not take it; sent once it can
        self._timers = {}
        self._closed = False
        self._cache = {}                        # path -> (sig, value)
        self._good = None                       # (build, dlcIds) of the last finished sync seen; a later failed run does not erase it
        self._last_key = None                   # what the last published state looked like (see touched)

    # ---- reading the files
    def _cached(self, path, loader):
        sig = _sig(path)
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == sig:
                return hit[1]
        val = loader(path) if sig else None
        with self._lock:
            self._cache[path] = (sig, val)
        return val

    @staticmethod
    def _load_status(path):
        d = _load_json(path)
        if not d or d.get("schema") != 1 or d.get("state") not in STATES or d.get("scope") not in SCOPES:
            return None
        for k in ("done", "total"):
            if isinstance(d.get(k), bool) or not isinstance(d.get(k), int) or d[k] < 0:
                return None
        return d

    @staticmethod
    def _load_head(path):
        try:
            with open(path, "rb") as f:
                head = f.read(_HEAD).decode("utf-8", "replace")
        except OSError:
            return None
        out = {}
        m = _RX_SCHEMA.search(head)
        out["schema"] = int(m.group(1)) if m else None
        m = _RX_STATE.search(head)
        out["state"] = m.group(1) if m else None
        m = _RX_WRITTEN.search(head)
        out["writtenAt"] = _parse_iso(m.group(1)) if m else None
        m = _RX_BUILD.search(head)
        out["build"] = int(m.group(1)) if m else None
        m = _RX_DLC.search(head)
        out["dlcIds"] = _dlc_list(m.group(1)) if m else None
        m = _RX_PAUSED.search(head)
        out["paused"] = bool(m and m.group(1) == "true")
        return out

    @staticmethod
    def _load_manifest(path):
        # the manifest can be large; its header is small and comes first
        head = SyncService._load_head(path)
        return head

    def _file_status(self):
        return self._cached(self.status_path, self._load_status) if self.status_path else None

    def _live(self):
        return self._cached(self.live_path, self._load_head) if self.live_path else None

    def _manifest(self):
        return self._cached(self.manifest_path, self._load_manifest) if self.manifest_path else None

    def _current(self):
        """(build, dlcIds) of the game the mod is running in, or (None, None). dlcIds = the active DLC content."""
        live, man = self._live(), self._manifest()
        build = None
        for src in (live, man):
            if src and src.get("build") is not None and src.get("dlcIds") is not None:
                build = src["build"]
                break
        if build is None:
            return None, None
        if man and man.get("build") == build and man.get("dlcIds") is not None:
            return build, man["dlcIds"]
        return build, live["dlcIds"] if live and live.get("build") == build else man["dlcIds"]

    def retarget(self, companion_dir):
        """The active ONI folder changed (plan 4.3): read and write the new one. A queued sync stays queued."""
        with self._lock:
            timers, self._timers = list(self._timers.values()), {}
            self._pending = self._failed = None
            self._good = None
            self._cache = {}
            self._last_key = None
            self.companion_dir = companion_dir
            d = os.path.abspath(companion_dir) if companion_dir else ""
            self.status_path = os.path.join(d, "sync", "status.json") if d else None
            self.live_path = os.path.join(d, "live", "live.json") if d else None
            self.manifest_path = os.path.join(d, "art", "manifest.json") if d else None
            self.fonts_dir = os.path.join(d, "fonts") if d else None
        for t in timers:
            t.cancel()

    def _kind(self):
        """What live.json says now: running | menu | stopped | stale | none (see cause.live_kind)."""
        if not self.companion_dir or not os.path.isdir(self.companion_dir):
            return "none"
        live = self._live()
        if not live or live.get("schema") not in (1, 2):
            return "none"
        return cause_mod.live_kind(live.get("state"), live.get("writtenAt"), live.get("paused"), self.clock())

    def _availability(self, kind=None):
        """None when a sync can start, else "menu" (a fresh live file says menu) or "no_mod" (anything else)."""
        kind = kind or self._kind()
        if kind == "running":
            return None
        return "menu" if kind == "menu" else "no_mod"

    def fonts_state(self, build=None):
        if build is None:
            build, _ = self._current()
        mod = False
        roots = [self.fonts_dir] + ([os.path.join(self.shared.root, "fonts")] if self.shared else [])
        for root in roots:
            if build is None or not root:
                continue
            d = os.path.join(root, str(build))
            if os.path.isfile(os.path.join(d, "graystroke.json")) and os.path.isfile(os.path.join(d, "graystroke.png")):
                mod = True
                break
        ttf = False
        if self.ttf_hook and build is not None:
            try:
                ttf = bool(self.ttf_hook(build))
            except Exception:
                ttf = False
        if self.ttf_hook is None:
            ttf = mod                            # no extraction lane wired in: the mod's export alone decides
        if mod and ttf:
            return "ready"
        return "partial" if (mod or ttf) else "none"

    # ---- the need
    def _needed(self, st, build, dlc):
        """(needed, reason|None, suggestedScope)."""
        if build is None:
            return True, "no_pack", "full"
        if self.shared:
            # one pack per game build + DLC set, kept by the core: a finished sync from any ONI folder counts here
            if self.shared.has_pack(build, dlc):
                return False, None, "missing"
            alt = self.shared.latest_pack(build)
            if alt and not (st and st.get("state") == "done"):
                st = {"state": "done", "build": alt["build"], "dlcIds": alt["dlcIds"]}
        if st and st.get("state") == "done":
            with self._lock:
                self._good = (st.get("build"), sorted(st.get("dlcIds") or []))
        elif st and self._good is not None:
            # a running or failed run after a good one: the earlier pack is still on disk, judge by it
            st = {"state": "done", "build": self._good[0], "dlcIds": self._good[1]}
        if not st or st.get("state") != "done":
            # no finished run seen yet: show the need as it stands before the run
            return True, "no_pack", "full"
        if st.get("build") != build:
            return True, "new_build", "full"
        if sorted(st.get("dlcIds") or []) != sorted(dlc or []):
            return True, "new_dlc", "missing"
        return False, None, "missing"

    # ---- the reply
    def status(self):
        now = self.clock()
        st = self._file_status()
        build, dlc = self._current()
        with self._lock:
            pend = self._pending
            failed = self._failed
        if pend and now - pend["sentAt"] > PENDING_SECONDS:
            pend = None
        fresh_run = st is not None and (pend is None or self._started_since(st, pend["sentAt"]))
        needed, reason, scope = self._needed(st, build, dlc)
        kind = self._kind()
        avail = self._availability(kind)
        out = {"state": "idle", "needed": needed, "canStart": avail is None}
        with self._lock:
            if self._queued:
                out["queued"] = True
        if reason:
            out["neededReason"] = reason
        out["suggestedScope"] = scope
        if avail:
            out["reason"] = avail
            ex = self.explainer.explain(kind, dlc) if self.explainer else None
            if ex:
                out.update(ex)
        out["fonts"] = self.fonts_state(build)

        failed_msg, failed_at = failed if failed else (None, 0)
        updated = _parse_iso(st.get("updatedAt", "")) if fresh_run and st.get("updatedAt") else None
        if fresh_run and st["state"] == "running" and not (updated is not None and now - updated > STALE_SECONDS):
            out["state"] = "running"
            out["canStart"] = True
            out.pop("reason", None)
            out.pop("cause", None)
            out.pop("message", None)
            self._copy_progress(out, st)
        elif pend and not fresh_run:
            out["state"] = "running"
            out["scope"] = pend["scope"]
            out["done"], out["total"], out["current"], out["errors"] = 0, 0, None, 0
        elif failed_msg and (updated is None or updated <= failed_at):
            out["state"] = "failed"
            out["lastError"] = failed_msg
        elif fresh_run and st["state"] == "running":
            out["state"] = "failed"
            self._copy_progress(out, st)
            out["lastError"] = "The game stopped answering during the sync."
        elif fresh_run and st["state"] in ("done", "failed"):
            out["state"] = st["state"]
            self._copy_progress(out, st)
        return out

    @staticmethod
    def _started_since(st, since):
        t = _parse_iso(st.get("startedAt", "")) if st.get("startedAt") else None
        return t is not None and t >= since - 2.0

    @staticmethod
    def _copy_progress(out, st):
        out["scope"] = st["scope"]
        out["done"], out["total"] = st["done"], st["total"]
        cur = st.get("current")
        out["current"] = cur if isinstance(cur, str) else None
        err = st.get("errors")
        out["errors"] = err if isinstance(err, int) and not isinstance(err, bool) and err >= 0 else 0
        le = st.get("lastError")
        if isinstance(le, str) and le:
            out["lastError"] = le[:200]
        for k in ("startedAt", "updatedAt"):
            if isinstance(st.get(k), str):
                out[k] = st[k]
        em = st.get("elapsedMs")
        if isinstance(em, int) and not isinstance(em, bool) and em >= 0:
            out["elapsedMs"] = em

    # ---- POST /sync
    def start(self, body):
        """POST /sync. When the game cannot take it now (menu, not running), the sync is queued and sent by `touched`
        as soon as live.json shows a running colony: the front end never waits for the game to allow the button."""
        if body is None:
            body = {}
        if not isinstance(body, dict) or set(body) - {"scope", "cancel"}:
            raise ApiError("bad_request", "Body must be {}, {\"scope\":\"full\"|\"missing\"} or {\"cancel\":true}.")
        if body.get("cancel") is True:
            with self._lock:
                self._queued = None
            self.publish("sync")
            return self.status()
        scope = body.get("scope")
        if scope is not None and scope not in SCOPES:
            raise ApiError("bad_request", "scope must be full or missing.")
        cur = self.status()
        if cur["state"] == "running":
            return cur                          # one sync at a time: the running one is the answer
        if not cur["canStart"]:
            with self._lock:
                self._queued = {"scope": scope}
                self._failed = None
            self.publish("sync")
            return self.status()
        return self._send(scope, cur)

    def _send(self, scope, cur):
        scope = scope or cur.get("suggestedScope") or "full"
        if scope not in SCOPES:
            scope = "full"
        seq = self.actions.send_command("sync_assets", {"scope": scope})    # raises ApiError unavailable
        with self._lock:
            self._pending = {"seq": seq, "scope": scope, "sentAt": self.clock()}
            self._failed = None
        self._arm("pending", PENDING_SECONDS + 0.5)
        return self.status()

    def handle_ack(self, seq, path):
        """ActionService hook for acks it does not know. True when the seq was our sync_assets command."""
        with self._lock:
            pend = self._pending
        if not pend or pend["seq"] != seq:
            return False
        ack = self.actions.read_ack(path, seq)
        if ack is None:
            return True
        state, msg = ack
        with self._lock:
            if state == "failed":
                self._pending = None
                self._failed = (msg or "The game did not start the sync.", self.clock())
        self.actions.drop_command(seq)
        if state == "failed":
            self.publish("sync")
        return True

    # ---- events
    def touched(self, path):
        """Service watcher hook. True when a `sync` event should go out for this file."""
        if not path:
            return False
        if path == self.status_path:
            st = self._file_status()
            with self._lock:
                if st and self._pending and self._started_since(st, self._pending["sentAt"]):
                    self._pending = None
            if st and st["state"] == "running":
                self._arm("stale", STALE_SECONDS + 0.5)
            return True
        if path in (self.live_path, self.manifest_path) or (self.fonts_dir and path.startswith(self.fonts_dir + os.sep)):
            if path == self.live_path and self._flush_queue():
                return True
            key = self._key()
            with self._lock:
                changed = key != self._last_key
                self._last_key = key
            return changed
        return False

    def _flush_queue(self):
        """Sends a queued sync once the game can take it. True when it was sent."""
        with self._lock:
            q = self._queued
        if not q:
            return False
        cur = self.status()
        if not cur["canStart"] or cur["state"] == "running":
            return False
        with self._lock:
            if self._queued is not q:
                return False
            self._queued = None
        try:
            self._send(q["scope"], cur)
        except Exception as e:                  # the command could not be written: show it like a refused one
            log.warning("queued sync not sent: %s", e)
            with self._lock:
                self._failed = ("The sync could not be sent to the game.", self.clock())
        return True

    def _key(self):
        s = self.status()
        return (s["canStart"], s.get("reason"), s["needed"], s.get("neededReason"), s["fonts"], s["state"] if s["state"] != "running" else "running")

    def _arm(self, name, delay):
        with self._lock:
            if self._closed:
                return
            old = self._timers.pop(name, None)
            t = threading.Timer(delay, self._fire, (name,))
            t.daemon = True
            self._timers[name] = t
        if old:
            old.cancel()
        t.start()

    def _fire(self, name):
        with self._lock:
            if self._closed:
                return
            self._timers.pop(name, None)
            if name == "pending" and self._pending and self.clock() - self._pending["sentAt"] > PENDING_SECONDS:
                self._pending = None
                self._failed = ("The game did not answer. Is it running with the mod?", self.clock())
        self.publish("sync")

    def close(self):
        with self._lock:
            self._closed = True
            timers, self._timers = list(self._timers.values()), {}
        for t in timers:
            t.cancel()
