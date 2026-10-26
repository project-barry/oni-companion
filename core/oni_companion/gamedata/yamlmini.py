"""Tiny YAML subset reader for the game's codex and element files.

Supports: block mappings, block sequences (also at the key's own indent),
"- key: value" items, quoted/plain scalars, ints/floats/bools/null, comments,
and `!Tag` markers (a mapping with a tag comes back as `Tagged` with `.tag`).
Empty flow `[]` / `{}` only. Not supported (not used in these files): other flow style, anchors, block scalars.
"""
import re


class YamlError(ValueError):
    pass


class Tagged(dict):
    tag = ""


_INT = re.compile(r'^[-+]?\d+$')
_FLOAT = re.compile(r'^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$')


def _strip_comment(s):
    """Remove a trailing comment that is outside quotes."""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == "\\" and quote == '"':
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or s[i - 1] in " :-["):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def _scalar(s):
    s = s.strip()
    if s == "":
        return None
    if s[0] == '"':
        end = s.rfind('"')
        body = s[1:end] if end > 0 else s[1:]
        return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)
    if s[0] == "'":
        end = s.rfind("'")
        return (s[1:end] if end > 0 else s[1:]).replace("''", "'")
    if s == "[]":
        return []
    if s == "{}":
        return {}
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


_KEY_RE = re.compile(r'^("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s"\'#:\-?][^:]*?|-[^\s:][^:]*?)\s*:(?:\s+(.*))?$')


def _split_key(content):
    m = _KEY_RE.match(content)
    if not m:
        return None
    return _scalar(m.group(1)) if m.group(1)[0] in "\"'" else m.group(1).strip(), m.group(2)


def _tokenize(text):
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError("tab indentation")
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        if stripped.strip() in ("---", "..."):
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.lstrip(" ")))
    return lines


class _Parser:
    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    def parse(self):
        if not self.lines:
            return None
        return self.block(self.lines[0][0])

    def block(self, indent, tag=None):
        content = self.lines[self.i][1]
        if content == "-" or content.startswith("- "):
            return self.sequence(indent, tag)
        if _split_key(content):
            return self.mapping(indent, tag)
        self.i += 1
        return _scalar(content)

    def _tagged(self, value, tag):
        if tag is None:
            return value
        t = Tagged(value if isinstance(value, dict) else {})
        t.tag = tag
        return t

    def _child(self, parent_indent, tag=None, allow_same_seq=False):
        """Parse the value on following lines (a nested block), or None."""
        if self.i < len(self.lines):
            ind, content = self.lines[self.i]
            if ind > parent_indent:
                return self.block(ind, tag)
            if allow_same_seq and ind == parent_indent and (content == "-" or content.startswith("- ")):
                return self.block(ind)
        return self._tagged({}, tag) if tag else None

    def mapping(self, indent, tag=None):
        result = {}
        while self.i < len(self.lines):
            ind, content = self.lines[self.i]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("bad indent at: " + content)
            kv = _split_key(content)
            if not kv:
                raise YamlError("expected key: " + content)
            key, rest = kv
            self.i += 1
            rest = (rest or "").strip()
            vtag = None
            if rest.startswith("!"):
                vtag, _, rest = rest.partition(" ")
                rest = rest.strip()
            if rest == "":
                result[key] = self._child(indent, vtag, allow_same_seq=True)
            else:
                result[key] = _scalar(rest)
        return self._tagged(result, tag) if tag else result

    def sequence(self, indent, tag=None):
        items = []
        while self.i < len(self.lines):
            ind, content = self.lines[self.i]
            if ind != indent or not (content == "-" or content.startswith("- ")):
                break
            rest = content[1:]
            rest = rest.lstrip(" ")
            if rest == "":
                self.i += 1
                items.append(self._child(indent))
                continue
            if rest.startswith("!"):
                itag, _, rest2 = rest.partition(" ")
                rest2 = rest2.strip()
                if rest2 == "":
                    self.i += 1
                    items.append(self._child(indent, itag))
                    continue
                rest = rest2
            if _split_key(rest):
                # "- key: value": the mapping starts at the key's own column.
                col = indent + (len(content) - len(rest))
                self.lines[self.i] = (col, rest)
                items.append(self.mapping(col))
            else:
                self.i += 1
                items.append(_scalar(rest))
        return items


def loads(text):
    return _Parser(_tokenize(text)).parse()


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return loads(f.read())
