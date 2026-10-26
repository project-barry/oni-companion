"""Power budget: add up the watts of the buildings picked.

  uses   = sum(power.usesW)
  makes  = sum(power.generatesW)
  net    = uses - makes     (negative = spare power)

Up to six slots; the same building may be picked twice.

Hand-worked in tests/test_tools.py:
  Synth Widget Maker 120 W + Synth Lamp 10 W = 130 W used
  test generator 200 W made -> net 130 - 200 = -70 W (spare power)
"""

from . import common as c

SLOTS = 6


def watts(building):
    p = building.get("power") or {}
    return float(p.get("usesW", 0) or 0), float(p.get("generatesW", 0) or 0)


def _fields(data):
    powered = [b for b in (data.get("buildings") or [])
               if (b.get("power") or {}).get("usesW") or (b.get("power") or {}).get("generatesW")]
    if not powered:
        raise c.DataProblem("No buildings are loaded yet.")
    options = [("", "None")] + sorted(((b["id"], b.get("name", b["id"])) for b in powered),
                                      key=lambda o: o[1])
    return [c.choice_field("building%d" % i, "Building %d" % i, options, default="")
            for i in range(1, SLOTS + 1)]


def _run(p, data):
    blds = c.index_by_id(data, "buildings")
    picked = [p["building%d" % i] for i in range(1, SLOTS + 1) if p["building%d" % i]]
    if not picked:
        return [c.notice("info", "Pick buildings above to add up their power.")]
    uses_total = 0.0
    makes_total = 0.0
    table_rows = []
    for bid in picked:
        b = blds[bid]
        uses, makes = watts(b)
        uses_total += uses
        makes_total += makes
        table_rows.append([{"text": b.get("name", bid), "ref": {"kind": "building", "id": bid}},
                           c.round_num(uses, 1), c.round_num(makes, 1)])
    net = uses_total - makes_total
    rows = [
        c.stat("Uses", c.round_num(uses_total, 1), unit="W"),
        c.stat("Makes", c.round_num(makes_total, 1), unit="W"),
        c.stat("Net draw", c.round_num(net, 1), unit="W",
               hint="Negative means spare power" if net <= 0 else "Needs more generation",
               tone="good" if net <= 0 else "warn"),
    ]
    return [
        c.stats_block(rows, title="Total"),
        {"type": "table", "title": "Buildings", "columns": ["Building", "Uses W", "Makes W"],
         "rows": table_rows},
    ]


TOOL = c.Tool(
    "power-budget", "Power budget", "Add up building watts",
    _fields, _run,
)
