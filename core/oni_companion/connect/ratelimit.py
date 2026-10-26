"""Rate limits (contracts/api.md, "Device token, 401 and rate limits"). Pure logic with an injectable clock."""
import threading
from collections import deque


class TokenBucket:
    def __init__(self, rate, burst, clock):
        self.rate, self.burst, self.clock = float(rate), float(burst), clock
        self.tokens = float(burst)
        self.stamp = clock()

    def take(self):
        """0 = allowed. Otherwise the whole seconds to wait (at least 1)."""
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0
        need = (1.0 - self.tokens) / self.rate
        return max(1, int(need) + (1 if need % 1 else 0))


class SlidingCount:
    """How many events in the last `window` seconds, per key."""

    def __init__(self, window, clock):
        self.window, self.clock = window, clock
        self._ev = {}

    def _trim(self, key):
        q = self._ev.get(key)
        if q is None:
            return None
        cut = self.clock() - self.window
        while q and q[0] <= cut:
            q.popleft()
        if not q:
            del self._ev[key]
            return None
        return q

    def add(self, key):
        self._trim(key)
        self._ev.setdefault(key, deque()).append(self.clock())

    def count(self, key):
        q = self._trim(key)
        return len(q) if q else 0

    def retry_after(self, key):
        q = self._trim(key)
        if not q:
            return 1
        return max(1, int(q[0] + self.window - self.clock()) + 1)

    def forget_old(self):
        for k in list(self._ev):
            self._trim(k)


class DeviceLimits:
    """Per-device token buckets: reads 20/s burst 40; POST and DELETE 5/s burst 10; at most 2 long-polls."""
    READ = (20, 40)
    WRITE = (5, 10)
    MAX_POLLS = 2

    def __init__(self, clock):
        self.clock = clock
        self._lock = threading.Lock()
        self._read, self._write, self._polls = {}, {}, {}

    def check(self, device_id, method):
        """0 when allowed, else Retry-After seconds."""
        with self._lock:
            table, spec = (self._read, self.READ) if method == "GET" else (self._write, self.WRITE)
            b = table.get(device_id)
            if b is None:
                b = table[device_id] = TokenBucket(spec[0], spec[1], self.clock)
            return b.take()

    def poll_enter(self, device_id):
        with self._lock:
            n = self._polls.get(device_id, 0)
            if n >= self.MAX_POLLS:
                return False
            self._polls[device_id] = n + 1
            return True

    def poll_exit(self, device_id):
        with self._lock:
            n = self._polls.get(device_id, 0) - 1
            if n > 0:
                self._polls[device_id] = n
            else:
                self._polls.pop(device_id, None)

    def forget(self, device_id):
        with self._lock:
            for t in (self._read, self._write):
                t.pop(device_id, None)
