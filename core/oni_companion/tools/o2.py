"""How many duplicants one oxygen source feeds.

  duplicants = supply [kg/s] / oxygen per duplicant [kg/s]   (whole duplicants: floor)

The per-duplicant rate is the game's DUPLICANTSTATS.STANDARD.BaseStats.OXYGEN_USED_PER_SECOND,
exported as `constants.dupeO2KgPerS`. The carbon dioxide each duplicant makes is
`constants.toolNumbers.dupeCo2KgPerS` (OXYGEN_USED_PER_SECOND * OXYGEN_TO_CO2_CONVERSION).

FALLBACK (marked): data written by an older version of the game-side add-on has no
`dupeO2KgPerS`. For those only, 0.1 kg/s is used. It is the game's own value
(decompiled Assembly-CSharp, ChangeList 744825: `OXYGEN_USED_PER_SECOND = 0.1f`) and is
dropped as soon as the number is in the data. It is not used for anything else.

Hand-worked in tests/test_tools.py (game value 0.1 kg/s = 100 g/s):
  300 g/s = 0.3 kg/s;  0.3 / 0.1 = 3 duplicants
  250 g/s = 0.25 kg/s; 0.25 / 0.1 = 2.5 -> 2 whole
"""

import math

from . import common as c

CONSTANT = "dupeO2KgPerS"
FALLBACK_DUPE_O2_KG_PER_S = 0.1     # game value, used only when the data has no CONSTANT (see above)
MAX_SUPPLY_KG_S = 1000.0            # sanity cap, far above any real build
CYCLE_S = 600.0                     # one game cycle in seconds (unit definition)


def duplicants_fed(supply_kg_s, per_dupe_kg_s):
    exact = supply_kg_s / per_dupe_kg_s
    return exact, math.floor(round(exact, 9))


def _fields(data):
    return [c.number_field("supply", "Oxygen supply", 100, units=c.RATE_UNITS,
                           default_unit="g/s", min=0)]


def _run(p, data):
    consts = data.get("constants") or {}
    per_dupe = consts.get(CONSTANT)
    if per_dupe is None:
        per_dupe = FALLBACK_DUPE_O2_KG_PER_S
    if per_dupe <= 0:
        raise c.DataProblem("The game's oxygen use per duplicant is not above zero, so this cannot be worked out.")
    s = p["supply"]
    supply_kg_s = s.value * c.RATE_TO_KG_S[s.unit]
    if supply_kg_s > MAX_SUPPLY_KG_S:
        raise c.ToolError("supply", "use %s kg/s or less" % c.fmt_num(MAX_SUPPLY_KG_S), label="Oxygen supply")
    exact, whole = duplicants_fed(supply_kg_s, per_dupe)
    rows = [
        c.stat("Duplicants fed", whole, tone="good", hint="Whole duplicants"),
        c.stat("Exact", c.round_num(exact, 2)),
        c.stat("Oxygen per duplicant", c.round_num(per_dupe * 1000, 1), unit="g/s",
               hint="%s kg per cycle" % c.fmt_num(per_dupe * CYCLE_S)),
    ]
    co2 = (consts.get("toolNumbers") or {}).get("dupeCo2KgPerS")
    if co2 is not None and co2 >= 0:
        rows.append(c.stat("Carbon dioxide per duplicant", c.round_num(co2 * 1000, 1), unit="g/s"))
    return [c.stats_block(rows, title="Result")]


TOOL = c.Tool(
    "o2-duplicants", "Oxygen for duplicants", "Duplicants one oxygen source feeds",
    _fields, _run,
)
