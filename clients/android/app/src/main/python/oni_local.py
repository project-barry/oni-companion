"""Local mode entry point (plan 4.2): the core runs inside the APK, with no sockets at all.

The Kotlin side mirrors the shared ONICompanion folder into a private folder and calls:
  start(user_dir, data_dir)          build the service; user_dir holds companion/
  call(method, path, body_text)      the same routes.dispatch the HTTP server uses; path is below /api/v1
  touch(path) / removed(path)        a mirrored file changed (replaces the inotify watcher)
  stale_in()                         seconds until the live file stops being fresh (0 = nothing to wait for)
  publish_stale()                    tell clients to look again (the deadline passed)
  stop()
Nothing here opens a port. Authorization is the process boundary: only this app calls it.
"""
import json
import logging
import os
import threading

from oni_companion.art import Png
from oni_companion.fonts import FontFile
from oni_companion.server import routes
from oni_companion.server.errors import ApiError
from oni_companion.server.service import Service, ServiceConfig

log = logging.getLogger("oni_local")
MAX_BODY = 64 * 1024

_svc = None


class LocalService(Service):
    """The core's service wiring without the HTTP server and without the file watcher."""

    def start(self):
        threading.Thread(target=self._fonts_once, name="oni-fonts", daemon=True).start()
        return self


def start(user_dir, data_dir):
    global _svc
    stop()
    os.environ["ONI_DATA_DIR"] = data_dir         # settings, caches and font cache live in the app's private folder
    os.environ["ONI_USER_DIR"] = user_dir
    cfg = ServiceConfig(user_dir=user_dir, save_dirs=[], game_dir=None, data_dir=data_dir, barry_mode=False)
    _svc = LocalService(cfg).start()
    return True


def stop():
    global _svc
    if _svc is not None:
        _svc.stop()
        _svc = None


def _json(status, obj):
    return (status, "application/json; charset=utf-8", "",
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def call(method, path, body_text=None):
    """(status, content type, etag, bytes). Errors come back as the API's error body, never as exceptions."""
    svc = _svc
    if svc is None:
        return _json(503, ApiError("unavailable", "The local service is not running.").body())
    try:
        body = None
        if method == "POST":
            raw = (body_text or "").encode("utf-8")
            if len(raw) > MAX_BODY:
                raise ApiError("bad_request", "Bad body size.")
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                raise ApiError("bad_request", "Body is not valid JSON.")
        out = routes.dispatch(method, routes.BASE + path, body, svc, svc.views)
        if isinstance(out, (Png, FontFile)):
            return (200, out.content_type, out.etag, bytes(out.data))
        return _json(200, out)
    except ApiError as e:
        return _json(e.http_status, e.body())
    except Exception:
        log.exception("internal error")
        return _json(500, ApiError("internal", "Internal error.").body())


def touch(path):
    if _svc is not None:
        _svc._on_file(path, "changed")


def removed(path):
    if _svc is not None:
        _svc._on_file(path, "removed")


def stale_in():
    """Seconds from now until live.json counts as stale, or 0 when it is already stale or missing."""
    svc = _svc
    if svc is None:
        return 0.0
    from oni_companion.colony import FRESH_SECONDS, FRESH_SECONDS_PAUSED, parse_iso
    live = svc.colony.read_live()
    if not live or live.get("state") != "running":
        return 0.0
    written = parse_iso(live.get("writtenAt", ""))
    if written is None:
        return 0.0
    left = written + (FRESH_SECONDS_PAUSED if live.get("paused") else FRESH_SECONDS) - svc.colony.clock()
    return max(0.0, left)


def publish_stale():
    if _svc is not None:
        _svc.bus.publish("colony", "status", "controls")
