"""The network listener: the same HTTP handler as the loopback one, behind TLS (or plain HTTP when the user chose
it). Event driven: the accept loop sleeps in select() on the socket and a wake pipe, and closing it drops every open
connection at once."""
import logging
import os
import select
import socket
import ssl
import threading
from http.server import ThreadingHTTPServer

log = logging.getLogger("oni_companion.net")
MAX_CONNECTIONS = 64


class Network:
    """What the HTTP handler needs to know about the listener it belongs to."""

    def __init__(self, kind):
        self.kind = kind            # "tls" or "http"


class NetServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, host, port, ctx, kind, tls_context=None, dest_ok=None):
        self.network = Network(kind)
        self.tls_context = tls_context
        self.dest_ok = dest_ok
        self.ctx = ctx
        self._conns = set()
        self._conn_lock = threading.Lock()
        self._wake_r, self._wake_w = os.pipe()
        self._thread = None
        super().__init__((host, port), _handler())

    @property
    def port(self):
        return self.server_address[1]

    def get_request(self):
        conn, addr = self.socket.accept()
        try:
            if self.dest_ok is not None and not self.dest_ok(conn.getsockname()[0]):
                raise OSError("not a LAN or Tailscale address")
            with self._conn_lock:
                if len(self._conns) >= MAX_CONNECTIONS:
                    raise OSError("too many connections")
            if self.tls_context is not None:
                conn = self.tls_context.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
        except Exception:
            conn.close()
            raise OSError("refused")
        with self._conn_lock:
            self._conns.add(conn)
        return conn, addr

    def shutdown_request(self, request):
        with self._conn_lock:
            self._conns.discard(request)
        try:
            super().shutdown_request(request)
        except Exception:
            pass

    def handle_error(self, request, client_address):
        log.debug("connection from %s ended with an error", client_address[0], exc_info=True)

    def start(self):
        self._thread = threading.Thread(target=self._serve, name="oni-net-%s" % self.network.kind, daemon=True)
        self._thread.start()
        return self

    def _serve(self):
        while True:
            r, _, _ = select.select([self.socket, self._wake_r], [], [])
            if self._wake_r in r:
                return
            self._handle_request_noblock()

    def close(self):
        """Stop accepting and cut every open connection (long-polls included) at once."""
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
        self.server_close()
        with self._conn_lock:
            conns, self._conns = list(self._conns), set()
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except (OSError, ssl.SSLError):
                pass
        for fd in (self._wake_r, self._wake_w):
            try:
                os.close(fd)
            except OSError:
                pass


def _handler():
    from ..server.http import Handler          # late: http.py imports the connect package for its checks
    return Handler
