"""Which ONI user folder is the active one (plan 4.3 item 1). Stdlib only.

The same device can run ONI as the Linux build (user folder ~/.config/unity3d/...) and as the Windows build under Proton
(one prefix per Steam library, e.g. on an SD card). The service watches all of those folders at once; this class decides
which one the app talks to. In order:
  1. a folder whose live.json says "running" and is fresh (the newest writtenAt wins);
  2. the folder of the running game process (lifetime.find_game: native build -> the Linux folder, Proton build -> the
     prefix named by STEAM_COMPAT_DATA_PATH / WINEPREFIX / the exe path);
  3. a folder whose live.json says "menu" and is fresh (the newest wins);
  4. the folder with the newest activity (saves, export files, live.json); on a tie the current one stays.
A forced folder (dev.json, ONI_USER_DIR, --user-dir) is always the active one.
Event driven: evaluate() runs on a file event of any folder, on the game starting or ending, and once at the moment
the shown live file would go stale (a crash writes nothing). No polling.
"""
import logging
import os
import threading
import time

from . import cause
from . import sources
from .sync import SyncService

log = logging.getLogger("oni_companion")
GAME_TTL = 2.0      # a /proc look is reused this long


class Follower:
    """paths: callable -> list of ONI user folders (default: sources.user_dir_paths). find: callable(proc) -> GameProcess|None,
    or None when the game process cannot be looked at (then rule 2 and "is the game running here" are unknown)."""

    def __init__(self, forced=None, paths=None, find=None, proc="/proc", env=None, clock=time.time, on_change=None):
        self.forced = forced or None
        self._paths_fn = paths or (lambda: sources.user_dir_paths(env))
        self.find, self.proc, self.env, self.clock = find, proc, env, clock
        self.on_change = on_change
        self.active = self.forced
        self.why = "forced" if self.forced else ""
        self._lock = threading.RLock()
        self._paths = []
        self._heads = {}                     # live path -> (sig, head)
        self._game = None
        self._game_at = None                 # clock time of the last /proc look
        self._timer = None
        self._closed = False
        self.refresh_paths()

    # ---- the folders
    def refresh_paths(self):
        """Look for ONI folders again (start, game start, a new Steam library). True if the set changed."""
        found = [] if self.forced else [p for p in self._paths_fn() if os.path.isdir(p)]
        with self._lock:
            for extra in ([self.forced] if self.forced else []) + ([self.active] if self.active else []):
                if extra and extra not in found and os.path.isdir(extra):
                    found.append(extra)
            changed = found != self._paths
            self._paths = found
        return changed

    @property
    def paths(self):
        with self._lock:
            return list(self._paths)

    def owner(self, path):
        """The ONI folder a file path lies in, or None."""
        best = None
        for p in self.paths:
            ap = os.path.abspath(p)
            if (path == ap or path.startswith(ap + os.sep)) and (best is None or len(ap) > len(best[0])):
                best = (ap, p)
        return best[1] if best else None

    # ---- what live.json says
    def head(self, user_dir):
        lp = sources.live_path(user_dir)
        try:
            st = os.stat(lp)
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None
        hit = self._heads.get(lp)
        if hit and hit[0] == sig:
            return hit[1]
        h = SyncService._load_head(lp)
        if not h or h.get("schema") not in (1, 2):
            h = None
        self._heads[lp] = (sig, h)
        return h

    def kind(self, user_dir):
        h = self.head(user_dir)
        if not h:
            return "none", None
        return cause.live_kind(h.get("state"), h.get("writtenAt"), h.get("paused"), self.clock()), h

    # ---- the game process
    def game(self, force=False):
        """The running game (cached GAME_TTL seconds), or None. Needs `find`."""
        if self.find is None:
            return None
        with self._lock:
            now = self.clock()
            if not force and self._game_at is not None and now - self._game_at < GAME_TTL:
                return self._game
        try:
            g = self.find(self.proc)
        except Exception:
            log.exception("game process look failed")
            g = None
        with self._lock:
            self._game, self._game_at = g, self.clock()
        return g

    def game_folder(self, game):
        """The ONI folder a game process writes to, or None when it cannot be told."""
        if game is None:
            return None
        if game.kind == "proton":
            d = sources.proton_user_dir_in_prefix(getattr(game, "prefix", None))
            if d:
                with self._lock:
                    known = {os.path.realpath(p): p for p in self._paths}
                    real = os.path.realpath(d)
                    if real in known:
                        return known[real]
                    self._paths.append(d)               # a library the first look did not know (SD card inserted later)
                return d
            proton = [p for p in self.paths if sources.user_dir_kind(p) == "proton"]
            return proton[0] if len(proton) == 1 else None
        linux = [p for p in self.paths if sources.user_dir_kind(p) == "linux"]
        return linux[0] if linux else None

    def game_here(self, user_dir=None):
        """True: the running game writes to this folder. False: no game runs, or one runs for another folder.
        None: cannot tell (no process look available, or the process' folder is unknown)."""
        if self.find is None:
            return None
        user_dir = user_dir or self.active
        g = self.game()
        if g is None:
            return False
        folder = self.game_folder(g)
        if folder is None or not user_dir:
            return None
        return os.path.realpath(folder) == os.path.realpath(user_dir)

    # ---- the choice
    def choose(self, fresh_game=False):
        """-> (folder or None, why)."""
        if self.forced:
            return self.forced, "forced"
        paths = self.paths
        if not paths:
            return None, "none"
        kinds = {p: self.kind(p) for p in paths}

        def newest(want, ok=None):
            hits = [(kinds[p][1].get("writtenAt") or 0, -i, p) for i, p in enumerate(paths)
                    if kinds[p][0] == want and (ok is None or ok(p))]
            return max(hits)[2] if hits else None

        g = self.game(force=fresh_game)
        # a running live.json only counts when no running game belongs to another folder: a crash or kill never writes "stopped"
        p = newest("running", lambda c: g is None or self.game_here(c) is not False)
        if p:
            return p, "live"
        folder = self.game_folder(g) if g else None
        if folder:
            return folder, "process"
        p = newest("menu")
        if p:
            return p, "menu"
        best, best_act = None, -1.0
        for p in paths:
            act = sources.user_activity(p)
            if act > best_act or (act == best_act and p == self.active):
                best, best_act = p, act
        return best, "activity"

    def evaluate(self, fresh_game=False):
        """Pick the active folder now (fresh_game: look at /proc again instead of using the last look). Calls on_change(old, new, why) outside the lock when it changed. Returns it."""
        with self._lock:
            if self._closed:
                return self.active
            new, why = self.choose(fresh_game)
            old = self.active
            if new is None or (old is not None and os.path.realpath(new) == os.path.realpath(old)):
                if new is not None:
                    self.why = why
                changed = False
            else:
                self.active, self.why = new, why
                changed = True
            self._arm()
        if changed:
            log.info("active ONI folder: %s (%s)", new, why)
            if self.on_change:
                try:
                    self.on_change(old, new, why)
                except Exception:
                    log.exception("folder switch failed")
        return self.active

    # ---- one timer: the moment the evidence of the current choice goes stale
    def _arm(self):
        if self.forced or self._closed:
            return
        deadline = None
        for p in self._paths:
            h = self.head(p)
            if not h or h.get("writtenAt") is None:
                continue
            st = h.get("state")
            limit = (cause.RUNNING_FRESH_PAUSED if h.get("paused") else cause.RUNNING_FRESH) if st == "running" \
                else cause.MENU_FRESH if st == "menu" else None
            if limit is None:
                continue
            d = h["writtenAt"] + limit + 0.5
            if d > self.clock() and (deadline is None or d < deadline):
                deadline = d
        old, self._timer = self._timer, None
        if old:
            old.cancel()
        if deadline is not None:
            t = threading.Timer(max(0.0, deadline - self.clock()), self.evaluate, (True,))
            t.daemon = True
            self._timer = t
            t.start()

    def close(self):
        with self._lock:
            self._closed = True
            t, self._timer = self._timer, None
        if t:
            t.cancel()
