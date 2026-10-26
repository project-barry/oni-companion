"""On-demand art: asks the mod to draw an image that is missing (command `art_request`).

When an app asks for GET /art/<kind>/<id> and the manifest has no such image, `request` writes ONE
companion/commands/cmd-<seq>.json {type: art_request, target: {kind, id}}. Rules:
- one request per item while it is outstanding (dedupe), at most MAX_OUTSTANDING at a time; the rest are
  dropped (the app asks again when it sees the `art` event, or reloads the page);
- an outstanding request ends with the mod's ack (done: the manifest lists the image and the watcher
  publishes `art`; failed: the item is not asked for again for a while, longer for a permanent reason),
  or after EXPIRE seconds without an ack (its command file is removed);
- only catalog kinds (never dupe: portraits draw themselves) and ids the mod accepts (letters, digits, _ . -);
- nothing is asked when the mod's manifest does not say `onDemand`, or when the game is not sending data.
Event driven: expiry is checked when a request or an ack comes in; there are no timers.
"""
import json
import logging
import os
import re
import threading
import time


log = logging.getLogger("oni_companion.art")

REQUEST_KINDS = ("building", "element", "critter", "plant", "seed", "egg", "food", "medicine", "item")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
MAX_OUTSTANDING = 20
EXPIRE = 30.0                 # seconds without an ack
FAIL_SHORT = 20.0             # retry pause after a failure that may pass (queue full, art off...)
FAIL_LONG = 3600.0            # the game has no such item or no picture for it
UNAVAILABLE_PAUSE = 2.0       # after "the game is not sending data": do not look again at once
PERMANENT = ("Unknown id", "The game has no picture for it")


def requestable(kind, ident):
    return kind in REQUEST_KINDS and isinstance(ident, str) and bool(SAFE_ID.match(ident))


class ArtRequests:
    def __init__(self, actions, store, clock=time.time, max_outstanding=MAX_OUTSTANDING, expire=EXPIRE):
        self.actions, self.store, self.clock = actions, store, clock
        self.max_outstanding, self.expire = max_outstanding, expire
        self._lock = threading.Lock()
        self._out = {}            # (kind, id) -> (seq, sent_at)
        self._by_seq = {}         # seq -> (kind, id)
        self._failed = {}         # (kind, id) -> retry_after
        self._pause_until = 0.0
        self.sent = 0             # for tests and logs

    def reset(self):
        """The active ONI folder changed: requests sent to the old one will never be answered here."""
        with self._lock:
            self._out.clear()
            self._by_seq.clear()
            self._pause_until = 0.0

    def outstanding(self):
        with self._lock:
            return len(self._out)

    def _purge(self, now):
        for key, (seq, at) in list(self._out.items()):
            if now - at > self.expire:
                del self._out[key]
                self._by_seq.pop(seq, None)
                self._failed[key] = now + FAIL_SHORT
                self.actions.drop_command(seq)
        for key, until in list(self._failed.items()):
            if until <= now:
                del self._failed[key]

    def request(self, kind, ident):
        """True when a command was sent. Called for every art GET that finds no image."""
        if not requestable(kind, ident):
            return False
        now = self.clock()
        key = (kind, ident)
        with self._lock:
            self._purge(now)
            if key in self._out or key in self._failed or now < self._pause_until:
                return False
            if len(self._out) >= self.max_outstanding:
                return False
        if not self.store.on_demand() or self.store.has(kind, ident):
            return False
        try:
            seq = self.actions.send_command("art_request", {"target": {"kind": kind, "id": ident}})
        except Exception as e:           # ApiError (not imported here: server/ imports this module)
            if getattr(e, "code", None) == "unavailable":
                with self._lock:
                    self._pause_until = now + UNAVAILABLE_PAUSE
            return False
        with self._lock:
            self._out[key] = (seq, now)
            self._by_seq[seq] = key
            self.sent += 1
        return True

    def handle_ack(self, seq, path):
        """ActionService hook for an ack it does not know. True when the seq was an art request."""
        with self._lock:
            key = self._by_seq.get(seq)
        if key is None:
            return False
        ack = self.actions.read_ack(path, seq)
        if ack is None:
            return True                       # not complete yet: the expiry settles it
        state, msg = ack
        with self._lock:
            if self._by_seq.pop(seq, None) is None:
                return True
            self._out.pop(key, None)
            if state == "failed":
                self._failed[key] = self.clock() + (FAIL_LONG if msg in PERMANENT else FAIL_SHORT)
        if state == "failed":
            log.info("art_request %s/%s failed: %s", key[0], key[1], msg)
        self.actions.drop_command(seq)
        return True
