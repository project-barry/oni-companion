"""KSerialization reader for ONI saves (templates + world body).

Written from the file bytes of real saves (build 744825, save version 7.38).
The container layout was cross-checked against the structure documented by
mithro/python-oni-save-parser (Apache-2.0) and RoboPhred/oni-save-parser (MIT);
no code was copied from either project.

Stdlib only. Every reader fails with KSerialError (never IndexError or
struct.error), so callers can fall back cleanly on a version they do not know.
"""

import struct
import zlib

from .header import SaveFormatError, parse_header

# ---- type ids (low 6 bits of the type byte) -------------------------------
USER, SBYTE, BYTE, BOOL, INT16, UINT16, INT32, UINT32, INT64, UINT64, \
    SINGLE, DOUBLE, STRING, ENUM, VEC2I, VEC2, VEC3, ARRAY, PAIR, DICT, \
    LIST, HASHSET, QUEUE, COLOUR = range(24)

FLAG_VALUE_TYPE = 0x40
FLAG_GENERIC = 0x80

_FIXED = {
    SBYTE: "<b", BYTE: "<B", BOOL: "<?", INT16: "<h", UINT16: "<H",
    INT32: "<i", UINT32: "<I", INT64: "<q", UINT64: "<Q",
    SINGLE: "<f", DOUBLE: "<d", ENUM: "<i",
    VEC2I: "<2i", VEC2: "<2f", VEC3: "<3f", COLOUR: "<4B",
}

MAX_TEMPLATES = 100000

def _hashable(v):
    """Dictionary keys can be structs (Tag, HashedString): reduce them to plain values."""
    if isinstance(v, dict):
        vals = tuple(_hashable(x) for x in v.values())
        return vals[0] if len(vals) == 1 else vals
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    return v


class KSerialError(SaveFormatError):
    """Bytes do not match what this reader knows."""


class TypeInfo:
    __slots__ = ("kind", "flags", "name", "args")

    def __init__(self, kind, flags, name=None, args=()):
        self.kind, self.flags, self.name, self.args = kind, flags, name, args

    def __repr__(self):
        return "TypeInfo(%d,%r,%r)" % (self.kind, self.name, self.args)


class Template:
    __slots__ = ("name", "fields", "props")

    def __init__(self, name, fields, props):
        self.name, self.fields, self.props = name, fields, props


class Reader:
    """Bounds-checked little-endian reader over bytes."""

    def __init__(self, data, pos=0, end=None):
        self.d = data
        self.p = pos
        self.end = len(data) if end is None else end

    def need(self, n):
        if n < 0 or self.p + n > self.end:
            raise KSerialError("read of %d bytes past end at %d" % (n, self.p))

    def take(self, n):
        self.need(n)
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        self.need(size)
        v = struct.unpack_from(fmt, self.d, self.p)
        self.p += size
        return v

    def i32(self):
        return self.unpack("<i")[0]

    def u8(self):
        return self.unpack("<B")[0]

    def string(self):
        n = self.i32()
        if n == -1:
            return None
        if n < 0:
            raise KSerialError("negative string length at %d" % self.p)
        raw = self.take(n)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", "replace")

    def remaining(self):
        return self.end - self.p


# ---- templates --------------------------------------------------------------

def read_type_info(r):
    t = r.u8()
    kind = t & 0x3F
    if kind > COLOUR:
        raise KSerialError("unknown type id %d" % kind)
    name = None
    args = ()
    if kind in (USER, ENUM):
        name = r.string()
    if t & FLAG_GENERIC:
        n = r.u8()
        args = tuple(read_type_info(r) for _ in range(n))
    elif kind == ARRAY:
        args = (read_type_info(r),)
    return TypeInfo(kind, t & 0xC0, name, args)


def read_templates(r):
    """Read the template table. Returns {name: Template}."""
    n = r.i32()
    if n < 0 or n > MAX_TEMPLATES:
        raise KSerialError("implausible template count %d" % n)
    out = {}
    for _ in range(n):
        name = r.string()
        nf, npr = r.i32(), r.i32()
        if nf < 0 or npr < 0 or nf > 10000 or npr > 10000:
            raise KSerialError("implausible field count in %r" % name)
        fields = [(r.string(), read_type_info(r)) for _ in range(nf)]
        props = [(r.string(), read_type_info(r)) for _ in range(npr)]
        out[name] = Template(name, fields, props)
    return out


# ---- values -----------------------------------------------------------------

class Parser:
    def __init__(self, templates):
        self.t = templates

    def value(self, r, ti, element=False):
        k = ti.kind
        fmt = _FIXED.get(k)
        if fmt is not None:
            v = r.unpack(fmt)
            return v[0] if len(v) == 1 else v
        if k == STRING:
            return r.string()
        if k in (ARRAY, LIST, HASHSET, QUEUE):
            return self.collection(r, ti)
        if k == DICT:
            return self.dictionary(r, ti)
        if k == PAIR:
            a = self.value(r, ti.args[0], True)
            b = self.value(r, ti.args[1], True)
            return (a, b)
        if k == USER:
            return self.user(r, ti, element)
        raise KSerialError("cannot read type %d" % k)

    def collection(self, r, ti):
        nbytes, count = r.i32(), r.i32()
        if nbytes == 0 and count == -1:
            return None  # null array/list
        if nbytes < 0 or count < 0 or nbytes > r.remaining():
            raise KSerialError("bad collection header (%d bytes, %d items)" % (nbytes, count))
        end = r.p + nbytes
        sub = Reader(r.d, r.p, end)
        r.p = end  # the byte length is authoritative: later fields stay in sync
        item = ti.args[0]
        if item.kind in (BYTE, SBYTE):
            return bytes(sub.take(min(count, sub.remaining())))
        return [self.value(sub, item, True) for _ in range(count)]

    def dictionary(self, r, ti):
        # [byteLength][count] then all VALUES, then all KEYS (verified on real saves)
        nbytes, count = r.i32(), r.i32()
        if nbytes == 0 and count == -1:
            return None  # null dictionary
        if nbytes < 0 or count < 0 or nbytes > r.remaining():
            raise KSerialError("bad dictionary header")
        end = r.p + nbytes
        sub = Reader(r.d, r.p, end)
        r.p = end
        values = [self.value(sub, ti.args[1], True) for _ in range(count)]
        keys = [_hashable(self.value(sub, ti.args[0])) for _ in range(count)]
        return dict(zip(keys, values))

    def user(self, r, ti, element=False):
        tpl = self.t.get(ti.name)
        if tpl is None:
            raise KSerialError("no template for %r" % ti.name)
        if element:
            return self.template_fields(r, tpl)
        # a struct/class FIELD or dictionary KEY is [int32 byteLength][fields]
        # (-1 = null); collection elements and dictionary values have no prefix
        n = r.i32()
        if n == -1:
            return None
        if n < 0 or n > r.remaining():
            raise KSerialError("bad object length %d for %s" % (n, ti.name))
        sub = Reader(r.d, r.p, r.p + n)
        r.p += n
        return self.template_fields(sub, tpl)

    def template_fields(self, r, tpl, lenient=False):
        """Read fields then properties of `tpl`.

        lenient=True keeps the fields read before an unreadable one and records
        the failing field name under "__partial__" instead of raising.
        """
        out = {}
        for name, fti in tpl.fields + tpl.props:
            try:
                out[name] = self.value(r, fti)
            except KSerialError:
                if not lenient:
                    raise
                out["__partial__"] = name
                break
        return out

    def template_data(self, data, tpl, lenient=False):
        """Parse the data block of one behavior. Returns (fields, extra_bytes).

        extra_bytes is whatever follows the template fields (components with
        custom save code, e.g. MinionModifiers, put their own data there).
        With lenient=True a field that cannot be read ends parsing early
        (see template_fields) and extra_bytes is empty.
        """
        r = Reader(data)
        fields = self.template_fields(r, tpl, lenient)
        if "__partial__" in fields:
            return fields, b""
        return fields, bytes(data[r.p:])


# ---- body -------------------------------------------------------------------

class GameObject:
    __slots__ = ("prefab", "position", "rotation", "scale", "behaviors")

    def __init__(self, prefab, position, rotation, scale, behaviors):
        self.prefab = prefab
        self.position = position
        self.rotation = rotation
        self.scale = scale
        self.behaviors = behaviors  # list of (name, bytes)

    def behavior(self, name):
        for n, data in self.behaviors:
            if n == name:
                return data
        return None


class SaveBody:
    def __init__(self, templates, body, objects_start, version, groups, game_objects, tail_start):
        self.templates = templates
        self.body = body
        self.objects_start = objects_start
        self.version = version            # (major, minor) from the body
        self.groups = groups              # {prefab: (count, offset, length)}
        self.game_objects = game_objects  # {prefab: [GameObject]}
        self.tail_start = tail_start      # offset of the data after the game objects
        self.parser = Parser(templates)


def split_save(data):
    """Return (header, templates, body_bytes). Raises SaveFormatError."""
    header = parse_header(data)
    r = Reader(data, header.body_offset)
    templates = read_templates(r)
    rest = data[r.p:]
    if header.compressed:
        try:
            body = zlib.decompress(rest)
        except zlib.error as exc:
            raise KSerialError("body will not decompress: %s" % exc) from None
    else:
        body = bytes(rest)
    return header, templates, body


# ---- game objects -----------------------------------------------------------

def _read_instance(q, prefab):
    pos = q.unpack("<3f")
    rot = q.unpack("<4f")
    scale = q.unpack("<3f")
    q.u8()  # folder/flags byte, always 0 in samples
    n = q.i32()
    if n < 0 or n > 10000:
        raise KSerialError("implausible behavior count %d" % n)
    behaviors = []
    for _ in range(n):
        name = q.string()
        length = q.i32()
        if length < 0:
            raise KSerialError("negative behavior length")
        behaviors.append((name, bytes(q.take(length))))
    return GameObject(prefab, pos, rot, scale, behaviors)


def read_body(templates, body):
    """Locate and read the game-object section of a decompressed body.

    Finds the (major, minor) version ints followed by the group count that
    precede the object groups, then reads every group. Raises KSerialError
    when the layout is not the one this reader knows.
    """
    start = _find_objects_start(body)
    r = Reader(body, start)
    major, minor, ngroups = r.i32(), r.i32(), r.i32()
    groups = {}
    objects = {}
    for _ in range(ngroups):
        prefab = r.string()
        count, length = r.i32(), r.i32()
        if count < 0 or length < 0 or length > r.remaining():
            raise KSerialError("bad group header for %r" % prefab)
        q = Reader(body, r.p, r.p + length)
        objs = [_read_instance(q, prefab) for _ in range(count)]
        if q.remaining():
            raise KSerialError("group %r has %d unread bytes" % (prefab, q.remaining()))
        groups[prefab] = (count, r.p, length)
        objects.setdefault(prefab, []).extend(objs)
        r.p += length
    return SaveBody(templates, body, start, (major, minor), groups, objects, r.p)


def _find_objects_start(body):
    """Offset of the (major, minor, groupCount) triple before the SaveGame group.

    The first group is always "SaveGame"; search for its name header right
    after a plausible version triple.
    """
    needle = struct.pack("<i", 8) + b"SaveGame"
    pos = body.find(needle)
    while pos != -1:
        if pos >= 12:
            major, minor, ngroups = struct.unpack_from("<3i", body, pos - 12)
            if 0 < major < 100 and 0 <= minor < 10000 and 0 < ngroups < 100000:
                return pos - 12
        pos = body.find(needle, pos + 1)
    raise KSerialError("game object section not found")
