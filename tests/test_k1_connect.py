"""K1: the v1.4 connection layer: identity, TLS listener, pairing, device tokens, limits, request files, mDNS,
impostor check, service lifetime."""
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion.connect import addresses as addr_mod  # noqa: E402
from oni_companion.connect import devices as devices_mod  # noqa: E402
from oni_companion.connect import identity as ident_mod  # noqa: E402
from oni_companion import lifetime
from oni_companion.connect import mdns  # noqa: E402
from oni_companion.connect.ratelimit import DeviceLimits, SlidingCount, TokenBucket  # noqa: E402
from oni_companion.connect.words import ADJECTIVES, ANIMALS  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402

V = Validator(os.path.join(ROOT, "contracts"))
FIX = os.path.join(ROOT, "fixtures", "synthetic")
TOKEN = "loopback-token"
ADDRS = [{"address": "192.168.1.23", "kind": "lan"}, {"address": "100.64.12.7", "kind": "tailscale"}]
HAVE_OPENSSL = bool(shutil.which("openssl"))


def utc_now(offset=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


class FakeAnnouncer:
    def __init__(self):
        self.calls = []
        self.active = None

    def start(self, info, port, lan):
        self.calls.append(("start", dict(info), port, list(lan)))
        self.active = (dict(info), port)

    def stop(self):
        if self.active:
            self.calls.append(("stop",))
        self.active = None


class PinError(Exception):
    pass


class PinnedClient:
    """What the Android app does: connect over TLS, check the certificate against the pinned fingerprint, and only
    then send anything (a token above all)."""

    def __init__(self, host, port, pinned, timeout=10):
        self.host, self.port, self.pinned, self.timeout = host, port, pinned, timeout
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE          # the fingerprint pin replaces the CA check
        self.ctx = ctx
        self.conn = None

    def connect(self):
        c = http.client.HTTPSConnection(self.host, self.port, context=self.ctx, timeout=self.timeout)
        c.connect()
        fp = hashlib.sha256(c.sock.getpeercert(binary_form=True)).hexdigest()
        if fp != self.pinned:
            c.close()
            raise PinError("certificate does not match the pinned fingerprint")
        self.conn = c

    def request(self, method, path, headers=None, body=None):
        if self.conn is None:
            self.connect()
        data = json.dumps(body).encode() if body is not None else None
        h = dict(headers or {})
        if data is not None:
            h["Content-Type"] = "application/json"
        self.conn.request(method, path, body=data, headers=h)
        r = self.conn.getresponse()
        raw = r.read()
        return r.status, dict(r.getheaders()), json.loads(raw) if raw else None

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


def loop_http(port, path, method="GET", headers=None, body=None, host="127.0.0.1", timeout=10):
    c = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers=headers or {})
        r = c.getresponse()
        raw = r.read()
        return r.status, dict(r.getheaders()), json.loads(raw) if raw else None
    finally:
        c.close()


def wait_for(fn, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-k1-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.services = []
        self.svc = self.make()

    def make(self, name="a", **opts):
        base = os.path.join(self.tmp, name)
        user = os.path.join(base, "user")
        os.makedirs(os.path.join(user, "companion", "live"), exist_ok=True)
        o = dict(announcer=FakeAnnouncer(), addresses_fn=lambda: list(ADDRS), bind_host="127.0.0.1",
                 dest_ok=None, preferred_port=0)
        o.update(opts)
        cfg = ServiceConfig(user_dir=user, token=TOKEN, data_dir=os.path.join(base, "data"),
                            views_factory=lambda ctx: StubViews(ctx), connect_opts=o)
        svc = Service(cfg).start()
        svc.user = user
        svc.ann = o["announcer"]
        self.services.append(svc)
        self.addCleanup(svc.stop)
        return svc

    # loopback calls with the loopback token
    def lb(self, path, method="GET", body=None, svc=None, token=TOKEN):
        svc = svc or self.svc
        hdr = {"X-Oni-Token": token} if token else {}
        return loop_http(svc.port, "/api/v1" + path, method, hdr, body)

    def on(self, svc=None, plain=False):
        svc = svc or self.svc
        st, _, body = self.lb("/connect/switch", "POST", {"enabled": True}, svc)
        self.assertEqual(st, 200, body)
        if plain:
            st, _, body = self.lb("/connect/plain-http", "POST", {"enabled": True}, svc)
            self.assertEqual(st, 200, body)
        return body

    def client(self, svc=None, state=None):
        svc = svc or self.svc
        state = state or self.lb("/connect", svc=svc)[2]
        return PinnedClient("127.0.0.1", state["port"], state["identity"]["fingerprint"])

    def pair(self, svc=None, label="Test phone", platform="android", client=None):
        svc = svc or self.svc
        state = self.lb("/connect", svc=svc)[2]
        client = client or self.client(svc, state)
        code = state["code"]["display"]
        st, _, rep = client.request("POST", "/api/v1/connect/claim", body={"code": code, "label": label, "platform": platform})
        self.assertEqual(st, 200, rep)
        return client, rep


class TestWords(unittest.TestCase):
    def test_lists(self):
        for lst in (ADJECTIVES, ANIMALS):
            self.assertGreaterEqual(len(lst), 200)
            self.assertEqual(len(lst), len(set(lst)))
            for w in lst:
                self.assertRegex(w, r"^[a-z]{2,20}$")
        banned = {"klei", "oni", "duplicant", "dupe", "hatch", "pip", "puft", "morb", "drecko", "slickster", "pacu", "vole", "shine"}
        self.assertFalse(banned & set(ADJECTIVES + ANIMALS))

    def test_names_vary_and_match_the_contract(self):
        names = {ident_mod.random_name() for _ in range(200)}
        self.assertGreater(len(names), 150)
        for n in names:
            self.assertRegex(n, r"^[a-z]{2,20}-[a-z]{2,20}$")


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="oni-k1-id-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_create_load_reset(self):
        i = ident_mod.Identity(self.d)
        self.assertFalse(i.exists)
        body = i.body()
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/Identity"), [])
        for f in ("key.pem", "cert.pem", "identity.json"):
            self.assertEqual(os.stat(os.path.join(self.d, f)).st_mode & 0o777, 0o600, f)
        pem = open(os.path.join(self.d, "cert.pem")).read()
        self.assertEqual(body["fingerprint"], hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest())
        self.assertEqual(body["fingerprintTag"], body["fingerprint"][:4].upper())
        out = subprocess.run(["openssl", "x509", "-in", os.path.join(self.d, "cert.pem"), "-noout", "-subject", "-enddate"],
                             capture_output=True, text=True).stdout
        self.assertIn(body["instanceId"], out)
        # a second start keeps everything
        again = ident_mod.Identity(self.d)
        self.assertEqual(again.body(), body)
        # reset: all new
        again.reset()
        new = again.body()
        self.assertNotEqual(new["fingerprint"], body["fingerprint"])
        self.assertNotEqual(new["instanceId"], body["instanceId"])
        self.assertEqual(sorted(os.listdir(self.d)), ["cert.pem", "identity.json", "key.pem"])   # no work files left

    def test_key_is_ec_p256(self):
        ident_mod.Identity(self.d).ensure()
        out = subprocess.run(["openssl", "x509", "-in", os.path.join(self.d, "cert.pem"), "-noout", "-text"],
                             capture_output=True, text=True).stdout
        self.assertRegex(out, r"prime256v1|P-256")

    def test_missing_openssl_is_a_clear_error(self):
        with self.assertRaises(ident_mod.IdentityError) as cm:
            ident_mod.Identity(self.d, openssl="no-such-openssl-command").ensure()
        self.assertIn("openssl", str(cm.exception))
        self.assertEqual(os.listdir(self.d), [])        # nothing half made

    def test_damaged_files_mean_no_identity_not_a_crash(self):
        ident_mod.Identity(self.d).ensure()
        with open(os.path.join(self.d, "cert.pem"), "w") as f:
            f.write("junk")
        self.assertFalse(ident_mod.Identity(self.d).exists)


class TestPieces(unittest.TestCase):
    def test_bucket(self):
        t = [0.0]
        b = TokenBucket(5, 10, lambda: t[0])
        self.assertEqual([b.take() for _ in range(10)], [0] * 10)
        self.assertGreaterEqual(b.take(), 1)
        t[0] += 1.0
        self.assertEqual(b.take(), 0)

    def test_sliding(self):
        t = [0.0]
        s = SlidingCount(60, lambda: t[0])
        for _ in range(3):
            s.add("x")
        self.assertEqual(s.count("x"), 3)
        t[0] = 61
        self.assertEqual(s.count("x"), 0)

    def test_address_classes(self):
        c = addr_mod.classify
        self.assertEqual(c("192.168.1.5"), "lan")
        self.assertEqual(c("192.168.1.73"), "lan")
        self.assertEqual(c("172.16.0.2"), "lan")
        self.assertEqual(c("100.64.12.7"), "tailscale")
        for a in ("127.0.0.1", "8.8.8.8", "169.254.1.1", "0.0.0.0", "::1", "junk"):
            self.assertIsNone(c(a), a)

    def test_address_listing_skips_containers_and_orders_lan_first(self):
        ipout = ("2: wlan0    inet 192.168.1.73/24 brd x scope global\n3: tailscale0    inet 100.64.12.7/32 scope global\n"
                 "4: docker0    inet 172.17.0.1/16 scope global\n")
        with mock.patch.object(addr_mod.shutil, "which", return_value="/sbin/ip"):
            got = addr_mod.local_addresses(run=lambda cmd: ipout)
        self.assertEqual(got, [{"address": "192.168.1.73", "kind": "lan"}, {"address": "100.64.12.7", "kind": "tailscale"}])


@unittest.skipUnless(hasattr(os, "pidfd_open"), "Linux only: the game wait uses a pidfd")
class TestLifetime(unittest.TestCase):
    def test_standalone_exits_at_once_without_game(self):
        from oni_companion import __main__ as m
        tmp = tempfile.mkdtemp(prefix="oni-k1-main-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.object(lifetime, "find_game", return_value=None):
            t0 = time.monotonic()
            with self.assertRaises(SystemExit) as cm:
                m.main(["--mode", "standalone", "--user-dir", tmp, "--listen", "127.0.0.1:0"])
            self.assertEqual(cm.exception.code, 0)
        self.assertLess(time.monotonic() - t0, 3)

    def test_standalone_stops_when_the_game_ends(self):
        from oni_companion import __main__ as m
        tmp = tempfile.mkdtemp(prefix="oni-k1-main-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = subprocess.Popen(["sleep", "30"])
        self.addCleanup(p.kill)
        threading.Timer(0.5, p.kill).start()
        env = {"ONI_DATA_DIR": os.path.join(tmp, "data"), "ONI_USER_DIR": tmp, "HOME": tmp}
        done = threading.Event()

        def run():
            with mock.patch.dict(os.environ, env), mock.patch.object(lifetime, "find_game", return_value=lifetime.GameProcess(p.pid, "native", ["x"])), \
                    mock.patch.object(lifetime, "still_game", return_value=True):
                try:
                    m.main(["--mode", "standalone", "--user-dir", tmp, "--listen", "127.0.0.1:0"])
                except SystemExit:
                    pass
            done.set()
        threading.Thread(target=run, daemon=True).start()
        self.assertTrue(done.wait(10), "the service did not end with the game")


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class TestConnect(Env):
    def test_off_by_default_nothing_listens_and_no_files_but_state(self):
        st, _, body = self.lb("/connect")
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/ConnectState"), [])
        self.assertFalse(body["enabled"])
        self.assertFalse(body["listening"])
        self.assertIsNone(body["port"])
        self.assertEqual((body["addresses"], body["code"], body["qrText"]), ([], None, None))
        self.assertFalse(body["plainHttp"])
        self.assertIsNone(self.svc.connect.port)
        self.assertEqual(self.svc.ann.calls, [])
        st, _, status = self.lb("/status")
        self.assertEqual(status["connect"], {"enabled": False, "listening": False, "devices": 0})
        self.assertEqual(V.validate(status, "api.schema.json#/$defs/Status"), [])
        state = json.load(open(os.path.join(self.svc.user, "companion", "pairing", "state.json")))
        self.assertEqual(V.validate(state, "pairing.schema.json#/$defs/State"), [])
        self.assertFalse(state["enabled"])

    def test_identity_endpoint_open_on_loopback_without_token(self):
        st, _, body = self.lb("/identity", token=None)
        self.assertEqual(st, 200)
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/Identity"), [])
        self.assertNotIn("colony", json.dumps(body).lower())
        st, _, _ = self.lb("/status", token=None)
        self.assertEqual(st, 403)                      # everything else still needs the loopback token

    def test_switch_on_listens_announces_and_validates(self):
        state = self.on()
        self.assertEqual(V.validate(state, "api.schema.json#/$defs/ConnectState"), [])
        self.assertTrue(state["listening"])
        self.assertEqual(state["addresses"], ADDRS)
        qr = json.loads(state["qrText"])
        self.assertEqual(V.validate(qr, "pairing.schema.json#/$defs/QrPayload"), [])
        self.assertLessEqual(len(state["qrText"].encode()), 400)
        self.assertEqual(state["qrText"], json.dumps(qr, separators=(",", ":")))
        self.assertEqual((qr["f"], qr["i"], qr["n"], qr["p"]), (state["identity"]["fingerprint"], state["identity"]["instanceId"],
                                                              state["identity"]["name"], state["port"]))
        self.assertEqual(qr["c"], state["code"]["display"].replace("-", ""))
        self.assertEqual(qr["a"], ["192.168.1.23", "100.64.12.7"])
        # announced with exactly the 4.1 fields
        start = self.svc.ann.calls[0]
        self.assertEqual(start[0], "start")
        self.assertEqual(start[2], state["port"])
        self.assertEqual(start[3], ["192.168.1.23"])             # multicast only on the LAN address
        # the file for the mod
        sf = json.load(open(os.path.join(self.svc.user, "companion", "pairing", "state.json")))
        self.assertEqual(V.validate(sf, "pairing.schema.json#/$defs/State"), [])
        self.assertEqual(sf["qrText"], state["qrText"])
        self.assertEqual(sf["pid"], os.getpid())
        self.assertNotIn("token", json.dumps(sf).lower().replace("devicetoken", ""))
        # the loopback listener is untouched
        self.assertEqual(self.lb("/status")[0], 200)

    def test_switch_survives_a_restart_and_off_closes_at_once(self):
        self.on()
        port = self.svc.connect.port
        self.svc.stop()
        svc2 = self.make("a")        # same folders
        self.assertTrue(svc2.connect.enabled)
        self.assertTrue(svc2.connect.listening)
        self.svc = svc2
        self.lb("/connect/switch", "POST", {"enabled": False})
        self.assertIsNone(svc2.connect.port)
        self.assertIsNone(svc2.ann.active)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)

    def test_tls_pinned_identity_and_open_endpoints(self):
        state = self.on()
        c = self.client(state=state)
        st, _, ident = c.request("GET", "/api/v1/identity")
        self.assertEqual(st, 200)
        self.assertEqual(ident, state["identity"])
        # everything else: 401, never 403, never a hint
        for path in ("/api/v1/status", "/api/v1/home", "/api/v1/nothing", "/other", "/api/v1/connect"):
            st, _, body = c.request("GET", path)
            self.assertEqual((st, body["error"]["code"]), (401, "unauthorized"), path)
            self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [])
        # loopback credentials mean nothing here
        for hdr in ({"X-Oni-Token": TOKEN}, {"X-Barry-Token": TOKEN}):
            self.assertEqual(c.request("GET", "/api/v1/status", hdr)[0], 401)
        self.assertEqual(c.request("GET", "/api/v1/status?token=" + TOKEN)[0], 401)

    def test_old_tls_is_refused(self):
        state = self.on()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.maximum_version = ssl.TLSVersion.TLSv1_1 if hasattr(ssl.TLSVersion, "TLSv1_1") else ssl.TLSVersion.TLSv1
        with self.assertRaises((ssl.SSLError, OSError)):
            with socket.create_connection(("127.0.0.1", state["port"]), timeout=5) as s:
                ctx.wrap_socket(s)

    def test_pairing_and_use(self):
        self.on()
        client, rep = self.pair(label="Pixel 9")
        self.assertEqual(V.validate(rep, "api.schema.json#/$defs/ClaimReply"), [])
        self.assertEqual(rep["identity"], self.lb("/identity", token=None)[2])
        h = {"X-Oni-Device": rep["deviceToken"]}
        for path, schema in (("/api/v1/status", "api.schema.json#/$defs/Status"), ("/api/v1/home", "screen.schema.json"),
                             ("/api/v1/events", "api.schema.json#/$defs/Events")):
            st, _, body = client.request("GET", path, h)
            self.assertEqual(st, 200, path)
            self.assertEqual(V.validate(body, schema), [], path)
        self.assertNotIn("connect", client.request("GET", "/api/v1/status", h)[2])       # never shown to a paired device
        # the device is listed (and only on loopback)
        devs = self.lb("/connect/devices")[2]
        self.assertEqual(V.validate(devs, "api.schema.json#/$defs/ConnectDevices"), [])
        self.assertEqual(len(devs["devices"]), 1)
        d = devs["devices"][0]
        self.assertEqual((d["deviceId"], d["label"], d["platform"], d["transport"]), (rep["deviceId"], "Pixel 9", "android", "tls"))
        self.assertIsNotNone(d["lastSeen"])
        # only the hash is stored
        raw = open(os.path.join(self.svc.connect.folder, "devices.json")).read()
        self.assertNotIn(rep["deviceToken"], raw)
        self.assertIn(hashlib.sha256(rep["deviceToken"].encode()).hexdigest(), raw)
        self.assertEqual(os.stat(os.path.join(self.svc.connect.folder, "devices.json")).st_mode & 0o777, 0o600)
        # the code is single use: a new one is shown, the old one fails
        state = self.lb("/connect")[2]
        self.assertEqual(len(state["devices"]), 1)
        # malformed tokens are 401
        for tok in ("", "x", rep["deviceToken"][:-1], rep["deviceToken"] + "A", "A" * 43):
            self.assertEqual(client.request("GET", "/api/v1/status", {"X-Oni-Device": tok})[0], 401, tok)

    def test_command_allow_list_unchanged_for_paired_devices(self):
        self.on()
        client, rep = self.pair()
        h = {"X-Oni-Device": rep["deviceToken"]}
        # unknown action id is 404, like on loopback (no mod here, so the action layer answers)
        loop = self.lb("/actions/definitely_not_an_action", "POST", {})[0]
        net = client.request("POST", "/api/v1/actions/definitely_not_an_action", h, {})[0]
        self.assertEqual(net, loop)
        # management is loopback only, with the same body for every one of them
        for method, path, body in (("GET", "/api/v1/connect", None), ("GET", "/api/v1/connect/devices", None),
                                   ("POST", "/api/v1/connect/switch", {"enabled": False}),
                                   ("POST", "/api/v1/connect/plain-http", {"enabled": True}),
                                   ("POST", "/api/v1/connect/code", {}), ("POST", "/api/v1/connect/reset-identity", {}),
                                   ("DELETE", "/api/v1/connect/devices/" + rep["deviceId"], None)):
            st, _, b = client.request(method, path, h, body)
            self.assertEqual((st, b["error"]["code"]), (403, "local_only"), (method, path))
            self.assertEqual(V.validate(b, "api.schema.json#/$defs/Error"), [])
        for path in ("/api/v1/mod/install", "/api/v1/actions/mod_install"):
            st, _, b = client.request("POST", path, h, {"confirm": True})
            self.assertEqual((st, b["error"]["code"]), (403, "local_only"), path)
        self.assertTrue(self.svc.connect.listening)
        self.assertEqual(len(self.svc.connect.devices.public_list()), 1)

    def test_claim_errors_and_code_rules(self):
        state = self.on()
        c = self.client(state=state)
        good = state["code"]["display"]
        st, _, body = c.request("POST", "/api/v1/connect/claim", body={"code": "AAAA-AAAA", "label": "x"})
        self.assertEqual((st, body["error"]["code"]), (403, "bad_code"))
        self.assertEqual(self.lb("/connect")[2]["code"]["failuresLeft"], 4)
        # bad requests
        for b in ({}, {"code": 5, "label": "x"}, {"code": good}, {"code": good, "label": ""}, {"code": good, "label": "x", "platform": "toaster"}):
            self.assertEqual(c.request("POST", "/api/v1/connect/claim", body=b)[0], 400, b)
        # lower case and no dash is fine; the used code can not be used again
        st, _, rep = c.request("POST", "/api/v1/connect/claim", body={"code": good.replace("-", "").lower(), "label": "one"})
        self.assertEqual(st, 200)
        st, _, body = c.request("POST", "/api/v1/connect/claim", body={"code": good, "label": "two"})
        self.assertEqual((st, body["error"]["code"]), (403, "bad_code"))
        self.assertEqual(self.lb("/connect")[2]["code"]["display"] != good, True)

    def test_five_wrong_codes_block_that_source_not_the_code(self):
        state = self.on()
        first = state["code"]["display"]
        c = self.client(state=state)
        for i in range(5):
            st, _, _ = c.request("POST", "/api/v1/connect/claim", body={"code": "ZZZZ-ZZZZ", "label": "x"})
            self.assertEqual(st, 403)
        now = self.lb("/connect")[2]["code"]
        self.assertEqual(now["display"], first)          # F3: the code stays for everybody else
        self.assertEqual(now["failuresLeft"], 0)
        # the blocked source is refused even with the right code
        st, h, body = c.request("POST", "/api/v1/connect/claim", body={"code": first, "label": "late"})
        self.assertEqual((st, body["error"]["code"]), (429, "rate_limited"))

    def test_expired_code_is_refused_and_replaced_by_timer(self):
        state = self.on()
        c = self.client(state=state)
        real = time.time
        self.svc.connect.clock = lambda: real() + 301
        st, _, body = c.request("POST", "/api/v1/connect/claim", body={"code": state["code"]["display"], "label": "x"})
        self.assertEqual((st, body["error"]["code"]), (403, "bad_code"))
        # the one-shot timer replaces an expired code (called directly: the timer itself is a real 300 s wait)
        code = self.svc.connect._code
        self.svc.connect._expired(code)
        self.assertNotEqual(self.svc.connect._code, code)

    def test_pairing_rate_limits(self):
        state = self.on()
        c = self.client(state=state)
        statuses = []
        for _ in range(12):
            st, hdr, body = c.request("POST", "/api/v1/connect/claim", body={"code": "ZZZZ-ZZZZ", "label": "x"})
            statuses.append(st)
            if st == 429:
                self.assertEqual(body["error"]["code"], "rate_limited")
                self.assertGreaterEqual(int(hdr["Retry-After"]), 1)
                self.assertEqual(V.validate(body, "api.schema.json#/$defs/Error"), [])
        # F3: after 5 wrong tries on one code this source is blocked until the code ends (429 from the 6th)
        self.assertEqual(statuses[:5], [403] * 5)
        self.assertEqual(set(statuses[5:]), {429})
        # while limited even the right code is refused
        st, _, _ = c.request("POST", "/api/v1/connect/claim", body={"code": self.lb("/connect")[2]["code"]["display"], "label": "x"})
        self.assertEqual(st, 429)

    def test_unauthorized_rate_limit_per_source(self):
        state = self.on()
        c = self.client(state=state)
        sts = [c.request("GET", "/api/v1/status")[0] for _ in range(32)]
        self.assertEqual(sts[:30], [401] * 30)
        self.assertEqual(sts[30:], [429, 429])

    def test_device_rate_limits_and_poll_limit(self):
        self.on()
        client, rep = self.pair()
        h = {"X-Oni-Device": rep["deviceToken"]}
        self.svc.connect.limits = DeviceLimits(lambda: 1000.0)       # frozen clock: no refill between requests
        seen = set()
        retry = None
        for _ in range(60):
            st, hdr, body = client.request("GET", "/api/v1/kinds", h)
            seen.add(st)
            if st == 429:
                retry = hdr.get("Retry-After")
                self.assertEqual(body["error"]["code"], "rate_limited")
        self.assertEqual(seen, {200, 429})
        self.assertIsNotNone(retry)
        self.assertEqual(self.svc.connect.limits.check(rep["deviceId"], "GET"), 1)
        # a second paired device has its own budget
        client2, rep2 = self.pair(label="other")
        self.assertEqual(client2.request("GET", "/api/v1/kinds", {"X-Oni-Device": rep2["deviceToken"]})[0], 200)
        # writes: burst 10
        sts = [client2.request("POST", "/api/v1/actions/nothing", {"X-Oni-Device": rep2["deviceToken"]}, {})[0] for _ in range(14)]
        self.assertIn(429, sts)
        self.assertEqual(sts[0], 404)

    def test_long_poll_limit_and_remove_wakes_poll_with_401(self):
        self.on()
        client, rep = self.pair()
        h = {"X-Oni-Device": rep["deviceToken"]}
        seq = client.request("GET", "/api/v1/events", h)[2]["seq"]
        results = {}

        def poll(n):
            c = PinnedClient("127.0.0.1", self.svc.connect.port, self.svc.connect.identity.fingerprint)
            results[n] = c.request("GET", "/api/v1/events?since=%d&timeout=20" % seq, h)
        ts = [threading.Thread(target=poll, args=(i,), daemon=True) for i in range(2)]
        for t in ts:
            t.start()
        wait_for(lambda: self.svc.connect.limits._polls.get(rep["deviceId"]) == 2)
        third = PinnedClient("127.0.0.1", self.svc.connect.port, self.svc.connect.identity.fingerprint)
        st, _, body = third.request("GET", "/api/v1/events?since=%d&timeout=1" % seq, h)
        self.assertEqual((st, body["error"]["code"]), (429, "rate_limited"))
        t0 = time.monotonic()
        st, _, body = self.lb("/connect/devices/" + rep["deviceId"], "DELETE")
        self.assertEqual((st, body), (200, {"ok": True, "removed": 1}))
        for t in ts:
            t.join(5)
        self.assertLess(time.monotonic() - t0, 3)             # woken by the event, not by the 20 s timeout
        self.assertEqual([results[i][0] for i in (0, 1)], [401, 401])

    def test_remove_device_revokes_at_once(self):
        self.on()
        client, rep = self.pair()
        h = {"X-Oni-Device": rep["deviceToken"]}
        self.assertEqual(client.request("GET", "/api/v1/status", h)[0], 200)
        st, _, body = self.lb("/connect/devices/" + rep["deviceId"], "DELETE")
        self.assertEqual(V.validate(body, "api.schema.json#/$defs/ConnectDone"), [])
        st, _, body = client.request("GET", "/api/v1/status", h)
        self.assertEqual((st, body["error"]["code"]), (401, "unauthorized"))
        self.assertEqual(self.lb("/connect/devices/" + rep["deviceId"], "DELETE")[0], 404)
        self.assertEqual(self.lb("/connect/devices/nonsense", "DELETE")[0], 404)
        # the token never comes back after a restart either
        self.svc.stop()
        self.svc = self.make("a")
        self.assertEqual(self.svc.connect.devices.count(), 0)

    def test_reset_identity_unpairs_everyone_and_turns_off(self):
        state = self.on(plain=True)
        client, rep = self.pair()
        old_fp, old_id, old_name = (state["identity"][k] for k in ("fingerprint", "instanceId", "name"))
        st, _, body = self.lb("/connect/reset-identity", "POST", {})
        self.assertEqual((st, body), (200, {"ok": True, "removed": 1}))
        new = self.lb("/connect")[2]
        self.assertEqual(V.validate(new, "api.schema.json#/$defs/ConnectState"), [])
        self.assertFalse(new["enabled"] or new["listening"] or new["plainHttp"])
        self.assertNotEqual(new["identity"]["fingerprint"], old_fp)
        self.assertNotEqual(new["identity"]["instanceId"], old_id)
        self.assertEqual(new["devices"], [])
        # turn it on again: the old pairing does not work, the old pin refuses the new certificate
        state2 = self.on()
        old_pin = PinnedClient("127.0.0.1", state2["port"], old_fp)
        with self.assertRaises(PinError):
            old_pin.request("GET", "/api/v1/status", {"X-Oni-Device": rep["deviceToken"]})
        fresh = self.client(state=state2)
        self.assertEqual(fresh.request("GET", "/api/v1/status", {"X-Oni-Device": rep["deviceToken"]})[0], 401)
        self.assertFalse(self.svc.connect.plain_http)

    def test_switch_off_cuts_open_connections_and_drops_code(self):
        state = self.on()
        client, rep = self.pair()
        h = {"X-Oni-Device": rep["deviceToken"]}
        client.request("GET", "/api/v1/status", h)          # keep-alive connection is open
        self.lb("/connect/switch", "POST", {"enabled": False})
        with self.assertRaises((OSError, http.client.HTTPException)):
            client.request("GET", "/api/v1/status", h)
        off = self.lb("/connect")[2]
        self.assertEqual((off["listening"], off["code"], off["qrText"], off["addresses"]), (False, None, None, []))
        self.assertEqual(self.svc.ann.calls[-1], ("stop",))
        self.assertEqual(len(off["devices"]), 1)            # pairings survive an off/on
        self.on()
        new_client = self.client()
        self.assertEqual(new_client.request("GET", "/api/v1/status", h)[0], 200)

    def test_plain_http_only_when_turned_on(self):
        state = self.on()
        self.assertFalse(state["plainHttp"])
        self.assertIsNone(state["plainHttpPort"])
        st = self.lb("/connect/plain-http", "POST", {"enabled": True})[2]
        self.assertEqual(V.validate(st, "api.schema.json#/$defs/ConnectState"), [])
        self.assertTrue(st["plainHttp"])
        pport = st["plainHttpPort"]
        self.assertIsNotNone(pport)
        self.assertIn("Plain HTTP is on", st["plainHttpNote"])
        # an iPhone pairs over plain HTTP
        code = st["code"]["display"]
        s, _, rep = loop_http(pport, "/api/v1/connect/claim", "POST", body={"code": code, "label": "iPhone", "platform": "ios"})
        self.assertEqual(s, 200, rep)
        tok = {"X-Oni-Device": rep["deviceToken"]}
        self.assertEqual(loop_http(pport, "/api/v1/status", headers=tok)[0], 200)
        self.assertEqual(loop_http(pport, "/api/v1/status", headers={})[0], 401)
        dev = self.lb("/connect/devices")[2]["devices"][0]
        self.assertEqual(dev["transport"], "http")
        self.assertIn("anyone on this Wi-Fi can read its token", self.lb("/connect")[2]["plainHttpNote"])
        # a TLS-paired token is refused on the plain port
        tls_client, tls_rep = self.pair(label="android")
        self.assertEqual(loop_http(pport, "/api/v1/status", headers={"X-Oni-Device": tls_rep["deviceToken"]})[0], 401)
        # the plain device also works over TLS
        self.assertEqual(self.client().request("GET", "/api/v1/status", tok)[0], 200)
        # management stays loopback only on the plain listener too
        self.assertEqual(loop_http(pport, "/api/v1/connect", headers=tok)[0], 403)
        # off again: the plain port closes
        self.lb("/connect/plain-http", "POST", {"enabled": False})
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", pport), timeout=1)
        # plain HTTP without the main switch is nothing
        self.lb("/connect/switch", "POST", {"enabled": False})
        self.lb("/connect/plain-http", "POST", {"enabled": True})
        self.assertIsNone(self.svc.connect.plain_port)

    def test_devices_of_one_service_are_useless_at_another(self):
        other = self.make("b")
        self.on()
        self.on(svc=other)
        a, rep_a = self.pair()
        b, rep_b = self.pair(svc=other)
        self.assertNotEqual(self.lb("/identity", token=None)[2]["fingerprint"], self.lb("/identity", svc=other, token=None)[2]["fingerprint"])
        self.assertEqual(a.request("GET", "/api/v1/status", {"X-Oni-Device": rep_a["deviceToken"]})[0], 200)
        self.assertEqual(b.request("GET", "/api/v1/status", {"X-Oni-Device": rep_a["deviceToken"]})[0], 401)
        self.assertEqual(b.request("GET", "/api/v1/status", {"X-Oni-Device": rep_b["deviceToken"]})[0], 200)

    def test_impostor_with_same_name_and_id_never_gets_a_token(self):
        state = self.on()
        client, rep = self.pair()          # paired and pinned to the real service
        real = state["identity"]
        # the impostor: another certificate, the real id and name, a logging TLS server
        imp_dir = os.path.join(self.tmp, "impostor")
        imp = ident_mod.Identity(imp_dir).ensure()
        imp.instance_id, imp.name = real["instanceId"], real["name"]
        self.assertNotEqual(imp.fingerprint, real["fingerprint"])
        ctx = imp.tls_context()
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(5)
        got = []
        stop = threading.Event()

        def serve():
            lsock.settimeout(0.2)
            while not stop.is_set():
                try:
                    conn, _ = lsock.accept()
                except (socket.timeout, OSError):
                    continue
                try:
                    tls = ctx.wrap_socket(conn, server_side=True)
                    tls.settimeout(1)
                    try:
                        got.append(tls.recv(65536))
                    except (OSError, ssl.SSLError):
                        pass
                    tls.close()
                except (OSError, ssl.SSLError):
                    conn.close()
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        self.addCleanup(lambda: (stop.set(), t.join(2), lsock.close()))
        victim = PinnedClient("127.0.0.1", lsock.getsockname()[1], real["fingerprint"])
        with self.assertRaises(PinError):
            victim.request("GET", "/api/v1/status", {"X-Oni-Device": rep["deviceToken"]})
        time.sleep(0.3)
        self.assertEqual([g for g in got if g], [], "the impostor received bytes after the handshake")
        self.assertNotIn(rep["deviceToken"].encode(), b"".join(got))
        # and the discovery view of it: same id, different fingerprint -> a client marks it "Can't verify"
        self.assertEqual(imp.body()["instanceId"], real["instanceId"])
        self.assertNotEqual(imp.body()["fingerprint"], real["fingerprint"])

    def test_two_services_on_one_machine_are_two_identities(self):
        other = self.make("b")
        a = self.on()
        b = self.on(svc=other)
        self.assertNotEqual(a["identity"]["fingerprint"], b["identity"]["fingerprint"])
        self.assertNotEqual(a["identity"]["instanceId"], b["identity"]["instanceId"])
        self.assertNotEqual(a["port"], b["port"])


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class TestRequestFiles(Env):
    def req(self, seq, **kw):
        d = os.path.join(self.svc.user, "companion", "pairing", "requests")
        os.makedirs(d, exist_ok=True)
        body = {"schema": 1, "seq": seq, "createdAt": utc_now(), "type": "set_enabled", "enabled": True}
        body.update(kw)
        path = os.path.join(d, "req-%d.json" % seq)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(body, f)
        os.rename(tmp, path)       # the mod's rule: temp file, then rename
        return path

    def state_file(self):
        with open(os.path.join(self.svc.user, "companion", "pairing", "state.json")) as f:
            return json.load(f)

    def done(self, seq, path):
        wait_for(lambda: not os.path.exists(path))
        return wait_for(lambda: (self.state_file().get("lastRequest") or {}).get("seq") == seq and self.state_file()["lastRequest"])

    def test_switch_on_off_via_files(self):
        p = self.req(1, type="set_enabled", enabled=True)
        self.assertEqual(self.done(1, p), {"seq": 1, "state": "done"})
        self.assertTrue(self.svc.connect.listening)
        sf = self.state_file()
        self.assertEqual(V.validate(sf, "pairing.schema.json#/$defs/State"), [])
        self.assertTrue(sf["listening"] and sf["qrText"])
        p = self.req(2, type="set_enabled", enabled=False)
        self.assertEqual(self.done(2, p)["state"], "done")
        self.assertFalse(self.svc.connect.listening)
        self.assertFalse(self.state_file()["enabled"])

    def test_deeply_nested_request_is_dropped_and_watcher_survives(self):
        d = os.path.join(self.svc.user, "companion", "pairing", "requests")
        os.makedirs(d, exist_ok=True)
        bad = os.path.join(d, "req-1.json")
        with open(bad, "w") as f:
            f.write("[" * 100000)
        self.svc.connect.handle_request_file(bad)       # must not raise
        self.assertFalse(os.path.exists(bad))
        p = self.req(2, type="set_enabled", enabled=True)
        self.assertEqual(self.done(2, p)["state"], "done")

    def test_every_request_type_and_fixtures_validate(self):
        for name in sorted(os.listdir(os.path.join(FIX, "companion", "pairing", "requests"))):
            d = json.load(open(os.path.join(FIX, "companion", "pairing", "requests", name)))
            self.assertEqual(V.validate(d, "pairing.schema.json#/$defs/Request"), [], name)

    def test_new_code_remove_device_reset_and_plain(self):
        self.done(1, self.req(1, type="set_enabled", enabled=True))
        first = self.state_file()["code"]["display"]
        self.assertEqual(self.done(2, self.req(2, type="new_code"))["state"], "done")
        self.assertNotEqual(self.state_file()["code"]["display"], first)
        client, rep = self.pair()
        self.assertEqual(self.done(3, self.req(3, type="remove_device", deviceId="d-ffffffffffff")),
                         {"seq": 3, "state": "failed", "message": "Device not found."})
        self.assertEqual(self.done(4, self.req(4, type="remove_device", deviceId=rep["deviceId"]))["state"], "done")
        self.assertEqual(client.request("GET", "/api/v1/status", {"X-Oni-Device": rep["deviceToken"]})[0], 401)
        self.assertEqual(self.done(5, self.req(5, type="set_plain_http", enabled=True))["state"], "done")
        self.assertIsNotNone(self.state_file()["plainHttpPort"])
        # reset needs confirm true
        r = self.done(6, self.req(6, type="reset_identity", confirm=False))
        self.assertEqual((r["state"], r["message"]), ("failed", "Not confirmed"))
        fp = self.state_file()["identity"]["fingerprint"]
        self.assertEqual(self.done(7, self.req(7, type="reset_identity", confirm=True))["state"], "done")
        sf = self.state_file()
        self.assertNotEqual(sf["identity"]["fingerprint"], fp)
        self.assertFalse(sf["enabled"])

    def test_old_and_out_of_order_requests_are_dropped(self):
        self.done(5, self.req(5, type="set_enabled", enabled=False))
        p = self.req(5, type="set_enabled", enabled=True, createdAt=utc_now())
        r = self.done(5, p)
        self.assertEqual(r["message"], "Request too old")
        self.assertFalse(self.svc.connect.enabled)
        p = self.req(9, type="set_enabled", enabled=True, createdAt=utc_now(-60))
        self.assertEqual(self.done(9, p), {"seq": 9, "state": "failed", "message": "Request too old"})
        self.assertFalse(self.svc.connect.enabled)
        self.assertFalse(os.path.exists(p))

    def test_bad_files_are_deleted_and_never_act(self):
        d = os.path.join(self.svc.user, "companion", "pairing", "requests")
        os.makedirs(d, exist_ok=True)
        junk = os.path.join(d, "req-3.json")
        with open(junk, "w") as f:
            f.write("{nope")
        self.assertTrue(wait_for(lambda: not os.path.exists(junk)))
        # unknown type, wrong value types, paths in a request: never acted on
        for seq, kw in ((10, {"type": "format_disk"}), (11, {"type": "set_enabled", "enabled": "yes"}),
                        (12, {"type": "remove_device", "deviceId": 5})):
            r = self.done(seq, self.req(seq, **kw))
            self.assertEqual(r["state"], "failed", kw)
        self.assertFalse(self.svc.connect.enabled)
        # a file whose seq differs from its name is ignored (and removed)
        p = os.path.join(d, "req-20.json")
        with open(p + ".tmp", "w") as f:
            json.dump({"schema": 1, "seq": 21, "createdAt": utc_now(), "type": "set_enabled", "enabled": True}, f)
        os.rename(p + ".tmp", p)
        self.assertTrue(wait_for(lambda: not os.path.exists(p)))
        self.assertFalse(self.svc.connect.enabled)

    def test_requests_waiting_at_start_are_handled_in_order(self):
        self.svc.stop()
        d = os.path.join(self.tmp, "a", "user", "companion", "pairing", "requests")
        os.makedirs(d, exist_ok=True)
        for seq, en in ((1, True), (2, False), (3, True)):
            with open(os.path.join(d, "req-%d.json" % seq), "w") as f:
                json.dump({"schema": 1, "seq": seq, "createdAt": utc_now(), "type": "set_enabled", "enabled": en}, f)
        self.svc = self.make("a")
        self.assertTrue(self.svc.connect.enabled)
        self.assertEqual(os.listdir(d), [])
        self.assertEqual(self.state_file()["lastRequest"], {"seq": 3, "state": "done"})

    def test_state_file_removed_on_normal_exit(self):
        path = os.path.join(self.svc.user, "companion", "pairing", "state.json")
        self.assertTrue(os.path.exists(path))
        self.svc.stop()
        self.assertFalse(os.path.exists(path))


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class TestGameGate(Env):
    def test_network_follows_the_game(self):
        self.svc.stop()
        self.svc = self.make("g")
        cm = self.svc.connect
        self.lb("/connect/switch", "POST", {"enabled": True})
        self.assertTrue(cm.listening)
        cm.set_game_running(False)
        self.assertFalse(cm.listening)
        self.assertTrue(cm.enabled)                      # the stored switch stays
        self.assertFalse(os.path.exists(cm.state_path))  # no state file without the game
        self.assertEqual(self.svc.ann.calls[-1], ("stop",))
        self.assertEqual(self.lb("/status")[0], 200)     # Barry's loopback side keeps working
        cm.set_game_running(True)
        self.assertTrue(cm.listening)
        self.assertTrue(os.path.exists(cm.state_path))

    def test_no_game_at_start_no_listener(self):
        self.svc.stop()
        base = os.path.join(self.tmp, "n")
        user = os.path.join(base, "user")
        os.makedirs(os.path.join(user, "companion"))
        os.makedirs(os.path.join(base, "data", "connect"))
        with open(os.path.join(base, "data", "connect", "config.json"), "w") as f:
            json.dump({"enabled": True, "plainHttp": False}, f)
        cfg = ServiceConfig(user_dir=user, token=TOKEN, data_dir=os.path.join(base, "data"), views_factory=lambda c: StubViews(c),
                            connect_opts=dict(announcer=FakeAnnouncer(), addresses_fn=lambda: ADDRS, bind_host="127.0.0.1", dest_ok=None))
        svc = Service(cfg)
        svc.connect.game_running = False
        svc.start()
        self.addCleanup(svc.stop)
        self.assertTrue(svc.connect.enabled)
        self.assertFalse(svc.connect.listening)


class TestMdns(unittest.TestCase):
    INFO = {"id": "3f6c1b2e-8a4d-4c5e-9b7a-1d2e3f405162", "name": "spiffy-raccoon", "api": 1, "core": "1.4.0", "tag": "A4CC"}

    def test_txt_is_exactly_the_four_fields(self):
        pairs = mdns.txt_pairs(dict(self.INFO, colony="Secret", steam="x"))
        self.assertEqual([k for k, _ in pairs], ["id", "name", "api", "core"])
        txt = dict(pairs)
        self.assertEqual(V.validate(txt, "pairing.schema.json#/$defs/MdnsTxt"), [])
        self.assertEqual(mdns.instance_label(self.INFO), "ONI Companion on spiffy-raccoon")

    def test_avahi_command_line(self):
        calls = []

        class P:
            def __init__(self, argv, **kw):
                calls.append(argv)
                self._ev = threading.Event()

            def wait(self, t=None):
                self._ev.wait(t)
                return 0

            def terminate(self):
                calls.append("terminated")
                self._ev.set()
        pub = mdns.AvahiPublisher(self.INFO, 47615, exe="avahi-publish-service", popen=P).start()
        self.assertEqual(calls[0], ["avahi-publish-service", "ONI Companion on spiffy-raccoon", "_onicompanion._tcp", "47615",
                                    "id=" + self.INFO["id"], "name=spiffy-raccoon", "api=1", "core=1.4.0"])
        pub.stop()
        self.assertEqual(calls[1], "terminated")

    def test_announcer_prefers_avahi_and_falls_back(self):
        made = []

        class FakeAvahi:
            def __init__(self, info, port):
                self.on_exit = None
                made.append(("avahi", port))

            def start(self):
                return self

            def stop(self):
                made.append("avahi-stop")

        class FakeResp:
            def __init__(self, info, port, lan):
                made.append(("resp", port, tuple(lan)))

            def start(self):
                return self

            def stop(self):
                made.append("resp-stop")
        a = mdns.Announcer(avahi_ok=lambda: True, avahi_factory=FakeAvahi, responder_factory=FakeResp)
        self.assertEqual(a.start(self.INFO, 1000, ["10.0.0.2"]), "avahi")
        a.stop()
        self.assertEqual(made, [("avahi", 1000), "avahi-stop"])
        made.clear()
        b = mdns.Announcer(avahi_ok=lambda: False, avahi_factory=FakeAvahi, responder_factory=FakeResp)
        self.assertEqual(b.start(self.INFO, 1001, ["10.0.0.2"]), "responder")
        b.stop()
        self.assertEqual(made, [("resp", 1001, ("10.0.0.2",)), "resp-stop"])
        # avahi dying while on moves to the responder
        made.clear()
        c = mdns.Announcer(avahi_ok=lambda: True, avahi_factory=FakeAvahi, responder_factory=FakeResp)
        c.start(self.INFO, 1002, ["10.0.0.2"])
        c._impl.on_exit(1)
        self.assertEqual(c.mode, "responder")
        c.stop()

    def test_avahi_detection(self):
        self.assertTrue(mdns.avahi_running(which=lambda n: "/usr/bin/" + n, exists=lambda p: p.startswith("/run/avahi")))
        self.assertFalse(mdns.avahi_running(which=lambda n: None, exists=lambda p: True))
        self.assertFalse(mdns.avahi_running(which=lambda n: "/x", exists=lambda p: False))

    def _records(self):
        return mdns.Records(self.INFO, 47615, ["192.168.1.23"])

    def _parse_rrs(self, pkt):
        _id, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", pkt[:12])
        off, out = 12, []
        for _ in range(an):
            name, off = mdns.dec_name(pkt, off)
            rtype, cls, ttl, ln = struct.unpack("!HHIH", pkt[off:off + 10])
            off += 10
            out.append((name, rtype, ttl, pkt[off:off + ln]))
            off += ln
        return flags, out

    def test_packet_carries_only_the_announced_fields(self):
        flags, rrs = self._parse_rrs(self._records().packet())
        self.assertEqual(flags, 0x8400)
        types = sorted({r[1] for r in rrs})
        self.assertEqual(types, [mdns.T_A, mdns.T_PTR, mdns.T_TXT, mdns.T_SRV])
        txt = [r for r in rrs if r[1] == mdns.T_TXT][0][3]
        strings, i = [], 0
        while i < len(txt):
            strings.append(txt[i + 1:i + 1 + txt[i]].decode())
            i += 1 + txt[i]
        self.assertEqual(sorted(s.split("=")[0] for s in strings), ["api", "core", "id", "name"])
        blob = b"".join(r[3] for r in rrs)
        for secret in (b"colony", b"fingerprint", b"token"):
            self.assertNotIn(secret, blob)
        srv = [r for r in rrs if r[1] == mdns.T_SRV][0]
        self.assertEqual(struct.unpack("!HHH", srv[3][:6])[2], 47615)
        # goodbye = the same records with TTL 0
        _f, gone = self._parse_rrs(self._records().goodbye())
        self.assertTrue(all(r[2] == 0 for r in gone))

    def test_questions_are_matched(self):
        r = self._records()
        self.assertTrue(r.wanted("_onicompanion._tcp.local.", mdns.T_PTR))
        self.assertTrue(r.wanted("_ONICOMPANION._tcp.local.", mdns.T_PTR))
        self.assertFalse(r.wanted("_http._tcp.local.", mdns.T_PTR))
        self.assertEqual(r.wanted("_services._dns-sd._udp.local.", mdns.T_PTR), ("meta",))
        q = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + mdns.enc_name("_onicompanion._tcp.local.") + struct.pack("!HH", mdns.T_PTR, 1)
        self.assertEqual(mdns.parse_questions(q), [("_onicompanion._tcp.local.", mdns.T_PTR, False)])
        self.assertEqual(mdns.parse_questions(b"junk"), [])
        self.assertEqual(mdns.parse_questions(self._records().packet()), [])      # responses are not questions

    def test_responder_answers_a_real_query(self):
        port = 55000 + os.getpid() % 5000
        lan = [a["address"] for a in addr_mod.local_addresses() if a["kind"] == "lan"]
        if not lan:
            self.skipTest("no LAN address")
        try:
            resp = mdns.Responder(self.INFO, 47615, lan, mport=port).start()
        except OSError as e:
            self.skipTest("multicast not available here: %s" % e)
        self.addCleanup(resp.stop)
        c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        c.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            c.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        c.bind(("", port))
        c.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(mdns.GROUP) + socket.inet_aton(lan[0]))
        c.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan[0]))
        c.settimeout(3)
        self.addCleanup(c.close)
        q = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + mdns.enc_name("_onicompanion._tcp.local.") + struct.pack("!HH", mdns.T_PTR, 1)
        c.sendto(q, (mdns.GROUP, port))
        found = False
        for _ in range(8):
            try:
                data, _src = c.recvfrom(9000)
            except socket.timeout:
                break
            _f, rrs = self._parse_rrs(data)
            if any(r[1] == mdns.T_PTR and mdns.dec_name(data, 0)[0] for r in rrs) and any(r[1] == mdns.T_TXT for r in rrs) \
                    and not any(r[2] == 0 for r in rrs):
                found = True
                break
        self.assertTrue(found, "no answer to the PTR query")


@unittest.skipUnless(HAVE_OPENSSL, "needs the openssl command")
class TestMissingOpenssl(Env):
    def test_switch_on_without_openssl_is_a_clear_503_and_stays_off(self):
        self.svc.stop()
        self.svc = self.make("m", openssl="no-such-openssl-command")
        st, _, body = self.lb("/connect/switch", "POST", {"enabled": True})
        self.assertEqual((st, body["error"]["code"]), (503, "unavailable"))
        self.assertIn("openssl", body["error"]["message"])
        self.assertFalse(self.svc.connect.enabled)
        self.assertFalse(self.svc.connect.listening)
        self.assertEqual(self.lb("/status")[0], 200)          # the loopback side does not care


if __name__ == "__main__":
    unittest.main()
