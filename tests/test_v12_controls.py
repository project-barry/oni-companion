"""v1.2 C12: GET/POST /api/v1/controls, the `controls` event, pending until live.json confirms.

Synthetic live.json only. The core writes companion/commands/ and nothing else; no game is touched.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import colony as colony_mod  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402  (import order: server before actions)
from oni_companion.actions import ActionService  # noqa: E402
from oni_companion.colony import Colony  # noqa: E402
from oni_companion.controls import Controls  # noqa: E402
from oni_companion.server.errors import ApiError  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from tests.test_c3_server import TOKEN, V, atomic_write, http, live_text  # noqa: E402

SCHEMA = "api.schema.json#/$defs/Controls"


class FakeClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c12-ctl-"))
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.comp, "live"))
        self.live = os.path.join(self.comp, "live", "live.json")
        self.svc = None

    def tearDown(self):
        if self.svc:
            self.svc.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self):
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        return self.svc

    def commands(self):
        d = os.path.join(self.comp, "commands")
        if not os.path.isdir(d):
            return []
        out = []
        for n in sorted(os.listdir(d)):
            if n.startswith("cmd-") and n.endswith(".json"):
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def ok(self, data):
        self.assertEqual(V.validate(data, SCHEMA), [])


class TestAvailability(Base):
    def get(self):
        status, body = http(self.start(), "/api/v1/controls")
        self.assertEqual(status, 200)
        self.ok(body)
        return body

    def test_running_and_fresh_is_available(self):
        atomic_write(self.live, live_text(paused=False))
        body = self.get()
        self.assertEqual((body["available"], body["paused"], body["speed"]), (True, False, 2))
        self.assertNotIn("reason", body)
        self.assertNotIn("pending", body)
        self.assertIn("asOf", body)

    def test_menu_is_unavailable(self):
        atomic_write(self.live, live_text(state="menu"))
        body = self.get()
        self.assertEqual((body["available"], body["reason"]), (False, "menu"))

    def test_stale_live_is_unavailable(self):
        atomic_write(self.live, live_text(written=time.time() - 120))
        body = self.get()
        self.assertEqual((body["available"], body["reason"]), (False, "stale"))
        self.assertIn("paused", body)           # last known values stay

    def test_no_live_file_means_no_mod(self):
        body = self.get()
        self.assertEqual((body["available"], body["reason"]), (False, "no_mod"))
        self.assertNotIn("paused", body)

    def test_no_companion_folder_means_no_mod(self):
        c = Controls(ActionService(None, lambda n: None), Colony(None), lambda *n: None, None)
        self.assertEqual(c.availability()[:2], (False, "no_mod"))
        self.assertEqual(c.get(), {"available": False, "reason": "no_mod",
                                   "game": {"state": "not_running", "label": "Game not running", "tone": "neutral"}})


class TestGameState(Base):
    """The header's game state (user, 2026-10-25: "Connected" said nothing about the game)."""

    def state(self, **kw):
        atomic_write(self.live, live_text(**kw))
        svc = self.start()
        try:
            return svc.controls.get()["game"]["state"]
        finally:
            self.svc.stop()
            self.svc = None

    def test_states(self):
        self.assertEqual(self.state(paused=False), "live")
        self.assertEqual(self.state(paused=True), "paused")
        self.assertEqual(self.state(state="menu"), "menu")

    def test_stopped_and_old_menu_are_not_running(self):
        atomic_write(self.live, json.dumps({"schema": 2, "seq": 1, "state": "stopped", "writtenAt": "2026-10-25T20:00:00Z", "modVersion": "0.4.1"}))
        svc = self.start()
        self.assertEqual(svc.controls.get()["game"]["state"], "not_running")
        atomic_write(self.live, json.dumps({"schema": 2, "seq": 2, "state": "menu", "writtenAt": "2020-01-01T00:00:00Z", "modVersion": "0.4.1"}))
        self.assertEqual(svc.controls.get()["game"]["state"], "not_running")

    def test_reply_validates(self):
        atomic_write(self.live, live_text(paused=True))
        svc = self.start()
        self.ok(svc.controls.get())


class TestPost(Base):
    def test_play_speed_writes_one_command_and_reports_pending(self):
        atomic_write(self.live, live_text(paused=True))
        svc = self.start()
        before = svc.bus.seq
        status, body = http(svc, "/api/v1/controls", "POST", body={"state": "play", "speed": 3})
        self.assertEqual(status, 200)
        self.ok(body)
        self.assertEqual(body["pending"]["state"], "play")
        self.assertEqual(body["pending"]["speed"], 3)
        self.assertGreaterEqual(body["pending"]["seq"], 1)
        cmds = self.commands()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["type"], "set_speed")
        self.assertEqual((cmds[0]["state"], cmds[0]["speed"]), ("play", 3))
        self.assertEqual(cmds[0]["seq"], body["pending"]["seq"])
        self.assertIn("controls", svc.bus.wait(before, 0)["changed"])

    def test_pause_has_no_speed_in_the_command(self):
        atomic_write(self.live, live_text(paused=False))
        svc = self.start()
        status, body = http(svc, "/api/v1/controls", "POST", body={"state": "pause"})
        self.assertEqual(status, 200)
        self.ok(body)
        self.assertEqual(body["pending"]["state"], "pause")
        self.assertNotIn("speed", body["pending"])
        cmd = self.commands()[0]
        self.assertEqual(cmd, {"schema": 1, "seq": cmd["seq"], "createdAt": cmd["createdAt"],
                               "type": "set_speed", "state": "pause"})

    def test_bad_bodies_are_400_and_write_nothing(self):
        atomic_write(self.live, live_text())
        svc = self.start()
        bad = ({"state": "stop"}, {"state": "pause", "speed": 2}, {"state": "play", "speed": 4},
               {"state": "play", "speed": True}, {"state": "play", "speed": 2.0},
               {"state": "play", "speed": None}, {"state": "play", "extra": 1}, {}, [], None)
        for b in bad:
            status, body = http(svc, "/api/v1/controls", "POST", body=b)
            self.assertEqual((status, body["error"]["code"]), (400, "bad_request"), b)
        self.assertEqual(self.commands(), [])

    def test_unavailable_is_503_and_writes_nothing(self):
        atomic_write(self.live, live_text(state="menu"))
        svc = self.start()
        status, body = http(svc, "/api/v1/controls", "POST", body={"state": "pause"})
        self.assertEqual((status, body["error"]["code"]), (503, "unavailable"))
        self.assertEqual(self.commands(), [])

    def test_post_when_already_in_that_state_confirms_at_once(self):
        atomic_write(self.live, live_text(paused=False, cycle=12))
        svc = self.start()
        status, body = http(svc, "/api/v1/controls", "POST", body={"state": "play", "speed": 2})
        self.assertEqual(status, 200)
        self.assertNotIn("pending", body)


class TestPendingLifecycle(Base):
    """Unit level with a fake clock, so the 10 s limit is exact."""

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.events = []
        self.actions = ActionService(self.comp, lambda n: None, clock=self.clock)
        self.colony = Colony(self.live, clock=self.clock)
        self.c = Controls(self.actions, self.colony, self.events.append, self.comp, clock=self.clock)

    def write_live(self, paused, speed=3, written=None):
        d = json.loads(live_text(paused=paused))
        d["speed"] = speed
        d["writtenAt"] = colony_mod.iso(self.clock.t if written is None else written)
        atomic_write(self.live, json.dumps(d))

    def test_pending_clears_when_live_confirms_and_not_before(self):
        self.write_live(paused=True, speed=2)
        self.c.post({"state": "play", "speed": 3})
        self.assertEqual(self.events, ["controls"])
        self.assertEqual(self.c.get()["pending"]["speed"], 3)
        self.write_live(paused=False, speed=2)            # play, but still the old speed
        self.assertIn("pending", self.c.get())
        self.write_live(paused=False, speed=3)            # confirmed
        body = self.c.get()
        self.assertNotIn("pending", body)
        self.assertEqual((body["paused"], body["speed"]), (False, 3))
        self.ok(body)

    def test_pause_confirms_on_paused_true(self):
        self.write_live(paused=False)
        self.c.post({"state": "pause"})
        self.assertIn("pending", self.c.get())
        self.write_live(paused=True)
        self.assertNotIn("pending", self.c.get())

    def test_speed_keeps_the_pause_and_confirms_on_the_speed(self):
        self.write_live(paused=True, speed=1)
        self.c.post({"state": "speed", "speed": 3})
        self.assertEqual(self.c.get()["pending"], {"state": "speed", "speed": 3, "seq": self.c.get()["pending"]["seq"]})
        self.write_live(paused=True, speed=3)             # still paused: that is what the game's speed buttons do
        body = self.c.get()
        self.assertNotIn("pending", body)
        self.assertEqual((body["paused"], body["speed"]), (True, 3))
        self.ok(body)

    def test_pending_expires_after_ten_seconds(self):
        self.write_live(paused=True)
        self.c.post({"state": "play"})
        self.clock.t += 9.5
        self.assertIn("pending", self.c.get())
        self.clock.t += 1.0
        self.assertNotIn("pending", self.c.get())

    def test_unavailable_drops_pending(self):
        self.write_live(paused=False)
        self.c.post({"state": "play"})
        self.write_live(paused=False, written=self.clock.t - 60)    # stale (a paused game gets 600 s)
        body = self.c.get()
        self.assertEqual((body["available"], body["reason"]), (False, "stale"))
        self.assertNotIn("pending", body)
        self.write_live(paused=False)                                 # fresh again: nothing pending
        self.assertNotIn("pending", self.c.get())

    def test_new_post_replaces_pending(self):
        self.write_live(paused=False)
        first = self.c.post({"state": "play", "speed": 1})["pending"]
        second = self.c.post({"state": "pause"})["pending"]
        self.assertGreater(second["seq"], first["seq"])
        self.assertEqual(second["state"], "pause")
        self.assertNotIn("speed", second)

    def test_parse_post_rules(self):
        self.assertEqual(Controls.parse_post({"state": "pause"}), ("pause", None))
        self.assertEqual(Controls.parse_post({"state": "play", "speed": 1}), ("play", 1))
        self.assertEqual(Controls.parse_post({"state": "speed", "speed": 2}), ("speed", 2))
        with self.assertRaises(ApiError):
            Controls.parse_post({"state": "speed"})
        with self.assertRaises(ApiError):
            Controls.parse_post({"state": "play", "speed": 0})


class TestEventName(Base):
    def test_live_file_change_names_controls(self):
        svc = self.start()
        self.assertIn("controls", svc.classify(self.live))
        self.assertNotIn("controls", svc.classify(os.path.join(self.comp, "live", "other.json")))


if __name__ == "__main__":
    unittest.main()
