#!/usr/bin/env python3
"""Dev tool, used by mirror-nova.sh: copies the files named by inotifywait events from the Nova, in batches.

One ssh + tar per file fell minutes behind when a sync drew 1,000+ pictures, and live.json waited in that queue.
This reads event lines ("EVENTS|/abs/path") from stdin, gathers whatever arrives within BATCH_S of the first one,
and copies the whole batch with one ssh running tar (names on stdin). A new folder (CREATE,ISDIR) is copied whole:
files written into it before inotifywait watches it send no event of their own.

Usage: mirror-batch.py USERDIR DEST   (env SSH_CMD, NOVA_HOST; ssh options as in mirror-nova.sh)
Nothing is written on the Nova. Stdlib only.
"""
import os
import queue
import subprocess
import sys
import threading
import time

BATCH_S = 0.15
MAX_BATCH = 2000
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3"]


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def relpath(userdir, line):
    events, sep, path = line.partition("|")
    if not sep or not path.startswith(userdir + "/") or path.endswith(".tmp"):
        return None
    if "CREATE" in events and "ISDIR" not in events:
        return None                        # a new file: its close_write / moved_to event follows
    return path[len(userdir) + 1:]


def copy(userdir, dest, ssh, names):
    remote = "tar -C %s --ignore-failed-read -cf - -T - 2>/dev/null" % q(userdir)
    t0 = time.time()
    src = subprocess.Popen(ssh + [remote], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    dst = subprocess.Popen(["tar", "-C", dest, "-xf", "-"], stdin=src.stdout, stderr=subprocess.DEVNULL)
    src.stdout.close()
    src.stdin.write(("\n".join(names) + "\n").encode())
    src.stdin.close()
    ok = dst.wait() == 0 and src.wait() in (0, 1)       # GNU tar exits 1 when a file vanished on the way (--ignore-failed-read)
    ms = (time.time() - t0) * 1000
    shown = names[0] if len(names) == 1 else "%d files (%s, ...)" % (len(names), names[0])
    log(("copied %s in %d ms" if ok else "copy failed: %s (%d ms)") % (shown, ms))


def main():
    userdir, dest = sys.argv[1].rstrip("/"), sys.argv[2]
    ssh = [os.environ.get("SSH_CMD", "ssh")] + SSH_OPTS + [os.environ.get("NOVA_HOST", "steamos@nova")]
    lines = queue.Queue()

    def reader():
        for raw in sys.stdin:
            lines.put(raw.rstrip("\n"))
        lines.put(None)
    threading.Thread(target=reader, daemon=True).start()

    while True:
        first = lines.get()
        if first is None:
            return
        batch, end, eof = [first], time.time() + BATCH_S, False
        while len(batch) < MAX_BATCH:
            try:
                nxt = lines.get(timeout=max(0.0, end - time.time()))
            except queue.Empty:
                break
            if nxt is None:
                eof = True
                break
            batch.append(nxt)
        names = []
        for line in batch:
            r = relpath(userdir, line)
            if r and r not in names:
                names.append(r)
        if names:
            copy(userdir, dest, ssh, names)
        if eof:
            return


if __name__ == "__main__":
    main()
