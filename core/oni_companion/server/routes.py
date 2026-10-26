"""Route table for /api/v1. Pure functions of (ctx, views): no sockets here."""
from urllib.parse import parse_qs, unquote, urlsplit

from . import connect_routes
from .errors import ApiError

BASE = "/api/v1"
MAX_LIMIT = 100
DEFAULT_TIMEOUT = 25
MAX_TIMEOUT = 60


def _int(q, name, default, lo, hi):
    raw = q.get(name, [None])[0]
    if raw in (None, ""):
        return default
    try:
        v = int(raw)
    except ValueError:
        raise ApiError("bad_request", "%s must be a whole number." % name)
    return max(lo, min(hi, v))


def _float(q, name, default, lo, hi):
    raw = q.get(name, [None])[0]
    if raw in (None, ""):
        return default
    try:
        v = float(raw)
    except ValueError:
        raise ApiError("bad_request", "%s must be a number." % name)
    if v != v:
        raise ApiError("bad_request", "%s must be a number." % name)
    return max(lo, min(hi, v))


def split(target):
    u = urlsplit(target)
    if not (u.path == BASE or u.path.startswith(BASE + "/")):
        raise ApiError("not_found", "Not found.")
    parts = [unquote(p) for p in u.path[len(BASE):].split("/") if p != ""]
    return parts, parse_qs(u.query, keep_blank_values=True)


class NetCtx:
    """Set when a request came in on the network listener (v1.4): which listener, from where, which device."""

    def __init__(self, kind, source, device):
        self.kind, self.source, self.device = kind, source, device


def dispatch(method, target, body, ctx, views, network=None):
    """Returns a JSON-ready dict (or an art.Png for /art/...). Raises ApiError. Auth is already done."""
    parts, q = split(target)
    n = len(parts)
    if n and parts[0] == "pair":
        raise ApiError("not_in_v1", "Not in v1.")
    if n and parts[0] == "connect":
        return connect_routes.handle(method, parts, body, ctx, network)
    if method == "GET" and n == 1 and parts[0] == "identity":
        return ctx.connect.identity_body()
    if method == "POST":
        if network is not None and ((n == 2 and parts[0] == "actions" and parts[1] == "mod_install")
                                    or (n == 2 and parts[0] == "mod" and parts[1] == "install")):
            raise ApiError("local_only", "Only on this device.")     # a paired device cannot install the mod (plan 2, 4.1)
        if n == 2 and parts[0] == "actions":
            return ctx.actions.post(parts[1], body)
        if n == 2 and parts[0] == "tools":
            if not isinstance(body, dict) or not isinstance(body.get("values", {}), dict):
                raise ApiError("bad_request", "Body must be {\"values\":{...}}.")
            return views.tool_run(parts[1], body.get("values", {}))
        if n == 1 and parts[0] == "sync":
            return ctx.sync.start(body)
        if n == 1 and parts[0] == "settings":
            if not isinstance(body, dict) or not isinstance(body.get("values"), dict):
                raise ApiError("bad_request", "Body must be {\"values\":{...}}.")
            return views.settings_save(body["values"], local=network is None)
        if n == 1 and parts[0] == "controls":
            return ctx.controls.post(body)
        if n == 2 and parts[0] == "mod" and parts[1] == "install":
            return views.mod_install(body)
        raise ApiError("not_found", "Not found.")
    if method != "GET":
        raise ApiError("not_found", "Not found.")
    if n == 1:
        p = parts[0]
        if p == "status":
            out = views.status()
            if network is None:
                out = dict(out, connect=ctx.connect.summary())      # v1.4: loopback only
            return out
        if p == "home":
            return views.home()
        if p == "kinds":
            return views.kinds()
        if p == "tools":
            return views.tools()
        if p == "theme":
            return views.theme()
        if p == "tabs":
            return views.tabs()
        if p == "pad":
            return views.pad()
        if p == "buildings":
            return views.buildings()
        if p == "colony":
            w = q.get("world", [None])[0]
            return views.colony(w if w not in (None, "") else None)
        if p == "resources":
            w = q.get("world", [None])[0]
            return views.resources(w if w not in (None, "") else None, q.get("q", [""])[0])
        if p == "settings":
            return views.settings(local=network is None)
        if p == "fonts":
            fonts = getattr(ctx, "fonts", None)
            return fonts.font_list() if fonts else {"fonts": []}
        if p == "controls":
            return ctx.controls.get()
        if p == "search":
            text = q.get("q", [""])[0].strip()
            if not text:
                raise ApiError("bad_request", "q must not be empty.")
            kind = q.get("kind", [None])[0] or None
            return views.search(text, kind, _int(q, "limit", 20, 1, MAX_LIMIT))
        if p == "sync":
            return ctx.sync.status()
        if p == "events":
            since = _int(q, "since", 0, 0, 1 << 62)
            timeout = _float(q, "timeout", DEFAULT_TIMEOUT, 0, MAX_TIMEOUT)
            return ctx.bus.wait(since, timeout)
    if n == 2 and parts[0] == "actions":
        return ctx.actions.status(parts[1])
    if n == 2 and parts[0] == "list":
        sort = q.get("sort", ["name"])[0] or "name"
        if sort not in ("name", "dlc"):
            raise ApiError("bad_request", "sort must be name or dlc.")
        return views.list_kind(parts[1], q.get("dlc", [None])[0] or None, sort)
    if n == 3 and parts[0] == "art":
        art = getattr(ctx, "art", None)
        png = art.read(parts[1], parts[2]) if art else None
        if png is None:
            raise ApiError("not_found", "No art.")
        return png
    if n == 2 and parts[0] == "fonts":
        fonts = getattr(ctx, "fonts", None)
        out = fonts.file(parts[1]) if fonts else None
        if out is None:
            raise ApiError("not_found", "No font.")
        return out
    if n == 3 and parts[0] == "entry":
        return views.entry(parts[1], parts[2])
    if n == 3 and parts[0] == "raw":
        return views.raw(parts[1], parts[2])
    if n == 2 and parts[0] == "tools":
        return views.tool_form(parts[1])
    raise ApiError("not_found", "Not found.")
