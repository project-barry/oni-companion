#!/usr/bin/env python3
"""Mock ONI Companion core: serves fixtures/synthetic exactly per contracts/api.md.

Stdlib only. Lets front-end work (Barry QML, later the apps) run
without the real core. Barry mode rules apply: loopback bind only, and the
token may come in X-Oni-Token, X-Barry-Token or ?token=.

Usage:
  python3 devtools/mock-server.py [--listen 127.0.0.1:8765] [--token T]
                                  [--tick SECONDS] [--fixtures DIR]

  --tick N   bump seq every N seconds (changed alternates colony / colony+status),
             so long-poll clients see events without a game
  --token    default: $ONI_MOCK_TOKEN, else a random token printed at start

Mapping (what each endpoint serves; anything else is 404 not_found):
  /status, /home, /kinds, /tools, /colony  -> the matching fixture, unchanged
  /search   -> api/search.json, filtered by q (name or id, case-insensitive),
               kind and limit
  /list/building -> screens/list-building.json (other kinds: 404)
  /entry/element/SynthWidgetium, /entry/building/SynthWidgetMaker -> entry screens
  /raw/building/SynthWidgetMaker -> api/raw-building.json
  /tools/heat    -> screens/tool-form.json; POST checks values against its fields
                    and replies with screens/tool-result.json
  /events        -> seq counter with long-poll (see EventHub)
  /pair/*        -> 501 not_in_v1

v1.1 (lane B2; the v1 routes above stay as they were unless --v11 is given):
  --v11 / make_server(v11=True): /colony serves screens/colony-v11.json
  /art/<kind>/<id>  -> PNG from <fixtures>/companion/art (manifest.json); 404 if missing
                       or when ONI_MOCK_NOART=1 / noart=True
  /theme            -> api/theme.json (api/theme-builtin.json when ONI_MOCK_NOTHEME=1)
  /resources        -> screens/resources.json
  /settings         -> GET/POST the zoom setting (kept in memory), sends a "settings" event
  /entry/dupe/<id>  -> the duplicant page (onOpen only while the setting is on)
  POST /actions/focus -> {seq}; the ack comes 0.6 s later as an "action" event.
                       Targets d1, d2 = done; "menu" = 503; anything else = failed.
  GET /actions/<seq> -> pending / done / failed
  ONI_MOCK_LOG=1 prints one stderr line per focus post (dev check of "once per page open").

v1.4 (Connect a phone, loopback side; the Barry Settings page uses it):
  GET /connect, POST /connect/switch|plain-http {enabled}, POST /connect/code,
  GET /connect/devices, DELETE /connect/devices/<id>, POST /connect/reset-identity
  -> in-memory state, starts from api/connect-state.json (ONI_MOCK_CONNECT=off: connect-state-off.json).
  A "connect" event on each change. GET /connect/qr.png -> a PLACEHOLDER PNG, not a scannable QR code.
  The network listener, mDNS, the claim endpoint and the device token are NOT simulated.
"""

import argparse
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
import uuid
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FIXTURES = os.path.join(os.path.dirname(HERE), "fixtures", "synthetic")
API = "/api/v1"
KINDS = ("element", "building", "critter", "plant", "geyser", "food", "medicine",
         "recipe", "tech", "trait", "skill", "room", "codex")
CHANGE_ORDER = ("colony", "gamedata", "status")
ALL_NAMES = CHANGE_ORDER + ("action", "settings", "art", "controls", "sync", "pad", "build", "connect")   # v1.1 adds action, settings; v1.2 art, controls, sync; v1.3 pad, build
START_SEQ = 42  # matches fixtures/synthetic/api/events.json
MAX_BODY = 64 * 1024

# Fixture routing tables. Paths are relative to the fixtures directory.
ENTRY_FIXTURES = {
    ("building", "SynthWidgetMaker"): "screens/entry-building.json",
    ("element", "SynthWidgetium"): "screens/entry-element.json",
}
RAW_FIXTURES = {
    ("building", "SynthWidgetMaker"): "api/raw-building.json",
}
LIST_FIXTURES = {"building": "screens/list-building.json"}
TOOL_FORMS = {"heat": "screens/tool-form.json"}
TOOL_RESULTS = {"heat": "screens/tool-result.json"}
LOOPBACK_NAMES = ("localhost",)


CONNECT_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CONNECT_WORDS = (("spiffy", "raccoon"), ("sleepy", "ant"), ("bouncy", "otter"), ("quiet", "heron"))
CONNECT_PORT = 47615


def utc_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_code():
    """A one-time code: 8 characters, shown ABCD-EFGH, valid 300 s (mock: no real secret)."""
    chars = "".join(secrets.choice(CONNECT_CODE_ALPHABET) for _ in range(8))
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=300)
    return {"display": chars[:4] + "-" + chars[4:], "expiresAt": utc_iso(expires), "failuresLeft": 5}


def new_identity():
    adjective, animal = secrets.choice(CONNECT_WORDS)
    return {"instanceId": str(uuid.uuid4()), "name": adjective + "-" + animal,
            "fingerprint": secrets.token_hex(32), "fingerprintTag": secrets.token_hex(2).upper(),
            "apiVersion": 1, "coreVersion": "1.4.0"}


def connect_qr_text(st):
    """The QrPayload of the current code (mock: the same shape as contracts/pairing.schema.json)."""
    c = st.connect
    if c["code"] is None:
        return None
    ident = st.identity
    addresses = [a["address"] for a in st.connect_addresses()]
    payload = {"v": 1, "t": "onic-pair", "a": addresses, "p": CONNECT_PORT,
               "c": c["code"]["display"].replace("-", ""), "i": ident["instanceId"],
               "f": ident["fingerprint"], "n": ident["name"], "x": c["code"]["expiresAt"]}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def connect_state(st):
    """ConnectState (api.schema.json) for the loopback listener."""
    c = st.connect
    on = c["enabled"]
    text = connect_qr_text(st) if on else None
    devices = list(c["devices"])
    note = None
    if on and c["plainHttp"] and any(d["transport"] == "http" for d in devices):
        note = "An iPhone is paired over plain HTTP: anyone on this Wi-Fi can read its token. Tailscale gives real HTTPS."
    return {"enabled": on, "listening": on, "port": CONNECT_PORT if on else None,
            "plainHttp": c["plainHttp"], "plainHttpPort": (CONNECT_PORT + 1) if on and c["plainHttp"] else None,
            "identity": dict(st.identity), "addresses": st.connect_addresses() if on else [],
            "code": dict(c["code"]) if on and c["code"] else None,
            "qrText": text, "devices": devices, "plainHttpNote": note}


def qr_placeholder_png(text):
    """MOCK ONLY: a placeholder PNG (finder squares plus a pattern seeded by the text), NOT a real
    QR code and not scannable. The core must encode qrText for real (a stdlib encoder)."""
    n = 25
    seed = hashlib.sha256((text or "").encode("utf-8")).digest()
    def dark(x, y):
        for fx, fy in ((0, 0), (n - 7, 0), (0, n - 7)):      # finder patterns in three corners
            if fx <= x < fx + 7 and fy <= y < fy + 7:
                return max(abs(x - fx - 3), abs(y - fy - 3)) != 2
        bit = (seed[(y * n + x) // 8 % len(seed)] >> ((y * n + x) % 8)) & 1
        return bool(bit)
    quiet, scale = 4, 8
    size = (n + 2 * quiet) * scale
    rows = []
    for py in range(size):
        row = bytearray([0])
        my = py // scale - quiet
        for px in range(size):
            mx = px // scale - quiet
            on = 0 <= mx < n and 0 <= my < n and dark(mx, my)
            row.append(0 if on else 255)
        rows.append(bytes(row))
    raw = b"".join(rows)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def bad(message):
    return ApiError(400, "bad_request", message)


def not_found(message):
    return ApiError(404, "not_found", message)


class EventHub:
    """Seq counter for /events. Long-poll waiters sleep on a condition variable,
    so a bump wakes them at once (well under the 100 ms contract)."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = START_SEQ
        self.oldest = START_SEQ
        # (seq, changed names) for the most recent bumps
        self.history = deque([(START_SEQ, ["colony", "status"])], maxlen=256)

    def bump(self, names):
        with self.cond:
            self.seq += 1
            self.history.append((self.seq, sorted(set(names), key=ALL_NAMES.index)))
            self.oldest = self.history[0][0]
            self.cond.notify_all()
            return self.seq

    def changed_since(self, since):
        """Names changed after `since`. If history no longer reaches back that far,
        report every name (conservative: the client re-fetches)."""
        if since + 1 < self.oldest:
            return list(CHANGE_ORDER)
        names = set()
        for seq, changed in self.history:
            if seq > since:
                names.update(changed)
        return sorted(names, key=ALL_NAMES.index)

    def poll(self, since, timeout):
        """since 0 = "give me the current seq now". Otherwise wait up to `timeout`
        for seq > since. On timeout: same seq, changed []."""
        with self.cond:
            if since == 0:
                return {"seq": self.seq, "changed": []}
            if self.seq <= since:
                self.cond.wait_for(lambda: self.seq > since, timeout)
            if self.seq <= since:
                return {"seq": self.seq, "changed": []}
            return {"seq": self.seq, "changed": self.changed_since(since)}


class MockState:
    def __init__(self, token, fixtures_dir):
        self.tokens = [token]
        self.fixtures = fixtures_dir
        self.hub = EventHub()
        self.v11 = False
        self.v12 = False             # --v12: theme with icons + font roles, colony alert list from the v1.2 fixture
        self.controls = {"paused": False, "speed": 2}
        self.pending = None
        self.sync = {"state": "idle", "needed": True, "neededReason": "no_pack", "suggestedScope": "full",
                     "canStart": True, "fonts": "none"}
        if os.environ.get("ONI_MOCK_SYNC") == "menu":     # the game is at its menu: the sync screen says "No colony is running yet" and Start sync queues
            self.sync.update(canStart=False, reason="menu")
        self.dismissed = set()
        self.noart = bool(os.environ.get("ONI_MOCK_NOART"))
        self.notheme = bool(os.environ.get("ONI_MOCK_NOTHEME"))
        self.log = bool(os.environ.get("ONI_MOCK_LOG"))
        self.zoom = bool(os.environ.get("ONI_MOCK_ZOOM"))   # start with the setting on
        self.tick = False                                   # set by --tick: pages change on each refresh
        self.next_seq = 5
        self.actions = {}          # seq -> {"state": ..., "message": ...}
        self.lock = threading.Lock()
        # v1.4: Connect a phone (in memory; ONI_MOCK_CONNECT=off starts with the switch off)
        start = self.fixture("api/connect-state-off.json" if os.environ.get("ONI_MOCK_CONNECT") == "off" else "api/connect-state.json")
        self.identity = dict(start["identity"])
        self.connect = {"enabled": start["enabled"], "plainHttp": start["plainHttp"],
                        "devices": list(start["devices"]), "code": start["code"]}

    def connect_addresses(self):
        return list(self.fixture("api/connect-state.json")["addresses"])

    def fixture(self, rel):
        with open(os.path.join(self.fixtures, rel), encoding="utf-8") as f:
            return json.load(f)


def _int_param(params, name, default, lo=None, hi=None, clamp=False):
    if name not in params:
        return default
    raw = params[name][-1]
    if not re.fullmatch(r"-?\d+", raw):
        raise bad("%s must be an integer." % name)
    value = int(raw)
    if lo is not None and value < lo:
        raise bad("%s must be at least %d." % (name, lo))
    if hi is not None and value > hi:
        if clamp:
            value = hi
        else:
            raise bad("%s must be at most %d." % (name, hi))
    return value


def _check_value(field, value):
    """Check one submitted value against a form field (blocks.schema.json Field).
    Raises bad() naming the field."""
    name = field["name"]
    kind = field["kind"]
    if kind == "number":
        if "units" in field:
            if not isinstance(value, dict) or set(value) - {"value", "unit"}:
                raise bad("%s must be {value, unit}." % name)
            unit_ids = [u["id"] for u in field["units"]]
            if value.get("unit") not in unit_ids:
                raise bad("%s: unit must be one of %s." % (name, ", ".join(unit_ids)))
            value = value.get("value")
        elif isinstance(value, dict):
            if field.get("unit") and value.get("unit") != field["unit"]:
                raise bad("%s: unit must be %s." % (name, field["unit"]))
            value = value.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise bad("%s must be a number." % name)
        if "min" in field and value < field["min"]:
            raise bad("%s must be at least %s." % (name, field["min"]))
        if "max" in field and value > field["max"]:
            raise bad("%s must be at most %s." % (name, field["max"]))
    elif kind == "element":
        if not isinstance(value, str) or not value:
            raise bad("%s must be an element id." % name)
    elif kind == "choice":
        options = [o["value"] for o in field["options"]]
        if value not in options:
            raise bad("%s must be one of %s." % (name, ", ".join(options)))
    elif kind == "toggle":
        if not isinstance(value, bool):
            raise bad("%s must be true or false." % name)


def check_tool_values(form_screen, body):
    """POST /tools body: {"values": {...}}. Unknown fields are ignored; missing
    values take the field default (so they are not checked)."""
    if not isinstance(body, dict) or not isinstance(body.get("values"), dict):
        raise bad('Body must be {"values": {...}}.')
    values = body["values"]
    for block in form_screen["blocks"]:
        if block.get("type") != "form":
            continue
        for field in block["fields"]:
            if field["name"] in values:
                _check_value(field, values[field["name"]])
    return values


class Handler(BaseHTTPRequestHandler):
    server_version = "ONIMock/1"
    protocol_version = "HTTP/1.1"

    @property
    def state(self):
        return self.server.state

    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ---- plumbing ----
    def _send(self, status, payload):
        if isinstance(payload, tuple):      # (content type, bytes): the art route
            ctype, body = payload
        else:
            ctype = "application/json; charset=utf-8"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, err):
        self._send(err.status, {"error": {"code": err.code, "message": err.message}})

    def _read_json(self):
        try:
            return json.loads(self._raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise bad("Body is not valid JSON.")

    def _authorized(self, query):
        presented = [self.headers.get("X-Oni-Token"), self.headers.get("X-Barry-Token")]
        presented += query.get("token", [])
        for token in self.state.tokens:
            for given in presented:
                if given is not None and hmac.compare_digest(given.encode(), token.encode()):
                    return True
        return False

    def _dispatch(self, method):
        # Read the body first, so an error reply never leaves bytes unread on a
        # keep-alive connection.
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.close_connection = True
            return self._error(bad("Body too large."))
        self._raw = self.rfile.read(length) if length else b""
        parts = urlsplit(self.path)
        if not parts.path.startswith(API + "/") and parts.path != API:
            return self._error(not_found("No such path."))
        query = parse_qs(parts.query, keep_blank_values=True)
        if not self._authorized(query):
            return self._error(ApiError(403, "bad_token", "Missing or wrong token."))
        segs = [unquote(s) for s in parts.path[len(API) + 1:].split("/")]
        try:
            status, payload = self.route(method, segs, query)
        except ApiError as err:
            return self._error(err)
        except Exception as exc:  # a bug in the mock: short reply, details on stderr
            sys.stderr.write("internal error: %r\n" % (exc,))
            return self._error(ApiError(500, "internal", "Mock server error."))
        self._send(status, payload)

    V13_ENTRIES = {"SynthTrap": "screens/entry-building-v13.json", "SynthPump": "screens/entry-building-ports.json",
                   "SynthWireBridge": "screens/entry-building-plain.json"}

    def route_v13(self, method, segs, query):
        """v1.3: tabs, Actions, Buildings, the pad actions and the mod install, from the synthetic fixtures."""
        st = self.state
        if method == "GET":
            if segs == ["tabs"]:
                return 200, st.fixture("api/tabs.json")
            if segs == ["pad"]:
                screen = st.fixture("screens/actions.json")
                if os.environ.get("ONI_MOCK_PADART"):     # dev: the overlay and tool buttons with a picture (a synced theme image)
                    for b in screen["blocks"]:
                        if b.get("variant") == "pad":
                            for c in b["cards"]:
                                c["art"] = "/api/v1/art/ui/button"
                return 200, screen
            if segs == ["settings"] and os.environ.get("ONI_MOCK_MODSTATE"):   # dev: the Settings page with the game-mod section
                return 200, st.fixture("screens/settings-modstate.json")
            if segs == ["buildings"]:
                return 200, st.fixture("screens/buildings.json")
            if len(segs) == 3 and segs[:2] == ["entry", "building"] and segs[2] in self.V13_ENTRIES:
                return 200, st.fixture(self.V13_ENTRIES[segs[2]])
            if len(segs) == 3 and segs[:2] == ["entry", "building"] and segs[2] == "SynthWidgetMaker" and os.environ.get("ONI_MOCK_LOCKED"):
                return 200, st.fixture("screens/entry-building-locked.json")     # dev: the locked building's page
            return None
        if method == "POST" and segs == ["mod", "install"]:
            body = self._read_json()
            if not isinstance(body, dict) or body.get("confirm") is not True:
                raise bad("Ask the user first, then send {\"confirm\":true}.")
            return 200, st.fixture("api/mod-install-reply.json")
        if method == "POST" and len(segs) == 2 and segs[0] == "actions" and segs[1] in ("overlay_set", "tool_select", "build_select", "mod_install"):
            body = self._read_json()
            if not isinstance(body, dict) or not body:
                raise bad("Body must be a JSON object.")
            if segs[1] == "mod_install" and body.get("confirm") is not True:
                raise bad("Ask the user first, then send {\"confirm\":true}.")
            if st.log:
                sys.stderr.write("ACTION %s %s\n" % (segs[1], json.dumps(body, sort_keys=True)))
            if segs[1] == "build_select" and not isinstance(body.get("buildingId"), str):
                raise bad("buildingId is required.")
            with st.lock:
                st.next_seq += 1
                seq = st.next_seq
                st.actions[seq] = {"state": "pending"}
            locked = segs[1] == "build_select" and body.get("buildingId") == "SynthWidgetMaker"

            def ack():
                time.sleep(0.3)
                st.actions[seq] = ({"state": "failed", "message": "Not researched yet"} if locked else {"state": "done"})
                st.hub.bump(["action"])
            threading.Thread(target=ack, daemon=True).start()
            return 200, {"seq": seq}
        return None

    # ---- v1.4: Connect a phone (loopback side: Barry's Settings page) ----
    def route_connect(self, method, segs, query):
        st = self.state
        c = st.connect
        if method == "GET" and segs == ["connect"]:
            return 200, connect_state(st)
        if method == "POST" and segs == ["connect", "switch"]:
            c["enabled"] = bool(self._read_json_bool())
            if not c["enabled"]:
                c["code"] = None
            elif c["code"] is None:
                c["code"] = new_code()
            st.hub.bump(["connect"])
            return 200, connect_state(st)
        if method == "POST" and segs == ["connect", "plain-http"]:
            c["plainHttp"] = bool(self._read_json_bool())
            st.hub.bump(["connect"])
            return 200, connect_state(st)
        if method == "POST" and segs == ["connect", "code"]:
            if not c["enabled"]:
                raise bad("Connect a phone is off.")
            c["code"] = new_code()
            st.hub.bump(["connect"])
            return 200, {"ok": True}
        if method == "GET" and segs == ["connect", "devices"]:
            return 200, {"devices": list(c["devices"])}
        if method == "DELETE" and len(segs) == 3 and segs[:2] == ["connect", "devices"]:
            before = len(c["devices"])
            c["devices"] = [d for d in c["devices"] if d["deviceId"] != segs[2]]
            if len(c["devices"]) == before:
                raise not_found("No paired device %s." % segs[2])
            st.hub.bump(["connect"])
            return 200, {"ok": True, "removed": 1}
        if method == "POST" and segs == ["connect", "reset-identity"]:
            removed = len(c["devices"])
            c.update(enabled=False, plainHttp=False, devices=[], code=None)
            st.identity = new_identity()
            st.hub.bump(["connect"])
            return 200, {"ok": True, "removed": removed}
        if method == "GET" and segs == ["connect", "qr.png"]:
            if c["code"] is None:
                raise not_found("No pairing code right now.")
            return 200, ("image/png", qr_placeholder_png(connect_qr_text(st)))
        return None

    def _read_json_bool(self):
        body = self._read_json()
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            raise bad("Body needs \"enabled\": true or false.")
        return body["enabled"]

    def route(self, method, segs, query):
        st = self.state
        v13 = self.route_v13(method, segs, query)
        if v13 is not None:
            return v13
        v11 = self.route_v11(method, segs, query)
        if v11 is not None:
            return v11
        if method == "GET" and segs == ["status"]:
            return 200, st.fixture("api/status.json")
        if method == "GET" and segs == ["home"]:
            return 200, st.fixture("screens/home.json")
        if method == "GET" and segs == ["kinds"]:
            return 200, st.fixture("api/kinds.json")
        if method == "GET" and segs == ["search"]:
            return 200, self.search(query)
        if method == "GET" and len(segs) == 2 and segs[0] == "list":
            return 200, self.list_kind(segs[1], query)
        if method == "GET" and len(segs) == 3 and segs[0] == "entry":
            key = (segs[1], segs[2])
            if key not in ENTRY_FIXTURES:
                raise not_found("No entry %s/%s in the mock fixtures." % key)
            return 200, st.fixture(ENTRY_FIXTURES[key])
        if method == "GET" and len(segs) == 3 and segs[0] == "raw":
            key = (segs[1], segs[2])
            if key not in RAW_FIXTURES:
                raise not_found("No raw data for %s/%s in the mock fixtures." % key)
            return 200, st.fixture(RAW_FIXTURES[key])
        if method == "GET" and segs == ["colony"]:
            world = _int_param(query, "world", 0)
            if world != 0:
                raise not_found("No world %d in the mock fixtures." % world)
            if st.v11 and st.v12:
                return 200, self.colony_v12()
            return 200, st.fixture("screens/colony-v11.json" if st.v11 else "screens/colony.json")
        if method == "GET" and segs == ["tools"]:
            return 200, st.fixture("api/tools.json")
        if len(segs) == 2 and segs[0] == "tools":
            tool = segs[1]
            if tool not in TOOL_FORMS:
                raise not_found("No tool %s in the mock fixtures." % tool)
            if method == "GET":
                return 200, st.fixture(TOOL_FORMS[tool])
            if method == "POST":
                form = st.fixture(TOOL_FORMS[tool])
                check_tool_values(form, self._read_json())
                return 200, st.fixture(TOOL_RESULTS[tool])
        if method == "GET" and segs == ["events"]:
            since = _int_param(query, "since", 0, lo=0)
            timeout = _int_param(query, "timeout", 25, lo=0, hi=60, clamp=True)
            return 200, st.hub.poll(since, timeout)
        if segs[:1] == ["connect"]:
            connect = self.route_connect(method, segs, query)
            if connect is not None:
                return connect
        if segs[:1] == ["pair"] and self._is_planned_pair(method, segs):
            raise ApiError(501, "not_in_v1", "Pairing is planned, not in v1.")
        raise not_found("No such endpoint.")

    # ---- v1.2 ----
    ALERT_PAGES = {"a1": "screens/alert-page.json", "a2": "screens/alert-page-dismissable.json",
                   "a3": "screens/alert-page-dismissable.json"}

    def route_v12(self, method, segs, query):
        st = self.state
        if segs == ["controls"] and method == "GET":
            return 200, self.controls_reply()
        if segs == ["controls"] and method == "POST":
            body = self._read_json()
            if os.environ.get("ONI_MOCK_CONTROLS_DOWN"):
                raise ApiError(503, "unavailable", "The game is not available.")
            if not isinstance(body, dict) or body.get("state") not in ("pause", "play", "speed"):
                raise bad("state must be pause, play or speed.")
            if "speed" in body and (body["state"] == "pause" or body["speed"] not in (1, 2, 3)):
                raise bad("speed (1, 2 or 3) goes only with play or speed.")
            if body["state"] == "speed" and "speed" not in body:
                raise bad("state speed needs speed.")
            with st.lock:
                st.next_seq += 1
                seq = st.next_seq
                st.pending = {"state": body["state"], "seq": seq}
                if "speed" in body:
                    st.pending["speed"] = body["speed"]
            pend = dict(st.pending)

            def apply():
                time.sleep(0.8)         # about what the push script + live write take
                with st.lock:
                    if pend["state"] != "speed":
                        st.controls["paused"] = pend["state"] == "pause"
                    if "speed" in pend:
                        st.controls["speed"] = pend["speed"]
                    st.pending = None
                st.hub.bump(["controls"])
            st.hub.bump(["controls"])
            threading.Thread(target=apply, daemon=True).start()
            return 200, self.controls_reply()
        if segs == ["sync"] and method == "GET":
            return 200, self.sync_reply()
        if segs == ["sync"] and method == "POST":
            body = self._read_json() if self._raw.strip() else {}
            if isinstance(body, dict) and body.get("cancel") is True:
                st.sync.pop("queued", None)
                st.hub.bump(["sync"])
                return 200, self.sync_reply()
            scope = body.get("scope", st.sync.get("suggestedScope", "full")) if isinstance(body, dict) else "full"
            if scope not in ("full", "missing"):
                raise bad("scope must be full or missing.")
            if not st.sync.get("canStart") and st.sync["state"] != "running":     # like the core: queued until a colony runs
                st.sync["queued"] = True
                st.hub.bump(["sync"])
                return 200, self.sync_reply()
            if st.sync["state"] != "running":
                st.sync.update(state="running", scope=scope, done=0, total=60, errors=0, current=None,
                               startedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

                def run():
                    for i in range(1, 61):
                        time.sleep(0.15)
                        st.sync.update(done=i, current="building: SynthWidget%d" % i)
                        st.hub.bump(["sync"])
                    st.sync.update(state="done", needed=False, fonts="ready", current=None)
                    st.sync.pop("neededReason", None)
                    st.hub.bump(["sync"])
                threading.Thread(target=run, daemon=True).start()
                st.hub.bump(["sync"])
            return 200, self.sync_reply()
        if segs == ["fonts"] and method == "GET":
            return 200, st.fixture("api/fonts.json")
        if method == "GET" and len(segs) == 2 and segs[0] == "fonts":
            listed = {f["name"] for f in st.fixture("api/fonts.json")["fonts"]}
            if segs[1] not in listed:
                raise not_found("No font %s." % segs[1])
            path = os.path.join(st.fixtures, "companion", "fonts", "100001", segs[1])
            if not os.path.isfile(path):
                raise not_found("No font %s." % segs[1])
            ctype = {"ttf": "font/ttf", "png": "image/png", "json": "application/json"}[segs[1].rsplit(".", 1)[-1]]
            with open(path, "rb") as f:
                return 200, (ctype, f.read())
        if method == "GET" and len(segs) == 3 and segs[:2] == ["entry", "alert"]:
            if segs[2] not in self.ALERT_PAGES or segs[2] in st.dismissed:
                raise not_found("Alert is gone.")
            return 200, st.fixture(self.ALERT_PAGES[segs[2]])
        return None

    def controls_reply(self):
        st = self.state
        if os.environ.get("ONI_MOCK_CONTROLS_DOWN"):     # dev: the bar dimmed (game in the menu)
            d = st.fixture("api/controls-unavailable.json")
            d.setdefault("game", {"state": "menu", "label": "At the main menu", "tone": "warn"})
            return d
        paused = st.controls["paused"]
        out = {"available": True, "paused": paused, "speed": st.controls["speed"],
               "game": {"state": "paused", "label": "Game paused", "tone": "good"} if paused
               else {"state": "live", "label": "Live", "tone": "good"},
               "asOf": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if st.pending:
            out["pending"] = dict(st.pending)
        return out

    def sync_reply(self):
        return {k: v for k, v in self.state.sync.items()}

    def colony_v12(self):
        scr = self.state.fixture("screens/colony-v11.json")
        alerts = self.state.fixture("screens/colony-alerts.json")["blocks"][0]
        alerts["items"] = [i for i in alerts["items"] if i["ref"]["id"] not in self.state.dismissed]
        blocks = [b for b in scr["blocks"] if not (b.get("type") == "list" and b.get("variant") == "alerts")]
        scr["blocks"] = [alerts] + blocks
        return scr

    # ---- v1.1 ----
    def route_v11(self, method, segs, query):
        st = self.state
        v12 = self.route_v12(method, segs, query)
        if v12 is not None:
            return v12
        if method == "GET" and len(segs) == 3 and segs[0] == "art":
            return self.art(segs[1], segs[2])
        if method == "GET" and segs == ["theme"]:
            return 200, st.fixture("api/theme-builtin.json" if st.notheme else
                                   "api/theme-v12.json" if st.v12 else "api/theme.json")
        if method == "GET" and segs == ["resources"]:
            world = _int_param(query, "world", 0)
            if world not in (0, 1):
                raise not_found("No world %d in the mock fixtures." % world)
            screen = st.fixture("screens/resources.json")
            if world == 1:
                screen["subtitle"] = "Far Asteroid"
                screen["worldSwitcher"]["active"] = 1
                screen["blocks"] = screen["blocks"][:1]
            return 200, screen
        if segs == ["settings"] and method in ("GET", "POST"):
            if method == "POST":
                body = self._read_json()
                values = body.get("values") if isinstance(body, dict) else None
                if not isinstance(values, dict):
                    raise bad('Body must be {"values": {...}}.')
                if "zoomToDupeOnSelect" in values:
                    if not isinstance(values["zoomToDupeOnSelect"], bool):
                        raise bad("zoomToDupeOnSelect must be true or false.")
                    st.zoom = values["zoomToDupeOnSelect"]
                st.hub.bump(["settings"])
            return 200, st.fixture("screens/settings-saved.json" if st.zoom else "screens/settings.json")
        if method == "GET" and len(segs) == 3 and segs[:2] == ["entry", "dupe"]:
            return self.dupe_page(segs[2])
        if method == "POST" and len(segs) == 2 and segs[0] == "actions":
            return self.post_action(segs[1])
        if method == "GET" and len(segs) == 2 and segs[0] == "actions":
            if not segs[1].isdigit() or int(segs[1]) not in st.actions:
                raise not_found("No action %s." % segs[1])
            seq = int(segs[1])
            out = {"seq": seq}
            out.update(st.actions[seq])
            return 200, out
        return None

    def art(self, kind, ident):
        st = self.state
        if st.noart:
            raise not_found("No art.")
        if kind == "ui":                     # theme images: companion/theme/<build>/<name>.png
            if st.notheme or not re.fullmatch(r"[A-Za-z0-9_-]+", ident):
                raise not_found("No art.")
            path = os.path.join(st.fixtures, "companion-v12" if st.v12 else "companion", "theme", "100001", ident + ".png")
            if not os.path.isfile(path):
                raise not_found("No art ui/%s." % ident)
            with open(path, "rb") as f:
                return 200, ("image/png", f.read())
        root = os.path.join(st.fixtures, "companion", "art")
        try:
            manifest = st.fixture("companion/art/manifest.json")
        except OSError:
            raise not_found("No art.")
        files = [f for f in manifest.get("files", []) if f["kind"] == kind]
        hit = [f for f in files if f["id"] == ident]
        if not hit and kind == "dupe":       # portraits are <id>-<appearanceHash>
            hit = [f for f in files if f["id"].startswith(ident + "-")]
        if not hit:
            raise not_found("No art %s/%s." % (kind, ident))
        with open(os.path.join(root, hit[0]["path"]), "rb") as f:
            return 200, ("image/png", f.read())

    def dupe_page(self, ident):
        st = self.state
        if ident not in ("d1", "d2"):
            raise not_found("No duplicant %s." % ident)
        page = st.fixture("screens/dupe-page-onopen.json" if st.zoom else "screens/dupe-page.json")
        if ident == "d2":
            text = json.dumps(page).replace('"d1"', '"d2"').replace("/dupe/d1", "/dupe/d2")
            page = json.loads(text.replace("Ada", "Bo").replace('"Dig"', '"Idle"'))
        if st.tick:       # with --tick every refresh differs, like a live colony
            page["asOf"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return 200, page

    def post_action(self, name):
        st = self.state
        if name in ("alert_activate", "alert_dismiss"):
            return self.post_alert_action(name)
        if name != "focus":
            raise not_found("No action %s." % name)
        body = self._read_json()
        target = body.get("target") if isinstance(body, dict) else None
        if not isinstance(target, dict) or target.get("kind") != "dupe" or not isinstance(target.get("id"), str):
            raise bad("target must be {kind: dupe, id}.")
        if st.log:
            sys.stderr.write("ACTION focus %s select=%s\n" % (target["id"], body.get("select", True)))
            sys.stderr.flush()
        if target["id"] == "menu":
            raise ApiError(503, "unavailable", "The game is in the menu. Load a colony first.")
        with st.lock:
            st.next_seq += 1
            seq = st.next_seq
            st.actions[seq] = {"state": "pending"}
        ok = target["id"] in ("d1", "d2")

        def ack():
            time.sleep(0.6)
            st.actions[seq] = {"state": "done"} if ok else {"state": "failed", "message": "Duplicant not found"}
            st.hub.bump(["action"])
        threading.Thread(target=ack, daemon=True).start()
        return 200, {"seq": seq}

    def post_alert_action(self, name):
        st = self.state
        body = self._read_json()
        aid = body.get("alertId") if isinstance(body, dict) else None
        if not isinstance(aid, str) or not aid:
            raise bad("alertId is required.")
        if "link" in body and (not isinstance(body["link"], int) or isinstance(body["link"], bool) or body["link"] < 0):
            raise bad("link must be a whole number, 0 or more.")
        with st.lock:
            st.next_seq += 1
            seq = st.next_seq
            st.actions[seq] = {"state": "pending"}
        known = aid in self.ALERT_PAGES and aid not in st.dismissed

        def ack():
            time.sleep(0.6)
            if not known:
                st.actions[seq] = {"state": "failed", "message": "Alert is gone"}
            elif name == "alert_dismiss" and aid != "a3":
                st.actions[seq] = {"state": "failed", "message": "Can't be dismissed"}
            else:
                st.actions[seq] = {"state": "done"}
                if name == "alert_dismiss":
                    st.dismissed.add(aid)
                    st.hub.bump(["colony"])
            st.hub.bump(["action"])
        threading.Thread(target=ack, daemon=True).start()
        return 200, {"seq": seq}

    @staticmethod
    def _is_planned_pair(method, segs):
        return ((method == "POST" and segs in (["pair", "start"], ["pair", "complete"]))
                or (method == "GET" and segs == ["pair", "clients"])
                or (method == "DELETE" and len(segs) == 3 and segs[:2] == ["pair", "clients"]))

    def search(self, query):
        q = query.get("q", [""])[-1]
        if not q.strip():
            raise bad("q is required.")
        kind = query.get("kind", [None])[-1]
        if kind is not None and kind not in KINDS:
            raise bad("Unknown kind %s." % kind)
        limit = _int_param(query, "limit", 20, lo=1, hi=100, clamp=True)
        needle = q.strip().lower()
        hits = [r for r in self.state.fixture("api/search.json")["results"]
                if (kind is None or r["kind"] == kind)
                and (needle in r["name"].lower() or needle in r["id"].lower())]
        return {"query": q, "results": hits[:limit], "truncated": len(hits) > limit}

    def list_kind(self, kind, query):
        if kind not in KINDS:
            raise not_found("Unknown kind %s." % kind)
        sort = query.get("sort", ["name"])[-1]
        if sort not in ("name", "dlc"):
            raise bad("sort must be name or dlc.")
        if kind not in LIST_FIXTURES:
            raise not_found("No list for %s in the mock fixtures." % kind)
        return self.state.fixture(LIST_FIXTURES[kind])

    # ---- HTTP verbs ----
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")


class MockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, state, verbose=False):
        self.state = state
        self.verbose = verbose
        super().__init__(addr, Handler)


def is_loopback(host):
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_server(host="127.0.0.1", port=0, token="mock-token", fixtures=DEFAULT_FIXTURES,
                verbose=False, v11=False, v12=False):
    """Build a server without starting it. Tests use port 0 and server.hub."""
    if not is_loopback(host):
        raise SystemExit("Non-loopback --listen is not in v1.")
    state = MockState(token, fixtures)
    state.v11 = v11
    state.v12 = v12
    return MockServer((host, port), state, verbose=verbose)


def start_tick(hub, seconds, stop):
    def run():
        n = 0
        while not stop.wait(seconds):
            n += 1
            names = ["colony"] if n % 2 else ["colony", "status"]
            hub.bump(names)
    threading.Thread(target=run, name="tick", daemon=True).start()


def parse_listen(value):
    host, sep, port = value.rpartition(":")
    if not sep or not port.isdigit():
        raise argparse.ArgumentTypeError("use HOST:PORT, for example 127.0.0.1:8765")
    return host or "127.0.0.1", int(port)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mock ONI Companion core (synthetic fixtures).")
    ap.add_argument("--listen", type=parse_listen, default=("127.0.0.1", 8765))
    ap.add_argument("--token", default=os.environ.get("ONI_MOCK_TOKEN"))
    ap.add_argument("--tick", type=float, default=0.0, metavar="SECONDS",
                    help="bump seq every SECONDS (0 = off)")
    ap.add_argument("--fixtures", default=DEFAULT_FIXTURES)
    ap.add_argument("--v11", action="store_true", help="serve the v1.1 Colony screen at /colony")
    ap.add_argument("--v12", action="store_true", help="v1.2: theme with icons + font roles, colony alerts like the game (implies --v11)")
    ap.add_argument("--v1", action="store_true", help="serve the v1 Colony screen (default is v1.1 when the Barry app starts the mock)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    host, port = args.listen
    if not is_loopback(host):
        ap.error("--listen %s: not in v1 (loopback only)." % host)
    if args.tick < 0:
        ap.error("--tick must be 0 or more.")
    token = args.token or secrets.token_urlsafe(16)
    server = make_server(host, port, token, args.fixtures, args.verbose, v11=(args.v11 or args.v12) and not args.v1, v12=args.v12 and not args.v1)
    stop = threading.Event()
    if args.tick > 0:
        server.state.tick = True
        start_tick(server.state.hub, args.tick, stop)
    bound_host, bound_port = server.server_address[:2]
    print("ONI mock core on http://%s:%d%s  (token: %s%s)" % (
        bound_host, bound_port, API, token,
        "" if not args.token else " from env/flag"), flush=True)
    if args.tick > 0:
        print("tick every %g s" % args.tick, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
