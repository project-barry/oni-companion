"""Display formatting. All Celsius, all short."""
from .blocks import num

CYCLE_S = 600


def c(x):
    return "%g C" % num(x, 2)


def c_range(lo, hi):
    if lo is None and hi is None:
        return None
    if lo is None:
        return "up to %s" % c(hi)
    if hi is None:
        return "%s and up" % c(lo)
    return "%g to %g C" % (num(lo, 2), num(hi, 2))


def minmax(d, scale=1.0, places=2):
    """{min,max} -> '1.2 to 3' or '2'."""
    if not isinstance(d, dict):
        return None
    lo, hi = d.get("min"), d.get("max")
    if lo is None and hi is None:
        return None
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    a, b = num(lo * scale, places), num(hi * scale, places)
    return "%g" % a if a == b else "%g to %g" % (a, b)


def seconds(s):
    if s is None:
        return "Never"
    if s >= CYCLE_S:
        return "%g cycles" % num(s / CYCLE_S, 2)
    return "%g s" % num(s, 1)


def percent(x, places=0):
    return "%g%%" % num(x * 100, places)


def paragraphs(text):
    """Split game text on blank lines; keeps list lines together."""
    out = []
    for p in (text or "").replace("\r", "").split("\n\n"):
        p = p.strip()
        if p:
            out.append(p)
    return out
