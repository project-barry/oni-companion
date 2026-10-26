"""TextMeshPro markup -> Spans (contracts/blocks.schema.json, Span). Stdlib only; the one place that knows markup.

The mod sends the game's tooltip exactly as the game builds it (<b>, <i>, <color>, <link>, <sprite>, <size>,
line breaks, ...). This turns it into plain/bold spans; front ends render spans and never see markup.

Rules:
- Tags this parser knows: b, i (kept as plain: the contract has no italic), color (-> theme color token by hue),
  link (-> a span `action` when the caller resolves it), sprite (-> an icon span when the caller has the art),
  br (line break), noparse. Every other tag-like thing (size, style, align, nobr, u, s, sup, mark, font, ...) is
  dropped without touching its text. A "<" that does not open a tag stays text.
- Colors become theme tokens, never hex: red-ish negative, orange/yellow warning, green positive, blue/cyan/violet
  info, grey textDim, white/default no color at all (the front end's text color), near-black no color (it would be
  unreadable on a dark theme).
- Input is capped (length, nesting, span count); control characters are removed. Bad input never raises.
"""
import colorsys
import re

MAX_CHARS = 20000
MAX_DEPTH = 64
MAX_SPANS = 400

_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)((?:[=\s][^<>]*)?)>")
_CTRL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
_QUOTED = re.compile(r"""^\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]*))""")
_NAME_ATTR = re.compile(r"""\bname\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]*))""", re.I)

_NAMED = {
    "red": "#ff0000", "green": "#00ff00", "blue": "#0000ff", "white": "#ffffff", "black": "#000000",
    "yellow": "#ffff00", "orange": "#ffa500", "purple": "#800080", "grey": "#808080", "gray": "#808080",
    "cyan": "#00ffff", "magenta": "#ff00ff", "pink": "#ffc0cb", "brown": "#8b4513", "lime": "#32cd32",
}
_SPRITE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")


def color_token(value):
    """'#RRGGBB' / '#RGB' / '#RRGGBBAA' / a color name -> a ColorToken, or None (= the default text color)."""
    if not isinstance(value, str):
        return None
    v = value.strip().strip("\"'").lower()
    v = _NAMED.get(v, v)
    if not v.startswith("#"):
        return None
    h = v[1:]
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-f]+", h):
        return None
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    if len(h) == 8 and int(h[6:8], 16) < 0x40:
        return None                           # (almost) invisible: do not tint
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    hue *= 360.0
    if light < 0.18:
        return None
    if sat < 0.18 or light > 0.92:
        return None if light > 0.80 else "textDim"
    if hue < 15 or hue >= 335:
        return "negative"
    if hue < 70:
        return "warning"
    if hue < 170:
        return "positive"
    return "info"


def _tag_value(rest):
    m = _QUOTED.match(rest or "")
    if not m:
        return None
    return next((g for g in m.groups() if g is not None), None)


def _clean(text):
    return _CTRL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def plain_text(markup, limit=200):
    """The text without any markup, newlines as spaces: for list titles and screen titles."""
    if not isinstance(markup, str):
        return ""
    out = []
    for kind, val, _st in _tokens(markup[:MAX_CHARS]):
        if kind == "text":
            out.append(val)
    return re.sub(r"\s+", " ", "".join(out)).strip()[:limit]


def _tokens(markup):
    """Yields ('text', str, state) / ('sprite', name, state). state = (bold, color, link) at that point."""
    bold = 0
    colors, links = [], []
    noparse = False
    pos = 0
    n = len(markup)
    while pos < n:
        m = _TAG.search(markup, pos)
        chunk_end = m.start() if m else n
        if chunk_end > pos:
            yield "text", _clean(markup[pos:chunk_end]), (bold > 0, colors[-1] if colors else None, links[-1] if links else None)
        if not m:
            break
        pos = m.end()
        closing, name, rest = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if noparse:
            if closing and name == "noparse":
                noparse = False
            else:
                yield "text", _clean(m.group(0)), (bold > 0, colors[-1] if colors else None, links[-1] if links else None)
            continue
        if name == "noparse" and not closing:
            noparse = True
        elif name == "b":
            bold = max(0, bold - 1) if closing else min(bold + 1, MAX_DEPTH)
        elif name == "color":
            if closing:
                if colors:
                    colors.pop()
            elif len(colors) < MAX_DEPTH:
                colors.append(color_token(_tag_value(rest)))
        elif name == "link":
            if closing:
                if links:
                    links.pop()
            elif len(links) < MAX_DEPTH:
                links.append(_tag_value(rest))
        elif name == "br" and not closing:
            yield "text", "\n", (bold > 0, colors[-1] if colors else None, links[-1] if links else None)
        elif name == "sprite" and not closing:
            nm = _NAME_ATTR.search(rest or "")
            sprite = next((g for g in nm.groups() if g), None) if nm else _tag_value(rest)
            if sprite and not sprite.isdigit() and _SPRITE_RE.match(sprite):   # sprite=<index> needs the game's atlas: dropped
                yield "sprite", sprite, (bold > 0, colors[-1] if colors else None, links[-1] if links else None)
        # anything else (i, size, style, align, nobr, u, s, sup, sub, mark, font, line-height, ...): dropped


def to_spans(markup, link_action=None, sprite_icon=None):
    """markup -> [Span]. link_action(link_id) -> an Action dict or None (the span gets it); sprite_icon(name) -> an
    ArtPath or None (None drops the sprite). Never raises; returns [] for empty input."""
    if not isinstance(markup, str) or not markup.strip():
        return []
    spans = []

    def push(span):
        if len(spans) >= MAX_SPANS:
            return
        prev = spans[-1] if spans else None
        if (prev and "icon" not in span and "icon" not in prev and prev["type"] == span["type"]
                and prev.get("color") == span.get("color") and prev.get("action") == span.get("action")):
            prev["text"] += span["text"]
        else:
            spans.append(span)

    for kind, val, (bold, color, link) in _tokens(markup[:MAX_CHARS]):
        if kind == "text":
            if not val:
                continue
            span = {"type": "bold" if bold else "plain", "text": val}
            act = None
            if link is not None and link_action:
                try:
                    act = link_action(link)
                except Exception:
                    act = None
            if color:
                span["color"] = color
            elif act and not val.isspace():
                span["color"] = "info"          # a tappable line must look tappable
            if act and not val.isspace():
                span["action"] = act
            push(span)
        else:
            icon = None
            if sprite_icon:
                try:
                    icon = sprite_icon(val)
                except Exception:
                    icon = None
            if icon:
                if len(spans) < MAX_SPANS:
                    spans.append({"type": "plain", "text": "", "icon": icon})
    while spans and spans[-1].get("text") and "icon" not in spans[-1]:
        t = spans[-1]["text"].rstrip("\n ")
        if t:
            spans[-1]["text"] = t
            break
        spans.pop()
    return spans
