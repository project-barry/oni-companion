"""Speed controls (v1.2): GET and POST /api/v1/controls. Stdlib only.

GET reads live.json through the Colony model (shared cache and freshness rule) and says whether the
game can take a speed command: `available` is false in the menu, without the mod, or when live.json is
too old (`reason`: menu, no_mod, stale).
POST {state, speed?} writes a `set_speed` command through the actions module and keeps a `pending`
record until live.json confirms it (or PENDING_SECONDS pass). The core never changes game state itself;
the mod does, through the game's own speed control. Event driven: POST and each live.json change send
the `controls` event; nothing polls.
"""
import os
import threading
import time

from . import cause as cause_mod
from .server.errors import ApiError

PENDING_SECONDS = 10.0
MENU_FRESH_SECONDS = 180       # mod 0.4.1+ rewrites the menu state every 60 s; older mods write it once
# The header's game state (front ends show `label` with a dot in `tone`); the core decides, front ends only draw it.
GAME_STATES = {
    "live": ("Live", "good"),
    "paused": ("Game paused", "good"),
    "menu": ("At the main menu", "warn"),
    "not_running": ("Game not running", "neutral"),
}
SPEEDS = (1, 2, 3)
STATES = ("pause", "play", "speed")      # speed = the game's speed buttons: set the speed, keep the pause state
REASON_TEXT = {
    "menu": "The game is in the menu. Load a colony to change the speed.",
    "no_mod": "The game is not running. Start a colony to change the speed.",
    "stale": "The game is not sending data. Is it running?",
}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class Controls:
    """actions: ActionService (send_command). colony: Colony (read_live, live_fresh).
    publish(name): the event bus. companion_dir: <user>/companion, or None."""

    def __init__(self, actions, colony, publish, companion_dir, clock=time.time,
                 pending_seconds=PENDING_SECONDS):
        self.actions = actions
        self.colony = colony
        self.publish = publish
        self.companion_dir = companion_dir
        self.clock = clock
        self.pending_seconds = pending_seconds
        self._lock = threading.Lock()
        self._pending = None          # {"state", "speed"?, "seq", "at"}
        self.explainer = None         # cause.Explainer: the real cause for the reply (cause, message)

    def retarget(self, companion_dir):
        """The active ONI folder changed (plan 4.3): the next reply and command use the new one."""
        with self._lock:
            self.companion_dir = companion_dir
            self._pending = None
            self._deadline = None
            t, self._expiry = getattr(self, "_expiry", None), None
        if t:
            t.cancel()

    def _kind(self, live):
        if not live:
            return "none"
        return cause_mod.live_kind(live.get("state"), self._written(live), live.get("paused") is True, self.clock())

    def _written(self, live):
        from .colony import parse_iso
        return parse_iso(live.get("writtenAt", "")) if isinstance(live.get("writtenAt"), str) else None

    def _menu_fresh(self, live):
        w = self._written(live)
        return w is not None and self.clock() - w <= MENU_FRESH_SECONDS

    def game_state(self, ok, reason, live):
        """{state, label, tone} for the header: what the game is doing right now."""
        if ok:
            key = "paused" if live.get("paused") is True else "live"
        elif reason == "menu":
            key = "menu"
        else:
            key = "not_running"
        label, tone = GAME_STATES[key]
        return {"state": key, "label": label, "tone": tone}

    def _arm_expiry(self, live):
        """One shot at the moment the shown state would go stale (a crash writes nothing): send `controls` then."""
        from .colony import FRESH_SECONDS, FRESH_SECONDS_PAUSED
        w = self._written(live) if live else None
        if w is None:
            return
        st = live.get("state")
        if st == "running":
            limit = FRESH_SECONDS_PAUSED if live.get("paused") else FRESH_SECONDS
        elif st == "menu":
            limit = MENU_FRESH_SECONDS
        else:
            return
        deadline = w + limit + 1
        delay = deadline - self.clock()
        if delay <= 0 or getattr(self, "_deadline", None) == deadline:
            return                                  # already past, or this deadline already has its timer
        self._deadline = deadline
        t = threading.Timer(delay, self.publish, ("controls",))
        t.daemon = True
        with self._lock:
            old, self._expiry = getattr(self, "_expiry", None), t
        if old:
            old.cancel()
        t.start()

    def close(self):
        with self._lock:
            t, self._expiry = getattr(self, "_expiry", None), None
        if t:
            t.cancel()

    # ---- availability ----
    def availability(self):
        """(available, reason, live). reason is None when available, else menu | no_mod | stale.
        live is the parsed live.json (or None), so the caller can show last known values."""
        if not self.companion_dir or not os.path.isdir(self.companion_dir):
            return False, "no_mod", None
        live = self.colony.read_live()
        if not live:
            return False, "no_mod", None
        if live.get("state") == "stopped" or (live.get("state") == "menu" and not self._menu_fresh(live)):
            return False, "no_mod", live
        if live.get("state") != "running":
            return False, "menu", live
        if not self.colony.live_fresh(live):
            return False, "stale", live
        return True, None, live

    # ---- pending ----
    @staticmethod
    def _confirms(pending, live):
        """True when live.json shows what the pending command asked for."""
        if not live or live.get("state") != "running" or not isinstance(live.get("paused"), bool):
            return False
        if pending["state"] != "speed" and live["paused"] != (pending["state"] == "pause"):
            return False
        if "speed" in pending and live.get("speed") != pending["speed"]:
            return False
        return True

    def _settle(self, live):
        """Under the lock: the pending record still to show, or None (and it is cleared)."""
        p = self._pending
        if p is None:
            return None
        if self.clock() - p["at"] > self.pending_seconds or self._confirms(p, live):
            self._pending = None
            return None
        return p

    # ---- replies ----
    def get(self):
        ok, reason, live = self.availability()
        out = {"available": ok, "game": self.game_state(ok, reason, live)}
        if not ok:
            out["reason"] = reason
            ex = self.explainer.explain(self._kind(live), (live or {}).get("dlcIds")) if self.explainer else None
            if ex:
                out.update(ex)
                if out.get("cause") in ("mod_off", "mod_crashed"):
                    out["game"] = {"state": "not_running", "label": "ONI Companion Link is off", "tone": "warn"}
        self._arm_expiry(live)
        if live and reason != "no_mod":
            if isinstance(live.get("paused"), bool):
                out["paused"] = live["paused"]
            if _is_int(live.get("speed")) and live["speed"] in SPEEDS:
                out["speed"] = live["speed"]
            if isinstance(live.get("writtenAt"), str):
                out["asOf"] = live["writtenAt"]
        with self._lock:
            if not ok:
                self._pending = None          # nothing to confirm while the game cannot take commands
                return out
            p = self._settle(live)
            if p:
                pend = {"state": p["state"], "seq": p["seq"]}
                if "speed" in p:
                    pend["speed"] = p["speed"]
                out["pending"] = pend
        return out

    @staticmethod
    def parse_post(body):
        """{state, speed?} -> (state, speed or None). Raises ApiError bad_request."""
        if not isinstance(body, dict) or set(body) - {"state", "speed"}:
            raise ApiError("bad_request", "Body must be {\"state\":\"pause\"|\"play\"|\"speed\",\"speed\":1|2|3}.")
        state = body.get("state")
        if state not in STATES:
            raise ApiError("bad_request", "state must be pause, play or speed.")
        if "speed" not in body:
            if state == "speed":
                raise ApiError("bad_request", "state speed needs speed 1, 2 or 3.")
            return state, None
        speed = body["speed"]
        if state == "pause":
            raise ApiError("bad_request", "speed goes only with play or speed.")
        if not _is_int(speed) or speed not in SPEEDS:
            raise ApiError("bad_request", "speed must be 1, 2 or 3.")
        return state, speed

    def post(self, body):
        state, speed = self.parse_post(body)
        ok, reason, _live = self.availability()
        if not ok:
            msg = REASON_TEXT[reason]
            ex = self.explainer.explain(self._kind(_live), (_live or {}).get("dlcIds")) if self.explainer else None
            if ex:
                msg = ex["message"]
            raise ApiError("unavailable", msg)
        fields = {"state": state}
        if speed is not None:
            fields["speed"] = speed
        seq = self.actions.send_command("set_speed", fields)
        pending = {"state": state, "seq": seq, "at": self.clock()}
        if speed is not None:
            pending["speed"] = speed
        with self._lock:
            self._pending = pending
        self.publish("controls")
        return self.get()
