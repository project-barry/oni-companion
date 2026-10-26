#!/usr/bin/env python3
"""Dev stand-in for the v1.4 network listener, for testing clients before the real core has it.

Stdlib only (plus the system `openssl` command to make the self-signed certificate, as the real
service does). Serves HTTPS with its own pinned certificate and the v1.4 rules from contracts/api.md:
GET /api/v1/identity and POST /api/v1/connect/claim are open; everything else needs
`X-Oni-Device: <token>` (401 `unauthorized` otherwise) and is forwarded to an upstream loopback
server (devtools/mock-server.py or the real core) with its X-Oni-Token. It prints one line per request
saying whether a device token header was present, so a test can prove an impostor never got one.

  python3 devtools/tls-front.py --listen 127.0.0.1:47615 --upstream 127.0.0.1:47001 \
      --upstream-token T --state-dir /tmp/tls-front-a --name spiffy-raccoon --code ABCD-EFGH
"""
import argparse
import base64
import hashlib
import http.client
import json
import os
import secrets
import ssl
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_cert(state_dir):
    os.makedirs(state_dir, exist_ok=True)
    key, crt = os.path.join(state_dir, "key.pem"), os.path.join(state_dir, "cert.pem")
    if not os.path.exists(crt):
        cn = str(uuid.uuid4())
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-keyout", key, "-out", crt, "-days", "3650", "-subj", "/CN=" + cn],
                       check=True, capture_output=True)
        os.chmod(key, 0o600)
    der = ssl.PEM_cert_to_DER_cert(open(crt).read())
    return key, crt, hashlib.sha256(der).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:47615")
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--upstream-token", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--name", default="spiffy-raccoon")
    ap.add_argument("--instance-id", default=str(uuid.uuid4()))
    ap.add_argument("--code", default="ABCD-EFGH")
    a = ap.parse_args()
    host, port = a.listen.rsplit(":", 1)
    key, crt, fp = make_cert(a.state_dir)
    up_host, up_port = a.upstream.rsplit(":", 1)
    tokens = {}                      # sha256(token) -> deviceId
    state = {"code": a.code.replace("-", "").upper(), "fails": 0}
    lock = threading.Lock()
    identity = {"instanceId": a.instance_id, "name": a.name, "fingerprint": fp, "fingerprintTag": fp[:4].upper(),
                "apiVersion": 1, "coreVersion": "1.4.0-devfront"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, status, obj, extra=None):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def err(self, status, code, msg):
            self.reply(status, {"error": {"code": code, "message": msg}})

        def handle_any(self):
            tok = self.headers.get("X-Oni-Device")
            print("%s %s device-token=%s" % (self.command, self.path, "PRESENT" if tok else "absent"), flush=True)
            path = self.path.split("?")[0]
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            if path == "/api/v1/identity" and self.command == "GET":
                return self.reply(200, identity)
            if path == "/api/v1/connect/claim" and self.command == "POST":
                try:
                    given = json.loads(body)["code"].replace("-", "").upper()
                except Exception:
                    return self.err(400, "bad_request", "Bad body.")
                with lock:
                    if state["code"] and secrets.compare_digest(given, state["code"]):
                        state["code"] = None
                        t = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
                        did = "d-" + secrets.token_hex(6)
                        tokens[hashlib.sha256(t.encode()).hexdigest()] = did
                        return self.reply(200, {"deviceToken": t, "deviceId": did, "identity": identity})
                return self.err(403, "bad_code", "Code is wrong, expired or used.")
            h = hashlib.sha256((tok or "").encode()).hexdigest()
            if h not in tokens:
                return self.err(401, "unauthorized", "Not paired.")
            if path.startswith("/api/v1/connect"):
                return self.err(403, "local_only", "Only on the gaming device.")
            c = http.client.HTTPConnection(up_host, int(up_port), timeout=90)
            c.request(self.command, self.path, body or None,
                      {"X-Oni-Token": a.upstream_token, "Content-Type": "application/json"})
            r = c.getresponse()
            data = r.read()
            self.send_response(r.status)
            self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = handle_any

    srv = ThreadingHTTPServer((host, int(port)), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("tls-front on %s:%s fingerprint %s name %s code %s" % (host, port, fp, a.name, a.code), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
