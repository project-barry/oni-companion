"""Elements from the game's elements/*.yaml (fallback when no mod export)."""
import os

from . import yamlmini
from .pot import strip_markup

K0 = 273.15
STATES = {"solid": "solid", "liquid": "liquid", "gas": "gas", "vacuum": "vacuum"}
FILES = ("gas.yaml", "liquid.yaml", "solid.yaml", "special.yaml")


def _c(kelvin):
    return round(float(kelvin) - K0, 4)


def _transition(row, prefix, temp_key):
    target = row.get(prefix + "Target")
    if not target or not isinstance(target, str) or row.get(temp_key) is None:
        return None
    t = {"tempC": _c(row[temp_key]), "target": target}
    secondary = row.get(prefix + "OreId")
    conv = row.get(prefix + "OreMassConversion")
    if secondary and isinstance(secondary, str) and conv:
        t["secondary"] = secondary
        # Assumption (UNVERIFIED in game): the conversion fraction goes to the secondary ore.
        t["targetKgRatio"] = round(1.0 - float(conv), 6)
    return t


def load_elements(assets_dir, strings):
    """assets_dir = .../StreamingAssets. Returns a list of Element dicts (schema shape)."""
    out = []
    for fname in FILES:
        path = os.path.join(assets_dir, "elements", fname)
        if not os.path.isfile(path):
            continue
        doc = yamlmini.load(path) or {}
        for row in doc.get("elements") or []:
            eid = row.get("elementId")
            if not eid:
                continue
            loc = row.get("localizationID") or ""
            base = loc[:-5] if loc.endswith(".NAME") else "STRINGS.ELEMENTS.%s" % eid.upper()
            name = strip_markup(strings.get(base + ".NAME", "")) or eid
            dlc = (row.get("dlcId") or "").strip()
            el = {
                "id": eid,
                "name": name,
                "dlc": [dlc] if dlc else [],
                "state": STATES.get(str(row.get("state", "")).lower(), "solid"),
                "tags": [t for t in (row.get("tags") or []) if isinstance(t, str)],
                "source": "yaml",
            }
            desc = strip_markup(strings.get(base + ".DESC", ""))
            if desc:
                el["desc"] = desc
            for src, dst in (("specificHeatCapacity", "specificHeat"),
                             ("thermalConductivity", "thermalConductivity"),
                             ("molarMass", "molarMass"), ("maxMass", "maxMass"),
                             ("hardness", "hardness")):
                if isinstance(row.get(src), (int, float)):
                    el[dst] = row[src]
            hi = _transition(row, "highTempTransition", "highTemp")
            lo = _transition(row, "lowTempTransition", "lowTemp")
            if hi:
                el["highTransition"] = hi
            if lo:
                el["lowTransition"] = lo
            if row.get("isDisabled"):
                el["disabled"] = True
            out.append(el)
    return out
