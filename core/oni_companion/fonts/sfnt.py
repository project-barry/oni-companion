"""Check that bytes are a usable sfnt font (TrueType or OpenType) and read its names. Stdlib only."""
import struct

MAGICS = {b"\x00\x01\x00\x00": "truetype", b"OTTO": "opentype-cff", b"true": "truetype"}
REQUIRED = ("cmap", "head", "hhea", "hmtx", "maxp", "name")
HEAD_MAGIC = 0x5F0F3CF5
MAX_TABLES = 64


class FontError(Exception):
    pass


def _tables(data):
    if len(data) < 12 or bytes(data[:4]) not in MAGICS:
        raise FontError("not an sfnt font")
    n = struct.unpack_from(">H", data, 4)[0]
    if not 1 <= n <= MAX_TABLES or len(data) < 12 + 16 * n:
        raise FontError("bad table directory")
    out = {}
    for i in range(n):
        tag, _sum, off, ln = struct.unpack_from(">4sIII", data, 12 + 16 * i)
        if off + ln > len(data) or off < 12 + 16 * n:
            raise FontError("table %r runs outside the file" % tag)
        out[tag.decode("latin-1")] = (off, ln)
    return out


def _decode(raw, platform):
    try:
        return raw.decode("utf-16-be" if platform in (0, 3) else "mac-roman").strip()
    except UnicodeDecodeError:
        return ""


def read_names(data, off, ln):
    """{nameID: text} from the name table, English preferred (Windows 0x409, else any Windows, else Mac)."""
    if ln < 6:
        raise FontError("name table too short")
    fmt, count, str_off = struct.unpack_from(">HHH", data, off)
    if fmt > 1 or 6 + 12 * count > ln or str_off > ln:
        raise FontError("bad name table")
    best = {}
    for i in range(count):
        pid, eid, lid, nid, length, o = struct.unpack_from(">HHHHHH", data, off + 6 + 12 * i)
        if str_off + o + length > ln:
            continue
        raw = bytes(data[off + str_off + o: off + str_off + o + length])
        text = _decode(raw, pid)
        if not text:
            continue
        rank = 0 if (pid == 3 and lid == 0x409) else 1 if pid == 3 else 2 if pid == 1 and lid == 0 else 3
        if nid not in best or rank < best[nid][0]:
            best[nid] = (rank, text)
    return {k: v[1] for k, v in best.items()}


def check(data):
    """Validate and describe. Returns {format, family, style, fullName, license, tables}. Raises FontError."""
    data = bytes(data)
    fmt = MAGICS.get(data[:4])
    tables = _tables(data)
    missing = [t for t in REQUIRED if t not in tables]
    if missing:
        raise FontError("missing tables: " + ", ".join(missing))
    if "glyf" not in tables and "CFF " not in tables and "CFF2" not in tables:
        raise FontError("no outlines")
    if fmt == "opentype-cff" and "CFF " not in tables and "CFF2" not in tables:
        raise FontError("OTTO font without CFF outlines")
    off, ln = tables["head"]
    if ln < 54 or struct.unpack_from(">I", data, off + 12)[0] != HEAD_MAGIC:
        raise FontError("bad head table")
    units = struct.unpack_from(">H", data, off + 18)[0]
    if not 16 <= units <= 16384:
        raise FontError("bad unitsPerEm")
    off, ln = tables["maxp"]
    if ln < 6 or struct.unpack_from(">H", data, off + 4)[0] < 1:
        raise FontError("no glyphs")
    names = read_names(data, *tables["name"])
    family = names.get(16) or names.get(1)
    style = names.get(17) or names.get(2) or ""
    if not family:
        raise FontError("no family name")
    return {"format": fmt, "family": family, "style": style, "fullName": names.get(4, ""),
            "license": names.get(13, ""), "tables": sorted(tables)}


def style_key(style):
    s = style.lower().replace(" ", "")
    bold, ital = "bold" in s, "italic" in s or "oblique" in s
    return "boldItalic" if bold and ital else "bold" if bold else "italic" if ital else "regular"
