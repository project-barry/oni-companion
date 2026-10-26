"""Text-only entries built from the .pot when no mod export covers them.

These have names and descriptions but no numbers, and no DLC info
(`dlcKnown: false`). Ids are the upper-cased game ids (the .pot keys); the
index matches ids case-insensitively, and a mod export replaces them.
"""
import re

from .pot import strip_markup

_LINK = re.compile(r'<link="([A-Za-z0-9_]+)"')

# kind -> (key prefix, {field: key suffix})
SPECS = {
    "building": ("STRINGS.BUILDINGS.PREFABS.", {"name": "NAME", "desc": "DESC", "effect": "EFFECT"}),
    "food": ("STRINGS.ITEMS.FOOD.", {"name": "NAME", "desc": "DESC"}),
    "medicine": ("STRINGS.ITEMS.PILLS.", {"name": "NAME", "desc": "DESC"}),
    "trait": ("STRINGS.DUPLICANTS.TRAITS.", {"name": "NAME", "desc": "DESC"}),
    "skill": ("STRINGS.DUPLICANTS.ROLES.", {"name": "NAME", "desc": "DESCRIPTION"}),
    "tech": ("STRINGS.RESEARCH.TECHS.", {"name": "NAME", "desc": "DESC"}),
    "room": ("STRINGS.ROOMS.TYPES.", {"name": "NAME", "desc": "TOOLTIP", "effect": "EFFECT"}),
    "geyser": ("STRINGS.CREATURES.SPECIES.GEYSER.", {"name": "NAME", "desc": "DESC"}),
}


def build_fallback(strings):
    """Returns {kind: [entry,...]}."""
    out = {}
    for kind, (prefix, fields) in SPECS.items():
        name_suffix = "." + fields["name"]
        rows = []
        plen = len(prefix)
        for key in strings:
            if not key.startswith(prefix) or not key.endswith(name_suffix):
                continue
            ident = raw_ident = key[plen:-len(name_suffix)]
            if not ident or "." in ident:
                continue
            if kind == "skill":
                # The skill's real id sits in the name's link: <link="MINING1">Hard Digging</link>
                m = _LINK.search(strings[key])
                if m:
                    ident = m.group(1)
            e = {"id": ident, "name": strip_markup(strings[key]) or ident,
                 "dlc": [], "dlcKnown": False, "source": "pot"}
            for field, suffix in fields.items():
                if field == "name":
                    continue
                v = strings.get(prefix + raw_ident + "." + suffix)
                if v:
                    e[field] = strip_markup(v)
            rows.append(e)
        rows.sort(key=lambda r: r["id"])
        out[kind] = rows
    return out
