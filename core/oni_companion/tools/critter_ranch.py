"""Food and output per cycle for a number of one critter.

A diet is one way the critter eats: it eats ONE of the listed foods (the game's
Diet.Info consumedTags are alternatives), about the same kilograms of whichever it
finds, and makes one output. So per critter and cycle:

  food   = kg of one item in the diet      (not the sum of the alternatives)
  output = kg of the produced item
  kcal   = calories one cycle costs it

The stats use the first diet; the table lists every diet. Food is at full ration.

Hand-worked in tests/test_tools.py:
  Hatch: 140 kg of rock a cycle (HatchConfig KG_ORE_EATEN_PER_CYCLE), 700 kcal
  (700000 cal / 1000), coal out = 140 * 0.5 = 70 kg.  10 Hatches -> 1400 kg, 700 kg, 7000 kcal.
  Pacu: 7.5 kg Algae a cycle, 100 kcal, 5 kg Polluted Dirt out (7.5 * 2/3).
        10 Pacu -> 75 kg, 50 kg, 1000 kcal.
"""

from . import common as c
from .names import words


def totals(diet):
    """(food kg, output kg, kcal) for one critter and one cycle on this diet."""
    eaten = [float(a["kg"]) for a in diet.get("consumes", [])]
    food = max(eaten) if eaten else 0.0
    out = sum(float(a["kg"]) for a in diet.get("produces", []))
    return food, out, diet.get("caloriesPerCycle")


def _names(data):
    """id -> display name for everything a diet can name: elements, foods, plants."""
    names = dict(data.get("names") or {})
    for key in ("elements", "foods", "plants"):
        for x in data.get(key) or []:
            if x.get("name") and x["id"] not in names:
                names[x["id"]] = x["name"]
    return names


def _amount_label(a, names):
    k = a.get("element") or a.get("tag") or "?"
    return names.get(k) or words(k)


def _join(items, limit=6):
    if len(items) > limit:
        return ", ".join(items[:limit]) + " and %d more" % (len(items) - limit)
    return ", ".join(items)


def _fields(data):
    critters = data.get("critters") or []
    if not critters:
        raise c.DataProblem("No critters are loaded yet.")
    options = sorted(((x["id"], x.get("name", x["id"])) for x in critters), key=lambda o: o[1])
    return [
        c.choice_field("critter", "Critter", options),
        c.number_field("count", "Number of critters", 10, min=0, max=1000, step=1),
    ]


def _run(p, data):
    crit = c.index_by_id(data, "critters")[p["critter"]]
    diets = crit.get("diets") or []
    if not diets:
        raise c.DataProblem("%s has no diet in the game." % crit.get("name", crit["id"]))
    n = p["count"].value
    names = _names(data)
    food, out, kcal = totals(diets[0])
    rows = [
        c.stat("Food eaten per cycle", c.round_num(food * n, 1), unit="kg"),
        c.stat("Output per cycle", c.round_num(out * n, 1), unit="kg"),
    ]
    if kcal is not None:
        rows.append(c.stat("Calories per cycle", c.round_num(kcal * n, 0), unit="kcal"))
    table_rows = []
    for i, d in enumerate(diets):
        eats = d.get("consumes", [])
        kg = max((float(a["kg"]) for a in eats), default=0.0)
        eat_text = ("%s kg of %s" % (c.fmt_num(kg), _join([_amount_label(a, names) for a in eats]))
                    if eats else "Nothing")
        makes = ", ".join("%s kg %s" % (c.fmt_num(a["kg"]), _amount_label(a, names))
                          for a in d.get("produces", [])) or "Nothing"
        table_rows.append([str(i + 1), eat_text, makes])
    return [
        c.stats_block(rows, title="Per cycle, %s critters" % c.fmt_num(n)),
        {"type": "table", "title": "Diets (each is one option; a critter eats one of the foods listed)",
         "columns": ["Diet", "Eats per critter", "Makes per critter"], "rows": table_rows},
        c.notice("info", "Food is at full ration. Real use depends on hunger and the food on hand."),
    ]


TOOL = c.Tool(
    "critter-ranch", "Critter ranch", "Food and output per cycle for a critter",
    _fields, _run,
)
