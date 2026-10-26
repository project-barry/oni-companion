"""kqueue watcher (macOS/BSD), event driven.

A directory vnode only says "something in here changed", so each directory
keeps a snapshot {name: (mtime_ns, size, inode)}. A directory event rescans and
diffs. Files that are written in place also get their own vnode watch (the
newest FILES_PER_DIR per directory) so a long write is seen when it finishes.
"""
import logging
import os
import select
import threading

log = logging.getLogger("oni_companion.watch")
FILES_PER_DIR = 32
MAX_DEPTH = 4
_DIR_FF = (select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_EXTEND)
_FILE_FF = (select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)


class KqueueWatcher:
    def __init__(self, roots, callback, recursive=True):
        self.roots = [os.path.abspath(r) for r in roots]
        self.callback = callback
        self.recursive = recursive
        self._kq = None
        self._fds = {}      # fd -> ("dir"|"file", path)
        self._by_path = {}  # path -> fd
        self._snap = {}     # dir -> {name: (mtime_ns, size, ino)}
        self._depth = {}
        self._wake = None
        self._thread = None

    # ---- registration ----
    def _register(self, path, kind, flags):
        if path in self._by_path:
            return self._by_path[path]
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_EVTONLY", 0))
        except OSError:
            return None
        ev = select.kevent(fd, select.KQ_FILTER_VNODE, select.KQ_EV_ADD | select.KQ_EV_CLEAR, flags)
        try:
            self._kq.control([ev], 0, 0)
        except OSError:
            os.close(fd)
            return None
        self._fds[fd] = (kind, path)
        self._by_path[path] = fd
        return fd

    def _unregister(self, path):
        fd = self._by_path.pop(path, None)
        if fd is not None:
            self._fds.pop(fd, None)
            try:
                os.close(fd)   # closing removes the kevent
            except OSError:
                pass

    def _scan(self, d):
        out = {}
        try:
            for e in os.scandir(d):
                if e.is_file(follow_symlinks=False):
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    out[e.name] = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return None
        return out

    def _subdirs(self, d):
        try:
            return [e.path for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return []

    def _add_dir(self, d, depth=0, report_existing=False):
        if self._register(d, "dir", _DIR_FF) is None:
            return
        self._depth[d] = depth
        snap = self._scan(d) or {}
        self._snap[d] = snap
        self._watch_files(d, snap)
        if report_existing:
            for name in snap:
                self.callback(os.path.join(d, name), "changed")
        if self.recursive and depth < MAX_DEPTH:
            for sd in self._subdirs(d):
                self._add_dir(sd, depth + 1, report_existing)

    def _watch_files(self, d, snap):
        newest = sorted(snap, key=lambda n: snap[n][0], reverse=True)[:FILES_PER_DIR]
        keep = {os.path.join(d, n) for n in newest}
        for n in newest:
            p = os.path.join(d, n)
            fd = self._by_path.get(p)
            if fd is not None:
                try:   # inode replaced (rename over): reopen
                    if os.fstat(fd).st_ino != snap[n][2]:
                        self._unregister(p)
                except OSError:
                    self._unregister(p)
            self._register(p, "file", _FILE_FF)
        for p in [p for p, fd in self._by_path.items()
                  if self._fds.get(fd, ("", ""))[0] == "file" and os.path.dirname(p) == d and p not in keep]:
            self._unregister(p)

    # ---- lifecycle ----
    def start(self):
        self._kq = select.kqueue()
        for r in self.roots:
            self._add_dir(r)
        self._wake = os.pipe()
        wev = select.kevent(self._wake[0], select.KQ_FILTER_READ, select.KQ_EV_ADD)
        self._kq.control([wev], 0, 0)
        self._thread = threading.Thread(target=self._run, name="oni-kqueue", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._wake:
            os.write(self._wake[1], b"x")
            if self._thread:
                self._thread.join(2)
            for fd in list(self._fds):
                try:
                    os.close(fd)
                except OSError:
                    pass
            for fd in (self._wake[0], self._wake[1]):
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._kq.close()
            self._wake = None

    def _run(self):
        while True:
            events = self._kq.control(None, 64, None)
            for ev in events:
                if ev.ident == self._wake[0]:
                    return
                info = self._fds.get(ev.ident)
                if info is None:
                    continue
                kind, path = info
                try:      # one bad event must never end the watcher thread
                    if kind == "dir":
                        self._dir_event(path)
                    else:
                        self._file_event(path, ev.fflags)
                except Exception:
                    log.exception("watch event failed for %s", path)

    def _dir_event(self, d):
        new = self._scan(d)
        if new is None:                       # directory gone
            for p in [p for p in self._by_path if p == d or p.startswith(d + os.sep)]:
                self._unregister(p)
            self._snap.pop(d, None)
            self.callback(d, "removed")
            return
        old = self._snap.get(d, {})
        self._snap[d] = new
        for name, sig in new.items():
            if old.get(name) != sig:
                self.callback(os.path.join(d, name), "changed")
        for name in old:
            if name not in new:
                self._unregister(os.path.join(d, name))
                self.callback(os.path.join(d, name), "removed")
        self._watch_files(d, new)
        if self.recursive and self._depth.get(d, 0) < MAX_DEPTH:
            for sd in self._subdirs(d):
                if sd in self._by_path and self._replaced(sd):
                    # The folder was swapped for a new one at the same path (sync tools do this):
                    # our watch is on the old, deleted folder. Drop it and watch the new one.
                    for p in [p for p in self._by_path if p == sd or p.startswith(sd + os.sep)]:
                        self._unregister(p)
                    self._snap.pop(sd, None)
                if sd not in self._by_path:
                    self._add_dir(sd, self._depth.get(d, 0) + 1, report_existing=True)

    def _replaced(self, d):
        fd = self._by_path.get(d)
        try:
            return fd is None or os.fstat(fd).st_ino != os.stat(d).st_ino
        except OSError:
            return True

    def _file_event(self, p, fflags):
        d = os.path.dirname(p)
        if fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME):
            # The directory event reports it. A stale event can name an fd number
            # that was reused for the replacement file: keep the watch if the path
            # still holds the very file this fd is open on.
            fd = self._by_path.get(p)
            try:
                if fd is not None and os.fstat(fd).st_ino == os.stat(p).st_ino:
                    return
            except OSError:
                pass
            self._unregister(p)
            return
        try:
            st = os.stat(p)
        except OSError:
            return
        snap = self._snap.get(d)
        if snap is not None:
            snap[os.path.basename(p)] = (st.st_mtime_ns, st.st_size, st.st_ino)
        self.callback(p, "changed")
