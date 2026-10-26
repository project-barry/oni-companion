"""Lane S1: art & font sync in the core. GET/POST /sync, needed detection, the `sync` event, the command, a fake mod.
Synthetic data only; no game files, no Nova."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import sync as sync_mod  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from oni_companion.watch import make_watcher  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402
from tests.test_c3_server import TOKEN, atomic_write, http, live_text  # noqa: E402

CONTRACTS = os.path.join(ROOT, "contracts")
V = Validator(CONTRACTS)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def status_doc(state="running", scope="full", done=10, total=100, build=100001, dlc=("DLC_ALPHA_ID",), started=None,
               updated=None, **extra):
    now = time.time()
    d = {"schema": 1, "modVersion": "0.3.0", "state": state, "scope": scope, "build": build, "dlcIds": list(dlc),
         "done": done, "total": total, "current": "building: SynthWidget" if state == "running" else None, "errors": 0,
         "stages": [{"name": "art", "state": "running"}, {"name": "theme", "state": "pending"},
                    {"name": "fonts", "state": "pending"}],
         "gamePausedBySync": state == "running",
         "startedAt": iso(started if started is not None else now), "updatedAt": iso(updated if updated is not None else now),
         "elapsedMs": 1000}
    d.update(extra)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-s1-"))
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.comp, "live"))
        self.live()
        self.svc = None
        self.mods = []

    def tearDown(self):
        if self.svc:
            self.svc.stop()
        for m in self.mods:
            m.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live(self, state="running", **kw):
        atomic_write(os.path.join(self.comp, "live", "live.json"), live_text(state=state, **kw))

    def write_status(self, **kw):
        atomic_write(os.path.join(self.comp, "sync", "status.json"), json.dumps(status_doc(**kw)))

    ttf = False

    def start(self):
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        self.svc = Service(cfg).start()
        self.svc.sync.ttf_hook = lambda build: self.ttf      # the font extractor has its own tests
        return self.svc

    def get(self, path="/api/v1/sync"):
        return http(self.svc, path)

    def post(self, body=None, path="/api/v1/sync"):
        return http(self.svc, path, method="POST", body={} if body is None else body)

    def cmds(self):
        d = os.path.join(self.comp, "commands")
        out = []
        try:
            for n in sorted(os.listdir(d)):
                if n.startswith("cmd-") and n.endswith(".json"):
                    with open(os.path.join(d, n)) as f:
                        out.append(json.load(f))
        except OSError:
            pass
        return out


def wait_for(fn, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


class TestNeeded(Base):
    def test_no_status_means_no_pack(self):
        self.start()
        st, d = self.get()
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])
        self.assertEqual((d["state"], d["needed"], d["neededReason"], d["suggestedScope"]), ("idle", True, "no_pack", "full"))
        self.assertTrue(d["canStart"])
        self.assertEqual(d["fonts"], "none")

    def test_done_same_build_and_dlc_is_not_needed(self):
        self.write_status(state="done", done=5, total=5)
        self.start()
        _, d = self.get()
        self.assertEqual((d["state"], d["needed"]), ("done", False))
        self.assertNotIn("neededReason", d)
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])

    def test_new_build_needs_full(self):
        self.write_status(state="done", build=100000)
        self.start()
        _, d = self.get()
        self.assertEqual((d["needed"], d["neededReason"], d["suggestedScope"]), (True, "new_build", "full"))

    def test_new_dlc_needs_missing_only(self):
        self.write_status(state="done", dlc=())
        self.start()
        _, d = self.get()
        self.assertEqual((d["needed"], d["neededReason"], d["suggestedScope"]), (True, "new_dlc", "missing"))

    def test_failed_or_cut_off_run_after_a_good_one_keeps_the_pack(self):
        self.write_status(state="done", done=5, total=5)
        self.start()
        self.assertFalse(self.get()[1]["needed"])
        for state in ("failed", "running"):
            self.write_status(state=state, scope="missing")
            _, d = self.get()
            self.assertFalse(d["needed"], state)
            self.assertNotIn("neededReason", d)

    def test_failed_run_is_still_needed(self):
        self.write_status(state="failed", lastError="No colony loaded")
        self.start()
        _, d = self.get()
        self.assertEqual((d["state"], d["needed"], d["neededReason"]), ("failed", True, "no_pack"))
        self.assertEqual(d["lastError"], "No colony loaded")

    def test_menu_and_no_mod(self):
        self.live(state="menu")
        self.start()
        _, d = self.get()
        self.assertEqual((d["canStart"], d["reason"]), (False, "menu"))
        shutil.rmtree(os.path.join(self.comp, "live"))
        _, d = self.get()
        self.assertEqual((d["canStart"], d["reason"]), (False, "no_mod"))
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])

    def test_old_live_is_no_mod(self):
        self.live(written=time.time() - 300)
        self.start()
        _, d = self.get()
        self.assertEqual((d["canStart"], d["reason"]), (False, "no_mod"))

    def test_menu_uses_manifest_for_the_build(self):
        self.live(state="menu")
        os.makedirs(os.path.join(self.comp, "art"))
        atomic_write(os.path.join(self.comp, "art", "manifest.json"),
                     json.dumps({"schema": 1, "modVersion": "0.3.0", "build": 100001, "dlcIds": ["DLC_ALPHA_ID"],
                                 "writtenAt": iso(time.time()), "files": []}))
        self.write_status(state="done")
        self.start()
        _, d = self.get()
        self.assertFalse(d["needed"])

    def test_fonts_state(self):
        self.start()
        fd = os.path.join(self.comp, "fonts", "100001")
        os.makedirs(fd)
        self.assertEqual(self.get()[1]["fonts"], "none")
        open(os.path.join(fd, "graystroke.png"), "wb").close()
        self.assertEqual(self.get()[1]["fonts"], "none")      # both files or nothing
        open(os.path.join(fd, "graystroke.json"), "w").close()
        self.svc.sync.ttf_hook = lambda build: True
        self.assertEqual(self.get()[1]["fonts"], "ready")
        self.svc.sync.ttf_hook = lambda build: False
        self.assertEqual(self.get()[1]["fonts"], "partial")
        self.svc.sync.ttf_hook = lambda build: True
        self.assertEqual(self.get()[1]["fonts"], "ready")


class TestProgress(Base):
    def test_running_status_passes_through(self):
        self.write_status(done=312, total=1033, scope="missing")
        self.start()
        _, d = self.get()
        self.assertEqual((d["state"], d["scope"], d["done"], d["total"]), ("running", "missing", 312, 1033))
        self.assertEqual(d["current"], "building: SynthWidget")
        self.assertTrue(d["canStart"])
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])

    def test_running_while_menu_live_still_reports_running(self):
        self.live(state="menu")
        self.write_status()
        self.start()
        _, d = self.get()
        self.assertEqual(d["state"], "running")
        self.assertNotIn("reason", d)

    def test_stale_running_status_is_failed(self):
        self.write_status(updated=time.time() - 60)
        self.start()
        _, d = self.get()
        self.assertEqual(d["state"], "failed")
        self.assertIn("stopped answering", d["lastError"])

    def test_invalid_status_is_ignored(self):
        atomic_write(os.path.join(self.comp, "sync", "status.json"), '{"schema":1,"state":"nope"}')
        self.start()
        _, d = self.get()
        self.assertEqual(d["state"], "idle")
        atomic_write(os.path.join(self.comp, "sync", "status.json"), "{not json")
        self.assertEqual(self.get()[1]["state"], "idle")


class TestPost(Base):
    def test_post_writes_a_command_and_shows_running(self):
        self.start()
        st, d = self.post({"scope": "full"})
        self.assertEqual(st, 200)
        self.assertEqual((d["state"], d["scope"], d["done"], d["total"]), ("running", "full", 0, 0))
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])
        cmds = self.cmds()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(V.validate(cmds[0], "mod-command.schema.json"), [])
        self.assertEqual((cmds[0]["type"], cmds[0]["scope"]), ("sync_assets", "full"))
        # a second POST while pending: the same running answer, no second command
        st, d2 = self.post({"scope": "missing"})
        self.assertEqual((st, d2["state"]), (200, "running"))
        self.assertEqual(len(self.cmds()), 1)

    def test_default_scope_is_suggested(self):
        self.write_status(state="done", dlc=())
        self.start()
        self.post()
        self.assertEqual(self.cmds()[0]["scope"], "missing")

    def test_default_scope_full_without_pack(self):
        self.start()
        self.post()
        self.assertEqual(self.cmds()[0]["scope"], "full")

    def test_bad_bodies(self):
        self.start()
        for body in ({"scope": "everything"}, {"scope": 1}, {"scope": "full", "x": 1}, [1]):
            st, d = self.post(body)
            self.assertEqual((st, d["error"]["code"]), (400, "bad_request"), body)
        self.assertEqual(self.cmds(), [])

    def test_menu_queues_and_sends_when_a_colony_runs(self):
        self.live(state="menu")
        self.start()
        st, d = self.post({"scope": "full"})
        self.assertEqual((st, d["state"], d.get("queued"), d["canStart"]), (200, "idle", True, False))
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/Sync"), [])
        self.assertEqual(self.cmds(), [])
        self.live()                                       # the colony is loaded: the queued sync goes out by itself
        got = wait_for(self.cmds)
        self.assertEqual([(c["type"], c["scope"]) for c in got], [("sync_assets", "full")])
        st, d = self.get()
        self.assertNotIn("queued", d)
        self.assertEqual(d["state"], "running")

    def test_cancel_drops_a_queued_sync(self):
        self.live(state="menu")
        self.start()
        self.post({})
        st, d = self.post({"cancel": True})
        self.assertEqual((st, d.get("queued")), (200, None))
        self.live()
        time.sleep(0.5)
        self.assertEqual(self.cmds(), [])

    def test_running_sync_is_returned_unchanged(self):
        self.write_status(done=3, total=9)
        self.start()
        st, d = self.post({"scope": "missing"})
        self.assertEqual((st, d["state"], d["done"], d["scope"]), (200, "running", 3, "full"))
        self.assertEqual(self.cmds(), [])

    def test_failed_ack_shows_the_reason(self):
        self.start()
        self.post({"scope": "full"})
        seq = self.cmds()[0]["seq"]
        os.makedirs(os.path.join(self.comp, "acks"), exist_ok=True)
        atomic_write(os.path.join(self.comp, "acks", "ack-%d.json" % seq), json.dumps(
            {"schema": 1, "seq": seq, "state": "failed", "message": "No colony loaded", "ackedAt": iso(time.time())}))
        d = wait_for(lambda: (lambda r: r if r["state"] == "failed" else None)(self.get()[1]))
        self.assertEqual(d["state"], "failed")
        self.assertEqual(d["lastError"], "No colony loaded")
        self.assertEqual(self.cmds(), [])           # the command file was dropped

    def test_old_done_status_is_not_the_new_run(self):
        self.write_status(state="done", started=time.time() - 3600, updated=time.time() - 3600)
        self.start()
        _, d = self.post({"scope": "full"})
        self.assertEqual((d["state"], d["done"]), ("running", 0))     # not "done" from the earlier run

    def test_pending_times_out(self):
        self.start()
        self.post({"scope": "full"})
        self.svc.sync.clock = lambda: time.time() + 60        # the mod never showed the run
        _, d = self.get()
        self.assertNotEqual(d["state"], "running")


class FakeMod:
    """Test double: reads sync_assets, acks, then writes status files like the mod (running... done)."""

    def __init__(self, base, steps=4):
        self.base, self.steps = base, steps
        self.seen = []
        os.makedirs(os.path.join(base.comp, "commands"), exist_ok=True)
        os.makedirs(os.path.join(base.comp, "acks"), exist_ok=True)
        self._w = make_watcher([os.path.join(base.comp, "commands")], self._on, recursive=False).start()

    def _on(self, path, what):
        n = os.path.basename(path)
        if what == "removed" or not (n.startswith("cmd-") and n.endswith(".json")):
            return
        try:
            with open(path, "rb") as f:
                d = json.loads(f.read().decode())
        except (OSError, ValueError):
            return
        if d["seq"] in self.seen or d.get("type") != "sync_assets":
            return
        self.seen.append(d["seq"])
        atomic_write(os.path.join(self.base.comp, "acks", "ack-%d.json" % d["seq"]), json.dumps(
            {"schema": 1, "seq": d["seq"], "state": "done", "message": "Started", "ackedAt": iso(time.time())}))
        threading.Thread(target=self._run, args=(d["scope"],), daemon=True).start()

    def _run(self, scope):
        t0 = time.time()
        for i in range(self.steps + 1):
            self.base.write_status(state="running", scope=scope, done=i * 10, total=self.steps * 10, started=t0)
            time.sleep(0.05)
        self.base.write_status(state="done", scope=scope, done=self.steps * 10, total=self.steps * 10, started=t0)
        fd = os.path.join(self.base.comp, "fonts", "100001")
        os.makedirs(fd, exist_ok=True)
        open(os.path.join(fd, "graystroke.png"), "wb").close()
        open(os.path.join(fd, "graystroke.json"), "w").close()

    def stop(self):
        self._w.stop()


class TestChain(Base):
    def wait_event(self, since, name, timeout=5):
        end = time.time() + timeout
        seq = since
        while time.time() < end:
            _, ev = http(self.svc, "/api/v1/events?since=%d&timeout=1" % seq)
            seq = ev["seq"]
            if name in ev["changed"]:
                return seq
        return None

    def test_whole_run_with_events(self):
        self.mods.append(FakeMod(self))
        self.ttf = True
        self.start()
        _, ev = http(self.svc, "/api/v1/events?since=0")
        seq = ev["seq"]
        self.post({"scope": "full"})
        self.assertIsNotNone(self.wait_event(seq, "sync"))
        d = wait_for(lambda: (lambda r: r if r["state"] == "done" else None)(self.get()[1]), 8)
        self.assertEqual(d["state"], "done")
        self.assertEqual((d["done"], d["total"]), (40, 40))
        self.assertFalse(d["needed"])
        wait_for(lambda: self.get()[1]["fonts"] == "ready")
        self.assertEqual(self.get()[1]["fonts"], "ready")

    def test_live_change_sends_sync_event_only_when_it_matters(self):
        self.start()
        _, ev = http(self.svc, "/api/v1/events?since=0")
        seq = ev["seq"]
        self.live(state="menu")                 # canStart flips
        self.assertIsNotNone(self.wait_event(seq, "sync"))
        _, ev = http(self.svc, "/api/v1/events?since=0")
        seq = ev["seq"]
        self.live(state="menu", cycle=99)       # nothing the sync cares about changed
        got = self.wait_event(seq, "colony", 3)
        self.assertIsNotNone(got)
        _, ev = http(self.svc, "/api/v1/events?since=%d&timeout=0" % seq)
        self.assertNotIn("sync", ev["changed"])


if __name__ == "__main__":
    unittest.main()
