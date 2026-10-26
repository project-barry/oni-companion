"""Tests for devtools/mock-server.py: every endpoint in contracts/api.md, the token
rules, the 501 pairing names, and the long-poll. Runs the real HTTP server on
127.0.0.1 with an ephemeral port, so no network beyond loopback is used."""

import http.client
import importlib.util
import json
import os
import threading
import time
import unittest

from tests.jsonschema_mini import Validator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
TOKEN = "test-token-123"

_spec = importlib.util.spec_from_file_location(
    "mock_server", os.path.join(ROOT, "devtools", "mock-server.py"))
mock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock)


def fixture(rel):
    with open(os.path.join(FIX, rel), encoding="utf-8") as f:
        return json.load(f)


class Client:
    def __init__(self, port):
        self.port = port

    def call(self, method, path, body=None, headers=None, raw_body=None, absolute=False):
        """path is relative to /api/v1 unless absolute=True. A header set to None is
        left out of the request."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"X-Oni-Token": TOKEN}
        for k, v in (headers or {}).items():
            if v is None:
                hdrs.pop(k, None)
            else:
                hdrs[k] = v
        payload = raw_body
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        if payload is not None:
            hdrs["Content-Type"] = "application/json"
        start = time.monotonic()
        full = path if absolute else "/api/v1" + path
        conn.request(method, full, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        elapsed = time.monotonic() - start
        ctype = resp.getheader("Content-Type")
        conn.close()
        return resp.status, json.loads(data.decode("utf-8")), elapsed, ctype


class MockTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = mock.make_server("127.0.0.1", 0, TOKEN, FIX)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.c = Client(cls.port)
        cls.v = Validator(CONTRACTS)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, **kw):
        return self.c.call("GET", path, **kw)

    def assertValid(self, data, schema):
        errs = self.v.validate(data, schema)
        self.assertEqual(errs, [], errs[:5])

    def assertError(self, status, body, want_status, code):
        self.assertEqual(status, want_status, body)
        self.assertEqual(body["error"]["code"], code)
        self.assertValid(body, "api.schema.json#/$defs/Error")


class Auth(MockTestBase):
    def test_no_token_is_403_bad_token(self):
        status, body, _, _ = self.c.call("GET", "/status", headers={"X-Oni-Token": ""})
        self.assertError(status, body, 403, "bad_token")
        self.assertEqual(body, fixture("api/error.json"))

    def test_wrong_token_is_403(self):
        status, body, _, _ = self.get("/status", headers={"X-Oni-Token": "nope"})
        self.assertError(status, body, 403, "bad_token")

    def test_barry_header_and_query_token_accepted(self):
        status, _, _, _ = self.get("/status", headers={"X-Oni-Token": None, "X-Barry-Token": TOKEN})
        self.assertEqual(status, 200)
        status, _, _, _ = self.c.call("GET", "/status?token=" + TOKEN,
                                      headers={"X-Oni-Token": None})
        self.assertEqual(status, 200)

    def test_wrong_query_token_is_403(self):
        status, body, _, _ = self.c.call("GET", "/status?token=bad", headers={"X-Oni-Token": None})
        self.assertError(status, body, 403, "bad_token")

    def test_token_checked_before_routing(self):
        status, body, _, _ = self.c.call("GET", "/nothing-here", headers={"X-Oni-Token": None},
                                         absolute=True)
        self.assertEqual(status, 404)
        status, body, _, _ = self.c.call("GET", "/api/v1/nothing", headers={"X-Oni-Token": None},
                                         absolute=True)
        self.assertError(status, body, 403, "bad_token")

    def test_non_api_path_is_404(self):
        status, body, _, _ = self.c.call("GET", "/", absolute=True)
        self.assertError(status, body, 404, "not_found")

    def test_json_content_type(self):
        _, _, _, ctype = self.get("/status")
        self.assertEqual(ctype, "application/json; charset=utf-8")


class ReadEndpoints(MockTestBase):
    def test_status(self):
        status, body, _, _ = self.get("/status")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/status.json"))
        self.assertValid(body, "api.schema.json#/$defs/Status")

    def test_home(self):
        status, body, _, _ = self.get("/home")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/home.json"))
        self.assertValid(body, "screen.schema.json")

    def test_kinds(self):
        status, body, _, _ = self.get("/kinds")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/kinds.json"))
        self.assertValid(body, "api.schema.json#/$defs/Kinds")

    def test_search_returns_fixture(self):
        status, body, _, _ = self.get("/search?q=wid")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/search.json"))
        self.assertValid(body, "api.schema.json#/$defs/Search")

    def test_search_filters_and_limits(self):
        _, body, _, _ = self.get("/search?q=WIDGETIUM")
        self.assertEqual([r["id"] for r in body["results"]], ["SynthWidgetium"])
        self.assertFalse(body["truncated"])
        _, body, _, _ = self.get("/search?q=wid&limit=1")
        self.assertEqual(len(body["results"]), 1)
        self.assertTrue(body["truncated"])
        _, body, _, _ = self.get("/search?q=wid&kind=building")
        self.assertEqual([r["kind"] for r in body["results"]], ["building"])
        _, body, _, _ = self.get("/search?q=zzzz")
        self.assertEqual(body["results"], [])
        self.assertValid(body, "api.schema.json#/$defs/Search")

    def test_search_bad_values(self):
        self.assertError(*self.get("/search")[:2], 400, "bad_request")
        self.assertError(*self.get("/search?q=")[:2], 400, "bad_request")
        self.assertError(*self.get("/search?q=wid&kind=spaceship")[:2], 400, "bad_request")
        self.assertError(*self.get("/search?q=wid&limit=abc")[:2], 400, "bad_request")

    def test_list_building(self):
        status, body, _, _ = self.get("/list/building?dlc=base&sort=dlc")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/list-building.json"))
        self.assertValid(body, "screen.schema.json")

    def test_list_bad_sort_and_unknown_kind(self):
        self.assertError(*self.get("/list/building?sort=color")[:2], 400, "bad_request")
        self.assertError(*self.get("/list/spaceship")[:2], 404, "not_found")
        self.assertError(*self.get("/list/element")[:2], 404, "not_found")

    def test_entry_building_and_element(self):
        status, body, _, _ = self.get("/entry/building/SynthWidgetMaker")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/entry-building.json"))
        self.assertValid(body, "screen.schema.json")
        status, body, _, _ = self.get("/entry/element/SynthWidgetium")
        self.assertEqual(body, fixture("screens/entry-element.json"))

    def test_entry_url_encoded_id_and_missing(self):
        status, _, _, _ = self.get("/entry/building/SynthWidget%4Daker")
        self.assertEqual(status, 200)
        self.assertError(*self.get("/entry/building/SynthMissing")[:2], 404, "not_found")
        self.assertError(*self.get("/entry/spaceship/SynthWidgetium")[:2], 404, "not_found")

    def test_raw(self):
        status, body, _, _ = self.get("/raw/building/SynthWidgetMaker")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/raw-building.json"))
        self.assertValid(body, "api.schema.json#/$defs/Raw")
        self.assertError(*self.get("/raw/building/SynthLamp")[:2], 404, "not_found")

    def test_colony(self):
        status, body, _, _ = self.get("/colony")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/colony.json"))
        self.assertValid(body, "api.schema.json#/$defs/ColonyReply")
        status, body, _, _ = self.get("/colony?world=0")
        self.assertEqual(status, 200)
        self.assertError(*self.get("/colony?world=7")[:2], 404, "not_found")
        self.assertError(*self.get("/colony?world=x")[:2], 400, "bad_request")

    def test_tools_list(self):
        status, body, _, _ = self.get("/tools")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/tools.json"))
        self.assertValid(body, "api.schema.json#/$defs/ToolList")

    def test_tool_form(self):
        status, body, _, _ = self.get("/tools/heat")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/tool-form.json"))
        self.assertValid(body, "screen.schema.json")
        self.assertError(*self.get("/tools/power-budget")[:2], 404, "not_found")


class ToolPost(MockTestBase):
    def post(self, body=None, raw=None, tool="heat"):
        return self.c.call("POST", "/tools/" + tool, body=body, raw_body=raw)

    def test_valid_post_returns_result(self):
        status, body, _, _ = self.post(fixture("api/tool-post.json"))
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("screens/tool-result.json"))
        self.assertValid(body, "screen.schema.json")

    def test_defaults_fill_missing_values(self):
        status, body, _, _ = self.post({"values": {}})
        self.assertEqual(status, 200)

    def test_bad_values_name_the_field(self):
        cases = [
            ({"mass": {"value": -1, "unit": "kg"}}, "mass"),
            ({"mass": {"value": 1, "unit": "lb"}}, "mass"),
            ({"mass": "heavy"}, "mass"),
            ({"element": 5}, "element"),
            ({"mode": "boil"}, "mode"),
            ({"useKelvin": "yes"}, "useKelvin"),
            ({"deltaT": {"value": 1, "unit": "F"}}, "deltaT"),
        ]
        for values, field in cases:
            status, body, _, _ = self.post({"values": values})
            self.assertError(status, body, 400, "bad_request")
            self.assertIn(field, body["error"]["message"], values)

    def test_bad_bodies(self):
        self.assertError(*self.post(raw=b"{not json")[:2], 400, "bad_request")
        self.assertError(*self.post(raw=b"")[:2], 400, "bad_request")
        self.assertError(*self.post([1, 2])[:2], 400, "bad_request")
        self.assertError(*self.post({"values": [1]})[:2], 400, "bad_request")

    def test_unknown_tool_and_method(self):
        self.assertError(*self.post({"values": {}}, tool="power-budget")[:2], 404, "not_found")
        self.assertError(*self.c.call("PUT", "/status", body={})[:2], 404, "not_found")
        self.assertError(*self.c.call("DELETE", "/tools/heat")[:2], 404, "not_found")

    def test_unknown_fields_ignored(self):
        status, _, _, _ = self.post({"values": {"nonsense": 1, "mode": "cool"}})
        self.assertEqual(status, 200)


class Events(MockTestBase):
    def test_since_zero_gives_current_seq(self):
        status, body, elapsed, _ = self.get("/events?since=0")
        self.assertEqual(body, fixture("api/events-timeout.json"))
        self.assertLess(elapsed, 2)

    def test_missing_since_is_zero(self):
        _, body, _, _ = self.get("/events")
        self.assertEqual(body, fixture("api/events-timeout.json"))

    def test_behind_client_gets_changes_at_once(self):
        status, body, elapsed, _ = self.get("/events?since=41&timeout=25")
        self.assertEqual(status, 200)
        self.assertEqual(body, fixture("api/events.json"))
        self.assertValid(body, "api.schema.json#/$defs/Events")
        self.assertLess(elapsed, 2)

    def test_timeout_returns_unchanged_seq(self):
        status, body, elapsed, _ = self.get("/events?since=42&timeout=1")
        self.assertEqual(body, fixture("api/events-timeout.json"))
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 5)

    def test_bad_params(self):
        self.assertError(*self.get("/events?since=abc")[:2], 400, "bad_request")
        self.assertError(*self.get("/events?since=-1")[:2], 400, "bad_request")
        self.assertError(*self.get("/events?since=1&timeout=soon")[:2], 400, "bad_request")
        self.assertError(*self.get("/events?since=1&timeout=-5")[:2], 400, "bad_request")

    def test_long_poll_wakes_on_bump(self):
        # Own server: this test moves seq, which the other Events tests rely on.
        server = mock.make_server("127.0.0.1", 0, TOKEN, FIX)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self._long_poll_case(server)
        finally:
            server.shutdown()
            server.server_close()

    def _long_poll_case(self, server):
        hub = server.state.hub
        client = Client(server.server_address[1])
        base = hub.seq
        result = {}

        def poll():
            result["r"] = client.call("GET", "/events?since=%d&timeout=10" % base)

        t = threading.Thread(target=poll)
        t.start()
        time.sleep(0.3)
        bumped_at = time.monotonic()
        hub.bump(["gamedata", "colony"])
        t.join(10)
        status, body, _, _ = result["r"]
        self.assertEqual(status, 200)
        self.assertEqual(body["seq"], base + 1)
        self.assertEqual(body["changed"], ["colony", "gamedata"])
        woke_after = time.monotonic() - bumped_at
        # Contract: within 100 ms of the file event. Allow slack for a loaded machine.
        self.assertLess(woke_after, 0.5, "woke after %.3f s" % woke_after)

    def test_history_union_for_older_client(self):
        hub = mock.EventHub()
        hub.bump(["colony"])
        hub.bump(["status"])
        hub.bump(["gamedata"])
        self.assertEqual(hub.changed_since(42), ["colony", "gamedata", "status"])
        self.assertEqual(hub.changed_since(44), ["gamedata"])
        self.assertEqual(hub.poll(0, 1), {"seq": 45, "changed": []})

    def test_history_gap_reports_everything(self):
        hub = mock.EventHub()
        for _ in range(300):
            hub.bump(["colony"])
        self.assertEqual(hub.changed_since(1), ["colony", "gamedata", "status"])

    def test_tick_bumps_seq(self):
        hub = mock.EventHub()
        stop = threading.Event()
        mock.start_tick(hub, 0.1, stop)
        try:
            deadline = time.monotonic() + 3
            while hub.seq < 44 and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(hub.seq, 44)
            self.assertEqual(hub.changed_since(42)[0], "colony")
        finally:
            stop.set()


class Pairing(MockTestBase):
    def test_planned_pairing_endpoints_are_501(self):
        self.assertError(*self.c.call("POST", "/pair/start")[:2], 501, "not_in_v1")
        self.assertError(*self.c.call("POST", "/pair/complete", body={})[:2], 501, "not_in_v1")
        self.assertError(*self.get("/pair/clients")[:2], 501, "not_in_v1")
        self.assertError(*self.c.call("DELETE", "/pair/clients/phone")[:2], 501, "not_in_v1")

    def test_unknown_pair_path_is_404(self):
        self.assertError(*self.get("/pair/nope")[:2], 404, "not_found")


class Config(unittest.TestCase):
    def test_non_loopback_is_refused(self):
        with self.assertRaises(SystemExit):
            mock.make_server("0.0.0.0", 0, TOKEN, FIX)
        with self.assertRaises(SystemExit):
            mock.main(["--listen", "192.168.1.5:8765"])

    def test_loopback_names_accepted(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            self.assertTrue(mock.is_loopback(host), host)

    def test_listen_parsing(self):
        self.assertEqual(mock.parse_listen("127.0.0.1:9000"), ("127.0.0.1", 9000))
        with self.assertRaises(Exception):
            mock.parse_listen("nope")


if __name__ == "__main__":
    unittest.main()


class V11Routes(unittest.TestCase):
    """Lane B2: the v1.1 routes the Barry screenshots and tests use."""

    @classmethod
    def setUpClass(cls):
        cls.server = mock.make_server("127.0.0.1", 0, TOKEN, FIX, v11=True)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = None if body is None else json.dumps(body)
        conn.request(method, "/api/v1/" + path, data, {"X-Oni-Token": TOKEN})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, r.getheader("Content-Type"), raw

    def test_art_png_and_missing(self):
        st, ctype, raw = self.call("GET", "art/dupe/d1")
        self.assertEqual((st, ctype), (200, "image/png"))
        self.assertTrue(raw.startswith(b"\x89PNG"))
        self.assertEqual(self.call("GET", "art/dupe/nobody")[0], 404)
        self.assertEqual(self.call("GET", "art/ui/panel")[0], 200)

    def test_theme_resources_and_colony(self):
        self.assertEqual(json.loads(self.call("GET", "theme")[2])["source"], "game")
        self.assertEqual(self.call("GET", "resources?world=1")[0], 200)
        colony = json.loads(self.call("GET", "colony")[2])
        self.assertIn("badges", colony["blocks"][2]["cards"][0])

    def test_settings_and_onopen(self):
        st, _, raw = self.call("POST", "settings", {"values": {"zoomToDupeOnSelect": True}})
        self.assertEqual(st, 200)
        self.assertIn("onOpen", json.loads(self.call("GET", "entry/dupe/d1")[2]))
        self.call("POST", "settings", {"values": {"zoomToDupeOnSelect": False}})
        self.assertNotIn("onOpen", json.loads(self.call("GET", "entry/dupe/d1")[2]))
        self.assertEqual(self.call("POST", "settings", {"values": {"zoomToDupeOnSelect": 3}})[0], 400)

    def test_actions(self):
        st, _, raw = self.call("POST", "actions/focus", {"target": {"kind": "dupe", "id": "d1"}})
        seq = json.loads(raw)["seq"]
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(self.call("GET", "actions/%d" % seq)[2])["state"], "pending")
        time.sleep(0.9)
        self.assertEqual(json.loads(self.call("GET", "actions/%d" % seq)[2])["state"], "done")
        self.assertEqual(self.call("POST", "actions/focus", {"target": {"kind": "dupe", "id": "menu"}})[0], 503)
        self.assertEqual(self.call("POST", "actions/other", {})[0], 404)
