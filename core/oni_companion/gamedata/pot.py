"""Reader for the game's gettext template (strings_template.pot) and markup helpers.

The .pot holds the English text as `msgid`, keyed by `msgctxt` (= the STRINGS.* key).
"""
import re

_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_ESC_RE = re.compile(r'\\(u[0-9a-fA-F]{4}|.)')


def _unescape(s):
    def rep(m):
        g = m.group(1)
        if g[0] == "u" and len(g) == 5:
            return chr(int(g[1:], 16))
        return _ESC.get(g, g)
    return _ESC_RE.sub(rep, s)


def _quoted(line):
    line = line.strip()
    if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
        return _unescape(line[1:-1])
    return ""


def parse_pot_text(text):
    """Return {key: english_text}. Entries with an empty msgid are skipped."""
    out = {}
    ctx = None
    msgid = None
    field = None  # which field continuation lines extend
    parts = []

    def flush():
        nonlocal ctx, msgid, parts, field
        if ctx is not None and msgid is not None:
            val = "".join(msgid)
            if val:
                out[ctx] = val
        ctx = None
        msgid = None
        field = None

    ctx_parts = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgctxt"):
            flush()
            ctx_parts = [_quoted(line[7:])]
            field = "ctx"
            ctx = None
        elif line.startswith("msgid"):
            if field == "ctx":
                ctx = "".join(ctx_parts)
            msgid = [_quoted(line[5:])]
            field = "id"
        elif line.startswith("msgstr"):
            field = "str"
        elif line.startswith('"'):
            if field == "ctx":
                ctx_parts.append(_quoted(line))
            elif field == "id" and msgid is not None:
                msgid.append(_quoted(line))
    flush()
    return out


def parse_pot(path):
    with open(path, encoding="utf-8") as f:
        return parse_pot_text(f.read())


_LINK_RE = re.compile(r'<link="([^"]*)">', re.I)
_TAG_RE = re.compile(r'</?[a-zA-Z][^<>]*>')


def markup_links(text):
    """Link ids in game markup: <link="OXYGEN">Oxygen</link> -> ["OXYGEN"]."""
    return _LINK_RE.findall(text or "")


def strip_markup(text):
    """Plain text: drops <link>, <b>, <i>, <style>, <color>, <sprite> and similar tags."""
    if not text:
        return text or ""
    text = text.replace("<br>", "\n").replace("<br/>", "\n")
    return _TAG_RE.sub("", text).strip()
