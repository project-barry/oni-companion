"""Paths, modes and environment overrides.

Priority for every path: environment variable > dev.json in the data folder > auto-detect.
  ONI_GAME_DIR  game install folder (the one holding OxygenNotIncluded_Data), or a copy of it
  ONI_USER_DIR  ONI user folder (holds cloud_save_files/, mods/, companion/). Forces that one folder. Without it the
                service watches the Linux build folder and every Proton prefix (compatdata/457140, all Steam libraries)
                and follows the running game (follow.py).
  ONI_SAVE_DIR  folder to search for .sav files (default: inside the user folder)
  ONI_DATA_DIR  where the core keeps its cache (and optional dev.json)
dev.json keys: game_dir, user_dir, save_dir. Looked up in the data folder, in $BARRY_APP_DATA, and in
clients/barry/dev.json of a repo checkout.
"""
import json
import os
import sys
from dataclasses import dataclass, field

from . import sources

MODES = ("barry", "standalone")
APP_ID = 457140


def default_data_dir(env=None):
    env = os.environ if env is None else env
    if env.get("ONI_DATA_DIR"):
        return env["ONI_DATA_DIR"]
    home = env.get("HOME") or os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "oni-companion")
    base = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "oni-companion")


@dataclass
class Config:
    mode: str = "barry"
    game_dir: str = ""
    user_dir: str = ""
    user_dirs: list = field(default_factory=list)   # every detected ONI folder (only when user_dir was auto-detected)
    save_dir: str = ""
    data_dir: str = ""
    notes: list = field(default_factory=list)  # how each path was chosen (for /status and debugging)
    user_dir_forced: bool = False              # user_dir came from an argument, ONI_USER_DIR or dev.json (not auto-detect)

    @property
    def user_dir_kind(self):
        return sources.user_dir_kind(self.user_dir) if self.user_dir else ""

    @property
    def assets_dir(self):
        return sources.assets_dir(self.game_dir) if self.game_dir else ""

    @property
    def companion_dir(self):
        return sources.companion_dir(self.user_dir) if self.user_dir else ""

    @property
    def cache_dir(self):
        return os.path.join(self.data_dir, "cache")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _dev_json(data_dir, env=None):
    """dev.json from the data folder, then the app's data folder (BARRY_APP_DATA), then, when running
    from a repo checkout, clients/barry/dev.json. The first file that has a key wins."""
    env = os.environ if env is None else env
    real_process = env is os.environ   # a test or caller handing in its own env never reads the repo file
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.join(data_dir, "dev.json")]
    if env.get("BARRY_APP_DATA"):
        paths.append(os.path.join(env["BARRY_APP_DATA"], "dev.json"))
    if real_process:
        paths.append(os.path.normpath(os.path.join(here, "..", "..", "clients", "barry", "dev.json")))
    out = {}
    for p in paths:
        for k, v in _read_json(p).items():
            out.setdefault(k, v)
    return out


def load(env=None, mode="barry", **overrides):
    """Build a Config. `overrides` (game_dir=, user_dir=, save_dir=, data_dir=) win over everything."""
    env = os.environ if env is None else env
    if mode not in MODES:
        raise ValueError("unknown mode %r" % (mode,))
    cfg = Config(mode=mode)
    cfg.data_dir = overrides.get("data_dir") or default_data_dir(env)
    dev = _dev_json(cfg.data_dir, env)

    def pick(name, envname, detect):
        if overrides.get(name):
            cfg.notes.append("%s: argument" % name)
            cfg.user_dir_forced = cfg.user_dir_forced or name == "user_dir"
            return overrides[name]
        if env.get(envname):
            cfg.notes.append("%s: %s" % (name, envname))
            cfg.user_dir_forced = cfg.user_dir_forced or name == "user_dir"
            return env[envname]
        if dev.get(name):
            cfg.notes.append("%s: dev.json" % name)
            cfg.user_dir_forced = cfg.user_dir_forced or name == "user_dir"
            return dev[name]
        found = detect()
        cfg.notes.append("%s: %s" % (name, "auto-detect" if found else "not found"))
        return found or ""

    cfg.game_dir = pick("game_dir", "ONI_GAME_DIR", lambda: sources.find_game_dir(env))
    cfg.user_dir = pick("user_dir", "ONI_USER_DIR", lambda: sources.default_user_dir(env))
    forced = not cfg.notes[-1].endswith("auto-detect") if cfg.notes else True
    cfg.user_dirs = [cfg.user_dir] if cfg.user_dir else []
    if cfg.user_dir and not forced:
        cfg.user_dirs += [c["path"] for c in sources.user_dir_candidates(env) if c["path"] != cfg.user_dir]
    cfg.save_dir = pick("save_dir", "ONI_SAVE_DIR", lambda: "")
    return cfg
