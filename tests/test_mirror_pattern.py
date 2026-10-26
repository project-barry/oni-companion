"""The Mac mirror (devtools/mirror-nova.sh) writes with `tar -xf -`: every file is a temp file
renamed into place, its mtime comes from the archive (whole seconds), and the first sync lays folders
over existing ones. The core must see every such write: watcher, /events, and the colony it serves."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import colony as colony_mod  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from oni_companion.watch import make_watcher  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic")


def tar_copy(src_dir, name, dest_dir):
    """Exactly the mirror's copy_one: tar on the 'remote' side, tar -xf - locally."""
    os.makedirs(dest_dir, exist_ok=True)
    p = subprocess.Popen(["tar", "-C", src_dir, "-cf", "-", name], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-C", dest_dir, "-xf", "-"], stdin=p.stdout, check=True)
    p.stdout.close()
    p.wait()


def live_json(tod, written=None):
    with open(os.path.join(FIX, "mod", "live-running.json")) as f:
        d = json.load(f)
    d.update(state="running", paused=False, timeOfDay=tod, writtenAt=colony_mod.iso(written or time.time()))
    return json.dumps(d)


@unittest.skipUnless(shutil.which("tar"), "needs tar")
class TestMirrorPattern(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-mirror-"))
        self.remote = os.path.join(self.tmp, "remote")
        self.user = os.path.join(self.tmp, "user")
        os.makedirs(self.remote)
        self.rlive = os.path.join(self.remote, "live")
        os.makedirs(self.rlive)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def remote_write(self, tod):
        with open(os.path.join(self.rlive, "live.json"), "w") as f:
            f.write(live_json(tod))
        t = time.time() // 1 + 0.0    # whole seconds, like a tar header
        os.utime(os.path.join(self.rlive, "live.json"), (t, t))

    def test_every_mirror_write_reaches_events_and_colony(self):
        live_dir = os.path.join(self.user, "companion", "live")
        os.makedirs(live_dir)                      # the folder exists before the core starts
        svc = Service(ServiceConfig(user_dir=self.user, save_dirs=[], token="t", views_factory=StubViews)).start()
        self.addCleanup(svc.stop)
        seq = svc.bus.wait(0, 0)["seq"]
        for i in range(12):
            tod = round(0.05 + i * 0.03, 5)
            self.remote_write(tod)                 # same size every time: only the content differs
            tar_copy(self.rlive, "live.json", live_dir)
            ev = svc.bus.wait(seq, 3)
            seq = ev["seq"]
            self.assertIn("colony", ev["changed"], "write %d produced no colony event" % i)
            self.assertEqual(svc.colony.facts()["timeOfDay"], tod, "write %d not served" % i)

    def test_folder_created_after_the_core_started_and_first_sync_over_it(self):
        os.makedirs(self.user)
        svc = Service(ServiceConfig(user_dir=self.user, save_dirs=[], token="t", views_factory=StubViews)).start()
        self.addCleanup(svc.stop)
        seq = svc.bus.wait(0, 0)["seq"]
        self.remote_write(0.2)
        # first sync: whole companion tree, like initial_sync
        os.makedirs(os.path.join(self.remote, "companion"))
        shutil.move(self.rlive, os.path.join(self.remote, "companion", "live"))
        subprocess.run("tar -C %s -cf - companion | tar -C %s -xf -" % (self.remote, self.user), shell=True, check=True)
        ev = svc.bus.wait(seq, 3)
        self.assertIn("colony", ev["changed"])
        seq = ev["seq"]
        self.assertEqual(svc.colony.facts()["timeOfDay"], 0.2)
        rl = os.path.join(self.remote, "companion", "live")
        for i, tod in enumerate((0.31, 0.32, 0.33)):
            with open(os.path.join(rl, "live.json"), "w") as f:
                f.write(live_json(tod))
            tar_copy(rl, "live.json", os.path.join(self.user, "companion", "live"))
            ev = svc.bus.wait(seq, 3)
            seq = ev["seq"]
            self.assertIn("colony", ev["changed"])
            self.assertEqual(svc.colony.facts()["timeOfDay"], tod)

    def test_long_poll_wakes_while_blocked(self):
        live_dir = os.path.join(self.user, "companion", "live")
        os.makedirs(live_dir)
        svc = Service(ServiceConfig(user_dir=self.user, save_dirs=[], token="t", views_factory=StubViews)).start()
        self.addCleanup(svc.stop)
        seq = svc.bus.wait(0, 0)["seq"]
        got = {}
        t = threading.Thread(target=lambda: got.update(svc.bus.wait(seq, 10)))
        t.start()
        time.sleep(0.3)                            # the poll is now waiting
        self.remote_write(0.7)
        tar_copy(self.rlive, "live.json", live_dir)
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertIn("colony", got["changed"])

    @unittest.skipUnless(sys.platform == "darwin", "kqueue watches folders by vnode")
    def test_folder_swapped_for_a_new_one_is_watched_again(self):
        """Sync tools (iCloud) can replace a folder at the same path; a watch on the old one goes deaf."""
        live_dir = os.path.join(self.user, "companion", "live")
        os.makedirs(live_dir)
        events = []
        cv = threading.Condition()

        def cb(path, what):
            with cv:
                events.append((path, what))
                cv.notify_all()
        w = make_watcher([self.user], cb).start()
        self.addCleanup(w.stop)
        shutil.rmtree(live_dir)                    # swap: the whole folder is replaced
        time.sleep(0.2)
        os.makedirs(live_dir)
        time.sleep(0.3)
        target = os.path.join(live_dir, "live.json")
        with open(target, "w") as f:
            f.write("{}")
        end = time.monotonic() + 3
        with cv:
            while (target, "changed") not in events and time.monotonic() < end:
                cv.wait(0.2)
        self.assertIn((target, "changed"), events)
        # and a later in-place or renamed write is still seen
        n = len(events)
        tmp = target + ".x"
        with open(tmp, "w") as f:
            f.write("{ }")
        os.rename(tmp, target)
        end = time.monotonic() + 3
        with cv:
            while (target, "changed") not in events[n:] and time.monotonic() < end:
                cv.wait(0.2)
        self.assertIn((target, "changed"), events[n:])


if __name__ == "__main__":
    unittest.main()
