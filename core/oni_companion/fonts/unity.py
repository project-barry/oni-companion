"""Read the object table of a Unity serialized file (sharedassets0.assets) and pull Font objects out of it.

Read-only, stdlib only, no reads of the whole file: the metadata block (a few hundred KB) is parsed, then
only the byte range of each Font object is read. Formats 17..24 (Unity 2017 .. 6) are understood; a file
with a type tree or any other format raises UnityError and the caller falls back.

Font object layout (class id 128, no type tree), as serialized by Unity 2017+:
    m_Name (string, aligned), m_LineSpacing f32, m_DefaultMaterial PPtr, m_FontSize f32, m_Texture PPtr,
    m_AsciiStartOffset i32, m_Tracking f32, m_CharacterPadding i32, m_CharacterSpacing i32,
    m_ConvertCase i32, m_CharacterRects [CharacterInfo], m_KerningValues [pair], m_PixelScale f32,
    m_FontData [u8], m_Ascent f32, m_Descent f32, m_DefaultStyle u32, m_FontNames [string],
    m_FallbackFontReferences [PPtr], m_FontRenderingMode i32, ... flags.
m_FontData is the embedded TrueType file (empty for a dynamic OS font).
"""
import struct

CLASS_FONT = 128
MAX_OBJECTS = 2_000_000
MAX_FONT_BYTES = 32 * 1024 * 1024


class UnityError(Exception):
    pass


class _Cur:
    """A bounds-checked cursor over bytes."""

    def __init__(self, data, pos=0, little=True):
        self.d, self.p, self.le = data, pos, little

    def need(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise UnityError("read past the end")

    def take(self, n):
        self.need(n)
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def _num(self, fmt, n):
        self.need(n)
        v = struct.unpack_from(("<" if self.le else ">") + fmt, self.d, self.p)[0]
        self.p += n
        return v

    def u8(self): return self._num("B", 1)
    def i16(self): return self._num("h", 2)
    def i32(self): return self._num("i", 4)
    def u32(self): return self._num("I", 4)
    def i64(self): return self._num("q", 8)
    def f32(self): return self._num("f", 4)

    def align(self, n=4, base=0):
        self.p += (-(self.p - base)) % n
        self.need(0)

    def cstr(self, limit=64):
        end = self.d.find(b"\0", self.p, self.p + limit)
        if end < 0:
            raise UnityError("unterminated string")
        s = self.d[self.p:end].decode("utf-8", "replace")
        self.p = end + 1
        return s

    def string(self, limit=4096):
        n = self.i32()
        if n < 0 or n > limit:
            raise UnityError("bad string length")
        s = self.take(n).decode("utf-8", "replace")
        self.align(4)
        return s


class Obj:
    __slots__ = ("path_id", "start", "size", "type_index", "class_id")

    def __init__(self, path_id, start, size, type_index, class_id):
        self.path_id, self.start, self.size, self.type_index, self.class_id = path_id, start, size, type_index, class_id


class SerializedFile:
    """Parsed metadata of one file. `f` is a binary file object (seekable)."""

    def __init__(self, f):
        self.f = f
        f.seek(0)
        head = f.read(0x30)
        if len(head) < 0x30:
            raise UnityError("too short")
        c = _Cur(head, 0, little=False)
        meta_size, file_size, version, data_off = c.u32(), c.u32(), c.u32(), c.u32()
        if not 17 <= version <= 24:
            raise UnityError("serialized file format %d is not supported" % version)
        self.version = version
        little = True
        if version >= 22:
            c.p = 0x10
            little = c.u8() == 0
            c.p = 0x14
            meta_size, file_size, data_off = c.u32(), c.i64(), c.i64()
            meta_at = 0x30
        else:
            c.p = 0x10
            little = c.u8() == 0
            meta_at = 0x14
        if not 0 < meta_size <= 64 * 1024 * 1024:
            raise UnityError("bad metadata size")
        f.seek(0)
        meta = f.read(meta_at + meta_size)
        if len(meta) < meta_at + meta_size:
            raise UnityError("truncated metadata")
        self.data_offset = data_off
        c = _Cur(meta, meta_at, little)
        self.unity_version = c.cstr()
        self.platform = c.u32()
        self.type_tree = c.u8() != 0
        self.class_ids = []
        for _ in range(self._count(c, 4096)):
            cid = c.i32()
            c.u8()                      # stripped
            script_index = c.i16()
            if cid == 114 or script_index >= 0:
                c.take(16)              # script hash
            c.take(16)                  # type hash
            if self.type_tree:
                nodes, buf = c.i32(), c.i32()
                if not (0 <= nodes < 100000 and 0 <= buf < 4 * 1024 * 1024):
                    raise UnityError("bad type tree")
                c.take(nodes * 24 + buf)
                if version >= 21:
                    c.take(4 * self._count(c, 100000))
            self.class_ids.append(cid)
        n_obj = self._count(c, MAX_OBJECTS)
        self.objects = []
        for _ in range(n_obj):
            c.align(4)
            pid = c.i64()
            start = c.i64() if version >= 22 else c.u32()
            size = c.u32()
            tidx = c.i32()
            if not 0 <= tidx < len(self.class_ids):
                raise UnityError("bad type index")
            self.objects.append(Obj(pid, data_off + start, size, tidx, self.class_ids[tidx]))
        self.file_size = file_size

    @staticmethod
    def _count(c, limit):
        n = c.i32()
        if not 0 <= n <= limit:
            raise UnityError("bad count")
        return n

    def fonts(self):
        return [o for o in self.objects if o.class_id == CLASS_FONT]

    def read(self, obj, max_bytes=MAX_FONT_BYTES + 4 * 1024 * 1024):
        if obj.size > max_bytes:
            raise UnityError("object too large")
        self.f.seek(obj.start)
        data = self.f.read(obj.size)
        if len(data) != obj.size:
            raise UnityError("object runs past the end of the file")
        return data

    @property
    def little(self):
        return True


def font_from_object(data, little=True):
    """(name, font bytes) from the raw bytes of a Font object. The embedded data is located by walking the
    layout in the header comment; the walk must land exactly so that the data's length fits in the object
    and the bytes after it still parse (ascent/descent floats, name list). Raises UnityError otherwise."""
    c = _Cur(data, 0, little)
    name = c.string()
    c.p += 4 + 12 + 4 + 12            # line spacing, default material PPtr, font size, texture PPtr
    c.p += 4 * 5                      # ascii offset, tracking, char padding, char spacing, convert case
    c.need(0)
    rects = c.i32()
    if not 0 <= rects <= 200000:
        raise UnityError("bad character count")
    # CharacterInfo: index i32, uv Rectf, vert Rectf, width f32, flipped bool (4-byte aligned in an array of structs)
    c.p += rects * (4 + 16 + 16 + 4 + 4)
    kern = c.i32()
    if not 0 <= kern <= 200000:
        raise UnityError("bad kerning count")
    c.p += kern * 8
    c.p += 4                          # pixel scale
    c.need(0)
    n = c.i32()
    if not 0 <= n <= MAX_FONT_BYTES or c.p + n > len(data):
        raise UnityError("font data length does not fit")
    return name, bytes(data[c.p:c.p + n])
