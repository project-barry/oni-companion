"""Where the game mod stands (v1.3): missing, disabled, no live data, version mismatch or ok, plus the ask-first
install of the bundled mod. Stdlib only. The core decides; every front end shows the same state and steps.

What it reads (never writes, except install): <user>/mods/Local/OniCompanionLink, <user>/mods/Steam/*,
<user>/mods/mods.json, live.json and the export (through the dataset meta), and the game's Player.log path.

The game's own rule for "enabled" (decompiled, KMod.Mod.IsEnabledForActiveDlc): mods.json lists per mod the DLC
sets it is enabled for (`enabledForDlc`); the set that counts is the highest active content id, which is
"EXPANSION1_ID" when Spaced Out is on and "" otherwise. The old `enabled` field is ignored.
"""
import json
import os
import re
import shutil
import zipfile

from . import __version__
from . import sources

MOD_ID = "OniCompanionLink"
MOD_TITLE = "ONI Companion Link"
# Mod versions this app can use. 0.4.0 is the mod of contract 3 (overlays, tools, build); an older mod still
# writes live data, so the other tabs keep working, but the state says to update it.
SUPPORTS_MOD = {"min": "0.4.0"}
BUNDLED_FILES = ("OniCompanionLink.dll", "mod.yaml", "mod_info.yaml")


def vtuple(text):
    """'1.3.0' -> (1, 3, 0); None for anything that is not dotted numbers."""
    if not isinstance(text, str) or not re.match(r"^[0-9]+(\.[0-9]+){0,3}$", text.strip()):
        return None
    return tuple(int(x) for x in text.strip().split("."))


def _cmp(a, b):
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def in_range(version, rng):
    """True/False, or None when the version or the range cannot be read."""
    v = vtuple(version)
    if v is None or not isinstance(rng, dict):
        return None
    lo, hi = vtuple(rng.get("min")), vtuple(rng.get("max")) if rng.get("max") else None
    if lo is None or (rng.get("max") and hi is None):
        return None
    return _cmp(v, lo) >= 0 and (hi is None or _cmp(v, hi) <= 0)


def _read_json(path):
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read().decode("utf-8-sig"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _info_version(folder):
    """version: of mod_info.yaml in a mod folder (a flat key: value file), or None."""
    try:
        with open(os.path.join(folder, "mod_info.yaml"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*version:\s*['\"]?([^'\"\s#]+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def _is_ours(folder):
    try:
        with open(os.path.join(folder, "mod.yaml"), encoding="utf-8", errors="replace") as f:
            return re.search(r"^\s*staticID:\s*['\"]?%s\b" % MOD_ID, f.read(), re.M) is not None
    except OSError:
        return False


def _yaml_is_ours(text):
    return re.search(r"^\s*staticID:\s*['\"]?%s\b" % MOD_ID, text, re.M) is not None


def _zip_is_ours(path):
    """A Workshop item as Steam stores it: one zip with mod.yaml in it (KMod.Steam reads it the same way)."""
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.replace("\\", "/").split("/")[-1] == "mod.yaml":
                    if _yaml_is_ours(z.read(n).decode("utf-8", "replace")):
                        return True
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, RuntimeError):
        pass
    return False


def workshop_item_roots(user_dir, env=None):
    """Folders where Steam keeps downloaded ONI Workshop items: <steamapps>/workshop/content/457140/<id>/.
    Verified in the game's code (KMod.Steam: SteamUGC.GetItemInstallInfo gives a zip inside the Steam content folder,
    the game later copies it to <user>/mods/Steam/<id>). The same on Linux and under Proton, so every Steam library
    counts, plus the library the Proton prefix sits in."""
    env = os.environ if env is None else env
    libs = []
    p = (user_dir or "").replace("\\", "/")
    if "/steamapps/compatdata/" in p:
        libs.append(p.split("/compatdata/")[0])
    try:
        libs += sources.library_folders(env)
    except Exception:
        pass
    roots = [env.get("ONI_WORKSHOP_DIR")] if env.get("ONI_WORKSHOP_DIR") else []
    for lib in libs:
        roots.append(os.path.join(lib, "workshop", "content", sources.APP_ID))
    seen, out = set(), []
    for r in roots:
        n = os.path.normpath(r)
        if n not in seen and os.path.isdir(n):
            seen.add(n)
            out.append(n)
    return out


def find_workshop_downloads(user_dir, env=None):
    found = []
    for root in workshop_item_roots(user_dir, env):
        try:
            items = sorted(os.listdir(root))
        except OSError:
            continue
        for item in items:
            base = os.path.join(root, item)
            files = [base] if os.path.isfile(base) else []
            if os.path.isdir(base):
                try:
                    files = [os.path.join(base, f) for f in sorted(os.listdir(base))]
                except OSError:
                    files = []
            for f in files:
                if os.path.isdir(f):
                    ok = _is_ours(f)
                else:
                    ok = _zip_is_ours(f)
                if ok:
                    found.append(base)
                    break
    return found


def find_copies(user_dir, env=None):
    """{'local': folder|None, 'workshop': [folders]}: our copy in <user>/mods/Local, a subscribed Workshop copy in
    <user>/mods/Steam (after the game copied it) or in Steam's download folder (right after subscribing), or one the
    game's mods.json lists as a Steam mod."""
    out = {"local": None, "workshop": []}
    if not user_dir:
        return out
    local = os.path.join(user_dir, "mods", "Local", MOD_ID)
    if os.path.isdir(local):
        out["local"] = local
    steam = os.path.join(user_dir, "mods", "Steam")
    try:
        names = sorted(os.listdir(steam))
    except OSError:
        names = []
    for n in names:
        p = os.path.join(steam, n)
        if os.path.isdir(p) and _is_ours(p):
            out["workshop"].append(p)
    out["workshop"] += [d for d in find_workshop_downloads(user_dir, env) if d not in out["workshop"]]
    rows, _ = mods_json_entries(user_dir)
    if not out["workshop"] and any((r.get("label") or {}).get("distribution_platform") == 1 for r in rows):
        out["workshop"].append("mods.json")
    return out


def mods_json_entries(user_dir):
    d = _read_json(os.path.join(user_dir, "mods", "mods.json")) if user_dir else None
    rows = []
    for m in (d or {}).get("mods") or []:
        if isinstance(m, dict) and MOD_ID in (m.get("staticID"), (m.get("label") or {}).get("id")):
            rows.append(m)
    return rows, d is not None


def active_set_id(dlc_ids):
    """The enabledForDlc key that counts: EXPANSION1_ID with Spaced Out active, else ''. None when unknown."""
    if dlc_ids is None:
        return None
    return "EXPANSION1_ID" if "EXPANSION1_ID" in dlc_ids else ""


def enabled_in_game(entries, dlc_ids):
    """True / False from mods.json, None when mods.json has no entry for the mod."""
    if not entries:
        return None
    want = active_set_id(dlc_ids)
    for m in entries:
        lst = m.get("enabledForDlc")
        if not isinstance(lst, list):
            lst = [""] if m.get("enabled") else []        # what the game does for an old file
        if (want in lst) if want is not None else bool(lst):
            return True
    return False


def player_log(user_dir, kind=None):
    """The game's Player.log if it can be found next to this user folder, else None."""
    if not user_dir:
        return None
    cands = []
    p = os.path.normpath(user_dir)
    up = os.path.dirname(os.path.dirname(os.path.dirname(p)))      # .../users/steamuser (Proton, Windows): up from Documents/Klei/<ONI>
    cands.append(os.path.join(up, "AppData", "LocalLow", "Klei", "Oxygen Not Included", "Player.log"))
    home = os.path.expanduser("~")
    cands.append(os.path.join(home, ".config", "unity3d", "Klei", "Oxygen Not Included", "Player.log"))
    cands.append(os.path.join(home, "Library", "Logs", "Klei", "Oxygen Not Included", "Player.log"))
    if kind == "proton":
        cands = cands[:1]
    elif kind == "linux":
        cands = cands[1:2]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def bundled_dir(env=None):
    """Folder with the built mod this app ships (the DLL and its two yaml files), or None."""
    env = os.environ if env is None else env
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [env.get("ONI_BUNDLED_MOD"), os.path.join(here, "bundled_mod", MOD_ID),
             os.path.normpath(os.path.join(here, "..", "..", "mod", "build", MOD_ID))]
    for c in cands:
        if c and all(os.path.isfile(os.path.join(c, f)) for f in BUNDLED_FILES):
            return c
    return None


KIND_LABEL = {"linux": "Linux", "proton": "Windows (Proton)", "macos": "macOS", "windows": "Windows", "custom": "Custom folder"}


def kind_label(kind):
    return KIND_LABEL.get(kind, "Other")


def library_of(path):
    """The Steam library that holds a Proton prefix (the folder with steamapps/compatdata inside), else None."""
    p = (path or "").replace("\\", "/")
    if "/compatdata/" not in p:
        return None
    lib = p.split("/compatdata/")[0]
    return lib[: -len("/steamapps")] if lib.endswith("/steamapps") else lib


def crash_blamed(user_dir, kind):
    """True when this version's Player.log has a game-logged error that names the mod (the game's crash screen
    then blames it and empties its mods.json entry). Only the last 512 KB are read."""
    log = player_log(user_dir, kind)
    if not log:
        return False
    try:
        with open(log, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 512 * 1024))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    return any(MOD_ID in ln and re.search(r"exception|error", ln, re.I) for ln in text.splitlines())


CRASH_MARK = "mod-crash-blamed"


def crash_flag(user_dir, kind, enabled):
    """True when the game's crash screen turned the mod off in this folder. Needs the emptied entry (caller checks) AND
    evidence: a Player.log line naming the mod, remembered in companion/mod-crash-blamed because the game rewrites
    Player.log on every start. The mark is dropped once the mod is on again. A plain toggle-off has no evidence."""
    mark = os.path.join(user_dir, "companion", CRASH_MARK) if user_dir else None
    if not mark:
        return False
    if enabled is not False:
        try:
            if enabled is True and os.path.isfile(mark):
                os.remove(mark)
        except OSError:
            pass
        return False
    if crash_blamed(user_dir, kind):
        try:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, "w") as f:
                f.write("1\n")
        except OSError:
            pass
        return True
    return os.path.isfile(mark)


def folder_state(user_dir, dlc_ids, env=None, active=False):
    """One ONI version's mod state: {kind, label, path, library, installed, copy, workshop, enabled, crashDisabled, active}."""
    kind = sources.user_dir_kind(user_dir)
    copies = find_copies(user_dir, env)
    have = [copies["local"]] if copies["local"] else []
    have += [w for w in copies["workshop"] if w != "mods.json"]
    ver = None
    for f in have:
        v = _info_version(f)
        if vtuple(v):
            ver = v
            break
    entries, _ = mods_json_entries(user_dir)
    enabled = enabled_in_game(entries, dlc_ids)
    present = bool(copies["local"] or copies["workshop"])
    emptied = bool(entries) and all(isinstance(m.get("enabledForDlc"), list) and not m["enabledForDlc"] for m in entries)
    return {"kind": kind, "label": kind_label(kind), "path": user_dir, "library": library_of(user_dir),
            "installed": ver, "copy": "workshop" if copies["workshop"] else ("local" if copies["local"] else None),
            "workshop": bool(copies["workshop"]), "enabled": enabled if present else None,
            "crashDisabled": bool(present and emptied and enabled is False and crash_flag(user_dir, kind, enabled)),
            "active": bool(active)}


def versions_summary(rows):
    """('Linux: on, 0.4.3 \u00b7 Windows (Proton): off', update_both) for the Settings page."""
    parts = []
    for r in rows:
        if r["copy"] is None:
            st = "not installed"
        elif r["crashDisabled"]:
            st = "switched off by a game error"
        else:
            st = "on" if r["enabled"] is not False else "off"
        if r["installed"] and r["copy"]:
            st += ", " + r["installed"]
        parts.append("%s: %s" % (r["label"], st))
    vs = [vtuple(r["installed"]) for r in rows if r["copy"] and r["installed"]]
    both = len(vs) > 1 and any(_cmp(vs[0], v) != 0 for v in vs[1:])
    return " \u00b7 ".join(parts), both


class ModState:
    """user_dir: the ONI user folder. meta(): dataset meta dict or {} (modVersion, modRequiresCore, ...).
    live(): the parsed live.json or None. fresh(live): bool. bundled: folder of the built mod, or None."""

    def __init__(self, user_dir, meta=None, live=None, fresh=None, bundled=None, core_version=__version__, env=None,
                 folders=None):
        self.env = env
        self.user_dir = user_dir
        self.folders = [f for f in (folders or []) if f]          # every detected ONI user folder (install + per-version state)
        if user_dir and user_dir not in self.folders:
            self.folders.insert(0, user_dir)
        self.meta = meta or (lambda: {})
        self.live = live or (lambda: None)
        self.fresh = fresh or (lambda lv: False)
        self.bundled = bundled
        self.core_version = core_version

    # ---- pieces
    def _mod_version(self, live, meta, copies):
        for v in ((live or {}).get("modVersion"), meta.get("modVersion")):
            if vtuple(v):
                return v
        for f in ([copies["local"]] if copies["local"] else []) + copies["workshop"]:
            v = _info_version(f)
            if vtuple(v):
                return v
        return None

    def _install_info(self, copies, user_dir=None):
        user_dir = user_dir or self.user_dir
        target = os.path.join(user_dir, "mods", "Local", MOD_ID) if user_dir else None
        if not user_dir or not os.path.isdir(user_dir):
            return {"available": False, "reason": "The game's folder was not found."}
        if copies["workshop"]:
            return {"available": False, "reason": "A Steam Workshop copy is subscribed. Two copies would both load.", "target": target}
        if not self.bundled:
            return {"available": False, "reason": "This app has no mod to install.", "target": target}
        if copies["local"]:
            have, ship = _info_version(copies["local"]), _info_version(self.bundled)
            if have and ship and vtuple(have) and vtuple(ship) and _cmp(vtuple(have), vtuple(ship)) >= 0:
                return {"available": False, "reason": "The newest version is already installed.", "target": target}
        return {"available": True, "target": target}

    def compute(self):
        live, meta = self.live(), self.meta() or {}
        copies = find_copies(self.user_dir, self.env)
        have_copy = bool(copies["local"] or copies["workshop"])
        entries, have_json = mods_json_entries(self.user_dir)
        dlc = (live or {}).get("dlcIds")
        if dlc is None:
            dlc = meta.get("dlcActive")
        enabled = enabled_in_game(entries, dlc if isinstance(dlc, list) else None)
        mod_v = self._mod_version(live, meta, copies)
        req = (live or {}).get("requiresCore") or meta.get("modRequiresCore")
        compat = {"core": self.core_version, "coreSupportsMod": dict(SUPPORTS_MOD), "mod": mod_v,
                  "modRequiresCore": req if isinstance(req, dict) else None}
        ran = bool(live) or bool(meta.get("exportFiles"))
        out = {"copies": (["local"] if copies["local"] else []) + (["workshop"] if copies["workshop"] else [])}
        install = self._install_info(copies)
        rows = []
        for f in self.folders:
            own = _read_json(sources.live_path(f)) or {}
            d = own.get("dlcIds")
            rows.append(folder_state(f, d if isinstance(d, list) else (dlc if isinstance(dlc, list) else None),
                                     self.env, active=(f == self.user_dir)))
        if rows:
            summ, both = versions_summary(rows)
            out.update(versions=rows, versionsSummary=summ, updateBoth=both)
        targets = [self._install_info(find_copies(f, self.env), f) for f in self.folders]
        install["targets"] = [t["target"] for t in targets if t["available"]]
        if len(self.folders) > 1 and install["targets"] and not install["available"]:
            install.pop("reason", None)
            install.update(available=True, target=install["targets"][0])
        install["blocked"] = [{"path": f, "reason": t.get("reason", "")} for f, t in zip(self.folders, targets) if not t["available"]]

        def done(state, summary, steps, problem=None):
            c = dict(compat)
            if problem:
                c["problem"] = problem
            out.update(state=state, summary=summary, steps=steps, install=install, compat=c)
            return out

        if not have_copy and not ran:
            steps = []
            if install["available"]:
                steps.append("Tap \"Install the game mod\" below.")
            steps.append("Or subscribe to ONI Companion Link on the Steam Workshop.")
            steps.append("Open the game's Mods menu, enable ONI Companion Link, and restart the game.")
            return done("missing", "The game mod is not installed.", steps)
        fresh = self.fresh(live)
        if not fresh and (enabled is False or (enabled is None and not ran)):
            return done("disabled", "The game mod is installed but switched off.",
                        ["Open the game's Mods menu.", "Switch ONI Companion Link on.", "Restart the game."])
        bad = None
        if mod_v and in_range(mod_v, SUPPORTS_MOD) is False:
            bad = "mod_too_old" if _cmp(vtuple(mod_v), vtuple(SUPPORTS_MOD["min"])) < 0 else "mod_too_new"
        elif req and in_range(self.core_version, req) is False:
            bad = "app_too_old" if _cmp(vtuple(self.core_version), vtuple(req.get("min"))) < 0 else "app_too_new"
        if bad:
            steps = {"mod_too_old": ["Update the game mod to version %s or newer." % SUPPORTS_MOD["min"]],
                     "mod_too_new": ["Update this app, the game mod is newer than it supports."],
                     "app_too_old": ["Update this app, the game mod needs a newer one."],
                     "app_too_new": ["Update the game mod, this app is newer than it supports."]}[bad]
            if bad == "mod_too_old" and install["available"]:
                steps = ["Tap \"Install the game mod\" below to update it."]
            if bad in ("mod_too_old", "app_too_new") and not install["available"]:
                steps.append("Restart the game afterwards.")
            return done("version_mismatch", "The game mod and this app do not fit together.", steps, bad)
        if not fresh:
            steps = ["Start Oxygen Not Included and load a colony."]
            log = player_log(self.user_dir)
            steps.append("If the game is already running and this stays, open %s and look for lines with %s."
                         % (log or "the game's Player.log", MOD_ID))
            return done("no_live", "The game is not sending data.", steps)
        return done("ok", "The game mod is working.", [])

    # ---- install
    def install(self):
        """Copies the bundled mod into <user>/mods/Local/OniCompanionLink. Returns the folder. Raises ValueError with the
        reason (plain language) when it must not. The caller has asked the user first."""
        copies = find_copies(self.user_dir, self.env)
        info = self._install_info(copies)
        if not info["available"]:
            raise ValueError(info.get("reason") or "Not possible.")
        target = info["target"]
        os.makedirs(target, exist_ok=True)
        for name in BUNDLED_FILES:                       # a fixed list: nothing else is ever copied
            src, dst = os.path.join(self.bundled, name), os.path.join(target, name)
            tmp = dst + ".tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        return target

    def install_all(self):
        """Copies the bundled mod into EVERY detected ONI user folder, except where a Workshop copy is (it already covers
        that version) or the newest version is there. Returns {"installed": [folders], "skipped": [{path, reason}]}.
        Raises ValueError with the reason when no folder can be written."""
        done, skipped = [], []
        for f in self.folders:
            info = self._install_info(find_copies(f, self.env), f)
            if not info["available"]:
                skipped.append({"path": f, "reason": info.get("reason") or "Not possible."})
                continue
            target = info["target"]
            os.makedirs(target, exist_ok=True)
            for name in BUNDLED_FILES:
                dst = os.path.join(target, name)
                tmp = dst + ".tmp"
                shutil.copyfile(os.path.join(self.bundled, name), tmp)
                os.replace(tmp, dst)
            done.append(target)
        if not done:
            reasons = []
            for s_ in skipped:
                if s_["reason"] not in reasons:
                    reasons.append(s_["reason"])
            raise ValueError(" ".join(reasons) or "Not possible.")
        return {"installed": done, "skipped": skipped}
