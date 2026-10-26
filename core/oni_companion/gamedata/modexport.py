"""Read the ONI Companion Link mod's export files (contracts/mod-export.schema.json)."""
import hashlib
import json
import os

LIST_KEYS = {  # export key -> kind
    "buildings": "building", "elements": "element", "critters": "critter", "plants": "plant",
    "geysers": "geyser", "foods": "food", "medicines": "medicine", "recipes": "recipe",
    "techs": "tech", "traits": "trait", "skills": "skill", "rooms": "room",
}


def load_export(path):
    """Returns (export_dict, sha1) or raises ValueError for a file we cannot use."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as e:
        raise ValueError("not JSON: %s" % e)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("unsupported schema %r" % (data.get("schema") if isinstance(data, dict) else None))
    if not isinstance(data.get("dlcIds"), list) or not isinstance(data.get("build"), int):
        raise ValueError("missing build/dlcIds")
    return data, hashlib.sha1(raw).hexdigest()


def load_exports(paths):
    """Returns (exports, errors). Each export: {path, name, sha1, data}. Keeps the best file per DLC set
    (highest build, then newest generatedAt), so an old build's file never shadows a newer one."""
    best = {}
    errors = []
    for p in paths:
        try:
            data, sha = load_export(p)
        except (OSError, ValueError) as e:
            errors.append({"file": os.path.basename(p), "error": str(e)})
            continue
        key = tuple(sorted(data["dlcIds"]))
        rank = (data["build"], str(data.get("generatedAt", "")))
        cur = best.get(key)
        if cur is None or rank > cur[0]:
            best[key] = (rank, {"path": p, "name": os.path.basename(p), "sha1": sha, "data": data})
    return [v[1] for v in best.values()], errors
