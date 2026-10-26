"""On-demand art: art_request contract, ArtStore pending URLs, ArtRequests rules, and the whole chain with a fake mod.
Synthetic data only; no game art, no Nova."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion.art import ArtStore, decorate  # noqa: E402
from oni_companion.art.requests import ArtRequests, MAX_OUTSTANDING, requestable  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from oni_companion.watch import make_watcher  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402
from tests.test_c3_server import TOKEN, atomic_write, http, live_text  # noqa: E402
from tests.test_c6_art import PNG, fake_png  # noqa: E402

CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
V = Validator(CONTRACTS)
STAMP = "2026-01-01T00:00:00Z"


def cmd(kind="building", ident="X", ctype="art_request", **extra):
    d = {"schema": 1, "seq": 1, "createdAt": STAMP, "type": ctype, "target": {"kind": kind, "id": ident}}
    d.update(extra)
    return d


class TestContract(unittest.TestCase):
    def test_art_request_valid(self):
        self.assertEqual(V.validate(cmd(), "mod-command.schema.json"), [])
        for k in ("building", "element", "critter", "plant", "seed", "egg", "food", "medicine", "item"):
            self.assertEqual(V.validate(cmd(k, "A.b-c_1"), "mod-command.schema.json"), [], k)

    def test_art_request_rejects(self):
        for bad in (cmd("dupe", "d1"), cmd("ui", "x"), cmd("building", "../etc/passwd"), cmd("building", "a b"),
                    cmd("building", ""), cmd("building", "x" * 101), cmd(path="/etc/x"), cmd(select=True),
                    cmd(ctype="delete")):
            self.assertTrue(V.validate(bad, "mod-command.schema.json"), bad)

    def test_focus_still_valid(self):
        f = cmd("dupe", "d1", ctype="focus", select=True)
        self.assertEqual(V.validate(f, "mod-command.schema.json"), [])
        self.assertTrue(V.validate(cmd("building", "x", ctype="focus"), "mod-command.schema.json"))

    def test_fixtures(self):
        for name in ("cmd-5.json", "cmd-7.json"):
            with open(os.path.join(FIX, "companion", "commands", name)) as f:
                self.assertEqual(V.validate(json.load(f), "mod-command.schema.json"), [], name)
        for name in ("ack-7.json", "ack-8.json"):
            with open(os.path.join(FIX, "companion", "acks", name)) as f:
                self.assertEqual(V.validate(json.load(f), "mod-ack.schema.json"), [], name)

    def test_manifest_fields(self):
        f = {"kind": "building", "id": "A", "path": "7/building/A.png", "size": 1, "sha256": "0" * 64,
             "width": 1, "height": 1, "srcKey": "0123456789abcdef"}
        m = {"schema": 1, "modVersion": "0.2.2", "build": 7, "dlcIds": [], "writtenAt": STAMP,
             "onDemand": True, "renderRev": 1, "files": [f]}
        self.assertEqual(V.validate(m, "mod-art-manifest.schema.json"), [])
        self.assertTrue(V.validate(dict(m, files=[dict(f, srcKey="XYZ")]), "mod-art-manifest.schema.json"))
        self.assertTrue(V.validate(dict(m, onDemand="yes"), "mod-art-manifest.schema.json"))

    def test_art_event_name(self):
        self.assertEqual(V.validate({"seq": 3, "changed": ["art"]}, "api.schema.json#/$defs/Events"), [])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c12-"))
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.comp, "live"))
        atomic_write(os.path.join(self.comp, "live", "live.json"), live_text())
        self.files = []
        self.svc = None
        self.mods = []

    def tearDown(self):
        if self.svc:
            self.svc.stop()
        for m in self.mods:
            m.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def manifest(self, on_demand=True):
        d = os.path.join(self.comp, "art")
        os.makedirs(d, exist_ok=True)
        m = {"schema": 1, "modVersion": "0.2.2", "build": 7, "dlcIds": [], "writtenAt": STAMP, "files": self.files}
        if on_demand:
            m["onDemand"] = True
            m["renderRev"] = 1
        atomic_write(os.path.join(d, "manifest.json"), json.dumps(m))

    def draw(self, kind, ident, tag=1):
        """What the mod does: PNG first, then the manifest."""
        rel = "7/%s/%s.png" % (kind, ident)
        full = os.path.join(self.comp, "art", *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        data = fake_png(tag)
        with open(full, "wb") as f:
            f.write(data)
        self.files.append({"kind": kind, "id": ident, "path": rel, "size": len(data),
                           "sha256": hashlib.sha256(data).hexdigest(), "width": 8, "height": 8})
        self.manifest()

    def start(self):
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        return self.svc

    def get(self, kind, ident):
        req = __import__("urllib.request").request.Request(
            "http://127.0.0.1:%d/api/v1/art/%s/%s" % (self.svc.port, kind, ident), headers={"X-Oni-Token": TOKEN})
        try:
            with __import__("urllib.request").request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except __import__("urllib.error").error.HTTPError as e:
            try:
                return e.code, e.read()
            finally:
                e.close()

    def cmd_files(self):
        d = os.path.join(self.comp, "commands")
        try:
            return sorted(n for n in os.listdir(d) if n.startswith("cmd-") and n.endswith(".json"))
        except OSError:
            return []

    def read_cmds(self):
        out = []
        for n in self.cmd_files():
            with open(os.path.join(self.comp, "commands", n)) as f:
                out.append(json.load(f))
        return out


class TestStoreOnDemand(Base):
    def test_pending_urls_only_when_on_demand(self):
        self.manifest(on_demand=False)
        s = ArtStore(self.comp)
        self.assertFalse(s.on_demand())
        self.assertIsNone(s.url_for("building", "X", pending=True))
        self.assertIsNone(s.url_for_ref("building", "X"))
        self.manifest(on_demand=True)
        self.assertTrue(s.on_demand())
        self.assertEqual(s.url_for("building", "X", pending=True), "/api/v1/art/building/X")
        self.assertIsNone(s.url_for("building", "X"))                  # without pending: as before
        self.assertIsNone(s.url_for("dupe", "d1", pending=True))        # portraits draw themselves
        self.assertEqual(s.url_for_ref("element", "Water"), "/api/v1/art/element/Water")

    def test_existing_art_wins_over_pending(self):
        self.draw("item", "Water")
        s = ArtStore(self.comp)
        self.assertEqual(s.url_for_ref("element", "Water"), "/api/v1/art/item/Water")

    def test_decorate_adds_pending_art(self):
        self.manifest()
        s = ArtStore(self.comp)
        scr = {"schema": 1, "title": "T", "blocks": [{"type": "list", "items": [
            {"title": "Widget", "ref": {"kind": "building", "id": "Widget"}}]}]}
        decorate(scr, s)
        it = scr["blocks"][0]["items"][0]
        self.assertEqual(it["ref"]["art"], "/api/v1/art/building/Widget")
        self.assertEqual(it["art"], "/api/v1/art/building/Widget")

    def test_requestable(self):
        self.assertTrue(requestable("building", "A.b-c_1"))
        for k, i in (("dupe", "d1"), ("ui", "x"), ("building", "a/b"), ("building", ""), ("building", "x" * 101),
                     ("building", None), ("nope", "x")):
            self.assertFalse(requestable(k, i), (k, i))


class FakeMod:
    """Test double: reads art_request commands, 'draws' (PNG + manifest), acks after the manifest."""

    def __init__(self, base, fail=None, hold=False):
        self.base, self.fail, self.hold = base, fail or {}, hold
        self.seen, self.pending = [], []
        cmd_dir = os.path.join(base.comp, "commands")
        os.makedirs(cmd_dir, exist_ok=True)
        os.makedirs(os.path.join(base.comp, "acks"), exist_ok=True)
        self._w = make_watcher([cmd_dir], self._on, recursive=False).start()

    def _on(self, path, what):
        n = os.path.basename(path)
        if what == "removed" or not (n.startswith("cmd-") and n.endswith(".json")):
            return
        try:
            with open(path, "rb") as f:
                d = json.loads(f.read().decode())
        except (OSError, ValueError):
            return
        if d["seq"] in [s["seq"] for s in self.seen]:
            return
        self.seen.append(d)
        if self.hold:
            return
        self.answer(d)

    def answer(self, d):
        kind, ident = d["target"]["kind"], d["target"]["id"]
        if ident in self.fail:
            ack = {"schema": 1, "seq": d["seq"], "state": "failed", "message": self.fail[ident], "ackedAt": STAMP}
        else:
            self.base.draw(kind, ident)
            ack = {"schema": 1, "seq": d["seq"], "state": "done", "message": "Drawn", "ackedAt": STAMP}
        atomic_write(os.path.join(self.base.comp, "acks", "ack-%d.json" % d["seq"]), json.dumps(ack))

    def stop(self):
        self._w.stop()


def wait_for(fn, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


class TestChain(Base):
    def mod(self, **kw):
        m = FakeMod(self, **kw)
        self.mods.append(m)
        return m

    def test_miss_sends_one_request_and_dedupes(self):
        self.manifest()
        self.start()
        st, _ = self.get("building", "Widget")
        self.assertEqual(st, 404)
        self.get("building", "Widget")
        self.get("building", "Widget")
        cmds = self.read_cmds()
        self.assertEqual(len(cmds), 1)
        c = cmds[0]
        self.assertEqual(c["type"], "art_request")
        self.assertEqual(c["target"], {"kind": "building", "id": "Widget"})
        self.assertEqual(V.validate(c, "mod-command.schema.json"), [])
        self.assertFalse(os.path.exists(os.path.join(self.comp, "commands", "cmd-%d.json.tmp" % c["seq"])))

    def test_nothing_asked_without_on_demand_or_for_bad_input(self):
        self.manifest(on_demand=False)
        self.start()
        self.get("building", "Widget")
        self.assertEqual(self.cmd_files(), [])
        self.manifest(on_demand=True)
        self.get("dupe", "d1")                       # portraits draw themselves
        self.get("building", "a%20b")                # not a plain id
        self.get("ui", "panel")
        self.get("nonsense", "x")
        self.assertEqual(self.cmd_files(), [])

    def test_game_not_sending_data_asks_nothing(self):
        atomic_write(os.path.join(self.comp, "live", "live.json"), live_text(state="menu"))
        self.manifest()
        self.start()
        self.get("building", "Widget")
        self.assertEqual(self.cmd_files(), [])

    def test_at_most_20_outstanding(self):
        self.manifest()
        self.start()
        for i in range(30):
            self.get("building", "B%02d" % i)
        self.assertEqual(len(self.cmd_files()), MAX_OUTSTANDING)
        self.assertEqual(self.svc.art_requests.outstanding(), MAX_OUTSTANDING)

    def test_done_ack_manifest_event_and_image(self):
        self.manifest()
        self.start()
        self.mod()
        seq0 = self.svc.bus.seq
        self.assertEqual(self.get("element", "Water")[0], 404)
        self.assertTrue(wait_for(lambda: self.get("element", "Water")[0] == 200), "image never served")
        st, data = self.get("element", "Water")
        self.assertEqual(data[:8], PNG[:8])
        r = self.svc.bus.wait(seq0, 3)
        self.assertIn("art", r["changed"])
        self.assertTrue(wait_for(lambda: self.svc.art_requests.outstanding() == 0))
        self.assertTrue(wait_for(lambda: self.cmd_files() == []))
        n = self.svc.art_requests.sent
        self.get("element", "Water")                 # now there: no new request
        self.assertEqual(self.svc.art_requests.sent, n)

    def test_failed_ack_is_not_asked_again(self):
        self.manifest()
        self.start()
        m = self.mod(fail={"Nothing": "Unknown id"})
        self.get("building", "Nothing")
        self.assertTrue(wait_for(lambda: self.svc.art_requests.outstanding() == 0 and len(m.seen) == 1))
        self.get("building", "Nothing")
        self.get("building", "Nothing")
        self.assertEqual(len(m.seen), 1)
        self.assertEqual(self.svc.art_requests.sent, 1)

    def test_art_event_when_manifest_changes(self):
        self.manifest()
        self.start()
        seq0 = self.svc.bus.seq
        self.draw("food", "Meal")
        r = self.svc.bus.wait(seq0, 3)
        self.assertIn("art", r["changed"])


class TestRequestsUnit(Base):
    """ArtRequests with a fake clock: expiry frees the slot and removes the command file."""

    def test_expiry(self):
        self.manifest()
        now = [1000.0]
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        r = ArtRequests(self.svc.actions, self.svc.art, clock=lambda: now[0], max_outstanding=2, expire=30.0)
        self.assertTrue(r.request("building", "A"))
        self.assertTrue(r.request("building", "B"))
        self.assertFalse(r.request("building", "C"))        # full
        self.assertFalse(r.request("building", "A"))        # dedupe
        self.assertEqual(len(self.cmd_files()), 2)
        now[0] += 31
        self.assertTrue(r.request("building", "C"))         # A and B expired
        self.assertEqual(len(self.cmd_files()), 1)          # their files were removed
        self.assertFalse(r.request("building", "A"))        # failed pause (20 s) after the expiry
        now[0] += 25
        self.assertTrue(r.request("building", "A"))

    def test_permanent_failure_pauses_for_an_hour(self):
        self.manifest()
        now = [1000.0]
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        r = ArtRequests(self.svc.actions, self.svc.art, clock=lambda: now[0])
        self.assertTrue(r.request("item", "Gone"))
        seq = self.read_cmds()[0]["seq"]
        p = os.path.join(self.comp, "acks", "ack-%d.json" % seq)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"schema": 1, "seq": seq, "state": "failed", "message": "Unknown id", "ackedAt": STAMP}, f)
        self.assertTrue(r.handle_ack(seq, p))
        now[0] += 600
        self.assertFalse(r.request("item", "Gone"))
        now[0] += 3600
        self.assertTrue(r.request("item", "Gone"))

    def test_foreign_ack_is_not_ours(self):
        self.manifest()
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        self.assertFalse(self.svc.art_requests.handle_ack(99999, "/nonexistent"))


if __name__ == "__main__":
    unittest.main()
