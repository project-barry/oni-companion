"""Long-run average output of a geyser type.

The game's own number (GeyserConfigurator.GetAverageEmission, shown on a geyser as
"average output over its lifetime"):

  average [kg/s] = mass per cycle / 600 * share of its year it is active

  (emit rate while erupting = mass per cycle / 600 / eruption share of an iteration;
   eruption time per active stretch cancels out of the average)

A geyser's mass per cycle and active share are rolled between a minimum and a
maximum when the world is made. The tool shows the middle of each range and the
lowest and highest the game can roll. `rateKgPerS` in the data is already mass per
cycle / 600, so it is NOT multiplied by the eruption share again.

Hand-worked in tests/test_tools.py:
  chlorine_gas: 70..140 kg per cycle (mid 105), active 0.4..0.8 of the year (mid 0.6)
    -> 105 / 600 * 0.6 = 0.105 kg/s; lowest 70/600*0.4 = 0.0467; highest 140/600*0.8 = 0.1867
  steam: 1000..2000 kg per cycle, same year share
    -> 1500 / 600 * 0.6 = 1.5 kg/s
"""

from . import common as c

CYCLE_S = 600.0         # one game cycle in seconds (unit definition, same as the game's 600f)


def mid(rng):
    return (rng["min"] + rng["max"]) / 2.0


def average_kg_per_s(per_cycle_kg, active_share):
    """The game's GetAverageEmission for one geyser."""
    return per_cycle_kg / CYCLE_S * active_share


def _per_cycle(g):
    """Mass-per-cycle range in kg; derived from the per-second rate when only that is given."""
    if "massPerCycleKg" in g:
        return g["massPerCycleKg"]
    r = g["rateKgPerS"]
    return {"min": r["min"] * CYCLE_S, "max": r["max"] * CYCLE_S}


def _complete(g):
    return ("rateKgPerS" in g or "massPerCycleKg" in g) and "activeFractionOfYear" in g \
        and "eruptDurationFraction" in g


def _fields(data):
    geysers = [g for g in (data.get("geysers") or []) if _complete(g)]
    if not geysers:
        raise c.DataProblem("No geysers are loaded yet.")
    options = sorted(((g["id"], g.get("name", g["id"])) for g in geysers), key=lambda o: o[1])
    return [c.choice_field("geyser", "Geyser", options)]


def _run(p, data):
    g = c.index_by_id(data, "geysers")[p["geyser"]]
    if not _complete(g):
        raise c.DataProblem("%s has no output numbers in the game." % g.get("name", g["id"]))
    mass = _per_cycle(g)
    year = g["activeFractionOfYear"]
    erupt = g["eruptDurationFraction"]
    avg = average_kg_per_s(mid(mass), mid(year))
    low = average_kg_per_s(mass["min"], year["min"])
    high = average_kg_per_s(mass["max"], year["max"])
    rate_erupting = mid(mass) / CYCLE_S / mid(erupt)
    rows = [
        c.stat("Average output", c.round_num(avg, 3), unit="kg/s", tone="info",
               hint="Lowest %s, highest %s" % (c.fmt_num(round(low, 3)), c.fmt_num(round(high, 3)))),
        c.stat("Per cycle", c.round_num(avg * CYCLE_S, 0), unit="kg"),
        c.stat("While erupting", c.round_num(rate_erupting, 2), unit="kg/s",
               hint="Mass per cycle %s to %s kg" % (c.fmt_num(mass["min"]), c.fmt_num(mass["max"]))),
        c.stat("Active share of its year", c.round_num(mid(year) * 100, 1), unit="%",
               hint="%s to %s%%" % (c.fmt_num(year["min"] * 100), c.fmt_num(year["max"] * 100))),
    ]
    if g.get("element"):
        els = c.index_by_id(data, "elements")
        name = els[g["element"]]["name"] if g["element"] in els else g["element"]
        rows.append(c.stat("Element", name, ref=c.element_ref(g["element"])))
    return [
        c.stats_block(rows, title="Result"),
        c.notice("info", "Uses the middle of each range. Each geyser rolls its own numbers when the world is made."),
    ]


TOOL = c.Tool(
    "geyser-average", "Geyser average", "Average output of a geyser",
    _fields, _run,
)
