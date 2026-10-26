"""F1: fonts read from the user's own game at run time (synthetic game files only; nothing from Klei)."""
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion.fonts import FontStore, sfnt, unity  # noqa: E402
from oni_companion.fonts import store as fstore  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic")
SYNTH_DIR = os.path.join(FIX, "companion", "fonts", "100001")
V = Validator(os.path.join(ROOT, "contracts"))
TOKEN = "t0ken-for-tests"


def synth_ttf():
    with open(os.path.join(SYNTH_DIR, "SynthSans.ttf"), "rb") as f:
        return f.read()


def pad4(b):
    return b + b"\0" * (-len(b) % 4)


def lstr(s):
    b = s.encode()
    return pad4(struct.pack("<i", len(b)) + b)


def font_object(name, data, rects=3, kern=2):
    """A Font object as Unity 2017+ serializes it (no type tree)."""
    out = lstr(name)
    out += struct.pack("<f", 0.0) + struct.pack("<iq", 0, 0) + struct.pack("<f", 16.0) + struct.pack("<iq", 0, 0)
    out += struct.pack("<iiiii", 0, 0, 0, 0, 0)
    out += struct.pack("<i", rects) + b"\x07" * (rects * 44)
    out += struct.pack("<i", kern) + b"\x05" * (kern * 8)
    out += struct.pack("<f", 1.0)
    out += struct.pack("<i", len(data)) + pad4(data)
    out += struct.pack("<ff", 10.0, -3.0) + struct.pack("<I", 0) + struct.pack("<i", 0) + struct.pack("<i", 0)
    out += struct.pack("<i", 0) + b"\0\0\0\0"
    return out


def serialized(objs, version=22, type_ids=(128, 114, 21)):
    """objs: [(path_id, class_id, bytes)]. A version-22 file with a metadata block and a data section."""
    types = b""
    for cid in type_ids:
        types += struct.pack("<iBh", cid, 0, -1 if cid != 114 else 0) + (b"\1" * 16 if cid == 114 else b"") + b"\2" * 16
    meta_head = b"6000.3.5f2\0" + struct.pack("<i", 19) + b"\0" + struct.pack("<i", len(type_ids)) + types
    # objects table: aligned entries; data offsets are into the data section
    data, rows, cur = b"", [], 0
    for pid, cid, raw in objs:
        rows.append((pid, cur, len(raw), type_ids.index(cid)))
        data += pad4(raw)
        cur += len(pad4(raw))
    base = 0x30
    meta = bytearray(meta_head)
    meta += struct.pack("<i", len(rows))
    for pid, start, size, tidx in rows:
        while (base + len(meta)) % 4:
            meta.append(0)
        meta += struct.pack("<qqIi", pid, start, size, tidx)
    meta += struct.pack("<i", 0) + struct.pack("<i", 0)      # externals, user info (unused by the reader)
    data_off = base + len(meta)
    data_off += (-data_off) % 16
    head = struct.pack(">IIII", 0, 0, version, 0) + b"\0\0\0\0" + struct.pack(">IQQQ", len(meta), 0, data_off, 0)
    f = head + bytes(meta)
    f += b"\0" * (data_off - len(f)) + data
    f = bytearray(f)
    struct.pack_into(">Q", f, 0x18, len(f))
    return bytes(f)


class TestUnity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, data, name="sharedassets0.assets"):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_object_table_and_fonts(self):
        ttf = synth_ttf()
        blob = serialized([(1, 21, b"x" * 10), (5, 128, font_object("Economica-Bold-OTF", ttf)),
                           (6, 114, b"y" * 30), (7, 128, font_object("Other", ttf))])
        with open(self.write(blob), "rb") as f:
            sf = unity.SerializedFile(f)
            self.assertEqual((sf.version, len(sf.objects)), (22, 4))
            fonts = sf.fonts()
            self.assertEqual([o.path_id for o in fonts], [5, 7])
            name, data = unity.font_from_object(sf.read(fonts[0]))
        self.assertEqual((name, data), ("Economica-Bold-OTF", ttf))

    def test_walk_does_not_trust_a_bogus_length(self):
        raw = bytearray(font_object("Broken", synth_ttf()))
        # the font data length sits right after the kerning table: claim far more than the object holds
        at = len(lstr("Broken")) + 4 + 12 + 4 + 12 + 20 + 4 + 3 * 44 + 4 + 2 * 8 + 4
        struct.pack_into("<i", raw, at, 1 << 20)
        with self.assertRaises(unity.UnityError):
            unity.font_from_object(bytes(raw))

    def test_rejects_other_formats_and_garbage(self):
        for blob in (b"", b"\0" * 100, os.urandom(2000), serialized([], version=22)[:40]):
            with open(self.write(blob), "rb") as f:
                with self.assertRaises(unity.UnityError):
                    unity.SerializedFile(f)

    def test_truncated_object_is_an_error(self):
        blob = serialized([(5, 128, font_object("A", synth_ttf()))])
        with open(self.write(blob[:-200]), "rb") as f:
            sf = unity.SerializedFile(f)
            with self.assertRaises(unity.UnityError):
                sf.read(sf.fonts()[0])


class TestSfnt(unittest.TestCase):
    def test_valid(self):
        info = sfnt.check(synth_ttf())
        self.assertEqual((info["family"], sfnt.style_key(info["style"])), ("Synth Sans", "regular"))

    def test_invalid(self):
        good = synth_ttf()
        for bad in (b"", b"OTTO", good[:100], b"junk" + good[4:], good[:12] + b"\0" * 40):
            with self.assertRaises(sfnt.FontError):
                sfnt.check(bad)

    def test_bad_head_magic(self):
        good = bytearray(synth_ttf())
        at = bytes(good).find(struct.pack(">I", 0x5F0F3CF5))
        good[at] ^= 0xFF
        with self.assertRaises(sfnt.FontError):
            sfnt.check(bytes(good))

    def test_style_keys(self):
        self.assertEqual([sfnt.style_key(s) for s in ("Bold Italic", "Bold", "Italic", "Regular")],
                         ["boldItalic", "bold", "italic", "regular"])


class GameBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.game = os.path.join(self.tmp, "game")
        self.data = os.path.join(self.tmp, "data")
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.game, "OxygenNotIncluded_Data", "StreamingAssets", "fonts"))
        os.makedirs(self.comp)
        self.ttf = synth_ttf()

    def put_noto(self):
        with open(os.path.join(self.game, "OxygenNotIncluded_Data", "StreamingAssets", "fonts", fstore.NOTO_FILE), "wb") as f:
            f.write(self.ttf)

    def put_assets(self, names=("Economica-Bold-OTF", "LeagueSpartan-Bold")):
        objs = [(i + 1, 128, font_object(n, self.ttf)) for i, n in enumerate(names)]
        objs.append((99, 21, b"z" * 8))
        with open(os.path.join(self.game, "OxygenNotIncluded_Data", "sharedassets0.assets"), "wb") as f:
            f.write(serialized(objs))

    def put_atlas(self, build="100001"):
        d = os.path.join(self.comp, "fonts", build)
        os.makedirs(d, exist_ok=True)
        for n in ("graystroke.png", "graystroke.json"):
            shutil.copy(os.path.join(SYNTH_DIR, n), os.path.join(d, n))

    @staticmethod
    def rw(path, change):
        with open(path) as f:
            d = json.load(f)
        change(d)
        with open(path, "w") as f:
            json.dump(d, f)

    def store(self):
        return FontStore(self.game, self.data, self.comp)


class TestStore(GameBase):
    def test_failed_extraction_is_retried(self):
        s = self.store()
        real = s._extract
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk full")
            return real()
        s._extract = flaky
        s.ensure()
        s.ensure()
        self.assertEqual(len(calls), 2)

    def test_nothing_in_game_is_an_empty_list(self):
        s = self.store()
        r = s.font_list()
        self.assertEqual(r, {"fonts": []})
        self.assertEqual(V.validate(r, "api.schema.json#/$defs/FontList"), [])
        self.assertIsNone(s.file("nothing.ttf"))

    def test_no_game_dir_at_all(self):
        s = FontStore("", self.data, "")
        self.assertEqual(s.font_list(), {"fonts": []})
        self.assertEqual(s.roles()["body"]["fallback"], ["Noto Sans"])

    def test_extracts_noto_and_embedded(self):
        self.put_noto()
        self.put_assets()
        s = self.store()
        r = s.font_list()
        self.assertEqual(V.validate(r, "api.schema.json#/$defs/FontList"), [])
        names = sorted(f["name"] for f in r["fonts"])
        self.assertEqual(names, ["Economica-Bold.ttf", "LeagueSpartan-Bold.ttf", "NotoSansUI-Regular.ttf"])
        got = s.file("Economica-Bold.ttf")
        self.assertEqual((got.data, got.content_type), (self.ttf, "font/ttf"))
        body = [f for f in r["fonts"] if f["name"] == fstore.NOTO_FILE][0]
        self.assertEqual(body["roles"], ["body"])

    def test_cache_is_reused_and_survives_game_files_leaving(self):
        self.put_noto()
        self.put_assets()
        self.store().font_list()
        cache = os.path.join(self.data, "fonts")
        key = os.listdir(cache)[0]
        mtime = os.path.getmtime(os.path.join(cache, key, "fonts.json"))
        again = self.store()
        again.font_list()
        self.assertEqual(os.path.getmtime(os.path.join(cache, key, "fonts.json")), mtime)

    def test_damaged_cache_is_extracted_again(self):
        self.put_noto()
        self.put_assets()
        self.store().font_list()
        cache = os.path.join(self.data, "fonts")
        key = os.listdir(cache)[0]
        with open(os.path.join(cache, key, "Economica-Bold.ttf"), "wb") as f:
            f.write(b"damaged")
        s = self.store()
        self.assertEqual(s.file("Economica-Bold.ttf").data, self.ttf)

    def test_game_change_extracts_again(self):
        self.put_noto()
        s = self.store()
        self.assertEqual(len(s.font_list()["fonts"]), 1)
        self.put_assets()
        os.utime(os.path.join(self.game, "OxygenNotIncluded_Data", "sharedassets0.assets"), (1, 1))
        self.assertEqual(len(s.font_list()["fonts"]), 3)

    def test_bad_embedded_font_is_skipped_others_kept(self):
        self.put_noto()
        objs = [(1, 128, font_object("Economica-Bold-OTF", b"not a font at all")),
                (2, 128, font_object("LeagueSpartan-Bold", self.ttf))]
        with open(os.path.join(self.game, "OxygenNotIncluded_Data", "sharedassets0.assets"), "wb") as f:
            f.write(serialized(objs))
        names = sorted(f["name"] for f in self.store().font_list()["fonts"])
        self.assertEqual(names, ["LeagueSpartan-Bold.ttf", "NotoSansUI-Regular.ttf"])

    def test_garbage_asset_file_does_not_raise(self):
        self.put_noto()
        with open(os.path.join(self.game, "OxygenNotIncluded_Data", "sharedassets0.assets"), "wb") as f:
            f.write(os.urandom(5000))
        s = self.store()
        self.assertEqual([f["name"] for f in s.font_list()["fonts"]], [fstore.NOTO_FILE])
        self.assertTrue(s.notes)

    def test_atlas_from_the_mod(self):
        self.put_noto()
        self.put_atlas()
        s = self.store()
        r = s.font_list()
        self.assertEqual(V.validate(r, "api.schema.json#/$defs/FontList"), [])
        self.assertEqual(r["build"], 100001)
        kinds = {f["name"]: f["kind"] for f in r["fonts"]}
        self.assertEqual(kinds["graystroke.png"], "sdfAtlasImage")
        self.assertEqual(s.file("graystroke.png").content_type, "image/png")
        table = json.loads(s.file("graystroke.json").data)
        self.assertEqual(V.validate(table, "font-atlas.schema.json"), [])
        roles = s.roles()
        self.assertEqual(roles["header"]["font"], "graystroke.json")
        self.assertEqual(roles["header"]["fallback"], ["Economica", "Noto Sans"])

    def test_bad_atlas_is_ignored(self):
        self.put_atlas()
        p = os.path.join(self.comp, "fonts", "100001", "graystroke.json")
        d = self.rw(p, lambda d: d["glyphs"][1].update(x=9999))
        s = self.store()
        self.assertEqual(s.font_list()["fonts"], [])
        self.assertTrue(any("outside" in n for n in s.notes))

    def test_atlas_png_size_must_match(self):
        self.put_atlas()
        p = os.path.join(self.comp, "fonts", "100001", "graystroke.json")
        self.rw(p, lambda d: d["atlas"].update(width=128))
        self.assertEqual(self.store().font_list()["fonts"], [])

    def test_header_falls_back_to_economica_then_unset(self):
        self.put_noto()
        self.put_assets()
        r = self.store().roles()
        self.assertEqual(r["header"]["font"], "Economica-Bold.ttf")
        self.assertEqual(r["body"]["font"], fstore.NOTO_FILE)
        none = FontStore("", self.data, "").roles()
        self.assertNotIn("font", none["header"])
        self.assertEqual(none["header"]["fallback"], ["Economica", "Noto Sans"])

    def test_names_never_reach_outside(self):
        self.put_noto()
        s = self.store()
        for bad in ("../x.ttf", "..", ".hidden", "a/b", "NotoSansUI-Regular.ttf/../../x", "", "x" * 200, "fonts.json"):
            self.assertIsNone(s.file(bad), bad)


class TestRoutes(GameBase):
    def setUp(self):
        super().setUp()
        self.put_noto()
        self.put_assets()
        self.put_atlas()
        cfg = ServiceConfig(user_dir=self.user, save_dirs=[], game_dir=self.game, token=TOKEN, data_dir=self.data)
        self.svc = Service(cfg).start()
        self.addCleanup(self.svc.stop)

    def get(self, path, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d/api/v1%s" % (self.svc.port, path),
                                     headers=dict({"X-Oni-Token": TOKEN}, **(headers or {})))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_list_and_files(self):
        st, _h, body = self.get("/fonts")
        self.assertEqual(st, 200)
        lst = json.loads(body)
        self.assertEqual(V.validate(lst, "api.schema.json#/$defs/FontList"), [])
        for f in lst["fonts"]:
            st, h, data = self.get(f["url"][len("/api/v1"):])
            self.assertEqual(st, 200)
            self.assertEqual(len(data), f["size"])
        st, h, _ = self.get("/fonts/graystroke.png")
        self.assertEqual(h["Content-Type"], "image/png")
        st, h, _ = self.get("/fonts/NotoSansUI-Regular.ttf")
        self.assertEqual(h["Content-Type"], "font/ttf")
        etag = h["ETag"]
        st, _h, _ = self.get("/fonts/NotoSansUI-Regular.ttf", {"If-None-Match": etag})
        self.assertEqual(st, 304)

    def test_unlisted_and_traversal_are_404_json(self):
        for p in ("/fonts/nope.ttf", "/fonts/..%2Fsettings.json", "/fonts/fonts.json", "/fonts/%2e%2e"):
            st, h, body = self.get(p)
            self.assertEqual(st, 404, p)
            self.assertEqual(json.loads(body)["error"]["code"], "not_found")

    def test_token_needed(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/v1/fonts" % self.svc.port)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 403)

    def test_theme_carries_roles(self):
        st, _h, body = self.get("/theme")
        theme = json.loads(body)
        self.assertEqual(V.validate(theme, "theme.schema.json#/$defs/Theme"), [])
        self.assertEqual(theme["font"]["roles"]["header"]["font"], "graystroke.json")
        self.assertEqual(theme["font"]["roles"]["body"]["font"], fstore.NOTO_FILE)


class TestRoutesNoGame(unittest.TestCase):
    def test_empty_everything(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        svc = Service(ServiceConfig(user_dir=os.path.join(tmp, "u"), save_dirs=[], token=TOKEN, data_dir=tmp)).start()
        self.addCleanup(svc.stop)
        req = urllib.request.Request("http://127.0.0.1:%d/api/v1/fonts" % svc.port, headers={"X-Oni-Token": TOKEN})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(json.loads(r.read()), {"fonts": []})
        req = urllib.request.Request("http://127.0.0.1:%d/api/v1/theme" % svc.port, headers={"X-Oni-Token": TOKEN})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertNotIn("roles", json.loads(r.read())["font"])


if __name__ == "__main__":
    unittest.main()
