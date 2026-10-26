"""Block builders (contracts/blocks.schema.json). Layout-free: meaning only, no sizes or colors.

Every builder returns a plain dict and drops keys whose value is None, so the
output validates against the frozen schema without further cleaning.
"""
import math

SCHEMA = 1


def num(x, places=2):
    """Display number: finite, rounded, int when whole."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return 0
    r = round(float(x), places)
    return int(r) if r == int(r) else r


def _clean(d):
    return {k: v for k, v in d.items() if v is not None}


def ref(kind, ident):
    return {"kind": kind, "id": ident}


# ---- spans
def plain(text):
    return {"type": "plain", "text": text}


def bold(text):
    return {"type": "bold", "text": text}


def ref_span(r, text):
    return {"type": "ref", "ref": r, "text": text}


def link_span(url, text):
    return {"type": "link", "url": url, "text": text}


# ---- blocks
def heading(text, level=None, art_key=None):
    return _clean({"type": "heading", "text": text, "level": level, "_art": art_key})


def image(art, caption=None, alt=None, size=None):
    """v1.1 image block. `art` is a finished art URL path, or an (artKind, id) key that the art step fills
    (the block is dropped when there is no art)."""
    if isinstance(art, (tuple, list)):
        return _clean({"type": "image", "_art": tuple(art), "caption": caption, "alt": alt, "size": size})
    return _clean({"type": "image", "art": art, "caption": caption, "alt": alt, "size": size})


def text(*spans):
    return {"type": "text", "spans": [plain(s) if isinstance(s, str) else s for s in spans]}


def stat(label, value, unit=None, hint=None, ref=None, tone=None):
    return _clean({"label": label, "value": value, "unit": unit, "hint": hint, "ref": ref, "tone": tone})


def stats(rows, title=None):
    return _clean({"type": "stats", "title": title, "rows": list(rows)})


def chip(label, style=None, ref=None):
    return _clean({"label": label, "style": style, "ref": ref})


def chips(items):
    return {"type": "chips", "chips": list(items)}


def item(title, ref=None, subtitle=None, badge=None, tone=None, art_key=None):
    return _clean({"ref": ref, "title": title, "subtitle": subtitle, "badge": badge, "tone": tone, "_art": art_key})


def list_block(items, title=None, empty=None, variant=None):
    return _clean({"type": "list", "title": title, "items": list(items), "empty": empty, "variant": variant})


def meter(label, value, max_, unit=None, tone=None):
    return _clean({"label": label, "value": num(value), "max": num(max(max_, 0)), "unit": unit, "tone": tone})


def card(title, subtitle=None, badge=None, ref=None, tone=None, stats=None, meters=None,
         art=None, badges=None, actions=None, art_key=None):
    return _clean({"title": title, "subtitle": subtitle, "badge": badge, "ref": ref, "tone": tone,
                   "stats": stats or None, "meters": meters or None, "art": art,
                   "badges": badges or None, "actions": actions or None, "_art": art_key})


def badge_level(level, label):
    return {"level": level, "label": label}


def action(id_, label, args=None):
    return _clean({"id": id_, "label": label, "args": args})



def form(tool, fields, submit_label, title=None, endpoint=None):
    return _clean({"type": "form", "tool": tool, "title": title, "submitLabel": submit_label,
                   "endpoint": endpoint, "fields": list(fields)})


def grid(cards, title=None):
    return _clean({"type": "grid", "title": title, "cards": list(cards)})


def port(label, element=None, rate=None, unit=None, conduit=None, note=None):
    return _clean({"label": label, "element": element,
                   "rate": None if rate is None else max(num(rate, 4), 0),
                   "unit": unit, "conduit": conduit, "note": note})


def ports(inputs, outputs, title=None):
    return _clean({"type": "ports", "title": title, "inputs": list(inputs), "outputs": list(outputs)})


def phase_state(state, label, range_=None, lo=None, hi=None, target=None):
    return _clean({"state": state, "label": label, "range": range_, "loC": lo, "hiC": hi, "target": target})


def phases(states, title=None):
    return _clean({"type": "phases", "title": title, "states": list(states)})


def progress(label, value, max_, unit=None, tone=None):
    return _clean({"type": "progress", "label": label, "value": num(value), "max": num(max(max_, 0)),
                   "unit": unit, "tone": tone})


def cell(text_, ref=None, tone=None):
    if ref is None and tone is None:
        return text_
    return _clean({"text": str(text_), "ref": ref, "tone": tone})


def table(columns, rows, title=None):
    return _clean({"type": "table", "title": title, "columns": list(columns), "rows": [list(r) for r in rows]})


def notice(level, text_, title=None):
    return _clean({"type": "notice", "level": level, "title": title, "text": text_})


def link(label, url):
    return {"type": "link", "label": label, "url": url}


def divider():
    return {"type": "divider"}


def group(title, blocks, collapsed=None):
    return _clean({"type": "group", "title": title, "collapsed": collapsed, "blocks": list(blocks)})


def screen(title, blocks, subtitle=None, source=None, as_of=None, back=None, refresh_on=None,
           on_open=None, world_switcher=None):
    nav = {"back": back} if back is not None else None
    return _clean({"schema": SCHEMA, "title": title or "ONI Companion", "subtitle": subtitle,
                   "source": source, "asOf": as_of, "nav": nav,
                   "refreshOn": list(refresh_on) if refresh_on else None,
                   "onOpen": list(on_open) if on_open else None,
                   "worldSwitcher": world_switcher, "blocks": list(blocks)})


# ---- walkers (used by the tests and by the provider's self-check)
def walk_blocks(blocks):
    for b in blocks:
        yield b
        if b.get("type") == "group":
            yield from walk_blocks(b["blocks"])


def walk_refs(node):
    """Every Ref dict inside a Screen (or any JSON): dicts with exactly kind and id."""
    if isinstance(node, dict):
        if set(node) == {"kind", "id"} and isinstance(node["kind"], str):
            yield node
        for v in node.values():
            yield from walk_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_refs(v)


def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v)
