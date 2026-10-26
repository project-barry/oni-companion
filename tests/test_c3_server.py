"""C3: server, auth, long-poll, watchers, colony source selection."""
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import colony as colony_mod  # noqa: E402
from oni_companion.__main__ import build_config  # noqa: E402
from oni_companion.server.events import EventBus  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic")
V = Validator(os.path.join(ROOT, "contracts"))
TOKEN = "t0ken-for-tests"


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.rename(tmp, path)


def live_text(state="running", written=None, paused=False, cycle=12):
    with open(os.path.join(FIX, "mod", "live-running.json")) as f:
        d = json.load(f)
    d["state"] = state
    d["paused"] = paused
    d["cycle"] = cycle
    d["writtenAt"] = colony_mod.iso(written if written is not None else time.time())
    return json.dumps(d)


def make_sav(path, cycles=7):
    hdr = json.dumps({"numberOfCycles": cycles, "numberOfDuplicants": 3}).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<IIII", 744825, len(hdr), 1, 1) + hdr + b"body")


def http(svc, path, method="GET", headers=None, body=None, timeout=10):
    h = {"X-Oni-Token": TOKEN}
    if headers is not None:
        h = headers
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (svc.port, path), data=data,
                                 method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class Env(unittest.TestCase):
    barry = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-c3-")
        self.user = os.path.join(self.tmp, "user")
        os.makedirs(os.path.join(self.user, "companion", "live"))
        os.makedirs(os.path.join(self.user, "companion", "export"))
        os.makedirs(os.path.join(self.user, "cloud_save_files", "1", "Synth"))
        self.live = os.path.join(self.user, "companion", "live", "live.json")
        # the fixture-driven stub on purpose: these tests are about routing and auth, not content
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, barry_mode=self.barry,
                            views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()

    def tearDown(self):
        self.svc.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestAuthAndRoutes(Env):
    def test_token_rejection(self):
        for hdrs in ({}, {"X-Oni-Token": "wrong"}, {"X-Oni-Token": ""},
                     {"X-Barry-Token": TOKEN}):
            st, body = http(self.svc, "/api/v1/status", headers=hdrs)
            self.assertEqual(st, 403, hdrs)
            self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [])
            self.assertEqual(body["error"]["code"], "bad_token")
        st, _ = http(self.svc, "/api/v1/status?token=" + TOKEN, headers={})
        self.assertEqual(st, 403)       # query token is Barry mode only
        st, _ = http(self.svc, "/nope", headers={})
        self.assertEqual(st, 403)       # no path info leaks without a token
        st, _ = http(self.svc, "/api/v1/status")
        self.assertEqual(st, 200)

    def test_every_endpoint_validates(self):
        cases = [
            ("/status", "api.schema.json#/$defs/Status"),
            ("/home", "screen.schema.json"),
            ("/search?q=wid", "api.schema.json#/$defs/Search"),
            ("/kinds", "api.schema.json#/$defs/Kinds"),
            ("/list/building", "screen.schema.json"),
            ("/entry/building/SynthWidgetMaker", "screen.schema.json"),
            ("/raw/building/SynthWidgetMaker", "api.schema.json#/$defs/Raw"),
            ("/colony", "api.schema.json#/$defs/ColonyReply"),
            ("/tools", "api.schema.json#/$defs/ToolList"),
            ("/tools/%s" % self._tool_id(), "screen.schema.json"),
            ("/events", "api.schema.json#/$defs/Events"),
        ]
        for path, schema in cases:
            st, body = http(self.svc, "/api/v1" + path)
            self.assertEqual(st, 200, path)
            self.assertEqual(V.validate(body, schema), [], path)
        st, body = http(self.svc, "/api/v1/tools/%s" % self._tool_id(), "POST",
                        body={"values": {}})
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(body, "screen.schema.json"), [])

    def _tool_id(self):
        return http(self.svc, "/api/v1/tools")[1]["tools"][0]["id"]

    def test_errors(self):
        expect = [
            ("GET", "/api/v1/search", 400), ("GET", "/api/v1/search?q=a&limit=x", 400),
            ("GET", "/api/v1/events?since=abc", 400), ("GET", "/api/v1/list/building?sort=zz", 400),
            ("GET", "/api/v1/nothing", 404), ("GET", "/api/v1/entry/building/Nope", 404),
            ("GET", "/api/v1/tools/nope", 404), ("GET", "/other", 404),
            ("GET", "/api/v1/pair/clients", 501), ("POST", "/api/v1/pair/start", 501),
            ("DELETE", "/api/v1/pair/clients/x", 501), ("POST", "/api/v1/status", 404),
        ]
        for method, path, code in expect:
            st, body = http(self.svc, path, method, body={} if method == "POST" else None)
            self.assertEqual(st, code, (method, path))
            self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [], path)
        st, body = http(self.svc, "/api/v1/tools/%s" % self._tool_id(), "POST", body=[1])
        self.assertEqual(st, 400)

    def test_bad_json_body(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/v1/tools/x" % self.svc.port,
                                     data=b"{nope", method="POST", headers={"X-Oni-Token": TOKEN})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)


class TestBarryAuth(Env):
    barry = True

    def test_barry_forms(self):
        self.assertEqual(http(self.svc, "/api/v1/status", headers={"X-Barry-Token": TOKEN})[0], 200)
        self.assertEqual(http(self.svc, "/api/v1/status?token=" + TOKEN, headers={})[0], 200)
        self.assertEqual(http(self.svc, "/api/v1/status?token=bad", headers={})[0], 403)


class TestLongPoll(Env):
    def _poll(self, since, out, timeout=10):
        st, body = http(self.svc, "/api/v1/events?since=%d&timeout=%d" % (since, timeout))
        out.append((time.monotonic(), st, body))

    def test_since_zero_returns_now(self):
        st, body = http(self.svc, "/api/v1/events")
        self.assertEqual((st, body["changed"]), (200, []))

    def test_timeout_returns_empty(self):
        self.svc.bus.publish("status")
        b0 = http(self.svc, "/api/v1/events")[1]
        t0 = time.monotonic()
        st, body = http(self.svc, "/api/v1/events?since=%d&timeout=0.3" % b0["seq"])
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)
        self.assertEqual(body["changed"], [])

    def test_wake_latency_live_file(self):
        self.svc.bus.publish("status")      # seq >= 1 so since is not "now"
        seq = http(self.svc, "/api/v1/events")[1]["seq"]
        lat = []
        for i in range(5):
            out = []
            th = threading.Thread(target=self._poll, args=(seq, out))
            th.start()
            time.sleep(0.15)                # the request is parked
            t0 = time.monotonic()
            atomic_write(self.live, live_text(cycle=20 + i))
            th.join(5)
            t1, st, body = out[0]
            self.assertEqual(st, 200)
            self.assertIn("colony", body["changed"])
            self.assertGreater(body["seq"], seq)
            seq = body["seq"]
            lat.append(t1 - t0)
        print("long-poll wake latency ms:", [round(x * 1000, 1) for x in lat],
              file=sys.stderr)
        self.assertLess(max(lat), 0.1)

    def test_export_and_save_and_tmp(self):
        self.svc.bus.publish("status")
        seq = http(self.svc, "/api/v1/events")[1]["seq"]
        atomic_write(os.path.join(self.user, "companion", "export", "gamedata-1-X.json"), "{}")
        st, body = http(self.svc, "/api/v1/events?since=%d&timeout=5" % seq)
        self.assertIn("gamedata", body["changed"])
        seq = body["seq"]
        make_sav(os.path.join(self.user, "cloud_save_files", "1", "Synth", "Synth.sav"))
        st, body = http(self.svc, "/api/v1/events?since=%d&timeout=5" % seq)
        self.assertIn("colony", body["changed"])
        seq = body["seq"]
        with open(os.path.join(self.user, "companion", "live", "x.tmp"), "w") as f:
            f.write("x")                    # .tmp files never wake clients
        st, body = http(self.svc, "/api/v1/events?since=%d&timeout=0.4" % seq)
        self.assertEqual(body["changed"], [])

    def test_stop_wakes_waiters(self):
        self.svc.bus.publish("status")
        seq = http(self.svc, "/api/v1/events")[1]["seq"]
        out = []
        th = threading.Thread(target=self._poll, args=(seq, out, 30))
        th.start()
        time.sleep(0.2)
        self.svc.bus.close()
        th.join(3)
        self.assertFalse(th.is_alive())


class TestBus(unittest.TestCase):
    def test_fresh_seq_is_not_zero(self):
        # since=0 means "current seq now"; a fresh bus must not return 0 or long-poll busy-loops
        b = EventBus()
        self.assertGreaterEqual(b.wait(0, 0)["seq"], 1)
        t = time.monotonic()
        self.assertEqual(b.wait(b.seq, 0.3)["changed"], [])
        self.assertGreaterEqual(time.monotonic() - t, 0.25)

    def test_restart_and_union(self):
        b = EventBus()
        b.publish("colony")
        b.publish("status")
        self.assertEqual(b.wait(2, 1)["changed"], ["status"])
        self.assertEqual(b.wait(0, 0)["changed"], [])
        self.assertEqual(sorted(b.wait(99, 0)["changed"]), ["action", "art", "build", "colony", "connect", "controls", "gamedata", "pad", "settings", "status", "sync"])
        self.assertEqual(b.publish("bogus"), b.seq)


class TestColony(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-c3-")
        self.live = os.path.join(self.tmp, "live.json")
        self.saves = os.path.join(self.tmp, "saves")
        self.c = colony_mod.Colony(self.live, [self.saves])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_order(self):
        self.assertEqual(self.c.facts()["source"], "none")
        make_sav(os.path.join(self.saves, "1", "Alpha", "Alpha Cycle 7.sav"), cycles=7)
        f = self.c.facts()
        self.assertEqual((f["source"], f["state"], f["colonyName"], f["cycle"]),
                         ("header", "saved", "Alpha", 8))  # header numberOfCycles is zero-based
        atomic_write(self.live, live_text())
        f = self.c.facts()
        self.assertEqual((f["source"], f["state"]), ("mod-live", "running"))
        self.assertEqual(V_ok(f), [])
        atomic_write(self.live, live_text(state="menu"))
        f = self.c.facts()
        self.assertEqual((f["source"], f["state"]), ("header", "saved"))
        atomic_write(self.live, live_text(written=time.time() - 120))
        self.assertEqual(self.c.facts()["source"], "header")        # stale
        atomic_write(self.live, live_text(written=time.time() - 120, paused=True))
        self.assertEqual(self.c.facts()["source"], "mod-live")      # paused is quiet, still ok
        atomic_write(self.live, "{ broken")
        self.assertEqual(self.c.facts()["source"], "header")

    def test_save_parser_hook_and_world(self):
        make_sav(os.path.join(self.saves, "A", "A.sav"))
        calls = []

        def parser(path):
            calls.append(path)
            return {"cycle": 9, "worlds": [{"id": 0, "name": "W", "dupes": []}]}
        c = colony_mod.Colony(self.live, [self.saves], parser)
        f = c.facts()
        c.facts()
        self.assertEqual((f["source"], f["cycle"], len(calls)), ("save", 9, 1))   # cached
        c2 = colony_mod.Colony(self.live, [self.saves], lambda p: 1 / 0)
        self.assertEqual(c2.facts()["source"], "header")           # parser bug -> fallback
        atomic_write(self.live, live_text())
        with self.assertRaises(KeyError):
            self.c.facts(world="99")
        self.assertEqual(self.c.facts(world="0")["worlds"][0]["id"], 0)

    def test_status_fields(self):
        atomic_write(self.live, live_text())
        make_sav(os.path.join(self.saves, "B", "B Cycle 3.sav"))
        s = self.c.status_fields()
        self.assertEqual(s["colony"]["source"], "mod-live")
        self.assertTrue(s["liveFresh"])
        self.assertEqual(s["newestSave"]["name"], "B Cycle 3")


def V_ok(facts):
    return V.validate({"schema": 1, "title": "x", "blocks": [], "raw": facts},
                      "api.schema.json#/$defs/ColonyReply")


class TestMain(unittest.TestCase):
    def test_non_loopback_exits(self):
        for argv in (["--mode", "standalone", "--listen", "0.0.0.0:9000"],
                     ["--mode", "standalone", "--listen", "192.168.1.5:9000"],
                     ["--mode", "barry", "--listen", "0.0.0.0:9000"]):
            with self.assertRaises(SystemExit) as cm:
                build_config(argv, {"BARRY_SERVICE_PORT": "1", "BARRY_SERVICE_TOKEN": "t"})
            self.assertIn("not in v1", str(cm.exception))

    def test_barry_env(self):
        with self.assertRaises(SystemExit):
            build_config(["--mode", "barry"], {})
        cfg = build_config(["--mode", "barry", "--user-dir", "/nonexistent"],
                           {"BARRY_SERVICE_PORT": "4242", "BARRY_SERVICE_TOKEN": "tt"})
        self.assertEqual((cfg.host, cfg.port, cfg.token, cfg.barry_mode),
                         ("127.0.0.1", 4242, "tt", True))
        cfg = build_config(["--mode", "standalone", "--listen", "127.0.0.1:0", "--user-dir", "/x"], {})
        self.assertEqual(cfg.host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
