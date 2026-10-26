"""Display names for the tags a critter diet can name (seeds, prey, plant parts, droppings).

The game names them in its own strings; the export carries the raw tag id. The
views hand the result to the tools as `data["names"]` (id -> name). Anything the
game does not name gets the id split into words, never a made-up name.
"""

import os
import re

from ..gamedata import pot

_KINDS = ("element", "food", "medicine", "building", "plant", "critter")


def _strings(assets_dir):
    try:
        return pot.parse_pot(os.path.join(assets_dir, "strings", "strings_template.pot"))
    except (OSError, ValueError, TypeError):
        return {}


def words(tag):
    """'PlantFiber' -> 'Plant Fiber'."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(tag)).replace("_", " ")


def _candidates(tag):
    u = tag.upper()
    out = ["STRINGS.MISC.TAGS.%s" % u, "STRINGS.ITEMS.FOOD.%s.NAME" % u,
           "STRINGS.ITEMS.INDUSTRIAL_PRODUCTS.%s.NAME" % u, "STRINGS.CREATURES.SPECIES.%s.NAME" % u]
    if tag.endswith("Seed"):
        out.append("STRINGS.CREATURES.SPECIES.SEEDS.%s.NAME" % u[:-4])
    return out


def tag_names(lk, assets_dir):
    """id -> display name for every tag used by a critter diet in this dataset."""
    tags = set()
    for crit in lk.kinds.get("critter", {}).values():
        for diet in crit.get("diets") or []:
            for a in (diet.get("consumes") or []) + (diet.get("produces") or []):
                t = a.get("element") or a.get("tag")
                if t:
                    tags.add(t)
    strings = _strings(assets_dir) if assets_dir else {}
    out = {}
    for t in sorted(tags):
        name = None
        for kind in _KINDS:
            e = lk.get(kind, t)
            if e and e.get("name"):
                name = e["name"]
                break
        if name is None and t.endswith("Baby"):          # a baby prey is named like its adult
            e = lk.get("critter", t[:-4])
            name = e["name"] if e else None
        if name is None:
            for key in _candidates(t):
                if strings.get(key):
                    name = pot.strip_markup(strings[key]).strip()
                    break
        out[t] = name or words(t)
    return out
