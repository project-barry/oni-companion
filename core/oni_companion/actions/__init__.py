"""Actions (v1.1): the app asks the game to do one thing, through a file inbox.

POST /actions/focus  -> write companion/commands/cmd-<seq>.json atomically, reply {seq}.
The mod runs it, writes companion/acks/ack-<seq>.json. The service watcher calls
`handle_file` for every file event; an ack changes the state and sends an `action` event.
No ack within `expire` seconds: state `expired` (one timer per command, no polling).
The core writes only companion/commands/. Event driven; stdlib only.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from ..server.errors import ApiError

log = logging.getLogger("oni_companion.actions")

EXPIRE_SECONDS = 10.0
KEEP = 256                       # finished commands kept for GET /actions/<seq>
FRESH_SECONDS = 15               # same limits as colony.py
FRESH_SECONDS_PAUSED = 180       # mod 0.3.1+ rewrites live.json at least every 60 s while paused
ACTION_IDS = ("focus", "alert_activate", "alert_dismiss", "overlay_set", "tool_select", "build_select", "mod_install")   # allow list of POST /actions/<id> (set_speed is POST /controls)
DISMISS_STUCK_SECONDS = 20.0     # a dismissed alert still in live.json this long after the ack stops showing "dismissing"
_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_CMD_RE = re.compile(r"^cmd-(\d+)\.json$")
_ACK_RE = re.compile(r"^ack-(\d+)\.json$")
MAX_MESSAGE = 200


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s):
    try:
        return datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, AttributeError):
        return None


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class _NoTimer:
    def cancel(self):
        pass


class ActionService:
    def __init__(self, companion_dir, publish, expire=EXPIRE_SECONDS, clock=time.time):
        self.companion_dir = companion_dir
        self.cmd_dir = os.path.join(companion_dir, "commands") if companion_dir else None
        self.ack_dir = os.path.join(companion_dir, "acks") if companion_dir else None
        self.live_path = os.path.join(companion_dir, "live", "live.json") if companion_dir else None
        self.publish = publish          # publish("action")
        self.expire = expire
        self.clock = clock
        self._lock = threading.Lock()
        self._seq = None
        self._items = {}                # seq -> {"state", "message", "timer"}
        self._closed = False
        self._dismissing = {}           # alertId -> {seq, since (clock time of the ack, None while pending)}
        self.validate = None            # hook(ctype, fields): v1.3 checks against the game's lists; raises ApiError
        self.install_hook = None        # hook(body) -> ModInstallReply dict: the ask-first mod install (mod_install)
        self.explainer = None           # cause.Explainer: names the real cause in the 503 message
        self.other_ack = None           # hook(seq, path) -> True for acks of commands this class did not send (art requests)

    def retarget(self, companion_dir):
        """The active ONI folder changed (plan 4.3): new commands, acks and live.json come from the new one."""
        with self._lock:
            self.companion_dir = companion_dir
            self.cmd_dir = os.path.join(companion_dir, "commands") if companion_dir else None
            self.ack_dir = os.path.join(companion_dir, "acks") if companion_dir else None
            self.live_path = os.path.join(companion_dir, "live", "live.json") if companion_dir else None
            self._seq = None
            self._dismissing = {}

    def _explain(self, live, default):
        if self.explainer is None:
            return default
        from .. import cause
        kind = "none"
        if isinstance(live, dict) and live.get("schema") in (1, 2):
            kind = cause.live_kind(live.get("state"), _parse_iso(live.get("writtenAt", "")), live.get("paused") is True,
                                   self.clock())
        ex = self.explainer.explain(kind, live.get("dlcIds") if isinstance(live, dict) else None)
        return ex["message"] if ex else default

    def _read_live(self):
        try:
            with open(self.live_path, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, TypeError):
            return None

    @staticmethod
    def live_alerts(live):
        """{alert id: alert dict} of every world in a live.json dict."""
        out = {}
        if isinstance(live, dict):
            for w in live.get("worlds") or []:
                for a in (w.get("alerts") or []) if isinstance(w, dict) else []:
                    if isinstance(a, dict) and isinstance(a.get("id"), str):
                        out.setdefault(a["id"], a)
        return out

    # ---- availability ----
    def _unavailable(self):
        """None when a command can go out, else the 503 message."""
        live = self._read_live() if self.companion_dir and os.path.isdir(self.companion_dir) else None
        if not isinstance(live, dict) or live.get("schema") not in (1, 2):
            return self._explain(live, "The game is not running. Start a colony first.")
        if live.get("state") != "running":
            from .. import cause
            fresh_menu = cause.live_kind(live.get("state"), _parse_iso(live.get("writtenAt", "")), False,
                                         self.clock()) == "menu"
            return self._explain(live, "The game is in the menu. Load a colony first." if fresh_menu
                                 else "The game is not running. Start a colony first.")
        written = _parse_iso(live.get("writtenAt", ""))
        limit = FRESH_SECONDS_PAUSED if live.get("paused") else FRESH_SECONDS
        if written is None or self.clock() - written > limit:
            return self._explain(live, "The game is not sending data. Is it running?")
        return None

    # ---- sending ----
    def _next_seq(self):
        # Above every cmd/ack file already on disk and above the wall clock in whole seconds, so a
        # restart can never reuse a number an old ack file still holds.
        if self._seq is None:
            top = 0
            for d, rx in ((self.cmd_dir, _CMD_RE), (self.ack_dir, _ACK_RE)):
                try:
                    for n in os.listdir(d):
                        m = rx.match(n)
                        if m:
                            top = max(top, int(m.group(1)))
                except OSError:
                    pass
            self._seq = max(top, int(self.clock()))
        self._seq += 1
        return self._seq

    @staticmethod
    def parse_focus(body):
        if not isinstance(body, dict) or set(body) - {"target", "select"}:
            raise ApiError("bad_request", "Body must be {\"target\":{\"kind\":\"dupe\",\"id\":...},\"select\":true}.")
        t = body.get("target")
        if (not isinstance(t, dict) or set(t) != {"kind", "id"} or t["kind"] != "dupe"
                or not isinstance(t["id"], str) or not t["id"] or len(t["id"]) > 128):
            raise ApiError("bad_request", "target must be {\"kind\":\"dupe\",\"id\":\"<duplicant id>\"}.")
        sel = body.get("select", True)
        if not isinstance(sel, bool):
            raise ApiError("bad_request", "select must be true or false.")
        return {"kind": "dupe", "id": t["id"]}, sel

    def parse_alert(self, action_id, body):
        """-> command fields for alert_activate / alert_dismiss. 400 for a bad body, 404 when the alert is gone."""
        allowed = {"alertId", "link"} if action_id == "alert_activate" else {"alertId"}
        if not isinstance(body, dict) or set(body) - allowed:
            raise ApiError("bad_request", "Body must be {\"alertId\":\"...\"%s}." % (
                ",\"link\":0" if action_id == "alert_activate" else ""))
        aid = body.get("alertId")
        if not isinstance(aid, str) or not aid or len(aid) > 100:
            raise ApiError("bad_request", "alertId must be the id of an alert.")
        link = body.get("link")
        if "link" in body and (isinstance(link, bool) or not isinstance(link, int) or link < 0):
            raise ApiError("bad_request", "link must be a whole number from 0.")
        why = self._unavailable()
        if why:
            raise ApiError("unavailable", why)
        alert = self.live_alerts(self._read_live()).get(aid)
        if alert is None:
            raise ApiError("not_found", "Alert is gone.")
        if action_id == "alert_dismiss" and alert.get("dismissable") is not True:
            raise ApiError("bad_request", "Can't be dismissed.")
        if link is not None and link not in [l.get("index") for l in alert.get("links") or [] if isinstance(l, dict)]:
            raise ApiError("bad_request", "That alert has no such link.")
        fields = {"alertId": aid}
        if link is not None:
            fields["link"] = link
        return fields

    @staticmethod
    def parse_pad(action_id, body):
        """-> command fields for overlay_set / tool_select / build_select (400 for a bad body)."""
        def ident(v, what):
            if not isinstance(v, str) or not _ID_RE.match(v):
                raise ApiError("bad_request", "%s must be an id from the game." % what)
            return v
        if not isinstance(body, dict):
            raise ApiError("bad_request", "Body must be a JSON object.")
        if action_id == "overlay_set":
            if set(body) != {"mode"}:
                raise ApiError("bad_request", "Body must be {\"mode\":\"<overlay id or None>\"}.")
            return {"mode": ident(body["mode"], "mode")}
        if action_id == "tool_select":
            if set(body) - {"tool", "priority"} or not body:
                raise ApiError("bad_request", "Body must be {\"tool\":\"<tool id>\",\"priority\":1-9|\"emergency\"}.")
            out = {}
            if "tool" in body:
                out["tool"] = ident(body["tool"], "tool")
            if "priority" in body:
                p = body["priority"]
                if not (p == "emergency" or (isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 9)):
                    raise ApiError("bad_request", "priority must be 1 to 9 or \"emergency\".")
                out["priority"] = p
            return out
        if set(body) - {"buildingId", "materials", "facadeId"} or "buildingId" not in body:
            raise ApiError("bad_request", "Body must be {\"buildingId\":\"...\",\"materials\":[\"<element id>\"]}.")
        out = {"buildingId": ident(body["buildingId"], "buildingId")}
        if "materials" in body:
            m = body["materials"]
            if not isinstance(m, list) or len(m) > 8:
                raise ApiError("bad_request", "materials must be a list of element ids, one per slot.")
            out["materials"] = [ident(x, "a material") for x in m]
        if "facadeId" in body:
            out["facadeId"] = ident(body["facadeId"], "facadeId")
        return out

    def _post_install(self, body):
        """mod_install: not a game command. Runs the install now and records the result like a finished action."""
        if self.install_hook is None:
            raise ApiError("unavailable", "Installing is not possible here.")
        self.install_hook(body)
        with self._lock:
            seq = self._next_seq()
            self._items[seq] = {"state": "done", "message": "Installed. Restart the game to load it.", "timer": _NoTimer()}
            self._trim()
        self.publish("action")
        return {"seq": seq}

    def post(self, action_id, body):
        if action_id not in ACTION_IDS:
            raise ApiError("not_found", "Unknown action.")
        if action_id == "mod_install":
            return self._post_install(body)
        if action_id in ("overlay_set", "tool_select", "build_select"):
            fields = self.parse_pad(action_id, body)
            why = self._unavailable()
            if why:
                raise ApiError("unavailable", why)
            if self.validate is not None:
                self.validate(action_id, fields)
            ctype = action_id
        elif action_id == "focus":
            target, select = self.parse_focus(body)
            why = self._unavailable()
            if why:
                raise ApiError("unavailable", why)
            ctype, fields = "focus", {"target": target, "select": select}
        elif action_id in ("alert_activate", "alert_dismiss"):
            ctype, fields = action_id, self.parse_alert(action_id, body)
        with self._lock:
            seq = self._next_seq()
            timer = threading.Timer(self.expire, self._expire, (seq,))
            timer.daemon = True
            self._items[seq] = {"state": "pending", "timer": timer}
            if ctype == "alert_dismiss":
                self._items[seq]["alert"] = fields["alertId"]
                self._dismissing[fields["alertId"]] = {"seq": seq, "since": None}
            self._trim()
        cmd = {"schema": 1, "seq": seq, "createdAt": _iso(self.clock()), "type": ctype}
        cmd.update(fields)
        try:
            os.makedirs(self.cmd_dir, exist_ok=True)
            _write_atomic(os.path.join(self.cmd_dir, "cmd-%d.json" % seq),
                          json.dumps(cmd, separators=(",", ":")))
        except OSError:
            log.exception("cannot write the command inbox")
            with self._lock:
                self._items.pop(seq, None)
                self._forget_dismiss(seq)
            raise ApiError("unavailable", "The command inbox cannot be written.")
        timer.start()           # the clock starts when the file is in place
        return {"seq": seq}

    def _forget_dismiss(self, seq):
        for aid, d in list(self._dismissing.items()):
            if d["seq"] == seq:
                del self._dismissing[aid]

    def dismissing(self, present_ids):
        """Alert ids shown as "dismissing": dismissed by the app, the game has not dropped them yet.
        An id leaves when it is no longer in live.json (present_ids), when the command failed or expired, or
        when it is still there DISMISS_STUCK_SECONDS after the game said done."""
        now = self.clock()
        with self._lock:
            for aid, d in list(self._dismissing.items()):
                if aid not in present_ids or (d["since"] is not None and now - d["since"] > DISMISS_STUCK_SECONDS):
                    del self._dismissing[aid]
            return set(self._dismissing)

    def send_command(self, ctype, fields):
        """Writes one command file of another type (art_request) and returns its seq. No timer, no state here:
        the caller keeps track and calls drop_command when it gives up. Raises ApiError like post()."""
        why = self._unavailable()
        if why:
            raise ApiError("unavailable", why)
        with self._lock:
            seq = self._next_seq()
        cmd = {"schema": 1, "seq": seq, "createdAt": _iso(self.clock()), "type": ctype}
        cmd.update(fields)
        try:
            os.makedirs(self.cmd_dir, exist_ok=True)
            _write_atomic(os.path.join(self.cmd_dir, "cmd-%d.json" % seq), json.dumps(cmd, separators=(",", ":")))
        except OSError:
            log.exception("cannot write the command inbox")
            raise ApiError("unavailable", "The command inbox cannot be written.")
        return seq

    def drop_command(self, seq):
        self._drop_command(seq)

    def read_ack(self, path, seq):
        return self._read_ack(path, seq)

    def _trim(self):
        done = [s for s, it in self._items.items() if it["state"] != "pending"]
        for s in sorted(done)[:-KEEP]:
            del self._items[s]

    # ---- results ----
    def _expire(self, seq):
        with self._lock:
            it = self._items.get(seq)
            if self._closed or not it or it["state"] != "pending":
                return
            it["state"] = "expired"
            it["message"] = "The game did not answer in time."
            self._forget_dismiss(seq)
        self._drop_command(seq)       # a mod that starts later must not run an old command
        self.publish("action")

    def _drop_command(self, seq):
        try:
            os.unlink(os.path.join(self.cmd_dir, "cmd-%d.json" % seq))
        except OSError:
            pass

    @staticmethod
    def _read_ack(path, seq):
        try:
            with open(path, "rb") as f:
                d = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if (not isinstance(d, dict) or d.get("schema") != 1 or d.get("seq") != seq
                or isinstance(d.get("seq"), bool) or d.get("state") not in ("done", "failed")):
            return None
        msg = d.get("message")
        msg = msg[:MAX_MESSAGE] if isinstance(msg, str) else None
        return d["state"], msg

    def handle_file(self, path):
        """Service watcher hook. True when the path is in acks/ (the service has nothing more to do)."""
        if not self.ack_dir or os.path.dirname(path) != self.ack_dir:
            return False
        m = _ACK_RE.match(os.path.basename(path))
        if not m:
            return True
        seq = int(m.group(1))
        with self._lock:
            known = seq in self._items
        if not known:
            hook = self.other_ack
            if hook:
                hook(seq, path)
            return True             # an old ack from an earlier run: GET reads it from disk on demand
        ack = self._read_ack(path, seq)
        if ack is None:
            return True             # not complete or not valid: the expiry timer settles it
        with self._lock:
            it = self._items.get(seq)
            if it is None or it["state"] in ("done", "failed"):
                return True
            it["timer"].cancel()
            it["state"], it["message"] = ack[0], ack[1]
            if it.get("alert"):
                if ack[0] == "failed":
                    self._forget_dismiss(seq)
                elif self._dismissing.get(it["alert"], {}).get("seq") == seq:
                    self._dismissing[it["alert"]]["since"] = self.clock()
        self._drop_command(seq)
        self.publish("action")
        return True

    def status(self, seq_text):
        try:
            seq = int(seq_text)
        except ValueError:
            raise ApiError("bad_request", "seq must be a whole number.")
        if seq < 1:
            raise ApiError("bad_request", "seq must be a whole number.")
        with self._lock:
            it = self._items.get(seq)
            if it:
                out = {"seq": seq, "state": it["state"]}
                if it.get("message"):
                    out["message"] = it["message"]
                return out
        if self.ack_dir:                      # earlier run of the core
            ack = self._read_ack(os.path.join(self.ack_dir, "ack-%d.json" % seq), seq)
            if ack:
                out = {"seq": seq, "state": ack[0]}
                if ack[1]:
                    out["message"] = ack[1]
                return out
        raise ApiError("not_found", "Unknown action number.")

    def close(self):
        with self._lock:
            self._closed = True
            for it in self._items.values():
                it["timer"].cancel()
