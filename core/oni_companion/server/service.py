"""Wires colony model, event bus, file watchers, token set and HTTP server."""
import logging
import os
import threading
import time

from ..art import ArtStore
from ..art.requests import ArtRequests
from ..actions import ActionService
from .. import config as oni_config
from ..colony import Colony
from ..sync import SyncService
from ..fonts import FontStore
from .. import sources
from ..connect.manager import ConnectManager
from ..cause import Explainer
from ..follow import Follower
from ..shared import SharedStore
from ..controls import Controls
from ..pad import PadWatch
from ..settings import FILE_NAME as SETTINGS_FILE, Settings
from ..watch import make_watcher
from . import http as http_mod
from .auth import TokenSet
from .events import EventBus
from .stub_views import load_views

log = logging.getLogger("oni_companion")
COALESCE_SECONDS = 0.03     # one burst of file events becomes one seq bump


class ServiceConfig:
    def __init__(self, user_dir=None, save_dirs=(), game_dir=None, host="127.0.0.1", port=0,
                 token=None, barry_mode=False, views_factory=None, save_parser=None, data_dir=None, ignore_game=False,
                 connect_opts=None, follow=False, shared=False, find=None, proc="/proc", follow_env=None,
                 follow_paths=None, auto_saves=False, user_dirs=None):
        self.user_dirs = list(user_dirs or [])   # every detected ONI folder (mod install + per-version state)
        self.user_dir = user_dir          # ONI user folder (holds companion/)
        self.save_dirs = list(save_dirs)
        self.game_dir = game_dir
        self.host, self.port = host, port
        self.token = token
        self.barry_mode = barry_mode
        self.views_factory = views_factory or load_views
        self.save_parser = save_parser
        self.ignore_game = ignore_game
        self.data_dir = data_dir          # where settings.json lives; None = the default data folder
        # v1.4 F1 (plan 4.3): follow the running game across every ONI user folder. follow=False: user_dir is the one
        # forced folder (dev.json, ONI_USER_DIR, --user-dir, tests). shared=True: the core keeps one art/font/theme copy
        # per game build + DLC set in <data_dir>/shared. find/proc: the game process finder (None = not looked at).
        self.follow, self.shared, self.find, self.proc = follow, shared, find, proc
        self.follow_env, self.follow_paths, self.auto_saves = follow_env, follow_paths, auto_saves
        self.connect_opts = connect_opts or {}   # ConnectManager arguments (tests: announcer, addresses_fn, bind_host, ...)

    @property
    def companion_dir(self):
        return os.path.join(self.user_dir, "companion") if self.user_dir else None


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.barry_mode = cfg.barry_mode
        self.tokens = TokenSet()
        self.token = self.tokens.add("default", cfg.token)
        self.bus = EventBus()
        data_dir = cfg.data_dir or oni_config.default_data_dir()
        self._switch_lock = threading.RLock()
        self.follower = Follower(forced=None if cfg.follow else cfg.user_dir, paths=cfg.follow_paths, find=cfg.find,
                                 proc=cfg.proc, env=cfg.follow_env)
        if cfg.follow:
            first = self.follower.evaluate()
            if first:
                cfg.user_dir = first
                if cfg.auto_saves:
                    cfg.save_dirs = self._saves_of(first)
        self.shared = SharedStore(os.path.join(data_dir, "shared")) if cfg.shared else None
        cdir = cfg.companion_dir
        self.live_path = os.path.join(cdir, "live", "live.json") if cdir else None
        self.export_dir = os.path.join(cdir, "export") if cdir else None
        self.art_dir = os.path.join(cdir, "art") if cdir else None
        self.art = ArtStore(cdir, self.live_path)
        self.colony = Colony(self.live_path, cfg.save_dirs, cfg.save_parser)
        self.actions = ActionService(cdir, self.bus.publish,
                                     expire=getattr(cfg, "action_expire", 10.0))
        self.controls = Controls(self.actions, self.colony, self.bus.publish, cdir)
        self.art_requests = ArtRequests(self.actions, self.art)
        self.art.on_miss = self.art_requests.request
        self.sync = SyncService(cdir, self.actions, lambda *names: self.bus.publish("sync"))
        self.actions.other_ack = lambda seq, path: self.art_requests.handle_ack(seq, path) or self.sync.handle_ack(seq, path)
        self.fonts_dir = os.path.join(cdir, "fonts") if cdir else None
        self.fonts = FontStore(cfg.game_dir, data_dir, self.shared.root if self.shared else cdir, build_id=self._steam_build)
        self.sync.ttf_hook = lambda build: any(f["kind"] == "ttf" for f in self.fonts.font_list()["fonts"])   # the core extracted the game's TTF fonts
        self.settings = Settings(os.path.join(data_dir, SETTINGS_FILE), lambda: self.bus.publish("settings"))
        # v1.4. Without an explicit data folder (tests) nothing is created until Connect a phone is used.
        connect_kw = dict(autostart=bool(cfg.data_dir))
        connect_kw.update(cfg.connect_opts)
        self.connect = ConnectManager(self, data_dir, cdir, **connect_kw)
        self.views = cfg.views_factory(self)
        self.actions.validate = getattr(self.views, "validate_command", None)
        self.actions.install_hook = getattr(self.views, "mod_install", None)
        self.pad_watch = PadWatch(self.colony.read_live, self.colony.live_fresh)
        self.server = None
        self._watcher = None
        self._timer = None
        self._pending = set()
        self._lock = threading.Lock()
        self._quit = threading.Event()
        # Game lifetime (plan 5.1): parts that must run only while the game runs (the network listener and
        # the mDNS announcement) add their open/close functions here; a GameGate calls them.
        self.on_game_up = []
        self.on_game_down = []
        self.game_gate = None
        self.on_game_up.append(lambda: self.connect.set_game_running(True))
        self.on_game_down.append(lambda: self.connect.set_game_running(False))
        # v1.4 F1: the real cause in every front end's message, the core's own art copy, the folder switch.
        self.explainer = Explainer(lambda: self.cfg.user_dir, self.follower.game_here)
        self.sync.explainer = self.controls.explainer = self.actions.explainer = self.explainer
        self.sync.shared = self.shared
        self._import_pending = set()
        self._import_evt = threading.Event()
        self._import_thread = None
        self._watch_set = None
        self._point_art()
        self.on_game_up.append(self._game_changed)
        self.on_game_down.append(self._game_changed)
        self.follower.on_change = lambda old, new, why: self.activate(new, why)

    # ---- v1.4 F1 (plan 4.3): the active ONI folder, the shared art copy
    def all_user_dirs(self):
        """Every ONI folder known right now: the startup list plus what the Follower finds again (a Proton prefix created
        after boot, an SD card inserted later). Mod install and per-version Settings state use this, not a snapshot."""
        try:
            self.follower.refresh_paths()
        except Exception:
            log.exception("folder look failed")
        out = list(self.cfg.user_dirs)
        known = {os.path.realpath(p) for p in out}
        for p in self.follower.paths:
            if os.path.realpath(p) not in known:
                out.append(p)
                known.add(os.path.realpath(p))
        self.cfg.user_dirs = out
        return out

    @staticmethod
    def _saves_of(user_dir):
        return [d for d in (os.path.join(user_dir, "cloud_save_files"), os.path.join(user_dir, "save_files"))
                if os.path.isdir(d)]

    def _game_changed(self):
        """The game started or ended: look at the folders and at /proc again."""
        self.follower.game(force=True)
        self.follower.refresh_paths()
        self.follower.evaluate()
        self._sync_watch()

    def activate(self, user_dir, why=""):
        """Make `user_dir` the folder the app talks to: commands, pairing files, live data, sync all follow it. Needs no
        restart; every screen is told to load again."""
        if not user_dir:
            return
        with self._switch_lock:
            cfg = self.cfg
            if cfg.user_dir and os.path.realpath(cfg.user_dir) == os.path.realpath(user_dir):
                return
            cfg.user_dir = user_dir
            if cfg.auto_saves:
                cfg.save_dirs = self._saves_of(user_dir)
            cdir = cfg.companion_dir
            self.live_path = os.path.join(cdir, "live", "live.json")
            self.export_dir = os.path.join(cdir, "export")
            self.art_dir = os.path.join(cdir, "art")
            self.colony.retarget(self.live_path, cfg.save_dirs if cfg.auto_saves else None)
            self.actions.retarget(cdir)
            self.controls.retarget(cdir)
            self.sync.retarget(cdir)
            self.art_requests.reset()
            self._point_art(force=True)
            self.pad_watch = PadWatch(self.colony.read_live, self.colony.live_fresh)
            self.connect.retarget(cdir)
            self.schedule_import(user_dir)
        log.info("now following %s (%s)", user_dir, why)
        self.bus.publish("status", "colony", "controls", "sync", "art", "gamedata", "pad", "build", "action")
        self._sync_watch()

    def active_folder(self):
        return self.cfg.user_dir

    def theme_root(self):
        """The folder holding theme/<build>: the core's shared copy when it has one, else the active ONI folder's."""
        if self.shared and self.shared.has_theme():
            return self.shared.root
        return self.cfg.companion_dir

    def _point_art(self, force=False):
        """Serve art from the shared copy of the current build + DLC set (or, until it has one, from the active folder).
        True when the art folder changed."""
        folder_art = os.path.join(self.cfg.companion_dir, "art") if self.cfg.companion_dir else None
        target = folder_art
        if self.shared:
            build, dlc = self.sync._current()
            d = self.shared.art_dir(build, dlc) if build is not None else None
            if d and os.path.isfile(os.path.join(d, "manifest.json")):
                target = d
        if force or target != self.art.art_dir:
            self.art.retarget(target, self.live_path)
            return True
        return False

    def schedule_import(self, user_dir):
        """Copy finished art, fonts and theme of one ONI folder into the shared copy (a worker does it, bursts are one)."""
        if not self.shared or not user_dir:
            return
        with self._lock:
            self._import_pending.add(user_dir)
            if self._import_thread is None and not self._quit.is_set():
                self._import_thread = threading.Thread(target=self._import_loop, name="oni-shared", daemon=True)
                self._import_thread.start()
        self._import_evt.set()

    def _import_loop(self):
        while True:
            self._import_evt.wait()
            if self._quit.is_set():
                return
            time.sleep(0.2)                          # a burst of file events is one import
            self._import_evt.clear()
            with self._lock:
                todo, self._import_pending = sorted(self._import_pending), set()
            names = set()
            for d in todo:
                try:
                    res = self.shared.import_folder(d)
                except Exception:
                    log.exception("shared import failed")
                    continue
                if res["art"]:
                    names.update(("art", "colony", "status"))
                if res["fonts"] or res["theme"] or res["pack"]:
                    names.add("sync")
            if self._point_art():
                names.update(("art", "colony", "status"))
            if names:
                self.bus.publish(*names)

    def _is_active(self, folder):
        a = self.cfg.user_dir
        return bool(a) and os.path.realpath(folder) == os.path.realpath(a)

    def _sync_watch(self):
        """Watch every ONI folder (and the save folders outside them). Restarts the watcher only when the set changed;
        the swap runs on its own thread because this can be called from the watcher's own thread."""
        roots = self._watch_roots()
        with self._lock:
            if self._watcher is None or roots == self._watch_set:
                return
            self._watch_set = roots
        threading.Thread(target=self._swap_watcher, args=(roots,), name="oni-rewatch", daemon=True).start()

    def _swap_watcher(self, roots):
        with self._lock:
            old, self._watcher = self._watcher, None
        if old:
            old.stop()
        if roots and not self._quit.is_set():
            w = make_watcher(roots, self._on_file, recursive=True).start()
            with self._lock:
                if self._watcher is None and not self._quit.is_set():
                    self._watcher = w
                    w = None
            if w:
                w.stop()

    def enable_game_gate(self, gate=None):
        """Barry's core keeps running; this follows the game for the parts above. Event driven: a file
        event from the mod makes it look for the game, and a process handle tells when it ended."""
        from ..lifetime import GameGate
        self.game_gate = gate or GameGate(self.on_game_up, self.on_game_down)
        self.game_gate.poke(force=True)
        return self.game_gate

    def _steam_build(self):
        mf = self.cfg.game_dir and sources.find_appmanifest(self.cfg.game_dir)
        info = sources.read_appmanifest(mf) if mf else None
        return info["buildid"] if info else None

    # file event -> change names
    def classify(self, path):
        names = self._classify(path)
        if not path.endswith(".tmp") and self.sync.touched(path):
            names = tuple(names) + ("sync",)
        return names

    def _classify(self, path):
        base = os.path.basename(path)
        if base.endswith(".tmp"):
            return ()
        if self.fonts_dir and path.startswith(self.fonts_dir + os.sep):
            return ("sync",)           # the mod exported the Graystroke atlas: GET /fonts and /theme change
        if self.live_path and os.path.dirname(self.live_path) == os.path.dirname(path):
            return ("colony", "status", "controls") + self.pad_watch.changed() if base == "live.json" else ()
        if self.art_dir and base == "manifest.json" and os.path.dirname(path) == self.art_dir:
            if self.shared:
                return ()                  # the import publishes `art` once the pictures are in the shared copy
            return ("colony", "status", "art")     # new portraits: screens carrying art are fetched again; "art": a 404 picture asks again
        if self.export_dir and os.path.dirname(path) == self.export_dir:
            return ("gamedata", "status") if base.endswith(".json") else ()
        if base.endswith(".sav"):
            return ("colony", "status")
        return ()

    _IMPORT_PARTS = (os.sep + "art" + os.sep, os.sep + "fonts" + os.sep, os.sep + "theme" + os.sep,
                     os.sep + "sync" + os.sep)

    def _on_file(self, path, what):
        if self.game_gate is not None:
            self.game_gate.poke()
        owner = self.follower.owner(path)
        if owner is not None and not path.endswith(".tmp"):
            if os.path.basename(path) == "live.json" and not self.follower.forced:
                self.follower.evaluate()                   # another folder's live file may now decide (may switch)
            if self.shared and any(part in path for part in self._IMPORT_PARTS):
                self.schedule_import(owner)
            if not self._is_active(owner):
                return                                      # a folder we are not following: only the above
        if self.connect.handle_file(path, what):
            return
        if what != "removed" and self.actions.handle_file(path):
            return
        names = self.classify(path)
        if not names:
            return
        with self._lock:
            self._pending.update(names)
            if self._timer is None:
                self._timer = threading.Timer(COALESCE_SECONDS, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self):
        with self._lock:
            names, self._pending, self._timer = self._pending, set(), None
        self.bus.publish(*names)

    def _watch_roots(self):
        """The whole ONI user folder (so companion/live appears later too), plus
        any save folder outside it. Nothing is created or written."""
        roots = []
        for p in ([self.cfg.user_dir] if self.cfg.user_dir else []) + self.follower.paths:
            if os.path.abspath(p) not in roots:
                roots.append(os.path.abspath(p))
        for d in self.cfg.save_dirs:
            d = os.path.abspath(d)
            if not any(d == r or d.startswith(r + os.sep) for r in roots):
                roots.append(d)
        return [r for r in roots if os.path.isdir(r)]

    def start(self):
        roots = self._watch_roots()
        self._watch_set = roots
        if roots:
            self._watcher = make_watcher(roots, self._on_file, recursive=True).start()
        for p in self.follower.paths:
            self.schedule_import(p)
        self.server = http_mod.make_server(self.cfg.host, self.cfg.port, self)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, name="oni-http", daemon=True).start()
        threading.Thread(target=self._fonts_once, name="oni-fonts", daemon=True).start()
        self.connect.start()
        return self

    def _fonts_once(self):
        """Read the game's fonts once at start (a few hundred KB of reads); tell clients when there are fonts."""
        try:
            entries, changed = self.fonts.ensure()
            if entries and changed:
                self.bus.publish("sync")
        except Exception:
            log.exception("font extraction failed")

    def serve_forever(self):
        try:
            self._quit.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def request_stop(self):
        """Ends serve_forever (the game ended, standalone mode)."""
        self._quit.set()

    def stop(self):
        self._quit.set()
        self._import_evt.set()
        self.follower.close()
        self.connect.close()
        if self.game_gate is not None:
            self.game_gate.close()
            self.game_gate = None
        self.controls.close()
        self.actions.close()
        self.sync.close()
        self.bus.close()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self._watcher:
            self._watcher.stop()
            self._watcher = None


def start(config):
    return Service(config).start()
