"""Game data: pot + codex + elements (fallback), mod export (numbers), merged and cached."""
import os
import time
from datetime import datetime, timezone

from .. import sources
from . import cache, codex, elements, fallback, merge, modexport, pot

__all__ = ["Dataset", "load_dataset"]

KIND_LABELS = {
    "element": "Elements", "building": "Buildings", "critter": "Critters", "plant": "Plants",
    "geyser": "Geysers", "food": "Foods", "medicine": "Medicines", "recipe": "Recipes",
    "tech": "Research", "trait": "Traits", "skill": "Skills", "room": "Rooms", "codex": "Codex",
}


class Dataset:
    """kinds: {kind: {id: entry}}; meta: facts for /status; timings in seconds."""

    def __init__(self, kinds, meta, key, from_cache, timings):
        self.kinds = kinds
        self.meta = meta
        self.key = key
        self.from_cache = from_cache
        self.timings = timings

    def counts(self):
        return {k: len(v) for k, v in self.kinds.items() if v}


def _union_by_id(exports, key):
    """v1.3 lists (overlays, tools, buildMenu): ids from every export file. The widest DLC set is read first, so
    the game's own order is kept; ids only another set has follow in their own order. A DLC's overlay or tool carries
    its `dlc` tags from the file that has it."""
    out, pos = [], {}
    for ex in sorted(exports, key=lambda e: (-len(e["data"]["dlcIds"]), e["name"])):
        for raw in ex["data"].get(key) or []:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                if raw["id"] not in pos:
                    pos[raw["id"]] = len(out)
                    out.append(dict(raw))
    return out


def _newest(exports):
    return max(exports, key=lambda e: (e["data"]["build"], str(e["data"].get("generatedAt", ""))), default=None)


def _build(cfg, exports, export_errors, installed, steam_build, manifest):
    assets = cfg.assets_dir
    if _has_assets(cfg):
        strings = pot.parse_pot(os.path.join(assets, "strings", "strings_template.pot"))
        els = elements.load_elements(assets, strings)
        cx, unresolved = codex.load_codex(assets, strings)
        fb = fallback.build_fallback(strings)
        fb["element"] = els
    else:
        # Mod export only (Android local mode, 4.2): the game's text files are in the emulator's private
        # container, so there is no .pot, no Codex text and no fallback. Names and numbers come from the export.
        strings, cx, unresolved, fb = {}, [], [], {}
    kinds = merge.merge(fb, exports, cx)
    exported = sorted({d for ex in exports for d in ex["data"]["dlcIds"]})
    builds = [ex["data"]["build"] for ex in exports]
    mod_versions = sorted({str(ex["data"].get("modVersion", "")) for ex in exports})
    meta = {
        "steamBuildId": steam_build,
        "build": max(builds) if builds else None,
        "dlcInstalled": installed,
        "dlcExported": exported,
        "dlcMissingExport": [d for d in installed if d not in exported],
        "exportFiles": sorted(ex["name"] for ex in exports),
        "exportErrors": export_errors,
        "modVersion": mod_versions[-1] if mod_versions else None,
        "constants": {k: v for ex in exports for k, v in (ex["data"].get("constants") or {}).items()},
        "researchTypes": [rt for ex in exports for rt in ex["data"].get("researchTypes") or []],
        "dlcNames": {k: v for ex in exports for k, v in (ex["data"].get("dlcNames") or {}).items() if isinstance(v, str)},
        "overlays": _union_by_id(exports, "overlays"),
        "padTools": _union_by_id(exports, "tools"),
        "buildMenu": _union_by_id(exports, "buildMenu"),
        "dlcActive": sorted((_newest(exports) or {"data": {"dlcIds": []}})["data"]["dlcIds"]) if exports else None,
        "modContract": max([ex["data"].get("contract") or 1 for ex in exports], default=None),
        "modRequiresCore": (_newest(exports) or {"data": {}})["data"].get("requiresCore"),
        "unresolvedStrings": unresolved,
        "stringCount": len(strings),
        "sourceCounts": {k: _source_counts(v) for k, v in kinds.items() if v},
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return kinds, meta


def _source_counts(entries):
    out = {}
    for e in entries.values():
        out[e.get("source", "?")] = out.get(e.get("source", "?"), 0) + 1
    return out


def _has_assets(cfg):
    return bool(cfg.game_dir) and os.path.isfile(os.path.join(cfg.assets_dir, "strings", "strings_template.pot"))


def load_dataset(cfg, use_cache=True):
    """Merged game data for the configured install. Raises FileNotFoundError when neither the game files nor a
    mod export are there. With a mod export and no game files the data is the export alone (names, numbers)."""
    t0 = time.perf_counter()
    assets = cfg.assets_dir
    if not _has_assets(cfg) and not (cfg.user_dir and sources.export_files(cfg.user_dir)):
        raise FileNotFoundError("ONI game files not found (looked in %r)" % (assets,))
    mf_path = sources.find_appmanifest(cfg.game_dir) if cfg.game_dir else None
    manifest = sources.read_appmanifest(mf_path) if mf_path else None
    steam_build = manifest["buildid"] if manifest else None
    installed = sources.installed_dlc_ids(assets) if assets else []
    files = sources.export_files(cfg.user_dir) if cfg.user_dir else []
    exports, export_errors = modexport.load_exports(files)
    key = cache.make_key(assets, steam_build, installed, [e["sha1"] for e in exports])
    t1 = time.perf_counter()
    if use_cache and cfg.data_dir:
        hit = cache.load(cfg.cache_dir, key)
        if hit:
            t2 = time.perf_counter()
            return Dataset(hit["kinds"], hit["meta"], key, True,
                           {"fingerprint": t1 - t0, "load": t2 - t1, "total": t2 - t0})
    kinds, meta = _build(cfg, exports, export_errors, installed, steam_build, manifest)
    t2 = time.perf_counter()
    if cfg.data_dir:
        try:
            cache.save(cfg.cache_dir, key, {"kinds": kinds, "meta": meta})
        except OSError:
            pass
    t3 = time.perf_counter()
    return Dataset(kinds, meta, key, False,
                   {"fingerprint": t1 - t0, "build": t2 - t1, "cacheWrite": t3 - t2, "total": t3 - t0})
