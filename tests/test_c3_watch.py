"""C3: file watchers (kqueue on Mac, inotify on Linux). Needs only the stdlib and
core/oni_companion/watch, so it also runs on a device:
    PYTHONPATH=<dir holding oni_companion/> python3 test_c3_watch.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

from oni_companion.watch import make_watcher  # noqa: E402


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.rename(tmp, path)


class TestWatcher(unittest.TestCase):
    """Runs the same on kqueue (Mac) and inotify (Linux)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-c3-w-"))
        self.events = []
        self.cv = threading.Condition()
        self.w = make_watcher([self.tmp], self._cb).start()

    def tearDown(self):
        self.w.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cb(self, path, what):
        with self.cv:
            self.events.append((path, what))
            self.cv.notify_all()

    def expect(self, path, what, since=0, timeout=2.0):
        end = time.monotonic() + timeout
        with self.cv:
            while True:
                if (path, what) in self.events[since:]:
                    return len(self.events)
                left = end - time.monotonic()
                if left <= 0:
                    self.fail("no %s for %s; got %r" % (what, path, self.events[since:]))
                self.cv.wait(left)

    def settle(self):
        """Wait until trailing events (tmp cleanup, duplicates) have arrived."""
        time.sleep(0.15)
        return len(self.events)

    def test_atomic_rename_in_place_delete(self):
        p = os.path.join(self.tmp, "live.json")
        n = len(self.events)
        t0 = time.monotonic()
        atomic_write(p, "1")
        self.expect(p, "changed", n)
        n = self.settle()
        print("%s first event ms: %.1f" % (type(self.w).__name__, (time.monotonic() - t0) * 1000),
              file=sys.stderr)
        atomic_write(p, "2")                      # rename over an existing file
        self.expect(p, "changed", n)
        n = self.settle()
        with open(p, "w") as f:                   # in-place write
            f.write("3")
        self.expect(p, "changed", n)
        n = self.settle()
        os.remove(p)
        self.expect(p, "removed", n)

    def test_new_subdirectory_and_nested_file(self):
        sub = os.path.join(self.tmp, "a", "b")
        os.makedirs(sub)
        f = os.path.join(sub, "x.sav")
        time.sleep(0.2)                           # let the watcher add the new dirs
        with open(f, "w") as fh:
            fh.write("data")
        self.expect(f, "changed")
        n = self.settle()
        with open(f, "a") as fh:
            fh.write("more")
        self.expect(f, "changed", n)

    def test_burst_of_files(self):
        paths = [os.path.join(self.tmp, "f%02d.json" % i) for i in range(60)]
        for p in paths:
            atomic_write(p, "x")
        for p in paths:
            self.expect(p, "changed")


if __name__ == "__main__":
    unittest.main()
