#!/usr/bin/env python3
"""Dev tool: pushes new ONI Companion command files from the Mac to the Nova, the moment they appear.

The Mac mirror (mirror-nova.sh) copies Nova -> Mac only. The core on the Mac writes
<mirror>/companion/commands/cmd-<seq>.json; this script copies each new one into the game's
companion/commands/ folder on the Nova over ssh (write to cmd-<seq>.json.tmp, then rename, so the mod
never sees a half file). The mod answers with acks/ack-<seq>.json, which the mirror brings back.

Event driven: it uses the core's own file watcher (kqueue on the Mac), no polling.
Writes on the Nova ONLY into companion/commands/. Stdlib only.

Usage: devtools/push-commands.py [--local-dir DIR] [--host user@host] [--remote-dir DIR]
  --local-dir   default: $ONI_MIRROR_DIR or ~/Library/Application Support/oni-companion/nova-user, + /companion/commands
  --host        default: $NOVA_HOST or steamos@nova
  --remote-dir  the Nova's companion/commands folder. Default: found like mirror-nova.sh does
                (NOVA_USER_DIR=<abs path> or NOVA_USER=proton|linux choose the user folder)
Env: SSH_CMD (the ssh program; tests put a stand-in here).
"""
import argparse
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "core"))
from oni_companion.watch import make_watcher  # noqa: E402

MAX_AGE = 10.0                  # same limit as the mod: an older command is never pushed
PUSH_TYPES = ("focus", "art_request", "alert_activate", "alert_dismiss", "set_speed", "sync_assets", "overlay_set", "tool_select", "build_select")   # the mod allow list (Commands.cs); it re-checks every command
CMD_RE = re.compile(r"^cmd-(\d+)\.json$")
SEEN_KEEP = 2048


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def parse_created(text):
    try:
        return datetime.strptime(text.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, AttributeError):
        return None


def check_command(raw, name, now):
    """Returns (ok, why). Only a well formed, fresh command of a PUSH_TYPES type is pushed (the mod re-checks)."""
    try:
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, "not valid JSON yet"
    m = CMD_RE.match(name)
    if (not isinstance(d, dict) or d.get("schema") != 1 or d.get("type") not in PUSH_TYPES
            or d.get("seq") != int(m.group(1)) or isinstance(d.get("seq"), bool)):
        return False, "not an allowed command for this file name"
    t = parse_created(d.get("createdAt"))
    if t is None:
        return False, "no createdAt"
    if now - t > MAX_AGE:
        return False, "older than %d s" % MAX_AGE
    return True, ""


class Pusher:
    def __init__(self, local_dir, ssh_argv, host, remote_dir, clock=time.time):
        self.local_dir = local_dir
        self.ssh = ssh_argv
        self.host = host
        self.remote_dir = remote_dir
        self.clock = clock
        self._q = queue.Queue()
        self._seen = {}           # name -> True, insertion ordered
        self._lock = threading.Lock()
        self._watcher = None
        self._worker = None
        self.pushed = []          # names, for tests

    def ssh_cmd(self, remote):
        return self.ssh + [self.host, remote]

    def on_file(self, path, what):          # watcher thread: only queue the name
        if what == "removed" or os.path.dirname(path) != self.local_dir:
            return
        name = os.path.basename(path)
        if CMD_RE.match(name):
            self._q.put(name)

    def start(self):
        os.makedirs(self.local_dir, exist_ok=True)
        self._watcher = make_watcher([self.local_dir], self.on_file, recursive=False).start()
        self._worker = threading.Thread(target=self._run, name="push", daemon=True)
        self._worker.start()
        return self

    def stop(self):
        self._q.put(None)
        if self._worker:
            self._worker.join(5)
        if self._watcher:
            self._watcher.stop()

    def _run(self):
        while True:
            name = self._q.get()
            if name is None:
                return
            try:
                self.push_one(name)
            except Exception as e:           # one bad command never ends the tool
                log("push of %s failed: %s" % (name, e))

    def push_one(self, name):
        with self._lock:
            if name in self._seen:           # the mirror copies a pushed file back: do not push it twice
                return False
        try:
            with open(os.path.join(self.local_dir, name), "rb") as f:
                raw = f.read()
        except OSError:
            return False
        ok, why = check_command(raw, name, self.clock())
        if not ok:
            if why != "not valid JSON yet":
                log("skipped %s: %s" % (name, why))
                self._mark(name)
            return False
        self._mark(name)
        t0 = time.monotonic()
        d = shlex.quote(self.remote_dir)
        tmp = shlex.quote(self.remote_dir + "/" + name + ".tmp")
        dst = shlex.quote(self.remote_dir + "/" + name)
        remote = "mkdir -p %s && cat > %s && mv %s %s" % (d, tmp, tmp, dst)
        r = subprocess.run(self.ssh_cmd(remote), input=raw, capture_output=True, timeout=20)
        if r.returncode != 0:
            log("push of %s failed (ssh exit %d): %s" % (name, r.returncode, r.stderr.decode("utf-8", "replace").strip()[:200]))
            return False
        self.pushed.append(name)
        log("pushed %s in %.0f ms" % (name, (time.monotonic() - t0) * 1000))
        return True

    def _mark(self, name):
        with self._lock:
            self._seen[name] = True
            while len(self._seen) > SEEN_KEEP:
                self._seen.pop(next(iter(self._seen)))


def ssh_base(host_opts=True):
    argv = shlex.split(os.environ.get("SSH_CMD", "ssh"))
    argv += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    sshdir = os.path.expanduser("~/.ssh")
    if host_opts and os.path.isdir(sshdir):          # one connection kept open: later pushes skip the handshake
        argv += ["-o", "ControlMaster=auto", "-o", "ControlPath=%s/oni-push-%%C" % sshdir,
                 "-o", "ControlPersist=300"]
    return argv


def find_remote_commands_dir(host, argv):
    """Same detection as mirror-nova.sh (nova-common.sh), then + /companion/commands."""
    env = dict(os.environ)
    if env.get("NOVA_USER_DIR"):
        return env["NOVA_USER_DIR"].rstrip("/") + "/companion/commands"
    script = '''
set -u
SSH=%s
ssh_run() { "${SSH[@]}" %s "$1"; }
. %s
REMOTE_HOME=x
pick_userdir || exit 1
printf %%s "$USERDIR"
''' % ("(" + " ".join(shlex.quote(a) for a in argv) + ")", shlex.quote(host),
       shlex.quote(os.path.join(HERE, "nova-common.sh")))
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip() + "/companion/commands"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Push ONI Companion command files from the Mac mirror to the Nova.")
    mirror = os.environ.get("ONI_MIRROR_DIR") or os.path.expanduser(
        "~/Library/Application Support/oni-companion/nova-user")
    ap.add_argument("--local-dir", default=os.path.join(mirror, "companion", "commands"))
    ap.add_argument("--host", default=os.environ.get("NOVA_HOST", "steamos@nova"))
    ap.add_argument("--remote-dir", default=None)
    args = ap.parse_args(argv)
    ssh = ssh_base()
    remote = args.remote_dir or find_remote_commands_dir(args.host, ssh)
    if not remote:
        sys.exit("push-commands: cannot find the ONI user folder on %s. Retry later, or pass --remote-dir." % args.host)
    local = os.path.abspath(args.local_dir)
    p = Pusher(local, ssh, args.host, remote).start()
    log("pushing %s -> %s:%s" % (local, args.host, remote))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        p.stop()


if __name__ == "__main__":
    main()
