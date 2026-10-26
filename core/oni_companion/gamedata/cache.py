"""On-disk cache of the merged dataset, keyed by (build, DLC sets, mod export hashes, source files)."""
import hashlib
import json
import os

CACHE_VERSION = 6
KEEP = 2


def _stat_sig(path):
    try:
        st = os.stat(path)
        return [path, st.st_size, st.st_mtime_ns]
    except OSError:
        return [path, -1, -1]


def _tree_sig(root, suffix):
    sig = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.endswith(suffix):
                p = os.path.join(dirpath, fn)
                st = os.stat(p)
                sig.append([os.path.relpath(p, root), st.st_size, st.st_mtime_ns])
    return sig


def make_key(assets_dir, steam_build, installed_dlcs, export_sha1s):
    parts = {
        "v": CACHE_VERSION,
        "steamBuild": steam_build,
        "dlc": sorted(installed_dlcs),
        "exports": sorted(export_sha1s),
        "pot": _stat_sig(os.path.join(assets_dir, "strings", "strings_template.pot")),
        "codex": _tree_sig(os.path.join(assets_dir, "codex"), ".yaml"),
        "elements": _tree_sig(os.path.join(assets_dir, "elements"), ".yaml"),
    }
    blob = json.dumps(parts, sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:20]


def _path(cache_dir, key):
    return os.path.join(cache_dir, "gamedata-%s.json" % key)


def load(cache_dir, key):
    try:
        with open(_path(cache_dir, key), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("key") != key or d.get("cacheVersion") != CACHE_VERSION:
        return None
    return d


def save(cache_dir, key, payload):
    """Atomic write (tmp + rename); prunes older cache files."""
    os.makedirs(cache_dir, exist_ok=True)
    payload = dict(payload, key=key, cacheVersion=CACHE_VERSION)
    final = _path(cache_dir, key)
    tmp = final + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, final)
    olds = sorted((n for n in os.listdir(cache_dir) if n.startswith("gamedata-") and n.endswith(".json")),
                  key=lambda n: os.path.getmtime(os.path.join(cache_dir, n)), reverse=True)
    for n in olds[KEEP:]:
        try:
            os.remove(os.path.join(cache_dir, n))
        except OSError:
            pass
    return final
