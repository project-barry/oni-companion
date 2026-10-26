"""A3: oni_local, the Android local-mode entry point (no sockets, files only)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "clients", "android", "app", "src", "main", "python"))

import oni_local  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic", "mod")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class LocalEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.user = os.path.join(self.tmp, "user")
        self.comp = os.path.join(self.user, "companion")
        os.makedirs(os.path.join(self.comp, "export"))
        shutil.copy(os.path.join(FIX, "export-v13.json"), os.path.join(self.comp, "export", "gamedata-1-X.json"))
        self.live(paused=False)
        oni_local.start(self.user, os.path.join(self.tmp, "data"))

    def tearDown(self):
        oni_local.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live(self, paused=False, written=None):
        with open(os.path.join(FIX, "live-running-v13.json")) as f:
            d = json.load(f)
        d["writtenAt"] = written or now_iso()
        d["paused"] = paused
        put(os.path.join(self.comp, "live", "live.json"), json.dumps(d))

    def get(self, path):
        st, ctype, etag, data = oni_local.call("GET", path)
        return st, json.loads(data) if ctype.startswith("application/json") else data

    def test_home_and_status_are_served_without_a_socket(self):
        st, home = self.get("/home")
        self.assertEqual(st, 200)
        self.assertIn("blocks", home)
        st, status = self.get("/status")
        self.assertEqual(st, 200)
        self.assertTrue(status["mod"]["liveFresh"])

    def test_every_tab_works_from_the_mod_export_alone(self):
        for path in ("/colony", "/resources", "/buildings", "/pad", "/tabs", "/settings", "/kinds", "/search?q=a"):
            st, body = self.get(path)
            self.assertEqual(st, 200, (path, body))

    def test_unknown_route_is_the_api_error(self):
        st, body = self.get("/nope")
        self.assertEqual((st, body["error"]["code"]), (404, "not_found"))

    def test_events_wake_on_touch(self):
        st, ev = self.get("/events?since=0&timeout=0")
        seq = ev["seq"]
        self.live()
        oni_local.touch(os.path.join(self.comp, "live", "live.json"))
        import time
        time.sleep(0.2)             # the 30 ms coalescing timer
        st, ev = self.get("/events?since=%d&timeout=2" % seq)
        self.assertGreater(ev["seq"], seq)
        self.assertIn("colony", ev["changed"])

    def test_command_goes_to_the_private_inbox_and_an_ack_comes_back(self):
        body = json.dumps({"target": {"kind": "dupe", "id": "d1"}})
        st, data, = oni_local.call("POST", "/actions/focus", body)[:2]
        self.assertEqual(st, 200, data)
        seq = json.loads(oni_local.call("POST", "/actions/focus", body)[3])["seq"]
        inbox = os.listdir(os.path.join(self.comp, "commands"))
        self.assertIn("cmd-%d.json" % seq, inbox)
        ack = os.path.join(self.comp, "acks", "ack-%d.json" % seq)
        put(ack, json.dumps({"schema": 1, "seq": seq, "state": "done", "ackedAt": now_iso()}))
        oni_local.touch(ack)
        st, res = self.get("/actions/%d" % seq)
        self.assertEqual(res["state"], "done")

    def test_stale_deadline(self):
        left = oni_local.stale_in()
        self.assertTrue(10 < left <= 15, left)
        self.live(paused=True)
        self.assertTrue(100 < oni_local.stale_in() <= 180)
        self.live(written="2020-01-01T00:00:00Z")
        self.assertEqual(oni_local.stale_in(), 0.0)

    def test_publish_stale_wakes_clients(self):
        seq = self.get("/events?since=0&timeout=0")[1]["seq"]
        oni_local.publish_stale()
        ev = self.get("/events?since=%d&timeout=2" % seq)[1]
        self.assertIn("status", ev["changed"])

    def test_stopped_service_answers_unavailable(self):
        oni_local.stop()
        self.assertEqual(oni_local.call("GET", "/home")[0], 503)


if __name__ == "__main__":
    unittest.main()
