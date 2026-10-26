"""Paired devices. Only the SHA-256 of a device token is stored. Tokens are per service (the store sits in this
service's identity folder, and Reset identity empties it)."""
import hashlib
import hmac
import re
import secrets
import threading
import time

from .files import read_json, write_json

MAX_DEVICES = 32
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
PLATFORMS = ("android", "ios", "web", "other")
SEEN_STEP = 30.0        # lastSeen moves at most every 30 s (and so does the file the mod reads)


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def clean_label(text):
    text = "".join(ch for ch in str(text) if ch.isprintable()).strip()
    return text[:40]


def hash_token(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class DeviceStore:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()
        self._devs = []      # dicts: deviceId, label, platform, pairedAt, lastSeen(float|None), transport, tokenHash
        self._dirty = False
        data = read_json(path, {}) if path else {}
        for d in (data.get("devices") if isinstance(data, dict) else None) or []:
            try:
                if re.fullmatch(r"d-[0-9a-f]{12}", d["deviceId"]) and re.fullmatch(r"[0-9a-f]{64}", d["tokenHash"]):
                    self._devs.append({"deviceId": d["deviceId"], "label": clean_label(d.get("label") or "Device") or "Device",
                                       "platform": d.get("platform") if d.get("platform") in PLATFORMS else "other",
                                       "pairedAt": d.get("pairedAt") or iso(clock()),
                                       "lastSeen": d.get("lastSeen"), "transport": "http" if d.get("transport") == "http" else "tls",
                                       "tokenHash": d["tokenHash"]})
            except (KeyError, TypeError):
                continue

    def _save_locked(self):
        if self.path:
            write_json(self.path, {"schema": 1, "devices": self._devs})
        self._dirty = False

    def count(self):
        with self._lock:
            return len(self._devs)

    def add(self, label, platform, transport):
        """Returns (token, public device dict). The token is not kept anywhere."""
        with self._lock:
            if len(self._devs) >= MAX_DEVICES:
                return None, None
            token = secrets.token_urlsafe(32)          # 32 random bytes -> 43 characters
            dev = {"deviceId": "d-" + secrets.token_hex(6), "label": clean_label(label) or "Device",
                   "platform": platform if platform in PLATFORMS else "other",
                   "pairedAt": iso(self.clock()), "lastSeen": None,
                   "transport": "http" if transport == "http" else "tls", "tokenHash": hash_token(token)}
            self._devs.append(dev)
            self._save_locked()
            return token, self._public(dev)

    def authenticate(self, token, transport):
        """The device dict for a valid token, else None. Compares against EVERY stored hash in constant time.
        A TLS-paired token is refused on the plain-HTTP listener; plain-HTTP-paired devices work on both."""
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            return None
        h = hash_token(token).encode("ascii")
        found = None
        with self._lock:
            for d in self._devs:
                if hmac.compare_digest(h, d["tokenHash"].encode("ascii")):
                    found = d
            if found is None:
                return None
            if transport == "http" and found["transport"] != "http":
                return None
            now = self.clock()
            moved = found["lastSeen"] is None or now - found["lastSeen"] >= SEEN_STEP
            if moved:
                found["lastSeen"] = now
                self._save_locked()
            pub = self._public(found)
            pub["_moved"] = moved
            return pub

    def still_valid(self, device_id):
        with self._lock:
            return any(d["deviceId"] == device_id for d in self._devs)

    def remove(self, device_id):
        with self._lock:
            n = len(self._devs)
            self._devs = [d for d in self._devs if d["deviceId"] != device_id]
            if len(self._devs) != n:
                self._save_locked()
                return True
            return False

    def clear(self):
        with self._lock:
            n = len(self._devs)
            self._devs = []
            self._save_locked()
            return n

    def _public(self, d):
        return {"deviceId": d["deviceId"], "label": d["label"], "platform": d["platform"], "pairedAt": d["pairedAt"],
                "lastSeen": iso(d["lastSeen"]) if isinstance(d["lastSeen"], (int, float)) else None,
                "transport": d["transport"]}

    def public_list(self):
        with self._lock:
            return [self._public(d) for d in self._devs]

    def has_http_device(self):
        with self._lock:
            return any(d["transport"] == "http" for d in self._devs)
