"""C6: art serving (companion/art manifest -> GET /art/<kind>/<id>) and `art` fields in Screens.
Synthetic placeholder PNGs only; no game art."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion.art import ArtStore, decorate  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.views import blocks as B  # noqa: E402
from oni_companion.views.provider import Views  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402
from tests.test_c4_views import synthetic_lookup  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic")
V = Validator(os.path.join(ROOT, "contracts"))
TOKEN = "t0ken-c6"
PNG = open(os.path.join(FIX, "art-dupe-d1.png"), "rb").read()


def fake_png(tag):
    return PNG + bytes([tag])        # still starts with the PNG signature; bytes differ per tag


class Art:
    """Builds a companion/ folder with a manifest and files."""

    def __init__(self, root):
        self.companion = os.path.join(root, "companion")
        self.dir = os.path.join(self.companion, "art")
        self.files = []

    def add(self, kind, ident, tag, build=7, appearance=None, data=None, size=None):
        name = ident + ("-" + appearance if appearance else "")
        rel = "%d/%s/%s.png" % (build, kind, name)
        data = data if data is not None else fake_png(tag)
        full = os.path.join(self.dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        e = {"kind": kind, "id": ident, "path": rel, "size": size or len(data),
             "sha256": hashlib.sha256(data).hexdigest(), "width": 8, "height": 8}
        if appearance:
            e["appearanceHash"] = appearance
        self.files.append(e)
        return full

    def write(self):
        os.makedirs(self.dir, exist_ok=True)
        m = {"schema": 1, "modVersion": "0.2.0", "build": 7, "dlcIds": [], "writtenAt": "2026-01-01T12:00:00Z",
             "files": self.files}
        tmp = os.path.join(self.dir, "manifest.json.tmp")
        with open(tmp, "w") as f:
            json.dump(m, f)
        os.replace(tmp, os.path.join(self.dir, "manifest.json"))
        return m


def write_live(companion, hashes):
    d = json.load(open(os.path.join(FIX, "mod", "live-running-v2.json")))
    for u in d["worlds"][0]["dupes"]:
        if u["id"] in hashes:
            u["appearanceHash"] = hashes[u["id"]]
    p = os.path.join(companion, "live", "live.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(d, f)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-c6-")
        self.user = os.path.join(self.tmp, "user")
        os.makedirs(self.user)
        self.art = Art(self.user)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class StoreTests(TmpCase):
    def store(self):
        return ArtStore(self.art.companion, os.path.join(self.art.companion, "live", "live.json"))

    def test_no_mod_no_art(self):
        s = self.store()
        self.assertIsNone(s.url_for("building", "X"))
        self.assertIsNone(s.read("building", "X"))
        self.assertIsNone(ArtStore(None).url_for("building", "X"))

    def test_lookup_and_fallbacks(self):
        self.art.add("building", "SynthWidgetMaker", 1)
        self.art.add("item", "SynthTag", 2)
        self.art.write()
        s = self.store()
        self.assertEqual(s.url_for("building", "SynthWidgetMaker"), "/api/v1/art/building/SynthWidgetMaker")
        self.assertEqual(s.url_for("building", "synthwidgetmaker"), "/api/v1/art/building/SynthWidgetMaker")
        self.assertIsNone(s.url_for("building", "Nope"))
        self.assertIsNone(s.url_for("sticker", "SynthTag"))
        # an element with no element art falls back to item art
        self.assertEqual(s.url_for_ref("element", "SynthTag"), "/api/v1/art/item/SynthTag")
        self.assertIsNone(s.url_for_ref("tech", "SynthTag"))
        self.assertEqual(s.read("building", "SynthWidgetMaker").data, fake_png(1))

    def test_manifest_reread_when_it_changes(self):
        self.art.add("building", "A", 1)
        self.art.write()
        s = self.store()
        self.assertTrue(s.has("building", "A"))
        self.assertFalse(s.has("building", "B"))
        self.art.add("building", "B", 2)
        self.art.write()
        self.assertTrue(s.has("building", "B"))
        os.remove(os.path.join(self.art.dir, "manifest.json"))
        self.assertFalse(s.has("building", "A"))

    def test_bad_manifest_entries_are_ignored(self):
        self.art.add("building", "Good", 1)
        self.art.add("building", "SizeLies", 2, size=999)
        self.art.add("building", "NotPng", 3, data=b"GIF89a....")
        self.art.add("building", "Gone", 4)
        os.remove(os.path.join(self.art.dir, "7", "building", "Gone.png"))
        self.art.files += [
            {"kind": "building", "id": "Trav", "path": "../../etc/passwd.png", "size": 5, "sha256": "0" * 64, "width": 1, "height": 1},
            {"kind": "building", "id": "Abs", "path": "/etc/hosts", "size": 5, "sha256": "0" * 64, "width": 1, "height": 1},
            {"kind": "building", "id": "Dots", "path": "7/../building/Good.png", "size": 5, "sha256": "0" * 64, "width": 1, "height": 1},
            {"kind": "weird", "id": "Z", "path": "7/weird/Z.png", "size": 5, "sha256": "0" * 64, "width": 1, "height": 1},
            "junk", {"kind": "building"},
        ]
        self.art.write()
        s = self.store()
        self.assertTrue(s.has("building", "Good"))
        for bad in ("SizeLies", "NotPng", "Gone", "Trav", "Abs", "Dots"):
            self.assertIsNone(s.read("building", bad), bad)
        self.assertIsNone(s.read("weird", "Z"))

    def test_symlink_out_of_art_dir_is_refused(self):
        outside = os.path.join(self.tmp, "secret.png")
        with open(outside, "wb") as f:
            f.write(fake_png(9))
        self.art.add("building", "Link", 1)
        link = os.path.join(self.art.dir, "7", "building", "Link.png")
        os.remove(link)
        os.symlink(outside, link)
        self.art.write()
        self.assertIsNone(self.store().read("building", "Link"))

    def test_request_text_never_becomes_a_path(self):
        self.art.add("building", "Good", 1)
        self.art.write()
        s = self.store()
        for evil in ("../7/building/Good", "7/building/Good.png", "Good/../Good", "..", "%2e%2e", "Good\x00"):
            self.assertIsNone(s.read("building", evil), evil)

    def test_dupe_picks_current_hash_else_newest(self):
        a = self.art.add("dupe", "d1", 1, appearance="aaaaaaaa")
        b = self.art.add("dupe", "d1", 2, appearance="bbbbbbbb")
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        self.art.write()
        s = self.store()
        self.assertEqual(s.read("dupe", "d1").data, fake_png(2))          # no live file: newest
        write_live(self.art.companion, {"d1": "aaaaaaaa"})
        self.assertEqual(s.read("dupe", "d1").data, fake_png(1))          # current hash wins over newer
        write_live(self.art.companion, {"d1": "cccccccc"})
        self.assertEqual(s.read("dupe", "d1").data, fake_png(2))          # hash not rendered yet: newest
        os.remove(b)
        self.assertEqual(s.read("dupe", "d1").data, fake_png(1))          # newest file missing: the other one
        self.assertEqual(s.url_for("dupe", "d1"), "/api/v1/art/dupe/d1")

    def test_ui_hook(self):
        s = self.store()
        self.assertIsNone(s.read("ui", "panel"))
        p = os.path.join(self.tmp, "ui.png")
        with open(p, "wb") as f:
            f.write(fake_png(5))
        s.ui_lookup = lambda i: p if i == "panel" else None
        self.assertEqual(s.read("ui", "panel").data, fake_png(5))
        self.assertIsNone(s.read("ui", "other"))


class FakeStore:
    def __init__(self, have):
        self.have = have

    def url_for(self, k, i):
        return "/api/v1/art/%s/%s" % (k, i) if (k, i) in self.have else None

    def url_for_ref(self, k, i):
        return self.url_for(k, i)


class DecorateTests(unittest.TestCase):
    def test_refs_items_cards_and_hooks(self):
        st = FakeStore({("building", "A"), ("dupe", "d1")})
        scr = B.screen("T", [
            B.text("x ", B.ref_span(B.ref("building", "A"), "A")),
            B.list_block([B.item("A", B.ref("building", "A")), B.item("B", B.ref("building", "B")), B.item("plain")]),
            B.grid([B.card("Ada", art_key=("dupe", "d1")), B.card("Bo", art_key=("dupe", "d9")),
                    B.card("Bldg", ref=B.ref("building", "A"))]),
            B.image(("dupe", "d1"), caption="c"), B.image(("dupe", "zzz")), B.heading("H", 2, art_key=("dupe", "d1")),
            B.stats([B.stat("s", 1, ref=B.ref("building", "A"))]),
        ])
        decorate(scr, st)
        bl = scr["blocks"]
        self.assertEqual(bl[0]["spans"][1]["ref"]["art"], "/api/v1/art/building/A")
        items = bl[1]["items"]
        self.assertEqual(items[0]["art"], "/api/v1/art/building/A")
        self.assertNotIn("art", items[1])
        self.assertNotIn("art", items[1]["ref"])
        self.assertNotIn("art", items[2])
        cards = bl[2]["cards"]
        self.assertEqual(cards[0]["art"], "/api/v1/art/dupe/d1")
        self.assertNotIn("art", cards[1])
        self.assertEqual(cards[2]["art"], "/api/v1/art/building/A")
        self.assertEqual(bl[3], {"type": "image", "caption": "c", "art": "/api/v1/art/dupe/d1"})
        self.assertEqual(bl[4]["type"], "heading")           # the image with no art was dropped
        self.assertEqual(bl[4]["art"], "/api/v1/art/dupe/d1")
        self.assertEqual(bl[5]["rows"][0]["ref"]["art"], "/api/v1/art/building/A")
        self.assertNotIn("_art", repr(scr))
        self.assertEqual(V.validate(scr, "screen.schema.json"), [])

    def test_no_store_is_exactly_the_v1_screen(self):
        def build():
            return B.screen("T", [B.list_block([B.item("A", B.ref("building", "A"))]),
                                  B.grid([B.card("Ada", art_key=("dupe", "d1"))]), B.image(("dupe", "d1"))])
        scr = decorate(build(), None, ("building", "A"))
        self.assertNotIn("art", json.dumps(scr))
        self.assertNotIn("image", json.dumps(scr))
        self.assertEqual(len(scr["blocks"]), 2)

    def test_entry_header(self):
        st = FakeStore({("building", "A")})
        scr = decorate(B.screen("Alpha", [B.text("x")]), st, ("building", "A"))
        self.assertEqual(scr["blocks"][0], {"type": "heading", "text": "Alpha", "level": 1, "art": "/api/v1/art/building/A"})
        scr = decorate(B.screen("Beta", [B.text("x")]), st, ("building", "B"))
        self.assertEqual(len(scr["blocks"]), 1)


class FakeCtx:
    def __init__(self, svc):
        self.cfg, self.colony, self.bus, self.art = svc.cfg, svc.colony, svc.bus, svc.art


def get(svc, path, headers=None):
    h = {"X-Oni-Token": TOKEN} if headers is None else headers
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (svc.port, path), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class HttpBase(TmpCase):
    barry = False

    def start(self):
        user = self.user
        os.makedirs(self.art.companion, exist_ok=True)
        self.svc = Service(ServiceConfig(user_dir=user, token=TOKEN, barry_mode=self.barry,
                                         views_factory=lambda ctx: Views(FakeCtx(ctx), lookup=synthetic_lookup()))).start()
        self.addCleanup(self.svc.stop)
        return user


class HttpTests(HttpBase):
    barry = True

    def test_serve_png_and_errors(self):
        self.art.add("building", "SynthWidgetMaker", 1)
        write_live(self.art.companion, {})
        self.art.write()
        self.start()
        st, h, body = get(self.svc, "/api/v1/art/building/SynthWidgetMaker")
        self.assertEqual((st, h["Content-Type"], body), (200, "image/png", fake_png(1)))
        self.assertEqual(h["Content-Length"], str(len(body)))
        self.assertIn("ETag", h)
        # token rules: header, barry query token; none or wrong = 403 JSON
        st, h, body = get(self.svc, "/api/v1/art/building/SynthWidgetMaker?token=" + TOKEN, headers={})
        self.assertEqual((st, body), (200, fake_png(1)))
        st, h, body = get(self.svc, "/api/v1/art/building/SynthWidgetMaker", headers={})
        self.assertEqual(st, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "bad_token")
        st, _, body = get(self.svc, "/api/v1/art/building/SynthWidgetMaker?token=wrong", headers={})
        self.assertEqual(st, 403)
        # 404s are JSON errors
        for p in ("/api/v1/art/building/Nope", "/api/v1/art/nokind/x", "/api/v1/art/building",
                  "/api/v1/art/building/..%2F..%2Fetc%2Fpasswd", "/api/v1/art/dupe/d1", "/api/v1/art/ui/panel"):
            st, h, body = get(self.svc, p)
            self.assertEqual(st, 404, p)
            self.assertTrue(h["Content-Type"].startswith("application/json"))
            self.assertEqual(V.validate(json.loads(body), "api.schema.json#/$defs/Error"), [])

    def test_etag_304(self):
        self.art.add("building", "SynthWidgetMaker", 1)
        self.art.write()
        self.start()
        _, h, _ = get(self.svc, "/api/v1/art/building/SynthWidgetMaker")
        st, h2, body = get(self.svc, "/api/v1/art/building/SynthWidgetMaker",
                           headers={"X-Oni-Token": TOKEN, "If-None-Match": h["ETag"]})
        self.assertEqual((st, body), (304, b""))

    def test_screens_carry_art(self):
        self.art.add("building", "SynthWidgetMaker", 1)
        self.art.add("element", "SynthWidgetium", 2)
        self.art.add("dupe", "d1", 3, appearance="ab12cd34")
        # schema 1 live file (no appearanceHash), written now so the colony view treats it as running
        from oni_companion import colony as colony_mod
        import time
        d = json.load(open(os.path.join(FIX, "mod", "live-running.json")))
        d["writtenAt"] = colony_mod.iso(time.time())
        os.makedirs(os.path.join(self.art.companion, "live"))
        json.dump(d, open(os.path.join(self.art.companion, "live", "live.json"), "w"))
        self.art.write()
        self.start()

        def jget(path):
            st, h, body = get(self.svc, path)
            self.assertEqual(st, 200, path)
            return json.loads(body)

        lst = jget("/api/v1/list/building")
        self.assertEqual(V.validate(lst, "screen.schema.json"), [])
        it = [i for i in lst["blocks"][0]["items"] if i["ref"]["id"] == "SynthWidgetMaker"][0]
        self.assertEqual(it["art"], "/api/v1/art/building/SynthWidgetMaker")
        self.assertEqual(it["ref"]["art"], it["art"])
        other = [i for i in lst["blocks"][0]["items"] if i["ref"]["id"] != "SynthWidgetMaker"]
        self.assertTrue(other and all("art" not in i for i in other))

        ent = jget("/api/v1/entry/building/SynthWidgetMaker")
        self.assertEqual(V.validate(ent, "screen.schema.json"), [])
        self.assertEqual(ent["blocks"][0]["type"], "heading")
        self.assertEqual(ent["blocks"][0]["art"], "/api/v1/art/building/SynthWidgetMaker")
        self.assertIn("/api/v1/art/element/SynthWidgetium", json.dumps(ent))
        # every art path in a Screen resolves to a PNG
        import re
        for path in set(re.findall(r'/api/v1/art/[A-Za-z]+/[A-Za-z0-9_.%-]+', json.dumps([lst, ent]))):
            st, h, body = get(self.svc, path)
            self.assertEqual((st, h["Content-Type"]), (200, "image/png"), path)

        col = jget("/api/v1/colony")
        self.assertEqual(V.validate(col, "screen.schema.json"), [])
        cards = [c for b in B.walk_blocks(col["blocks"]) if b["type"] == "grid" for c in b["cards"]]
        self.assertEqual([c.get("art") for c in cards if c["title"] == "Ada"], ["/api/v1/art/dupe/d1"])
        self.assertNotIn("_art", json.dumps(col))
        st, _, body = get(self.svc, "/api/v1/art/dupe/d1")
        self.assertEqual((st, body), (200, fake_png(3)))

    def test_without_mod_no_art_anywhere(self):
        user = self.start()
        for path in ("/api/v1/list/building", "/api/v1/entry/building/SynthWidgetMaker", "/api/v1/home"):
            st, h, body = get(self.svc, path)
            self.assertEqual(st, 200, path)
            self.assertNotIn('"art"', body.decode())
            self.assertNotIn("_art", body.decode())

    def test_manifest_change_publishes_event(self):
        self.art.add("building", "A", 1)
        self.art.write()
        self.start()
        import time
        st, _, body = get(self.svc, "/api/v1/events?since=0")
        seq = json.loads(body)["seq"]
        art = Art(self.user)
        art.files = list(self.art.files)
        art.add("building", "B", 2)
        art.write()
        st, _, body = get(self.svc, "/api/v1/events?since=%d&timeout=5" % seq)
        ev = json.loads(body)
        self.assertIn("colony", ev["changed"])


class StandaloneHttp(HttpBase):
    def test_query_token_is_barry_only(self):
        self.art.add("building", "A", 1)
        self.art.write()
        self.start()
        st, _, _ = get(self.svc, "/api/v1/art/building/A?token=" + TOKEN, headers={})
        self.assertEqual(st, 403)
        st, _, _ = get(self.svc, "/api/v1/art/building/A")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()


class ActionArgsKeepNoArt(unittest.TestCase):
    def test_action_args_not_decorated(self):
        from oni_companion.art.decorate import decorate

        class Store:
            def url_for(self, *a):
                return "/x"

            def url_for_ref(self, k, i):
                return "/api/v1/art/%s/%s" % (k, i)
        args = {"target": {"kind": "dupe", "id": "d1"}, "select": True}
        scr = {"blocks": [{"type": "grid", "cards": [{"title": "A", "ref": {"kind": "dupe", "id": "d1"},
                                                      "actions": [{"id": "focus", "label": "Show", "args": args}]}]}]}
        decorate(scr, Store())
        self.assertEqual(args, {"target": {"kind": "dupe", "id": "d1"}, "select": True})
        self.assertIn("art", scr["blocks"][0]["cards"][0]["ref"])
