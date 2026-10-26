"""ThreadingHTTPServer front for routes.py. JSON only; token on every request."""
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ..art import Png
from ..fonts import FontFile
from . import routes
from .errors import ApiError

log = logging.getLogger("oni_companion.http")
MAX_BODY = 64 * 1024
HANDSHAKE_TIMEOUT = 10
IDLE_TIMEOUT = 60
OPEN_NETWORK = {("GET", routes.BASE + "/identity"), ("POST", routes.BASE + "/connect/claim")}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


class Handler(BaseHTTPRequestHandler):
    server_version = "OniCompanion"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):      # request lines can hold ?token=
        pass

    def setup(self):
        net = getattr(self.server, "network", None)
        if net is not None:
            # Network listener: a slow or silent peer must not hold a thread (handshake 10 s, idle 60 s).
            if net.kind == "tls":
                self.request.settimeout(HANDSHAKE_TIMEOUT)
                self.request.do_handshake()
            self.timeout = IDLE_TIMEOUT
        super().setup()

    def _send(self, status, obj, headers=None):
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_png(self, png):
        if self.headers.get("If-None-Match") == png.etag:
            self.send_response(304)
            self.send_header("ETag", png.etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", png.content_type)
        self.send_header("Content-Length", str(len(png.data)))
        self.send_header("ETag", png.etag)
        self.send_header("Cache-Control", "no-cache")     # a portrait changes under the same URL
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(png.data)

    def _token(self):
        hdr = self.headers
        cands = [hdr.get("X-Oni-Token")]
        if self.server.ctx.barry_mode:
            cands.append(hdr.get("X-Barry-Token"))
            cands.append(parse_qs(urlsplit(self.path).query).get("token", [None])[0])
        return cands

    def _handle(self, method):
        ctx = self.server.ctx
        net = getattr(self.server, "network", None)
        polling = None
        try:
            # Always read a declared body so the connection stays usable.
            body_raw = b""
            if method != "GET":
                try:
                    ln = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    ln = -1
                if ln < 0 or ln > MAX_BODY:
                    self.close_connection = True
                    raise ApiError("bad_request", "Bad body size.")
                body_raw = self.rfile.read(ln) if ln else b""
            path = urlsplit(self.path).path.rstrip("/")
            netctx = None
            if net is not None:
                # Network listener: a device token on every request, except identity and claim (v1.4).
                source = self.client_address[0]
                device = None
                if (method, path) not in OPEN_NETWORK:
                    device = ctx.connect.authenticate(self.headers.get("X-Oni-Device"), net.kind, source)
                    ctx.connect.limit(device["deviceId"], method)
                netctx = routes.NetCtx(net.kind, source, device)
            elif (method, path) != ("GET", routes.BASE + "/identity"):
                label = None
                for c in self._token():
                    label = ctx.tokens.check(c) or label
                if label is None:
                    raise ApiError("bad_token", "Missing or wrong token.")
            body = None
            if method == "POST":
                try:
                    body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
                except (ValueError, UnicodeDecodeError):
                    raise ApiError("bad_request", "Body is not valid JSON.")
            if netctx is not None and netctx.device is not None and method == "GET" and path == routes.BASE + "/events":
                if not ctx.connect.limits.poll_enter(netctx.device["deviceId"]):
                    raise ApiError("rate_limited", "Too many open requests.", 1)
                polling = netctx.device["deviceId"]
            out = routes.dispatch(method, self.path, body, ctx, ctx.views, network=netctx)
            if polling and not ctx.connect.still_paired(polling):
                self.close_connection = True
                raise ApiError("unauthorized", "Not paired.")       # removed while waiting
            if isinstance(out, (Png, FontFile)):
                self._send_png(out)
            else:
                self._send(200, out)
        except ApiError as e:
            hdrs = {"Retry-After": str(e.retry_after)} if e.retry_after else None
            self._send(e.http_status, e.body(), hdrs)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            log.exception("internal error")
            try:
                self._send(500, ApiError("internal", "Internal error.").body())
            except OSError:
                pass
        finally:
            if polling:
                ctx.connect.limits.poll_exit(polling)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    do_PATCH = do_PUT


def make_server(host, port, ctx):
    srv = _Server((host, port), Handler)
    srv.ctx = ctx
    return srv
