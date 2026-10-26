"""inotify through ctypes (Linux). One thread blocked in select(); no polling."""
import ctypes
import ctypes.util
import os
import select
import struct
import threading

IN_MODIFY = 0x2
IN_MOVED_FROM = 0x40
IN_MOVED_TO = 0x80
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_DELETE_SELF = 0x400
IN_CLOSE_WRITE = 0x8
IN_ISDIR = 0x40000000
IN_Q_OVERFLOW = 0x4000
IN_IGNORED = 0x8000
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
# close_write/moved_to mean "a file is complete"; delete/moved_from mean gone.
MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_MOVED_FROM | IN_CREATE | IN_DELETE | IN_DELETE_SELF
_HDR = struct.Struct("iIII")
MAX_DEPTH = 4


class InotifyWatcher:
    def __init__(self, roots, callback, recursive=True):
        self.roots = [os.path.abspath(r) for r in roots]
        self.callback = callback
        self.recursive = recursive
        self._libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self._fd = -1
        self._wd = {}       # wd -> dir path
        self._depth = {}
        self._pipe = None
        self._thread = None

    def _add(self, path, depth=0):
        wd = self._libc.inotify_add_watch(self._fd, os.fsencode(path), MASK)
        if wd < 0:
            return False
        self._wd[wd] = path
        self._depth[wd] = depth
        if self.recursive and depth < MAX_DEPTH:
            try:
                for e in os.scandir(path):
                    if e.is_dir(follow_symlinks=False):
                        self._add(e.path, depth + 1)
            except OSError:
                pass
        return True

    def start(self):
        self._fd = self._libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        for r in self.roots:
            self._add(r)
        self._pipe = os.pipe()
        self._thread = threading.Thread(target=self._run, name="oni-inotify", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._pipe:
            os.write(self._pipe[1], b"x")
            if self._thread:
                self._thread.join(2)
            for fd in (self._pipe[0], self._pipe[1], self._fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._pipe = None

    def _run(self):
        while True:
            r, _, _ = select.select([self._fd, self._pipe[0]], [], [])
            if self._pipe[0] in r:
                return
            try:
                buf = os.read(self._fd, 65536)
            except BlockingIOError:
                continue
            off = 0
            while off + _HDR.size <= len(buf):
                wd, mask, _cookie, ln = _HDR.unpack_from(buf, off)
                name = buf[off + _HDR.size: off + _HDR.size + ln].split(b"\0", 1)[0]
                off += _HDR.size + ln
                self._handle(wd, mask, os.fsdecode(name))

    def _handle(self, wd, mask, name):
        d = self._wd.get(wd)
        if mask & IN_IGNORED:
            self._wd.pop(wd, None)
            return
        if d is None:
            return
        if mask & IN_Q_OVERFLOW:
            self.callback(d, "changed")
            return
        full = os.path.join(d, name) if name else d
        if mask & IN_ISDIR:
            if mask & (IN_CREATE | IN_MOVED_TO) and self.recursive and self._depth[wd] < MAX_DEPTH:
                self._add(full, self._depth[wd] + 1)
                # files created before the watch existed
                try:
                    for e in os.scandir(full):
                        if e.is_file():
                            self.callback(e.path, "changed")
                except OSError:
                    pass
            return
        if mask & (IN_CLOSE_WRITE | IN_MOVED_TO):
            self.callback(full, "changed")
        elif mask & (IN_DELETE | IN_MOVED_FROM | IN_DELETE_SELF):
            self.callback(full, "removed")
        elif mask & IN_CREATE:
            pass  # wait for close_write
