"""mDNS / DNS-SD announcement of `_onicompanion._tcp` (plan 3, contracts/api.md "Discovery").

Announces ONLY the four TXT keys id, name, api, core (and the port), and only between start() and stop().
When avahi-daemon runs, the avahi-publish-service command registers it (the daemon owns port 5353 then, so a
second responder would clash). Without avahi a small stdlib responder answers on 224.0.0.251:5353.
Discovery is a hint only: nothing here is trusted by a client.
"""
import logging
import os
import select
import shutil
import socket
import struct
import subprocess
import threading

log = logging.getLogger("oni_companion.mdns")

SERVICE = "_onicompanion._tcp"
GROUP, PORT = "224.0.0.251", 5353
AVAHI_SOCKETS = ("/run/avahi-daemon/socket", "/var/run/avahi-daemon/socket")
T_A, T_PTR, T_TXT, T_SRV, T_ANY = 1, 12, 16, 33, 255
IN = 1
CACHE_FLUSH = 0x8000


def txt_pairs(info):
    """The ONLY fields we announce. info: id, name, api, core."""
    return [("id", info["id"]), ("name", info["name"]), ("api", str(info["api"])), ("core", info["core"])]


def instance_label(info):
    return "ONI Companion on %s" % info["name"]


# ---------------------------------------------------------------- DNS wire format

def enc_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        b = label.encode("utf-8")
        if not 0 < len(b) < 64:
            raise ValueError("bad label")
        out += bytes([len(b)]) + b
    return out + b"\0"


def dec_name(data, off):
    labels, jumped, end = [], False, off
    for _ in range(64):
        if off >= len(data):
            raise ValueError("short")
        n = data[off]
        if n & 0xC0 == 0xC0:
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            if not jumped:
                end = off + 2
            jumped, off = True, ptr
            continue
        if n == 0:
            if not jumped:
                end = off + 1
            return ".".join(labels) + ".", end
        labels.append(data[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    raise ValueError("loop")


def rr(name, rtype, ttl, rdata, flush=True):
    return enc_name(name) + struct.pack("!HHIH", rtype, IN | (CACHE_FLUSH if flush else 0), ttl, len(rdata)) + rdata


def parse_questions(data):
    """[(name_lower, qtype, unicast_bit)] of a query packet; [] for responses or damaged packets."""
    try:
        _id, flags, qd, _an, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
        if flags & 0x8000:
            return []
        off, out = 12, []
        for _ in range(min(qd, 16)):
            name, off = dec_name(data, off)
            qtype, qclass = struct.unpack("!HH", data[off:off + 4])
            off += 4
            out.append((name.lower(), qtype, bool(qclass & 0x8000)))
        return out
    except (ValueError, struct.error, IndexError):
        return []


class Records:
    """The records for one announced service."""

    def __init__(self, info, port, ipv4_addrs):
        self.service = SERVICE + ".local."
        self.instance = "%s.%s" % (instance_label(info), self.service)
        self.host = "%s-%s.local." % (info["name"], info.get("tag", "").lower() or "x")
        self.info, self.port, self.addrs = info, port, list(ipv4_addrs)

    def ptr(self, ttl):
        return rr(self.service, T_PTR, ttl, enc_name(self.instance), flush=False)

    def ptr_meta(self, ttl):
        return rr("_services._dns-sd._udp.local.", T_PTR, ttl, enc_name(self.service), flush=False)

    def srv(self, ttl):
        return rr(self.instance, T_SRV, ttl, struct.pack("!HHH", 0, 0, self.port) + enc_name(self.host))

    def txt(self, ttl):
        body = b"".join(bytes([len(s)]) + s for s in ((k + "=" + v).encode("utf-8") for k, v in txt_pairs(self.info)))
        return rr(self.instance, T_TXT, ttl, body)

    def a(self, ttl):
        return [rr(self.host, T_A, ttl, socket.inet_aton(x)) for x in self.addrs]

    def packet(self, ttl_long=4500, ttl_short=120, qid=0, answers=("ptr", "meta", "srv", "txt", "a")):
        ans = []
        if "ptr" in answers:
            ans.append(self.ptr(ttl_long))
        if "meta" in answers:
            ans.append(self.ptr_meta(ttl_long))
        if "srv" in answers:
            ans.append(self.srv(ttl_short))
        if "txt" in answers:
            ans.append(self.txt(ttl_long))
        if "a" in answers:
            ans.extend(self.a(ttl_short))
        return struct.pack("!HHHHHH", qid, 0x8400, 0, len(ans), 0, 0) + b"".join(ans)

    def goodbye(self):
        return self.packet(ttl_long=0, ttl_short=0)

    def wanted(self, name, qtype):
        """Which answers a question needs, [] when it is not about us."""
        name = name.lower()
        if name == self.service.lower() and qtype in (T_PTR, T_ANY):
            return ("ptr", "srv", "txt", "a")
        if name == "_services._dns-sd._udp.local." and qtype in (T_PTR, T_ANY):
            return ("meta",)
        if name == self.instance.lower() and qtype in (T_SRV, T_TXT, T_ANY):
            return ("ptr", "srv", "txt", "a")
        if name == self.host.lower() and qtype in (T_A, T_ANY):
            return ("a",)
        return ()


# ---------------------------------------------------------------- the stdlib responder

class Responder:
    """Joins the mDNS group, answers questions about our one service, announces at start, says goodbye at stop."""

    def __init__(self, info, port, lan_addrs, group=GROUP, mport=PORT, loop=True):
        self.records = Records(info, port, lan_addrs)
        self.group, self.mport, self.loop = group, mport, loop
        self.sock = None
        self.sent = []                    # packets we sent (tests read this)
        self._wake_r = self._wake_w = None
        self._thread = None
        self._lock = threading.Lock()

    def _open(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.bind(("", self.mport))
        ifaces = self.records.addrs or ["0.0.0.0"]
        joined = 0
        for a in ifaces:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(self.group) + socket.inet_aton(a))
                joined += 1
            except OSError as e:
                log.info("mdns: cannot join the group on %s: %s", a, e)
        if not joined:
            s.close()
            raise OSError("mdns: no interface joined the multicast group")
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1 if self.loop else 0)
        if self.records.addrs:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.records.addrs[0]))
        return s

    def start(self):
        self.sock = self._open()
        self._wake_r, self._wake_w = os.pipe()
        self._thread = threading.Thread(target=self._run, name="oni-mdns", daemon=True)
        self._thread.start()
        return self

    def _send(self, pkt, dest=None):
        self.sent.append(pkt)
        try:
            self.sock.sendto(pkt, dest or (self.group, self.mport))
        except OSError as e:
            log.info("mdns: send failed: %s", e)

    def _run(self):
        import time
        # unsolicited announcements: now and again after a second (event wait, not a poll)
        self._send(self.records.packet())
        deadline = time.monotonic() + 1.0
        announced = 1
        while True:
            timeout = max(0.0, deadline - time.monotonic()) if announced < 2 else None
            r, _, _ = select.select([self.sock, self._wake_r], [], [], timeout)
            if self._wake_r in r:
                break
            if not r:
                self._send(self.records.packet())
                announced = 2
                continue
            try:
                data, src = self.sock.recvfrom(9000)
            except OSError:
                continue
            need = []
            for name, qtype, _qu in parse_questions(data):
                for w in self.records.wanted(name, qtype):
                    if w not in need:
                        need.append(w)
            if need:
                legacy = src[1] != self.mport
                self._send(self.records.packet(qid=struct.unpack("!H", data[:2])[0] if legacy else 0, answers=tuple(need)),
                           src if legacy else None)

    def stop(self):
        with self._lock:
            if self.sock is None:
                return
            os.write(self._wake_w, b"x")
            if self._thread and self._thread is not threading.current_thread():
                self._thread.join(2)
            self._send(self.records.goodbye())
            self.sock.close()
            self.sock = None
            for fd in (self._wake_r, self._wake_w):
                os.close(fd)


# ---------------------------------------------------------------- avahi

def avahi_running(which=shutil.which, exists=os.path.exists):
    return bool(which("avahi-publish-service")) and any(exists(p) for p in AVAHI_SOCKETS)


class AvahiPublisher:
    def __init__(self, info, port, exe=None, popen=subprocess.Popen):
        self.info, self.port = info, port
        self.exe = exe or shutil.which("avahi-publish-service") or "avahi-publish-service"
        self.popen = popen
        self.proc = None
        self.on_exit = None             # called with the return code if it ends while we still want it

    def argv(self):
        return [self.exe, instance_label(self.info), SERVICE, str(self.port)] + ["%s=%s" % kv for kv in txt_pairs(self.info)]

    def start(self):
        self.proc = self.popen(self.argv(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc = self.proc

        def watch():
            rc = proc.wait()
            if self.proc is proc and self.on_exit:      # not stopped by us
                self.on_exit(rc)
        threading.Thread(target=watch, name="oni-avahi-watch", daemon=True).start()
        return self

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


class Announcer:
    """What the manager uses: start(info, port, lan_addrs) / stop(). `mode` is "avahi", "responder" or None."""

    def __init__(self, avahi_ok=avahi_running, avahi_factory=AvahiPublisher, responder_factory=Responder):
        self.avahi_ok, self.avahi_factory, self.responder_factory = avahi_ok, avahi_factory, responder_factory
        self.mode = None
        self._impl = None
        self._lock = threading.Lock()
        self._args = None

    def start(self, info, port, lan_addrs):
        with self._lock:
            self._stop_locked()
            self._args = (info, port, lan_addrs)
            if self.avahi_ok():
                try:
                    pub = self.avahi_factory(info, port)
                    pub.on_exit = lambda rc, p=pub: self._avahi_died(p, rc)
                    pub.start()
                    self._impl, self.mode = pub, "avahi"
                    return self.mode
                except OSError as e:
                    log.warning("mdns: avahi-publish-service failed to start: %s", e)
            self._start_responder_locked()
            return self.mode

    def _start_responder_locked(self):
        info, port, lan = self._args
        try:
            self._impl = self.responder_factory(info, port, lan).start()
            self.mode = "responder"
        except OSError as e:
            log.warning("mdns: no announcement possible: %s", e)
            self._impl, self.mode = None, None

    def _avahi_died(self, pub, rc):
        with self._lock:
            if self._impl is not pub:
                return
            log.warning("mdns: avahi-publish-service ended (%s); using the built-in responder", rc)
            self._impl = None
            self._start_responder_locked()

    def _stop_locked(self):
        impl, self._impl, self.mode = self._impl, None, None
        if impl is not None:
            impl.stop()

    def stop(self):
        with self._lock:
            self._stop_locked()
            self._args = None
