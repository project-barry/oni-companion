"""Event-driven file watching (no polling).

make_watcher(roots, callback) picks inotify on Linux and kqueue on macOS/BSD.
callback(path, what) is called from the watcher thread; what is "changed" or
"removed". Watches are on directories (live files are replaced by rename), and
recursive for sub-folders (save folders).
"""
import sys


def make_watcher(roots, callback, recursive=True):
    if sys.platform.startswith("linux"):
        from .inotify import InotifyWatcher
        return InotifyWatcher(roots, callback, recursive)
    from .kqueue import KqueueWatcher
    return KqueueWatcher(roots, callback, recursive)
