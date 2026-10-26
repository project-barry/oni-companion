"""Merge: mod export > YAML/.pot fallback; union over DLC sets with dlc tags."""
import re

from .modexport import LIST_KEYS
from .pot import strip_markup

TEXT_FIELDS = ("name", "desc", "effect")
SKIP_FALLBACK_FIELDS = {"source", "dlcKnown", "id", "dlc"}


def _clean(entry):
    for f in TEXT_FIELDS:
        v = entry.get(f)
        if isinstance(v, str) and "<" in v:
            entry[f] = strip_markup(v)
    return entry


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _match_export(have, by_upper, by_norm_id, by_name, fb):
    """Id of the export entry that is the same thing as this .pot entry, or None.
    Tries the upper-cased id, the id without punctuation (BIONICS_A1 = BionicsA1), then the name
    (only when exactly one export entry of the kind has it)."""
    real = by_upper.get(fb["id"].upper()) or by_norm_id.get(_norm(fb["id"]))
    if real is None:
        cands = by_name.get(_norm(fb.get("name")))
        if cands and len(cands) == 1:
            real = cands[0]
    return real


# Kinds whose export is the complete list of what the loaded game has. A building the export lacks is not
# in the game being played (another DLC's, a developer tool, cut content), so the .pot text must not add it.
# The other kinds' exports are partial (traits, skills, foods, techs the export does not carry are real),
# so the .pot still fills those.
EXPORT_COMPLETE = {"building"}
_DEPRECATED_RE = re.compile(r"\[DEPRECATED\]|CANNOT BE BUILT", re.I)


def _is_deprecated(e):
    return any(_DEPRECATED_RE.search(e.get(f) or "") for f in TEXT_FIELDS)


def _union(a, b):
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def merge_exports(exports):
    """Union of all export files. Widest DLC set wins field values; every entry's dlc tags are unioned.
    Returns {kind: {id: entry}}."""
    kinds = {k: {} for k in LIST_KEYS.values()}
    for ex in sorted(exports, key=lambda e: (-len(e["data"]["dlcIds"]), e["name"])):
        data = ex["data"]
        for key, kind in LIST_KEYS.items():
            for raw in data.get(key) or []:
                if not isinstance(raw, dict) or not raw.get("id"):
                    continue
                e = _clean(dict(raw))
                e.setdefault("dlc", [])
                cur = kinds[kind].get(e["id"])
                if cur is None:
                    e["source"] = "mod-export"
                    e["exportSets"] = [sorted(data["dlcIds"])]
                    kinds[kind][e["id"]] = e
                else:
                    cur["dlc"] = _union(cur["dlc"], e["dlc"])
                    cur["exportSets"].append(sorted(data["dlcIds"]))
    return kinds


def merge(fallback, exports, codex_entries=None):
    """fallback: {kind: [entry]} (yaml/pot). Returns {kind: {id: entry}}."""
    kinds = merge_exports(exports)
    for kind, rows in fallback.items():
        have = kinds.setdefault(kind, {})
        by_upper = {i.upper(): i for i in have}
        by_norm_id = {_norm(i): i for i in have}
        by_name = {}
        for i, e in have.items():
            by_name.setdefault(_norm(e.get("name")), []).append(i)
        complete = kind in EXPORT_COMPLETE and any(e.get("source") == "mod-export" for e in have.values())
        for fb in rows:
            real = _match_export(have, by_upper, by_norm_id, by_name, fb)
            if real is None:
                if complete:
                    continue
                have[fb["id"]] = fb
                by_upper[fb["id"].upper()] = fb["id"]
                by_norm_id.setdefault(_norm(fb["id"]), fb["id"])
                continue
            tgt = have[real]
            for k, v in fb.items():
                if k not in SKIP_FALLBACK_FIELDS and k not in tgt:
                    tgt[k] = v
    for entries in kinds.values():
        for e in entries.values():
            if _is_deprecated(e):
                e["hidden"] = True
    cx = kinds.setdefault("codex", {})
    for e in codex_entries or []:
        cx[e["id"]] = e
    return kinds
