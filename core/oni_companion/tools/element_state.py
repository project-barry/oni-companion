"""What an element turns into at a temperature, and the phases it passes through.

The game decides this per element: an element above its `highTransition` temperature
becomes that transition's target, below its `lowTransition` temperature it becomes
that target, and the new element is checked the same way (the game's Element
lowTemp / highTemp and their target elements). The tool does exactly that, so the
answer is what the game does to a lump of the chosen element held at that temperature.

The ladder is not one straight line: Sand heated becomes Molten Glass, but Molten
Glass cooled becomes Glass, not Sand. The phases list therefore shows, for each
element on the heating and cooling path from the chosen one, that element's own
temperature range.

A temperature equal to a threshold takes the new element (heating past a
threshold changes it; the game uses >= for high and < for low).

Hand-worked in tests/test_tools.py:
  Water: Ice below -0.65 C (272.5 K), Steam from 99.35 C (372.5 K).
  Sand (highTemp 1986 K = 1712.85 C) at 2000 C -> Molten Glass.
  Molten Glass (lowTemp 1400 K = 1126.85 C) at 20 C -> Glass.
"""

from . import common as c

MAX_STEPS = 32
ABSOLUTE_ZERO_C = -273.15
MAX_TEMP_C = 1000000.0


def _transition(el, key):
    """(tempC, target id) of a transition, or None."""
    tr = el.get(key)
    if not tr:
        return None
    t = tr.get("tempC")
    tgt = tr.get("target")
    if t is None or not tgt:
        return None
    return float(t), tgt


def _chain(els, start, key):
    out = []
    seen = {start}
    cur = start
    while True:
        tr = _transition(els[cur], key)
        if tr is None or tr[1] not in els or tr[1] in seen:
            break
        out.append(tr[1])
        seen.add(tr[1])
        cur = tr[1]
    return out


def ladder(els, start):
    """Element ids from coldest to hottest along the cooling and heating paths of `start`."""
    down = _chain(els, start, "lowTransition")
    up = _chain(els, start, "highTransition")
    return list(reversed(down)) + [start] + up


def settle(els, start, temp_c):
    """Element ids the game goes through at a constant temperature; the last one stays."""
    path = [start]
    cur = start
    for _ in range(MAX_STEPS):
        el = els[cur]
        hi = _transition(el, "highTransition")
        lo = _transition(el, "lowTransition")
        if hi and hi[1] in els and temp_c >= hi[0]:
            cur = hi[1]
        elif lo and lo[1] in els and temp_c < lo[0]:
            cur = lo[1]
        else:
            return path
        if cur in path:
            raise c.DataProblem("This element keeps changing back and forth at that temperature.")
        path.append(cur)
    raise c.DataProblem("This element keeps changing at that temperature.")


def _range_text(lo, hi):
    if lo is None and hi is None:
        return "All temperatures"
    if lo is None:
        return "Below %s C" % c.fmt_num(hi)
    if hi is None:
        return "Above %s C" % c.fmt_num(lo)
    return "%s to %s C" % (c.fmt_num(lo), c.fmt_num(hi))


def phase_states(els, order):
    """PhaseState dicts (blocks.schema.json), coldest first, each with the element's own range."""
    states = []
    for i, eid in enumerate(order):
        lo = _transition(els[eid], "lowTransition")
        hi = _transition(els[eid], "highTransition")
        lo = lo[0] if lo else None
        hi = hi[0] if hi else None
        state = {
            "state": els[eid]["state"],
            "label": els[eid]["name"],
            "range": _range_text(lo, hi),
            "loC": lo,
            "hiC": hi,
        }
        if i < len(order) - 1:
            state["target"] = c.element_ref(order[i + 1])
        states.append(state)
    return states


def _fields(data):
    if not data.get("elements"):
        raise c.DataProblem("No elements are loaded yet.")
    return [
        c.element_field("element", "Element"),
        c.number_field("temperature", "Temperature", 20, units=c.TEMP_UNITS, default_unit="C"),
    ]


def _run(p, data):
    els = c.index_by_id(data, "elements")
    start = p["element"]
    t_c = c.temp_to_c(p["temperature"])
    if t_c < ABSOLUTE_ZERO_C:
        raise c.ToolError("temperature", "nothing can be colder than absolute zero (-273.15 C, 0 K)", label="Temperature")
    if t_c > MAX_TEMP_C:
        raise c.ToolError("temperature", "use %s C or less" % c.fmt_num(MAX_TEMP_C), label="Temperature")
    path = settle(els, start, t_c)
    here = path[-1]
    rows = [
        c.stat("Element", els[here]["name"], ref=c.element_ref(here)),
        c.stat("State", els[here]["state"]),
        c.stat("Temperature", c.round_num(t_c, 1), unit="C"),
    ]
    if here != start:
        rows.insert(0, c.stat("Starts as", els[start]["name"], ref=c.element_ref(start)))
    return [
        c.stats_block(rows, title="At this temperature"),
        {"type": "phases", "title": "Phases of %s" % els[start]["name"],
         "states": phase_states(els, ladder(els, start))},
    ]


TOOL = c.Tool(
    "element-state", "Element state", "What an element becomes at a temperature",
    _fields, _run,
)
