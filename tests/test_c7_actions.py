"""C7: actions (POST /actions/focus, GET /actions/<seq>, 'action' event) and devtools/push-commands.py.

A fake mod (test double) turns command files into acks. The Nova is never touched: push-commands runs
against a fake ssh that executes the remote command into a temp dir.
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import colony as colony_mod  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from oni_companion.watch import make_watcher  # noqa: E402
from tests.test_c3_server import TOKEN, V, atomic_write, http, live_text  # noqa: E402

spec = importlib.util.spec_from_file_location("push_commands", os.path.join(ROOT, "devtools", "push-commands.py"))
push_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push_mod)

KNOWN = {"d1", "d2"}


def now_iso(offset=0):
    return colony_mod.iso(time.time() + offset)


class FakeMod:
    """Test double for the mod: allow list, age limit, target lookup, then an ack and the file removed."""

    def __init__(self, companion, known=KNOWN, latency=0.0):
        self.cmd = os.path.join(companion, "commands")
        self.ack = os.path.join(companion, "acks")
        os.makedirs(self.cmd, exist_ok=True)
        os.makedirs(self.ack, exist_ok=True)
        self.known, self.latency = known, latency
        self.ran = []
        self._w = make_watcher([self.cmd], self._on, recursive=False).start()

    def _on(self, path, what):
        n = os.path.basename(path)
        if what == "removed" or not n.startswith("cmd-") or not n.endswith(".json"):
            return
        try:
            with open(path, "rb") as f:
                d = json.loads(f.read().decode())
        except (OSError, ValueError):
            return
        if self.latency:
            time.sleep(self.latency)
        ack = {"schema": 1, "seq": d["seq"], "ackedAt": now_iso()}
        age = time.time() - colony_mod.parse_iso(d["createdAt"])
        if d.get("type") != "focus":
            ack.update(state="failed", message="Unknown command")
        elif age > 10:
            ack.update(state="failed", message="Command too old")
        elif d["target"]["id"] not in self.known:
            ack.update(state="failed", message="Duplicant not found")
        else:
            ack.update(state="done")
            self.ran.append(d)
        atomic_write(os.path.join(self.ack, "ack-%d.json" % d["seq"]), json.dumps(ack))
        try:
            os.unlink(path)
        except OSError:
            pass

    def stop(self):
        self._w.stop()


class Env(unittest.TestCase):
    expire = None

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c7-"))
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.comp, "live"))
        self.live = os.path.join(self.comp, "live", "live.json")
        atomic_write(self.live, live_text())
        self.mods = []
        self.svc = None

    def start(self):
        cfg = ServiceConfig(user_dir=self.user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
        if self.expire:
            cfg.action_expire = self.expire
        self.svc = Service(cfg).start()
        return self.svc

    def mod(self, **kw):
        m = FakeMod(self.comp, **kw)
        self.mods.append(m)
        return m

    def tearDown(self):
        if self.svc:
            self.svc.stop()
        for m in self.mods:
            m.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, body, action="focus"):
        return http(self.svc, "/api/v1/actions/" + action, method="POST", body=body)

    def get(self, seq):
        return http(self.svc, "/api/v1/actions/%s" % seq)

    def wait_state(self, seq, want, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            st, d = self.get(seq)
            if st == 200 and d["state"] in want:
                return d
            time.sleep(0.02)
        self.fail("state of %s never became %s (last %s)" % (seq, want, d))


FOCUS = {"target": {"kind": "dupe", "id": "d1"}, "select": True}


class TestPostAndStatus(Env):
    def test_command_file_is_atomic_and_valid(self):
        self.start()
        st, body = self.post(FOCUS)
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/ActionSent"), [])
        seq = body["seq"]
        cmds = os.listdir(os.path.join(self.comp, "commands"))
        self.assertEqual(cmds, ["cmd-%d.json" % seq])             # no .tmp left behind
        with open(os.path.join(self.comp, "commands", cmds[0])) as f:
            d = json.load(f)
        self.assertEqual(V.validate(d, "mod-command.schema.json"), [])
        self.assertEqual((d["seq"], d["type"], d["select"], d["target"]), (seq, "focus", True, FOCUS["target"]))
        st, s = self.get(seq)
        self.assertEqual((st, s), (200, {"seq": seq, "state": "pending"}))
        self.assertEqual(V.validate(s, "api.schema.json#/$defs/ActionStatus"), [])

    def test_select_defaults_true_and_false_is_kept(self):
        self.start()
        a = self.post({"target": FOCUS["target"]})[1]["seq"]
        b = self.post({"target": FOCUS["target"], "select": False})[1]["seq"]
        for seq, want in ((a, True), (b, False)):
            with open(os.path.join(self.comp, "commands", "cmd-%d.json" % seq)) as f:
                self.assertIs(json.load(f)["select"], want)
        self.assertGreater(b, a)

    def test_bad_requests(self):
        self.start()
        bads = [{}, {"target": {"kind": "dupe"}}, {"target": {"kind": "building", "id": "x"}},
                {"target": {"kind": "dupe", "id": ""}}, {"target": {"kind": "dupe", "id": 5}},
                {"target": FOCUS["target"], "select": "yes"}, {"target": FOCUS["target"], "path": "/etc"},
                {"target": {"kind": "dupe", "id": "d1", "x": 1}}, [], "focus"]
        for b in bads:
            st, body = self.post(b)
            self.assertEqual((st, body["error"]["code"]), (400, "bad_request"), b)
            self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [])
        self.assertEqual(os.listdir(os.path.join(self.comp)) .count("commands"), 0)   # nothing written
        st, body = self.post(FOCUS, action="teleport")
        self.assertEqual((st, body["error"]["code"]), (404, "not_found"))
        for bad in ("abc", "0", "-3", "1.5"):
            self.assertEqual(self.get(bad)[0], 400, bad)
        self.assertEqual(self.get(99)[0], 404)
        # the unknown-action check comes before body checks, the allow list is the only list
        st, _ = http(self.svc, "/api/v1/actions/focus", method="DELETE")
        self.assertEqual(st, 404)

    def test_token_needed(self):
        self.start()
        st, body = http(self.svc, "/api/v1/actions/focus", method="POST", headers={}, body=FOCUS)
        self.assertEqual((st, body["error"]["code"]), (403, "bad_token"))
        st, _ = http(self.svc, "/api/v1/actions/1", headers={})
        self.assertEqual(st, 403)


class TestUnavailable(Env):
    def check(self, text_part):
        st, body = self.post(FOCUS)
        self.assertEqual((st, body["error"]["code"]), (503, "unavailable"))
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [])
        self.assertIn(text_part, body["error"]["message"])
        self.assertFalse(os.path.exists(os.path.join(self.comp, "commands")))     # nothing was written

    def test_no_mod_folder(self):
        shutil.rmtree(self.comp)
        self.start()
        self.check("game is not running")

    def test_no_live_file(self):
        os.unlink(self.live)
        self.start()
        self.check("game is not running")

    def test_menu(self):
        atomic_write(self.live, live_text(state="menu"))
        self.start()
        self.check("in the menu")

    def test_stale_live(self):
        atomic_write(self.live, live_text(written=time.time() - 120))
        self.start()
        self.check("not sending data")

    def test_paused_game_is_fresh_for_long(self):
        atomic_write(self.live, live_text(written=time.time() - 120, paused=True))
        self.start()
        self.assertEqual(self.post(FOCUS)[0], 200)

    def test_schema2_live_is_accepted(self):
        with open(os.path.join(ROOT, "fixtures", "synthetic", "mod", "live-running-v2.json")) as f:
            d = json.load(f)
        d["writtenAt"] = now_iso()
        d["state"] = "running"
        atomic_write(self.live, json.dumps(d))
        self.start()
        self.assertEqual(self.post(FOCUS)[0], 200)

    def test_inbox_cannot_be_written(self):
        open(os.path.join(self.comp, "commands"), "w").close()     # a file where the folder should be
        self.start()
        st, body = self.post(FOCUS)
        self.assertEqual((st, body["error"]["code"]), (503, "unavailable"))


class TestAcks(Env):
    def events(self, since, timeout=5):
        return http(self.svc, "/api/v1/events?since=%d&timeout=%s" % (since, timeout), timeout=timeout + 5)[1]

    def test_done_with_fake_mod_and_event(self):
        self.start()
        m = self.mod()
        since = self.events(0)["seq"]
        got = {}

        def wait():
            got.update(self.events(since))
        t = threading.Thread(target=wait)
        t.start()
        time.sleep(0.2)
        t0 = time.time()
        seq = self.post(FOCUS)[1]["seq"]
        t.join(6)
        self.assertIn("action", got["changed"])
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(self.get(seq)[1], {"seq": seq, "state": "done"})
        self.assertEqual(m.ran[0]["target"]["id"], "d1")
        self.assertEqual(os.listdir(os.path.join(self.comp, "commands")), [])   # the inbox is empty again
        self.assertEqual(V.validate(got, "api.schema.json#/$defs/Events"), [])

    def test_failed_message(self):
        self.start()
        self.mod()
        seq = self.post({"target": {"kind": "dupe", "id": "nobody"}})[1]["seq"]
        d = self.wait_state(seq, ("failed",))
        self.assertEqual(d, {"seq": seq, "state": "failed", "message": "Duplicant not found"})
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/ActionStatus"), [])

    def test_invalid_acks_are_ignored(self):
        self.start()
        seq = self.post(FOCUS)[1]["seq"]
        ack = os.path.join(self.comp, "acks")
        os.makedirs(ack)
        for name, text in (("ack-%d.json" % seq, "{not json"),
                           ("ack-%d.json" % seq, json.dumps({"schema": 1, "seq": seq + 1, "state": "done", "ackedAt": now_iso()})),
                           ("ack-%d.json" % seq, json.dumps({"schema": 1, "seq": seq, "state": "bogus", "ackedAt": now_iso()})),
                           ("notes.txt", "hi"), ("ack-x.json", "{}")):
            atomic_write(os.path.join(ack, name), text)
            time.sleep(0.15)
        self.assertEqual(self.get(seq)[1]["state"], "pending")
        atomic_write(os.path.join(ack, "ack-%d.json" % seq),
                     json.dumps({"schema": 1, "seq": seq, "state": "done", "ackedAt": now_iso(), "message": "x" * 500}))
        d = self.wait_state(seq, ("done",))
        self.assertEqual(len(d["message"]), 200)

    def test_first_ack_wins(self):
        self.start()
        seq = self.post(FOCUS)[1]["seq"]
        ack = os.path.join(self.comp, "acks", "ack-%d.json" % seq)
        atomic_write(ack, json.dumps({"schema": 1, "seq": seq, "state": "done", "ackedAt": now_iso()}))
        self.wait_state(seq, ("done",))
        atomic_write(ack, json.dumps({"schema": 1, "seq": seq, "state": "failed", "message": "late", "ackedAt": now_iso()}))
        time.sleep(0.3)
        self.assertEqual(self.get(seq)[1]["state"], "done")

    def test_old_ack_on_disk_is_answered_after_restart(self):
        self.start()
        self.mod()
        seq = self.post(FOCUS)[1]["seq"]
        self.wait_state(seq, ("done",))
        self.svc.stop()
        self.start()
        self.assertEqual(self.get(seq)[1], {"seq": seq, "state": "done"})

    def test_seq_never_reuses_an_ack_on_disk(self):
        os.makedirs(os.path.join(self.comp, "acks"))
        big = int(time.time()) + 5000
        atomic_write(os.path.join(self.comp, "acks", "ack-%d.json" % big),
                     json.dumps({"schema": 1, "seq": big, "state": "done", "ackedAt": now_iso()}))
        self.start()
        self.assertGreater(self.post(FOCUS)[1]["seq"], big)


class TestExpiry(Env):
    expire = 0.4

    def test_no_ack_expires_and_inbox_is_cleaned(self):
        self.start()
        since = http(self.svc, "/api/v1/events?since=0")[1]["seq"]
        seq = self.post(FOCUS)[1]["seq"]
        self.assertEqual(self.get(seq)[1]["state"], "pending")
        t0 = time.time()
        ev = http(self.svc, "/api/v1/events?since=%d&timeout=5" % since, timeout=10)[1]
        self.assertIn("action", ev["changed"])
        self.assertGreaterEqual(time.time() - t0, 0.3)
        d = self.get(seq)[1]
        self.assertEqual(d["state"], "expired")
        self.assertTrue(d["message"])
        self.assertEqual(V.validate(d, "api.schema.json#/$defs/ActionStatus"), [])
        self.assertEqual(os.listdir(os.path.join(self.comp, "commands")), [])     # a late mod never runs it

    def test_ack_in_time_cancels_expiry(self):
        self.start()
        self.mod()
        seq = self.post(FOCUS)[1]["seq"]
        self.wait_state(seq, ("done",))
        time.sleep(0.7)
        self.assertEqual(self.get(seq)[1]["state"], "done")


class FakeSsh:
    """An ssh stand-in: drops the options and the host, runs the remote command with sh, here."""

    def __init__(self, tmp):
        self.path = os.path.join(tmp, "fake-ssh")
        with open(self.path, "w") as f:
            f.write('#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in -o) shift 2;; -*) shift;; *) break;; esac; done\n'
                    'shift\nexec sh -c "$1"\n')
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR)


class TestPushCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c7p-"))
        self.local = os.path.join(self.tmp, "mac", "companion", "commands")
        self.remote = os.path.join(self.tmp, "nova user with space", "companion", "commands")
        self.ssh = FakeSsh(self.tmp)
        self.p = push_mod.Pusher(self.local, [self.ssh.path, "-o", "BatchMode=yes"], "steamos@nova", self.remote).start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cmd(self, seq, offset=0, **kw):
        d = {"schema": 1, "seq": seq, "createdAt": now_iso(offset), "type": "focus",
             "target": {"kind": "dupe", "id": "d1"}, "select": True}
        d.update(kw)
        return json.dumps(d)

    def wait_remote(self, name, timeout=3):
        end = time.time() + timeout
        p = os.path.join(self.remote, name)
        while time.time() < end:
            if os.path.exists(p):
                return time.time()
            time.sleep(0.005)
        return None

    def test_new_command_arrives_within_a_second(self):
        text = self.cmd(7)
        t0 = time.time()
        atomic_write(os.path.join(self.local, "cmd-7.json"), text)
        t1 = self.wait_remote("cmd-7.json")
        self.assertIsNotNone(t1)
        self.assertLess(t1 - t0, 1.0)         # against a local stand-in only: the real ssh hop is untested
        with open(os.path.join(self.remote, "cmd-7.json")) as f:
            self.assertEqual(f.read(), text)
        self.assertEqual([n for n in os.listdir(self.remote) if n.endswith(".tmp")], [])

    def test_art_request_is_pushed_too(self):
        text = self.cmd(14, type="art_request")
        atomic_write(os.path.join(self.local, "cmd-14.json"), text)
        self.assertIsNotNone(self.wait_remote("cmd-14.json"))

    def test_sync_assets_is_pushed_too(self):
        atomic_write(os.path.join(self.local, "cmd-15.json"), self.cmd(15, type="sync_assets", scope="full"))
        self.assertIsNotNone(self.wait_remote("cmd-15.json"))

    def test_not_pushed_twice_when_the_mirror_copies_it_back(self):
        atomic_write(os.path.join(self.local, "cmd-8.json"), self.cmd(8))
        self.assertIsNotNone(self.wait_remote("cmd-8.json"))
        os.unlink(os.path.join(self.remote, "cmd-8.json"))              # the mod ran it and deleted it
        atomic_write(os.path.join(self.local, "cmd-8.json"), self.cmd(8))   # the mirror's copy lands
        time.sleep(0.4)
        self.assertFalse(os.path.exists(os.path.join(self.remote, "cmd-8.json")))
        self.assertEqual(self.p.pushed, ["cmd-8.json"])

    def test_stale_and_foreign_files_are_not_pushed(self):
        atomic_write(os.path.join(self.local, "cmd-9.json"), self.cmd(9, offset=-60))          # too old
        atomic_write(os.path.join(self.local, "cmd-10.json"), self.cmd(10, type="shell"))       # not on the allow list
        atomic_write(os.path.join(self.local, "cmd-11.json"), self.cmd(12))                     # name and seq differ
        atomic_write(os.path.join(self.local, "notes.json"), "{}")
        atomic_write(os.path.join(self.local, "cmd-13.json"), "{broken")
        time.sleep(0.5)
        self.assertEqual(self.p.pushed, [])
        self.assertFalse(os.path.exists(self.remote))

    def test_failed_ssh_is_logged_and_the_tool_keeps_going(self):
        self.p.remote_dir = "/proc/nope/never"          # the fake remote command fails
        atomic_write(os.path.join(self.local, "cmd-14.json"), self.cmd(14))
        time.sleep(0.5)
        self.assertEqual(self.p.pushed, [])
        self.p.remote_dir = self.remote
        atomic_write(os.path.join(self.local, "cmd-15.json"), self.cmd(15))
        self.assertIsNotNone(self.wait_remote("cmd-15.json"))

    def test_remote_path_with_shell_characters(self):
        self.p.remote_dir = os.path.join(self.tmp, "a'b $x;c")
        atomic_write(os.path.join(self.local, "cmd-16.json"), self.cmd(16))
        self.assertTrue(self.wait_remote_path(os.path.join(self.p.remote_dir, "cmd-16.json")))

    def wait_remote_path(self, p, timeout=3):
        end = time.time() + timeout
        while time.time() < end:
            if os.path.exists(p):
                return True
            time.sleep(0.01)
        return False


class TestEndToEnd(unittest.TestCase):
    """core (Mac) -> push-commands (fake ssh) -> Nova inbox -> fake mod -> ack on the Nova ->
    mirror copy (tar, like mirror-nova.sh) -> core -> GET /actions + 'action' event."""

    def test_chain(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c7e-"))
        try:
            mac_user = os.path.join(tmp, "mac")
            nova_comp = os.path.join(tmp, "nova", "companion")
            mac_comp = os.path.join(mac_user, "companion")
            os.makedirs(os.path.join(mac_comp, "live"))
            atomic_write(os.path.join(mac_comp, "live", "live.json"), live_text())
            os.makedirs(os.path.join(nova_comp, "acks"))
            mod = FakeMod(nova_comp)

            def mirror(path, what):       # the mirror: copy a finished ack Nova -> Mac, and cmd files too
                n = os.path.basename(path)
                if what == "removed" or n.endswith(".tmp") or not os.path.exists(path):
                    return
                sub = os.path.basename(os.path.dirname(path))
                dest = os.path.join(mac_comp, sub)
                os.makedirs(dest, exist_ok=True)
                p = subprocess.Popen(["tar", "-C", os.path.dirname(path), "-cf", "-", n], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                subprocess.run(["tar", "-C", dest, "-xf", "-"], stdin=p.stdout, stderr=subprocess.DEVNULL)
                p.stdout.close()
                p.wait()
            mw = make_watcher([os.path.join(nova_comp, "acks"), os.path.join(nova_comp, "commands")], mirror,
                              recursive=False).start()
            fake = FakeSsh(tmp)
            pusher = push_mod.Pusher(os.path.join(mac_comp, "commands"), [fake.path], "steamos@nova",
                                     os.path.join(nova_comp, "commands")).start()
            cfg = ServiceConfig(user_dir=mac_user, token=TOKEN, views_factory=lambda ctx: StubViews(ctx))
            svc = Service(cfg).start()
            try:
                since = http(svc, "/api/v1/events?since=0")[1]["seq"]
                t0 = time.time()
                st, body = http(svc, "/api/v1/actions/focus", method="POST", body=FOCUS)
                self.assertEqual(st, 200)
                seq = body["seq"]
                ev = http(svc, "/api/v1/events?since=%d&timeout=8" % since, timeout=12)[1]
                dt = time.time() - t0
                self.assertIn("action", ev["changed"])
                self.assertEqual(http(svc, "/api/v1/actions/%d" % seq)[1], {"seq": seq, "state": "done"})
                self.assertEqual(mod.ran[0]["seq"], seq)
                self.assertLess(dt, 3.0)
                print("\nC7 chain (all local, no network): POST -> done event in %.0f ms" % (dt * 1000))
            finally:
                svc.stop()
                pusher.stop()
                mw.stop()
                mod.stop()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCli(unittest.TestCase):
    def test_script_runs_with_stand_in_ssh(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c7c-"))
        try:
            fake = FakeSsh(tmp)
            local = os.path.join(tmp, "mirror", "companion", "commands")
            remote = os.path.join(tmp, "nova", "companion", "commands")
            env = dict(os.environ, SSH_CMD=fake.path)
            p = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "devtools", "push-commands.py"),
                                  "--local-dir", local, "--host", "x@y", "--remote-dir", remote],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
            try:
                for _ in range(100):             # wait until it watches
                    if os.path.isdir(local):
                        break
                    time.sleep(0.05)
                time.sleep(0.3)
                d = {"schema": 1, "seq": 21, "createdAt": now_iso(), "type": "focus",
                     "target": {"kind": "dupe", "id": "d1"}, "select": True}
                atomic_write(os.path.join(local, "cmd-21.json"), json.dumps(d))
                end = time.time() + 5
                while time.time() < end and not os.path.exists(os.path.join(remote, "cmd-21.json")):
                    time.sleep(0.02)
                self.assertTrue(os.path.exists(os.path.join(remote, "cmd-21.json")))
            finally:
                p.terminate()
                out, _ = p.communicate(timeout=5)
            self.assertIn("pushed cmd-21.json", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
