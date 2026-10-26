"""v1.4 (lane B5): the mock's loopback Connect a phone endpoints, as the Barry Settings page uses them.
Replies are checked against contracts/api.schema.json. The QR image is a placeholder in the mock and
is only checked for PNG shape, never for scanning."""

import http.client
import importlib.util
import json
import os
import threading
import unittest

from tests.jsonschema_mini import Validator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
TOKEN = "test-token-connect"

_spec = importlib.util.spec_from_file_location("mock_server", os.path.join(ROOT, "devtools", "mock-server.py"))
mock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock)


class ConnectMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = Validator(CONTRACTS)

    def setUp(self):   # a fresh mock per test: each one changes the state
        self.server = mock.make_server("127.0.0.1", 0, TOKEN, FIX)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"X-Oni-Token": TOKEN}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, "/api/v1" + path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        ctype = resp.getheader("Content-Type", "")
        conn.close()
        if ctype.startswith("image/"):
            return resp.status, raw
        return resp.status, json.loads(raw.decode("utf-8"))

    def assertState(self, state):
        self.assertEqual(self.v.validate(state, "api.schema.json#/$defs/ConnectState"), [])

    def test_state_starts_from_the_fixture_and_is_valid(self):
        status, body = self.call("GET", "/connect")
        self.assertEqual(status, 200)
        self.assertState(body)
        self.assertTrue(body["enabled"])
        self.assertEqual(body["devices"][0]["label"], "Pixel 9")

    def test_switch_off_closes_listener_drops_code_and_qr(self):
        status, body = self.call("POST", "/connect/switch", {"enabled": False})
        self.assertEqual(status, 200)
        self.assertState(body)
        self.assertFalse(body["listening"])
        self.assertIsNone(body["port"])
        self.assertIsNone(body["code"])
        self.assertIsNone(body["qrText"])
        self.assertEqual(self.call("GET", "/connect/qr.png")[0], 404)

    def test_switch_on_makes_a_code_and_a_valid_qr_text(self):
        self.call("POST", "/connect/switch", {"enabled": False})
        status, body = self.call("POST", "/connect/switch", {"enabled": True})
        self.assertEqual(status, 200)
        self.assertState(body)
        self.assertTrue(body["listening"])
        code = body["code"]
        self.assertEqual(self.v.validate(code, "api.schema.json#/$defs/PairingCode"), [])
        payload = json.loads(body["qrText"])
        self.assertEqual(self.v.validate(payload, "pairing.schema.json#/$defs/QrPayload"), [])
        self.assertEqual(payload["c"], code["display"].replace("-", ""))
        self.assertEqual(payload["n"], body["identity"]["name"])

    def test_png_qr_when_on(self):
        self.call("POST", "/connect/switch", {"enabled": True})
        status, raw = self.call("GET", "/connect/qr.png")
        self.assertEqual(status, 200)
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")

    def test_switch_needs_a_boolean(self):
        status, body = self.call("POST", "/connect/switch", {"enabled": "yes"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "bad_request")

    def test_new_code_is_refused_while_off(self):
        self.call("POST", "/connect/switch", {"enabled": False})
        status, body = self.call("POST", "/connect/code", {})
        self.assertEqual(status, 400)
        self.call("POST", "/connect/switch", {"enabled": True})
        status, body = self.call("POST", "/connect/code", {})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    def test_remove_device_and_unknown_id(self):
        status, body = self.call("DELETE", "/connect/devices/d-a1b2c3d4e5f6")
        self.assertEqual((status, body), (200, {"ok": True, "removed": 1}))
        status, body = self.call("GET", "/connect/devices")
        self.assertEqual(self.v.validate(body, "api.schema.json#/$defs/ConnectDevices"), [])
        self.assertNotIn("d-a1b2c3d4e5f6", [d["deviceId"] for d in body["devices"]])
        self.assertEqual(self.call("DELETE", "/connect/devices/d-a1b2c3d4e5f6")[0], 404)

    def test_reset_identity_unpairs_switches_off_and_keeps_plain_http_off(self):
        self.call("POST", "/connect/switch", {"enabled": True})
        self.call("POST", "/connect/plain-http", {"enabled": True})
        before = self.call("GET", "/connect")[1]["identity"]
        status, body = self.call("POST", "/connect/reset-identity", {})
        self.assertEqual(status, 200)
        self.assertEqual(self.v.validate(body, "api.schema.json#/$defs/ConnectDone"), [])
        state = self.call("GET", "/connect")[1]
        self.assertState(state)
        self.assertFalse(state["enabled"])
        self.assertFalse(state["plainHttp"])
        self.assertEqual(state["devices"], [])
        self.assertNotEqual(state["identity"]["instanceId"], before["instanceId"])

    def test_plain_http_switch(self):
        self.call("POST", "/connect/switch", {"enabled": True})
        status, body = self.call("POST", "/connect/plain-http", {"enabled": True})
        self.assertEqual(status, 200)
        self.assertState(body)
        self.assertTrue(body["plainHttp"])
        self.assertEqual(body["plainHttpPort"], body["port"] + 1)

    def test_change_publishes_a_connect_event(self):
        before = self.call("GET", "/events?timeout=0")[1]["seq"]
        self.call("POST", "/connect/switch", {"enabled": False})
        status, body = self.call("GET", "/events?since=%d&timeout=0" % before)
        self.assertEqual(status, 200)
        self.assertIn("connect", body["changed"])


if __name__ == "__main__":
    unittest.main()
