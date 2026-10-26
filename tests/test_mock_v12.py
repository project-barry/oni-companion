"""v1.2 routes of devtools/mock-server.py (controls, sync, fonts, alerts) against the contracts."""

import http.client
import threading
import time
import unittest

from tests.test_mock_server import CONTRACTS, FIX, TOKEN, Client, fixture, mock
from tests.jsonschema_mini import Validator


class V12Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = mock.make_server("127.0.0.1", 0, TOKEN, FIX, v11=True, v12=True)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.c = Client(cls.port)
        cls.v = Validator(CONTRACTS)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def ok(self, data, schema):
        self.assertEqual(self.v.validate(data, schema), [])

    def test_controls_follow_a_post(self):
        status, body, _, _ = self.c.call("GET", "/controls")
        self.assertEqual(status, 200)
        self.ok(body, "api.schema.json#/$defs/Controls")
        status, body, _, _ = self.c.call("POST", "/controls", {"state": "play", "speed": 3})
        self.assertEqual(status, 200)
        self.ok(body, "api.schema.json#/$defs/Controls")
        self.assertEqual(body["pending"]["speed"], 3)
        time.sleep(1.3)
        _, body, _, _ = self.c.call("GET", "/controls")
        self.assertEqual((body["paused"], body["speed"], "pending" in body), (False, 3, False))

    def test_controls_bad_bodies(self):
        for bad in ({"state": "stop"}, {"state": "pause", "speed": 2}, {"state": "play", "speed": 4}):
            status, body, _, _ = self.c.call("POST", "/controls", bad)
            self.assertEqual((status, body["error"]["code"]), (400, "bad_request"))

    def test_sync_runs_and_finishes(self):
        _, body, _, _ = self.c.call("GET", "/sync")
        self.ok(body, "api.schema.json#/$defs/Sync")
        status, body, _, _ = self.c.call("POST", "/sync", {"scope": "full"})
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "running")
        self.ok(body, "api.schema.json#/$defs/Sync")
        for _ in range(60):
            time.sleep(0.2)
            _, body, _, _ = self.c.call("GET", "/sync")
            if body["state"] == "done":
                break
        self.assertEqual((body["state"], body["needed"]), ("done", False))
        self.ok(body, "api.schema.json#/$defs/Sync")

    def test_fonts_list_and_files(self):
        _, body, _, _ = self.c.call("GET", "/fonts")
        self.ok(body, "api.schema.json#/$defs/FontList")
        for f in body["fonts"]:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", f["url"], headers={"X-Oni-Token": TOKEN})
            r = conn.getresponse()
            data = r.read()
            self.assertEqual(r.status, 200, f)
            self.assertTrue(data)
            self.assertEqual(r.getheader("Content-Type"),
                             {"ttf": "font/ttf", "png": "image/png", "json": "application/json"}[f["name"].rsplit(".", 1)[1]])
            conn.close()
        status, body, _, _ = self.c.call("GET", "/fonts/..%2Fmanifest.json")
        self.assertEqual(status, 404)

    def test_theme_v12_and_alert_pages(self):
        _, th, _, _ = self.c.call("GET", "/theme")
        self.ok(th, "theme.schema.json#/$defs/Theme")
        self.assertIn("icons", th)
        status, page, _, _ = self.c.call("GET", "/entry/alert/a1")
        self.assertEqual(status, 200)
        self.ok(page, "screen.schema.json")
        status, _, _, _ = self.c.call("GET", "/entry/alert/zzz")
        self.assertEqual(status, 404)
        _, col, _, _ = self.c.call("GET", "/colony")
        self.ok(col, "screen.schema.json")

    def test_alert_actions_and_dismiss(self):
        status, body, _, _ = self.c.call("POST", "/actions/alert_activate", {"alertId": "a1", "link": 1})
        self.assertEqual(status, 200)
        seq = body["seq"]
        time.sleep(1.0)
        _, st, _, _ = self.c.call("GET", "/actions/%d" % seq)
        self.assertEqual(st["state"], "done")
        status, body, _, _ = self.c.call("POST", "/actions/alert_dismiss", {"alertId": "a1"})
        time.sleep(1.0)
        _, st, _, _ = self.c.call("GET", "/actions/%d" % body["seq"])
        self.assertEqual((st["state"], st["message"]), ("failed", "Can't be dismissed"))
        status, body, _, _ = self.c.call("POST", "/actions/alert_dismiss", {"alertId": "a3"})
        time.sleep(1.0)
        _, st, _, _ = self.c.call("GET", "/actions/%d" % body["seq"])
        self.assertEqual(st["state"], "done")
        status, _, _, _ = self.c.call("GET", "/entry/alert/a3")
        self.assertEqual(status, 404)
        status, body, _, _ = self.c.call("POST", "/actions/alert_dismiss", {})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
