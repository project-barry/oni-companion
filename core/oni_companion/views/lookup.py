"""Lookup: one loaded dataset plus everything the views need to name and link things."""
import os
import re

from ..gamedata import KIND_LABELS, pot
from ..index import Index, KIND_ORDER

SINGULAR = {
    "element": "Element", "building": "Building", "critter": "Critter", "plant": "Plant",
    "geyser": "Geyser", "food": "Food", "medicine": "Medicine", "recipe": "Recipe",
    "tech": "Research", "trait": "Trait", "skill": "Skill", "room": "Room", "codex": "Codex entry",
}
# Kinds an Amount.element id may name (recipe items are foods, medicines, buildings and so on).
ITEM_KINDS = ("element", "food", "medicine", "building", "plant", "critter")

_ID_WORDS = re.compile(r"[_\s]+")


def pretty_dlc(dlc_id):
    base = re.sub(r"_ID$", "", dlc_id)
    return _ID_WORDS.sub(" ", base).title()


def _load_strings(assets_dir):
    try:
        return pot.parse_pot(os.path.join(assets_dir, "strings", "strings_template.pot"))
    except (OSError, ValueError):
        return {}


def codex_label(strings):
    """The game's own word for its encyclopedia: STRINGS.UI.CODEX.TITLE (the game draws it in capitals; shown
    here as a title). Falls back to Database, the word the game uses for that screen."""
    t = pot.strip_markup(strings.get("STRINGS.UI.CODEX.TITLE", "")).strip()
    return t.title() if t else "Database"


def dlc_names_from_pot(assets_dir, ids, strings=None):
    """STRINGS.UI.<X>.NAME is the game's own name for DLC id <X>_ID. Missing -> prettified id."""
    out = {}
    if strings is None:
        strings = _load_strings(assets_dir) if assets_dir else {}
    for d in ids:
        key = "STRINGS.UI.%s.NAME" % re.sub(r"_ID$", "", d)
        name = pot.strip_markup(strings.get(key, ""))
        out[d] = name or pretty_dlc(d)
    return out


class Lookup:
    def __init__(self, dataset, assets_dir=None):
        self.ds = dataset
        self.index = Index(dataset)
        self.kinds = dataset.kinds
        self.meta = dataset.meta
        ids = set(dataset.meta.get("dlcInstalled") or [])
        for entries in self.kinds.values():
            for e in entries.values():
                ids.update(e.get("dlc") or [])
                ids.update(e.get("dlcAny") or [])
        strings = _load_strings(assets_dir) if assets_dir else {}
        self._dlc_names = dlc_names_from_pot(assets_dir, ids, strings)
        for d, n in (dataset.meta.get("dlcNames") or {}).items():       # the mod's names come from the running game
            if isinstance(n, str) and n.strip():
                self._dlc_names[d] = pot.strip_markup(n).strip()
        self.codex_label = codex_label(strings)
        self._strings = strings
        self.research_types = {rt["id"]: rt.get("name") or rt["id"] for rt in self.meta.get("researchTypes") or []}
        self.as_of = self.meta.get("builtAt")
        self._rev = None

    # ---- names
    def dlc_name(self, dlc_id):
        return self._dlc_names.get(dlc_id) or pretty_dlc(dlc_id)

    def logic_texts(self, building_id):
        """The game's own automation port texts of a building, from its strings: [(name, green, red)], in the
        game's key order. Only for buildings that name them as STRINGS.BUILDINGS.PREFABS.<ID>.<KEY>, <KEY>_ACTIVE
        and <KEY>_INACTIVE; empty otherwise."""
        pre = "STRINGS.BUILDINGS.PREFABS.%s." % str(building_id).upper()
        out = []
        for k, v in self._strings.items():
            if not k.startswith(pre) or not k[len(pre):].startswith("LOGIC"):
                continue
            base = k[len(pre):]
            if base.endswith("_ACTIVE") or base.endswith("_INACTIVE"):
                continue
            g, r = self._strings.get(k + "_ACTIVE"), self._strings.get(k + "_INACTIVE")
            if g or r:
                out.append(tuple(pot.strip_markup(x).strip() if x else None for x in (v, g, r)))
        return out

    def dlc_badge(self, e):
        d = e.get("dlc") or []
        return ", ".join(self.dlc_name(x) for x in d) if d else None

    def get(self, kind, ident):
        return self.index.get(kind, ident)

    def ref(self, kind, ident):
        """A Ref that resolves, or None. Ids match case-insensitively; the real id is returned."""
        if not isinstance(ident, str) or not ident:
            return None
        e = self.index.get(kind, ident)
        return {"kind": kind, "id": e["id"]} if e else None

    def ref_any(self, ident, kinds=ITEM_KINDS):
        for k in kinds:
            r = self.ref(k, ident)
            if r:
                return r
        return None

    def name(self, kind, ident):
        e = self.index.get(kind, ident)
        return (e.get("name") or e["id"]) if e else str(ident)

    def name_any(self, ident, kinds=ITEM_KINDS):
        r = self.ref_any(ident, kinds)
        return self.name(r["kind"], r["id"]) if r else str(ident)

    # ---- reverse links (built once per dataset)
    def reverse(self):
        if self._rev is None:
            rev = {"unlocked_by": {}, "required_by": {}, "recipes_at": {}, "hatches_from": {}, "morphs_from": {}}
            for t in self.kinds.get("tech", {}).values():
                for u in t.get("unlocks") or []:
                    if isinstance(u, dict) and u.get("kind") and u.get("id"):
                        rev["unlocked_by"].setdefault((u["kind"], str(u["id"]).upper()), []).append(t["id"])
                for r in t.get("requires") or []:
                    rev["required_by"].setdefault(str(r).upper(), []).append(t["id"])
            for e in self.kinds.get("building", {}).values():
                if e.get("tech"):
                    lst = rev["unlocked_by"].setdefault(("building", e["id"].upper()), [])
                    if e["tech"] not in lst:
                        lst.append(e["tech"])
            for r in self.kinds.get("recipe", {}).values():
                if r.get("fabricator"):
                    rev["recipes_at"].setdefault(str(r["fabricator"]).upper(), []).append(r["id"])
            for c in self.kinds.get("critter", {}).values():
                egg = (c.get("egg") or {}).get("id")
                if egg:
                    rev["hatches_from"].setdefault(str(egg).upper(), []).append(c["id"])
                for m in c.get("morphs") or []:
                    rev["morphs_from"].setdefault(str(m).upper(), []).append(c["id"])
            self._rev = rev
        return self._rev

    def item_relations(self, which, kind, ident):
        """produced_by / used_by for any kind whose id can appear as an Amount (items, not only elements)."""
        if kind == "element":
            return (self.index.produced_by if which == "produced" else self.index.used_by)(kind, ident)
        e = self.index.get(kind, ident)
        if e is None or kind not in ("food", "medicine", "building", "plant", "critter"):
            return []
        idx = self.index
        if idx._graph is None:
            idx._build_graph()
        table_ = idx._graph[0 if which == "produced" else 1]
        out = []
        for rk, rid, role, amt in table_.get(("element", e["id"].upper()), []):
            src = self.kinds[rk][rid]
            row = {"kind": rk, "id": rid, "name": src.get("name") or rid, "dlc": list(src.get("dlc") or []), "role": role}
            if amt is not None:
                row["kg"] = amt
            out.append(row)
        out.sort(key=lambda r: (KIND_ORDER.index(r["kind"]) if r["kind"] in KIND_ORDER else 20, r["name"].lower()))
        return out

    def kind_label(self, kind):
        return KIND_LABELS.get(kind, kind.title())
