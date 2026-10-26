"""Service lifetime = the game's lifetime (plan 5.1).

find_game()   looks for the running game in /proc (no ps, no polling).
wait_exit()   waits on a process handle (os.pidfd_open + select), so a normal quit and a crash (kill -9)
              both end the wait at once. Nothing sleeps in a loop.
GameGate      for a core that keeps running (Barry): opens the network parts when the game is found,
              closes them when the game ends.
run_standalone()  the standalone service: no game -> exit at once; game -> serve until it ends.

Linux only (pidfd_open needs Linux 5.3 and Python 3.9). The core reads only /proc entries of the user
who runs it.
"""
import logging
import os
import select
import signal
import threading
import time

log = logging.getLogger("oni_companion")

NATIVE_NAME = "OxygenNotIncluded"        # the Linux build (runs under FEX on ARM)
PROTON_NAME = "OxygenNotIncluded.exe"    # the Windows build under Proton/Wine
APP_ID = "457140"
POKE_MIN_SECONDS = 1.0                   # file events that arrive in a burst cause one /proc look


class GameProcess:
    def __init__(self, pid, kind, cmdline, prefix=None):
        self.pid, self.kind, self.cmdline = pid, kind, cmdline
        self.prefix = prefix        # Proton: the compat folder (.../compatdata/457140) the game runs in, when known

    @property
    def compat_path(self):
        return self.prefix

    def __repr__(self):
        return "GameProcess(pid=%d, kind=%s)" % (self.pid, self.kind)


def _base(arg):
    """Last path part of a Unix or Windows (Wine) path."""
    return arg.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _read_cmdline(proc, pid):
    try:
        with open(os.path.join(proc, str(pid), "cmdline"), "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def _ppid(proc, pid):
    try:
        with open(os.path.join(proc, str(pid), "stat"), "rb") as f:
            data = f.read().decode("utf-8", "replace")
        return int(data[data.rindex(")") + 2:].split()[1])      # after "(comm)": state, ppid
    except (OSError, ValueError, IndexError):
        return None


def _pids(proc):
    try:
        return [int(n) for n in os.listdir(proc) if n.isdigit()]
    except OSError:
        return []


def _is_native(args):
    # FEX runs the game as "<fex> /path/OxygenNotIncluded ...": the game binary is among the first words.
    # Other tools only carry the folder name "Oxygen Not Included" (with spaces), which does not match.
    return any(_base(a) == NATIVE_NAME for a in args[:3])


def _is_proton_game(args):
    return any(_base(a) == PROTON_NAME for a in args[:3])


def _is_reaper(args):
    return _base(args[0]) == "reaper" and ("AppId=" + APP_ID) in args


def _descends_from(proc, pid, ancestors):
    seen = 0
    while pid and pid > 1 and seen < 64:
        if pid in ancestors:
            return True
        pid = _ppid(proc, pid)
        seen += 1
    return False


def _read_environ(proc, pid):
    try:
        with open(os.path.join(proc, str(pid), "environ"), "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    out = {}
    for item in raw.split(b"\0"):
        k, sep, v = item.partition(b"=")
        if sep:
            out[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    return out


def proton_prefix(proc, pid, args):
    """The compat folder of a Proton game process: STEAM_COMPAT_DATA_PATH from its environment, else
    WINEPREFIX (minus /pfx), else the folder next to the game's library taken from the exe path in the command line
    (<library>/steamapps/common/<game>/OxygenNotIncluded.exe -> <library>/steamapps/compatdata/457140). None if unknown."""
    env = _read_environ(proc, pid)
    if env.get("STEAM_COMPAT_DATA_PATH"):
        return env["STEAM_COMPAT_DATA_PATH"].rstrip("/")
    wp = env.get("WINEPREFIX")
    if wp:
        wp = wp.rstrip("/")
        return os.path.dirname(wp) if os.path.basename(wp) == "pfx" else wp
    for a in args:
        norm = a.replace("\\", "/")
        i = norm.find("/steamapps/common/")
        if i > 0:
            lib = norm[:i]
            if len(lib) > 2 and lib[1] == ":" and lib[0].isalpha():    # Wine drive path Z:/... -> /...
                lib = lib[2:]
            return lib + "/steamapps/compatdata/" + APP_ID
    return None


def _prefix_of(user_dir):
    """The Proton prefix folder (.../compatdata/457140) an ONI user folder lies in, or None for a Linux user folder."""
    parts = os.path.normpath(user_dir).split(os.sep)
    for i in range(len(parts) - 1):
        if parts[i] == "compatdata" and parts[i + 1] == APP_ID:
            return os.sep.join(parts[:i + 2])
    return None


def matches_user_dir(game, user_dir, proc="/proc"):
    """True when this running game is the one that uses this user folder. A user folder inside a Proton prefix
    belongs to the Windows build in that prefix; any other user folder belongs to the Linux build."""
    prefix = _prefix_of(user_dir)
    if prefix is None:
        return game.kind == "native"
    if game.kind != "proton":
        return False
    cp = game.prefix if game.prefix is not None else proton_prefix(proc, game.pid, game.cmdline)
    return cp is not None and os.path.normpath(cp) == os.path.normpath(prefix)


def find_games(proc="/proc", own_pid=None):
    """Every running game as GameProcess: native builds first, then Proton's under the reaper that Steam
    started for AppId 457140."""
    own = own_pid or os.getpid()
    native, wine, reapers = [], [], set()
    for pid in sorted(_pids(proc)):
        if pid == own:
            continue
        args = _read_cmdline(proc, pid)
        if not args:
            continue
        if _is_native(args):
            native.append(GameProcess(pid, "native", args))
        elif _is_proton_game(args):
            wine.append((pid, args))
        elif _is_reaper(args):
            reapers.add(pid)
    out = native
    for pid, args in wine:
        if reapers and _descends_from(proc, pid, reapers):
            out.append(GameProcess(pid, "proton", args, proton_prefix(proc, pid, args)))
    return out


def find_game(proc="/proc", own_pid=None, user_dir=None):
    """The running game as GameProcess, or None. With several games running (Linux and Windows build at
    once) the one that uses `user_dir` is chosen (F1 passes the active folder; a callable is asked now). Without a
    folder, or when none matches, the first found: native before Proton."""
    games = find_games(proc, own_pid)
    if callable(user_dir):
        user_dir = user_dir()
    if user_dir and len(games) > 1:
        for g in games:
            if matches_user_dir(g, user_dir, proc):
                return g
    return games[0] if games else None


def still_game(proc, game):
    """The pid still is that game (guards against pid reuse between find and wait)."""
    args = _read_cmdline(proc, game.pid)
    return bool(args) and (_is_native(args) if game.kind == "native" else _is_proton_game(args))


class Stopper:
    """A pipe that wakes a wait on request (SIGTERM, shutdown)."""
    def __init__(self):
        self.r, self.w = os.pipe()
        os.set_blocking(self.w, False)

    def set(self):
        try:
            os.write(self.w, b"x")
        except OSError:
            pass

    def close(self):
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass


def wait_exit(pid, stopper=None):
    """Block until the process ends. Returns "exited" (also when it was gone already) or "stopped"."""
    try:
        pfd = os.pidfd_open(pid)
    except ProcessLookupError:
        return "exited"
    try:
        fds = [pfd] + ([stopper.r] if stopper else [])
        while True:
            try:
                ready, _, _ = select.select(fds, [], [])
            except InterruptedError:
                continue
            if pfd in ready:
                return "exited"
            if stopper and stopper.r in ready:
                return "stopped"
    finally:
        os.close(pfd)


class GameGate:
    """For a core that keeps running. poke() is called on a file event from the mod; when no game is
    being followed it looks once (throttled), and on finding the game it runs the up callbacks and waits
    on the game in its own thread. When the game ends (quit or crash) it runs the down callbacks."""

    def __init__(self, on_up=None, on_down=None, find=find_game, proc="/proc"):
        self.on_up = list(on_up or [])
        self.on_down = list(on_down or [])
        self._find, self._proc = find, proc
        self._lock = threading.Lock()
        self.game = None
        self._last_look = 0.0
        self._stopper = Stopper()
        self._thread = None
        self._closed = False

    @property
    def game_running(self):
        return self.game is not None

    def poke(self, force=False):
        with self._lock:
            if self.game is not None or self._closed:
                return
            now = time.monotonic()
            if not force and now - self._last_look < POKE_MIN_SECONDS:
                return
            self._last_look = now
            game = self._find(self._proc)
            if game is None:
                return
            self.game = game
            self._thread = threading.Thread(target=self._follow, args=(game,), name="oni-game", daemon=True)
        log.info("game found: %r", game)
        self._call(self.on_up)
        self._thread.start()

    def _follow(self, game):
        try:
            if still_game(self._proc, game):
                wait_exit(game.pid, self._stopper)
        except OSError:
            log.exception("waiting for the game failed")
        with self._lock:
            self.game = None
        log.info("game ended")
        self._call(self.on_down)

    def _call(self, fns):
        for fn in list(fns):
            try:
                fn()
            except Exception:
                log.exception("game callback failed")

    def close(self):
        with self._lock:
            self._closed = True
        self._stopper.set()
        t = self._thread
        if t and t is not threading.current_thread():
            t.join(2)
        self._stopper.close()


def run_standalone(service_factory, find=None, proc="/proc", install_signals=True, user_dir=None):
    """The standalone service's whole life. Returns the process exit code (0 = normal).
    service_factory() builds and starts the service; it is called only when the game is there.
    user_dir (a folder or a function returning it) = the active user folder: with two games running, follow its game."""
    game = find(proc) if find else find_game(proc, user_dir=user_dir)
    if game is None:
        log.info("no game process found: exiting at once")
        return 0
    stopper = Stopper()
    if install_signals and threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda *_: stopper.set())
    svc = service_factory()
    try:
        log.info("following %r", game)
        if still_game(proc, game):
            why = wait_exit(game.pid, stopper)
            log.info("%s: shutting down", "game ended" if why == "exited" else "stop requested")
    finally:
        for fn in list(getattr(svc, "on_game_down", [])):
            try:
                fn()
            except Exception:
                log.exception("game-down callback failed")
        svc.stop()
        stopper.close()
    return 0
