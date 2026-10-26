"""Connect a phone: the switch, the one-time code, pairing, device tokens, the network listener, mDNS and the
pairing files the mod shows (contracts/api.md "v1.4 additions", pairing.schema.json).

Everything here is event driven: the listener sleeps in select(), the code's expiry is a one-shot timer, request
files arrive from the file watcher.
"""
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time

from .. import __version__
from ..server.errors import ApiError
from . import addresses as addr_mod
from .devices import DeviceStore, PLATFORMS, clean_label, iso
from .files import read_json, write_atomic, write_json
from .identity import API_VERSION, Identity, IdentityError
from .mdns import Announcer
from .netserver import NetServer
from .ratelimit import DeviceLimits, SlidingCount

log = logging.getLogger("oni_companion.connect")

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
CODE_SECONDS = 300
CODE_FAILURES = 5
CLAIM_FAIL_PER_SOURCE = 10          # per minute
CLAIM_FAIL_ALL = 30                 # per minute
UNAUTH_PER_SOURCE = 30              # per minute
REQUEST_MAX_AGE = 10.0
SEQ_WINDOW = 1000000                # a request file may be at most this far above the last handled seq
MAX_FAIL_SOURCES = 2000             # sources tracked per code; beyond this the code is replaced
DEFAULT_PORT = 47615
QR_MAX = 400
REQ_RE = re.compile(r"^req-(\d+)\.json$")


def parse_utc(text):
    """'2026-01-01T12:00:00Z' (fraction and +00:00 allowed) -> epoch seconds, or None."""
    import calendar
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(?:Z|\+00:00)", text or "")
    if not m:
        return None
    try:
        return calendar.timegm(tuple(int(x) for x in m.groups()) + (0, 0, 0))
    except (ValueError, OverflowError):
        return None


def make_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(text):
    return re.sub(r"[\s-]", "", str(text)).upper()


class ConnectManager:
    def __init__(self, svc, data_dir, companion_dir=None, autostart=True, clock=time.time, openssl="openssl",
                 announcer=None, addresses_fn=addr_mod.local_addresses, bind_host="0.0.0.0",
                 dest_ok=addr_mod.allowed_destination, preferred_port=DEFAULT_PORT, rng=None):
        self.svc = svc
        self.folder = os.path.join(data_dir, "connect")
        self.companion_dir = companion_dir
        self.autostart = autostart
        self.clock = clock
        self.identity = Identity(self.folder, openssl=openssl, rng=rng)
        self.devices = DeviceStore(os.path.join(self.folder, "devices.json"), clock)
        self.announcer = announcer or Announcer()
        self.addresses_fn, self.bind_host, self.dest_ok = addresses_fn, bind_host, dest_ok
        self.preferred_port = preferred_port
        self.limits = DeviceLimits(clock)
        self._claim_src = SlidingCount(60, clock)
        self._claim_all = SlidingCount(60, clock)
        self._unauth = SlidingCount(60, clock)
        self._lock = threading.RLock()
        cfg = read_json(os.path.join(self.folder, "config.json"), {}) or {}
        self.enabled = cfg.get("enabled") is True
        self.plain_http = cfg.get("plainHttp") is True
        self.game_running = True            # the lifetime gate: set False/True by a GameWatcher (Barry's core)
        self._tls = self._plain = None
        self._code = None                   # {"code", "expires", "failures"}
        self._timer = None
        self._seen_timer = None
        self._addresses = []
        self._last_request = None
        self._handled_seq = 0
        self._closed = False

    # ------------------------------------------------------------------ files and config

    @property
    def pairing_dir(self):
        return os.path.join(self.companion_dir, "pairing") if self.companion_dir else None

    @property
    def state_path(self):
        return os.path.join(self.pairing_dir, "state.json") if self.pairing_dir else None

    @property
    def requests_dir(self):
        return os.path.join(self.pairing_dir, "requests") if self.pairing_dir else None

    def _save_config(self):
        write_json(os.path.join(self.folder, "config.json"), {"enabled": self.enabled, "plainHttp": self.plain_http})

    def _changed(self):
        """Tell loopback clients (the event) and the mod (the file)."""
        self.svc.bus.publish("connect")
        self.write_state_file()

    # ------------------------------------------------------------------ identity

    def ensure_identity(self):
        with self._lock:
            try:
                return self.identity.ensure()
            except IdentityError as e:
                raise ApiError("unavailable", str(e))

    def identity_body(self):
        with self._lock:
            self.ensure_identity()
            return self.identity.body()

    def reset_identity(self):
        with self._lock:
            self.ensure_identity()
            removed = self.devices.clear()
            self.enabled = False
            self.plain_http = False
            self._save_config()
            self._reconcile_locked()
            try:
                self.identity.reset()
            except IdentityError as e:
                raise ApiError("unavailable", str(e))
            self.limits = DeviceLimits(self.clock)
        self._changed()
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------ the switch

    def set_enabled(self, on):
        with self._lock:
            if on:
                self.ensure_identity()
            self.enabled = bool(on)
            if not self.enabled:
                self.plain_http = False       # off means off: plain HTTP does not come back with the next ON
            self._save_config()
            self._reconcile_locked()
        self._changed()

    def set_plain_http(self, on):
        with self._lock:
            self.plain_http = bool(on)
            self._save_config()
            self._reconcile_locked()
        self._changed()

    def set_game_running(self, running):
        """Barry's core: the network side lives only while the game runs (plan 5.1)."""
        with self._lock:
            self.game_running = bool(running)
            self._reconcile_locked()
        if running:
            self._changed()
        else:
            self.svc.bus.publish("connect")
            self.remove_state_file()

    @property
    def listening(self):
        return self._tls is not None

    @property
    def port(self):
        return self._tls.port if self._tls else None

    @property
    def plain_port(self):
        return self._plain.port if self._plain else None

    def _open(self, kind, preferred, tls_ctx):
        try:
            return NetServer(self.bind_host, preferred, self.svc, kind, tls_ctx, self.dest_ok).start()
        except OSError:
            return NetServer(self.bind_host, 0, self.svc, kind, tls_ctx, self.dest_ok).start()

    def _reconcile_locked(self):
        want = self.enabled and self.game_running and not self._closed
        if want:
            if self._tls is None:
                self.ensure_identity()
                self._tls = self._open("tls", self.preferred_port, self.identity.tls_context())
                self._new_code_locked()
                self._refresh_addresses_locked()
                self._announce_locked()
            if self.plain_http and self._plain is None:
                self._plain = self._open("http", self._tls.port + 1, None)
            elif not self.plain_http and self._plain is not None:
                self._plain.close()
                self._plain = None
        else:
            self._close_listeners_locked()

    def _close_listeners_locked(self):
        self.announcer.stop()
        if self._timer:
            self._timer.cancel()
            self._timer = None
        for name in ("_tls", "_plain"):
            srv = getattr(self, name)
            setattr(self, name, None)
            if srv is not None:
                srv.close()
        self._code = None
        self._addresses = []

    def _info(self):
        i = self.identity
        return {"id": i.instance_id, "name": i.name, "api": API_VERSION, "core": __version__, "tag": i.fingerprint[:4]}

    def _announce_locked(self):
        lan = [a["address"] for a in self._addresses if a["kind"] == "lan"]
        try:
            self.announcer.start(self._info(), self._tls.port, lan)
        except Exception:
            log.exception("mdns announcement failed")

    def _refresh_addresses_locked(self):
        try:
            self._addresses = list(self.addresses_fn())
        except Exception:
            log.exception("address lookup failed")
            self._addresses = []

    def refresh_addresses(self):
        with self._lock:
            if not self._tls:
                return
            before = self._addresses
            self._refresh_addresses_locked()
            changed = before != self._addresses
            if changed:
                self._announce_locked()
        if changed:
            self._changed()

    # ------------------------------------------------------------------ the code

    def _new_code_locked(self):
        self._code = {"code": make_code(), "expires": self.clock() + CODE_SECONDS, "failures": {}}
        if self._timer:
            self._timer.cancel()
        t = self._timer = threading.Timer(CODE_SECONDS, self._expired, args=(self._code,))
        t.daemon = True
        t.start()

    def _expired(self, code):
        with self._lock:
            if self._code is not code or not self._tls:
                return
            self._new_code_locked()
        self._changed()

    def new_code(self):
        with self._lock:
            if not self._tls:
                raise ApiError("unavailable", "Connect a phone is off.")
            self._new_code_locked()
        self._changed()
        return {"ok": True}

    def _code_view(self):
        c = self._code
        if not c:
            return None
        return {"display": "%s-%s" % (c["code"][:4], c["code"][4:]), "expiresAt": iso(c["expires"]),
                "failuresLeft": max(0, CODE_FAILURES - max(c["failures"].values(), default=0))}

    # ------------------------------------------------------------------ claim (pairing)

    def claim(self, source, kind, code, label, platform):
        """kind = which listener the request came in on. Returns the ClaimReply."""
        with self._lock:
            if self._claim_src.count(source) >= CLAIM_FAIL_PER_SOURCE:
                raise ApiError("rate_limited", "Too many tries. Wait a minute.", self._claim_src.retry_after(source))
            if self._claim_all.count("all") >= CLAIM_FAIL_ALL:
                raise ApiError("rate_limited", "Too many tries. Wait a minute.", self._claim_all.retry_after("all"))
            c = self._code
            now = self.clock()
            ok = False
            live = c is not None and now < c["expires"]
            if live and c["failures"].get(source, 0) >= CODE_FAILURES:
                # This source used up its tries on this code: it is blocked until the code ends. The code stays
                # for everybody else, so one pest cannot keep the on-screen code (and QR) changing.
                raise ApiError("rate_limited", "Too many tries. Wait for the next code.",
                               max(1, int(c["expires"] - now) + 1))
            if live:
                ok = hmac.compare_digest(normalize_code(code).encode("utf-8"), c["code"].encode("ascii"))
            if not ok:
                self._claim_src.add(source)
                self._claim_all.add("all")
                if live:
                    c["failures"][source] = c["failures"].get(source, 0) + 1
                    if len(c["failures"]) > MAX_FAIL_SOURCES:      # a flood from very many sources: start over
                        self._new_code_locked()
                err = ApiError("bad_code", "That code is wrong or has expired.")
            else:
                token, dev = self.devices.add(label, platform, "http" if kind == "http" else "tls")
                if token is None:
                    raise ApiError("bad_request", "Too many devices. Remove one on the game device first.")
                self._new_code_locked()           # the used code is burned; a fresh one is shown
                err = None
                reply = {"deviceToken": token, "deviceId": dev["deviceId"], "identity": self.identity.body()}
        self._changed()
        if err:
            raise err
        return reply

    # ------------------------------------------------------------------ network requests

    def unauth_blocked(self, source):
        """Seconds to wait when this source has sent too many 401s, else 0."""
        with self._lock:
            if self._unauth.count(source) >= UNAUTH_PER_SOURCE:
                return self._unauth.retry_after(source)
        return 0

    def authenticate(self, token, kind, source):
        retry = self.unauth_blocked(source)
        if retry:
            raise ApiError("rate_limited", "Too many tries. Wait a minute.", retry)
        dev = self.devices.authenticate(token, kind)
        if dev is None:
            with self._lock:
                self._unauth.add(source)
            raise ApiError("unauthorized", "Not paired.")
        if dev.pop("_moved", False):
            self._schedule_state_write()
        return dev

    def limit(self, device_id, method):
        retry = self.limits.check(device_id, method)
        if retry:
            raise ApiError("rate_limited", "Too many requests. Slow down.", retry)

    def still_paired(self, device_id):
        return self.devices.still_valid(device_id)

    def _schedule_state_write(self):
        with self._lock:
            if self._seen_timer is not None or self._closed:
                return
            t = self._seen_timer = threading.Timer(1.0, self._seen_flush)
            t.daemon = True
            t.start()

    def _seen_flush(self):
        with self._lock:
            self._seen_timer = None
        self.write_state_file()

    # ------------------------------------------------------------------ devices

    def list_devices(self):
        return {"devices": self.devices.public_list()}

    def remove_device(self, device_id):
        with self._lock:
            if not self.devices.remove(device_id):
                raise ApiError("not_found", "Device not found.")
            self.limits.forget(device_id)
        self._changed()          # wakes that device's long-polls; they find it unpaired and answer 401
        return {"ok": True, "removed": 1}

    # ------------------------------------------------------------------ state

    def _note(self):
        if self.devices.has_http_device():
            return "An iPhone is paired over plain HTTP: anyone on this Wi-Fi can read its token. Tailscale gives real HTTPS."
        if self._plain is not None:
            return "Plain HTTP is on: anyone on this Wi-Fi can read what an iPhone sends. Tailscale gives real HTTPS."
        return None

    def state(self):
        """ConnectState (api.schema.json). Creates the identity if it does not exist yet."""
        with self._lock:
            self.ensure_identity()
            return self._state_locked()

    def _state_locked(self):
        listening = self._tls is not None
        code = self._code_view() if listening else None
        qr = None
        if listening and code:
            qr = self._qr_text()
        return {"enabled": self.enabled, "listening": listening, "port": self.port,
                "plainHttp": self.plain_http, "plainHttpPort": self.plain_port,
                "identity": self.identity.body(), "addresses": list(self._addresses) if listening else [],
                "code": code, "qrText": qr, "devices": self.devices.public_list(), "plainHttpNote": self._note()}

    def _qr_text(self):
        c, i = self._code, self.identity
        addrs = [a["address"] for a in self._addresses][:6]
        while True:
            payload = {"v": 1, "t": "onic-pair", "a": addrs, "p": self.port, "c": c["code"], "i": i.instance_id,
                       "f": i.fingerprint, "n": i.name, "x": iso(c["expires"])}
            text = json.dumps(payload, separators=(",", ":"))
            if len(text.encode("utf-8")) <= QR_MAX or len(addrs) <= 1:
                return text
            addrs = addrs[:-1]

    def summary(self):
        """Status.connect (loopback only). Does not create an identity."""
        with self._lock:
            return {"enabled": self.enabled, "listening": self.listening, "devices": self.devices.count()}

    def write_state_file(self):
        if not self.pairing_dir or not os.path.isdir(self.companion_dir) or self._closed or not self.game_running:
            return
        with self._lock:
            if not self.identity.exists:
                return
            st = self._state_locked()
        st.update({"schema": 1, "updatedAt": iso(self.clock()), "pid": os.getpid(), "lastRequest": self._last_request})
        try:
            for d in (self.pairing_dir, self.requests_dir):      # folders we create are owner only
                if not os.path.isdir(d):
                    os.mkdir(d, 0o700)
            write_atomic(self.state_path, json.dumps(st, indent=1), 0o600)    # holds the live code: owner only (the mod runs as the same user)
        except OSError:
            log.exception("cannot write the pairing state file")

    def retarget(self, companion_dir):
        """The active ONI folder changed (plan 4.3): the pairing state and the mod's request files live in the new
        folder; the old folder's state file goes (its mod must not show a code that no longer follows the game)."""
        with self._lock:
            self.remove_state_file()
            self.companion_dir = companion_dir
            self._last_request = None
            self._handled_seq = 0
            if self.state_path:
                old = read_json(self.state_path, {}) or {}
                lr = old.get("lastRequest") if isinstance(old, dict) else None
                if isinstance(lr, dict) and isinstance(lr.get("seq"), int):
                    self._handled_seq = lr["seq"]
                    self._last_request = lr
        self.scan_requests()
        self.write_state_file()

    def remove_state_file(self):
        if self.state_path:
            try:
                os.unlink(self.state_path)
            except OSError:
                pass

    # ------------------------------------------------------------------ the mod's request files

    def start(self):
        """Called once when the service starts."""
        if self.state_path:
            old = read_json(self.state_path, {}) or {}
            lr = old.get("lastRequest") if isinstance(old, dict) else None
            if isinstance(lr, dict) and isinstance(lr.get("seq"), int):
                self._handled_seq = lr["seq"]
                self._last_request = lr
        if self.autostart:
            try:
                self.ensure_identity()
            except ApiError as e:
                log.warning("identity: %s", e.message)
        with self._lock:
            try:
                self._reconcile_locked()
            except ApiError as e:
                log.warning("connect: %s", e.message)
        self.scan_requests()
        self.write_state_file()

    def scan_requests(self):
        d = self.requests_dir
        if not d or not os.path.isdir(d):
            return
        files = []
        for n in os.listdir(d):
            m = REQ_RE.match(n)
            if m:
                files.append((int(m.group(1)), os.path.join(d, n)))
        for _, p in sorted(files):
            self.handle_request_file(p)

    def handle_file(self, path, what):
        """File watcher hook. True when the path was ours (so nothing else looks at it)."""
        if not self.pairing_dir:
            return False
        d = self.requests_dir
        if os.path.dirname(path) == d:
            if what != "removed" and REQ_RE.match(os.path.basename(path)):
                self.handle_request_file(path)
            return True
        if path == self.pairing_dir or path.startswith(self.pairing_dir + os.sep):
            return True
        if (path == self.companion_dir or os.path.dirname(path) == self.companion_dir) and not os.path.exists(self.state_path):
            self.write_state_file()      # the companion folder just appeared (or the state file was removed)
        return False

    def handle_request_file(self, path):
        m = REQ_RE.match(os.path.basename(path))
        try:
            req = read_json(path, None)
            if not m or not isinstance(req, dict):
                return
            seq = req.get("seq")
            if not (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1 and seq == int(m.group(1))
                    and req.get("schema") == 1):
                return
            created = parse_utc(req.get("createdAt"))
            result = None
            with self._lock:
                if created is None or self.clock() - created > REQUEST_MAX_AGE or seq <= self._handled_seq:
                    self._last_request = {"seq": seq, "state": "failed", "message": "Request too old"}
                    result = False
                elif seq > self._handled_seq + SEQ_WINDOW:
                    # A huge seq must not lock out the real ones that follow.
                    self._last_request = {"seq": seq, "state": "failed", "message": "Request out of range"}
                    result = False
                else:
                    self._handled_seq = seq
                    try:
                        self._do_request(req)
                        self._last_request = {"seq": seq, "state": "done"}
                    except ApiError as e:
                        self._last_request = {"seq": seq, "state": "failed", "message": e.message}
                    except Exception:
                        log.exception("pairing request failed")
                        self._last_request = {"seq": seq, "state": "failed", "message": "Something went wrong."}
            self._changed()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _do_request(self, req):
        t = req.get("type")
        if t == "set_enabled" and isinstance(req.get("enabled"), bool):
            self.set_enabled(req["enabled"])
        elif t == "set_plain_http" and isinstance(req.get("enabled"), bool):
            self.set_plain_http(req["enabled"])
        elif t == "new_code":
            self.new_code()
        elif t == "remove_device" and isinstance(req.get("deviceId"), str):
            self.remove_device(req["deviceId"])
        elif t == "reset_identity":
            if req.get("confirm") is not True:
                raise ApiError("bad_request", "Not confirmed")
            self.reset_identity()
        else:
            raise ApiError("bad_request", "Unknown request")

    # ------------------------------------------------------------------ end

    def close(self):
        with self._lock:
            self._closed = True
            self._close_listeners_locked()
            if self._seen_timer:
                self._seen_timer.cancel()
        self.remove_state_file()
