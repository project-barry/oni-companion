"""Find the game install, the user folder, saves and the mod's output."""
import json
import os
import re
import sys

APP_ID = "457140"
GAME_FOLDER = "OxygenNotIncluded"


# ---- minimal Valve KeyValues (VDF) reader: libraryfolders.vdf, appmanifest_*.acf ----

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text):
    root = {}
    stack = [root]
    key = None
    for m in _VDF_TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            s = s.replace("\\\\", "\\")
            if key is None:
                key = s
            else:
                stack[-1][key] = s
                key = None
    return root


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def read_appmanifest(path):
    """{buildid:int|None, installdir:str, depots:[str], lastUpdated:int|None} or None."""
    text = _read(path)
    if text is None:
        return None
    st = parse_vdf(text).get("AppState", {})
    def num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return {"buildid": num(st.get("buildid")), "installdir": st.get("installdir", ""),
            "depots": sorted((st.get("InstalledDepots") or {}).keys()),
            "lastUpdated": num(st.get("LastUpdated"))}


def steam_roots(env=None):
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    cands = [os.path.join(home, ".local/share/Steam"), os.path.join(home, ".steam/steam"),
             os.path.join(home, ".steam/root"),
             os.path.join(home, "Library/Application Support/Steam"),
             os.path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    seen, out = set(), []
    for c in cands:
        real = os.path.realpath(c)
        if os.path.isdir(real) and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def library_folders(env=None):
    """Every steamapps folder known to Steam."""
    libs, seen = [], set()
    def add(p):
        p = os.path.realpath(p)
        if p not in seen and os.path.isdir(p):
            seen.add(p)
            libs.append(p)
    for root in steam_roots(env):
        add(os.path.join(root, "steamapps"))
        text = _read(os.path.join(root, "steamapps", "libraryfolders.vdf"))
        if text:
            lf = parse_vdf(text).get("libraryfolders", {})
            for v in lf.values():
                path = v.get("path") if isinstance(v, dict) else v
                if isinstance(path, str):
                    add(os.path.join(path, "steamapps"))
    return libs


def find_game_dir(env=None):
    """Install folder of ONI (appid 457140) or None."""
    for lib in library_folders(env):
        mf = read_appmanifest(os.path.join(lib, "appmanifest_%s.acf" % APP_ID))
        if mf is None:
            continue
        d = os.path.join(lib, "common", mf["installdir"] or GAME_FOLDER)
        if os.path.isdir(d):
            return d
    return None


def find_appmanifest(game_dir):
    """The appmanifest for a game folder: inside it (a dev copy) or in the steamapps parent."""
    for rel in (".", "..", os.path.join("..", "..")):
        p = os.path.normpath(os.path.join(game_dir, rel, "appmanifest_%s.acf" % APP_ID))
        if os.path.isfile(p):
            return p
    return None


def assets_dir(game_dir):
    """StreamingAssets folder for Linux/Windows, macOS .app, or a flat copy."""
    for rel in (os.path.join("OxygenNotIncluded_Data", "StreamingAssets"),
                os.path.join("OxygenNotIncluded.app", "Contents", "Resources", "Data", "StreamingAssets"),
                "StreamingAssets"):
        p = os.path.join(game_dir, rel)
        if os.path.isdir(p):
            return p
    return os.path.join(game_dir, "OxygenNotIncluded_Data", "StreamingAssets")


def installed_dlc_ids(assets):
    """DLC ids from dlc/<folder>: expansion1 -> EXPANSION1_ID, dlcN -> DLCN_ID. Cosmetic packs have no id."""
    out = []
    d = os.path.join(assets, "dlc")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not os.path.isdir(os.path.join(d, n)):
            continue
        if n == "expansion1" or re.fullmatch(r"dlc\d+", n):
            out.append(n.upper() + "_ID")
    return out


# ---- user folder, saves, mod output ----

PROTON_USER_REL = os.path.join("pfx", "drive_c", "users")  # under compatdata/<appid>/


def proton_user_dirs(env=None):
    """ONI user folders inside Proton prefixes (compatdata/457140) of every Steam library."""
    out = []
    for lib in library_folders(env):
        users = os.path.join(lib, "compatdata", APP_ID, PROTON_USER_REL)
        try:
            names = sorted(os.listdir(users))
        except OSError:
            continue
        for n in names:
            if n == "Public":
                continue
            d = os.path.join(users, n, "Documents", "Klei", "OxygenNotIncluded")
            if os.path.isdir(d):
                out.append(d)
    return out


def user_dir_kind(path):
    """'proton', 'linux', 'macos', 'windows' or 'custom' from where the folder sits."""
    p = (path or "").replace("\\", "/")
    if "/compatdata/" in p and "/pfx/" in p:
        return "proton"
    if "/.config/unity3d/Klei/" in p:
        return "linux"
    if "unity.Klei.Oxygen Not Included" in p:
        return "macos"
    if p.endswith("Documents/Klei/OxygenNotIncluded"):
        return "windows"
    return "custom"


def user_activity(user_dir):
    """Newest mtime of anything that shows the game ran there: live.json, export files, saves. 0 if none."""
    best = 0.0
    def look(p):
        nonlocal best
        try:
            best = max(best, os.stat(p).st_mtime)
        except OSError:
            pass
    look(live_path(user_dir))
    for p in export_files(user_dir):
        look(p)
    sv = newest_save(user_dir)
    if sv:
        best = max(best, sv["mtime"])
    return best


def user_dir_paths(env=None):
    """Every existing ONI user folder (all Steam libraries incl. SD cards, every Proton prefix, the Linux
    folder), Proton first. Cheap: no file is read."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    paths = proton_user_dirs(env) + [
        os.path.join(home, ".config/unity3d/Klei/Oxygen Not Included"),
        os.path.join(home, "Library/Application Support/unity.Klei.Oxygen Not Included"),  # macOS (UNTESTED)
        os.path.join(home, "Documents/Klei/OxygenNotIncluded")]  # Windows-style (UNTESTED)
    out, seen = [], set()
    for c in paths:
        real = os.path.realpath(c)
        if real in seen or not os.path.isdir(c):
            continue
        seen.add(real)
        out.append(c)
    return out


def user_dir_candidates(env=None):
    """Every existing ONI user folder: [{path, kind, activity}], Proton first (the Nova's current setup)."""
    return [{"path": c, "kind": user_dir_kind(c), "activity": user_activity(c)} for c in user_dir_paths(env)]


def proton_user_dir_in_prefix(compat_dir):
    """The ONI user folder inside one Proton compat folder (<library>/steamapps/compatdata/457140), or None.
    A WINEPREFIX (.../pfx) is accepted too."""
    if not compat_dir:
        return None
    base = compat_dir.rstrip("/")
    if os.path.basename(base) == "pfx":
        base = os.path.dirname(base)
    users = os.path.join(base, PROTON_USER_REL)
    try:
        names = sorted(os.listdir(users))
    except OSError:
        return None
    for n in names:
        if n == "Public":
            continue
        d = os.path.join(users, n, "Documents", "Klei", "OxygenNotIncluded")
        if os.path.isdir(d):
            return d
    return None


def default_user_dir(env=None):
    """The user folder with the newest save/companion activity; on a tie the first (Proton before Linux)."""
    cands = user_dir_candidates(env)
    if not cands:
        return None
    best = cands[0]
    for c in cands[1:]:
        if c["activity"] > best["activity"]:
            best = c
    return best["path"]


def companion_dir(user_dir):
    return os.path.join(user_dir, "companion")


def export_files(user_dir):
    d = os.path.join(companion_dir(user_dir), "export")
    try:
        names = sorted(n for n in os.listdir(d) if n.startswith("gamedata-") and n.endswith(".json"))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names]


def live_path(user_dir):
    return os.path.join(companion_dir(user_dir), "live", "live.json")


_CYCLE = re.compile(r"Cycle\s+(\d+)", re.I)


def newest_save(user_dir="", save_dir=""):
    """Newest .sav by mtime: {path, name, cycle|None, mtime} or None."""
    roots = [save_dir] if save_dir else [os.path.join(user_dir, "cloud_save_files"),
                                         os.path.join(user_dir, "save_files")] if user_dir else []
    best = None
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".sav"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    mt = os.stat(p).st_mtime
                except OSError:
                    continue
                if best is None or mt > best["mtime"]:
                    m = _CYCLE.search(fn)
                    best = {"path": p, "name": fn[:-4], "cycle": int(m.group(1)) if m else None, "mtime": mt}
    return best
