"""Sequence number + condition variable for long-poll. Event driven."""
import threading
import time

ALL = ("colony", "gamedata", "status", "action", "settings", "art", "controls", "sync", "pad", "build", "connect")
HISTORY = 256


class EventBus:
    def __init__(self):
        self._cv = threading.Condition()
        self.seq = 1        # never 0: since=0 means "give me the current seq", so a fresh core must not hand out 0
        self._hist = []      # (seq, frozenset(names))
        self._closed = False

    def publish(self, *names):
        names = frozenset(n for n in names if n in ALL)
        if not names:
            return self.seq
        with self._cv:
            self.seq += 1
            self._hist.append((self.seq, names))
            del self._hist[:-HISTORY]
            self._cv.notify_all()
            return self.seq

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def _changed_since(self, since):
        if since > self.seq or (self._hist and since < self._hist[0][0] - 1):
            return list(ALL)            # server restarted, or history trimmed: refetch all
        out = set()
        for s, names in self._hist:
            if s > since:
                out |= names
        return [n for n in ALL if n in out]

    def wait(self, since, timeout):
        """since 0/None = give the current seq now. Returns {"seq", "changed"}."""
        deadline = time.monotonic() + timeout
        with self._cv:
            if not since:
                return {"seq": self.seq, "changed": []}
            while self.seq == since:
                left = deadline - time.monotonic()
                if left <= 0 or self._closed:
                    return {"seq": self.seq, "changed": []}
                self._cv.wait(left)
            return {"seq": self.seq, "changed": self._changed_since(since)}
