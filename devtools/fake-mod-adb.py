#!/usr/bin/env python3
"""Stands in for the mod on an Android emulator (lane A3 test harness, not shipped).

Writes <folder>/companion/{export,live} from the synthetic fixtures through adb, then answers commands: every
cmd-N.json the app puts in <folder>/companion/commands gets an ack-N.json (state done) and is removed, as the mod does.
Usage: fake-mod-adb.py SERIAL [FOLDER] [--stop-after SECONDS] [--paused]
"""
import json, os, subprocess, sys, tempfile, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "..", "fixtures", "synthetic", "mod")


def adb(serial, *a, inp=None):
    return subprocess.run(["adb", "-s", serial, *a], capture_output=True, input=inp, timeout=60)


def put(serial, remote, data: bytes):
    d = os.path.dirname(remote)
    tmp = remote + ".tmp"
    adb(serial, "shell", "mkdir -p '%s'" % d)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
    adb(serial, "push", f.name, tmp)
    os.unlink(f.name)
    adb(serial, "shell", "mv '%s' '%s'" % (tmp, remote))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    serial = sys.argv[1]
    folder = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "/sdcard/ONICompanion"
    stop_after = float(sys.argv[sys.argv.index("--stop-after") + 1]) if "--stop-after" in sys.argv else None
    paused = "--paused" in sys.argv
    comp = folder + "/companion"
    with open(os.path.join(FIX, "export-v13.json"), "rb") as f:
        put(serial, comp + "/export/gamedata-1-X.json", f.read())
    with open(os.path.join(FIX, "live-running-v13.json")) as f:
        live = json.load(f)
    t0 = time.time()
    last = 0
    while stop_after is None or time.time() - t0 < stop_after:
        if time.time() - last >= 4:
            live["writtenAt"] = now()
            live["paused"] = paused
            put(serial, comp + "/live/live.json", json.dumps(live).encode())
            last = time.time()
        out = adb(serial, "shell", "ls '%s/commands' 2>/dev/null" % comp).stdout.decode().split()
        for n in out:
            if n.startswith("cmd-") and n.endswith(".json"):
                seq = int(n[4:-5])
                body = adb(serial, "shell", "cat '%s/commands/%s'" % (comp, n)).stdout.decode()
                print("command", seq, body[:120], flush=True)
                put(serial, "%s/acks/ack-%d.json" % (comp, seq),
                    json.dumps({"schema": 1, "seq": seq, "state": "done", "ackedAt": now()}).encode())
                adb(serial, "shell", "rm '%s/commands/%s'" % (comp, n))
        time.sleep(0.7)


main()
