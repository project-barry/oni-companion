"""Fixes from the first v1.2 live test (2026-10-25):
- theme.json with the mod's v1.2 `icons` list is a game theme (it fell back to the built-in theme);
- the sync's DLC set is the active DLC content from the art manifest, not the save's DLC from live.json
  (a base-game save asked for a sync after every finished sync);
- the dev mirror's batch copier turns inotifywait lines into tar names."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "devtools"))

from oni_companion import theme  # noqa: E402
from oni_companion.sync import SyncService  # noqa: E402

FIX = os.path.join(ROOT, "fixtures", "synthetic", "companion")
DLC = ["COSMETIC1_ID", "DLC2_ID", "DLC3_ID"]


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ThemeIcons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        src = os.path.join(FIX, "theme")
        shutil.copytree(src, os.path.join(self.tmp, "theme"))
        self.build = os.listdir(os.path.join(self.tmp, "theme"))[0]
        self.dir = os.path.join(self.tmp, "theme", self.build)
        shutil.copy(os.path.join(self.dir, "button.png"), os.path.join(self.dir, "speedPause.png"))
        p = os.path.join(self.dir, "theme.json")
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        doc["icons"] = [{"name": "speedPause", "file": "speedPause.png", "width": 42, "height": 48},
                        {"name": "alertBad", "file": "missing.png", "width": 8, "height": 8}]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_icons_keep_the_game_theme(self):
        r = theme.load(self.tmp)
        self.assertEqual(r.reply["source"], "game", r.notes)
        self.assertEqual(r.reply["icons"], [{"name": "speedPause", "art": "/api/v1/art/ui/speedPause", "width": 42, "height": 48}])
        self.assertEqual(r.image_path("speedPause"), os.path.join(self.dir, "speedPause.png"))
        self.assertTrue(any("alertBad" in n for n in r.notes), r.notes)    # a bad icon is dropped, not the theme


class SyncDlcSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for d in ("live", "art", "sync"):
            os.makedirs(os.path.join(self.tmp, d))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rel, doc):
        with open(os.path.join(self.tmp, rel), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def test_base_game_save_after_a_finished_sync_needs_nothing(self):
        self.write("live/live.json", {"schema": 2, "seq": 1, "state": "running", "writtenAt": now_iso(), "modVersion": "0.3.1",
                                      "build": 744825, "dlcIds": [], "paused": True})
        self.write("art/manifest.json", {"schema": 1, "modVersion": "0.3.1", "build": 744825, "dlcIds": DLC, "files": []})
        self.write("sync/status.json", {"schema": 1, "state": "done", "scope": "missing", "build": 744825, "dlcIds": DLC,
                                        "done": 10, "total": 10})
        s = SyncService(self.tmp, None, lambda *a: None)
        try:
            st = s.status()
            self.assertFalse(st["needed"], st)
            self.assertTrue(st["canStart"], st)
        finally:
            s.close()

    def test_new_dlc_still_detected(self):
        self.write("live/live.json", {"schema": 2, "seq": 1, "state": "running", "writtenAt": now_iso(), "modVersion": "0.3.1",
                                      "build": 744825, "dlcIds": [], "paused": False})
        self.write("art/manifest.json", {"schema": 1, "modVersion": "0.3.1", "build": 744825, "dlcIds": DLC + ["DLC4_ID"], "files": []})
        self.write("sync/status.json", {"schema": 1, "state": "done", "scope": "missing", "build": 744825, "dlcIds": DLC,
                                        "done": 10, "total": 10})
        s = SyncService(self.tmp, None, lambda *a: None)
        try:
            self.assertEqual(s.status().get("neededReason"), "new_dlc")
        finally:
            s.close()


class MirrorBatch(unittest.TestCase):
    def test_relpath(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mirror_batch", os.path.join(ROOT, "devtools", "mirror-batch.py"))
        mb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mb)
        u = "/home/x/OxygenNotIncluded"
        self.assertEqual(mb.relpath(u, "CLOSE_WRITE,CLOSE|/home/x/OxygenNotIncluded/companion/live/live.json"), "companion/live/live.json")
        self.assertEqual(mb.relpath(u, "CREATE,ISDIR|/home/x/OxygenNotIncluded/companion/fonts/744825"), "companion/fonts/744825")
        self.assertIsNone(mb.relpath(u, "CREATE|/home/x/OxygenNotIncluded/companion/live/live.json"))
        self.assertIsNone(mb.relpath(u, "MOVED_TO|/home/x/OxygenNotIncluded/companion/live/live.json.tmp"))
        self.assertIsNone(mb.relpath(u, "MOVED_TO|/elsewhere/live.json"))

    def test_batch_copy_with_a_local_ssh_stand_in(self):
        src, dest, bin_ = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(src, "companion", "fonts", "1"))
            for rel in ("companion/a.json", "companion/fonts/1/g.png"):
                with open(os.path.join(src, rel), "w") as f:
                    f.write(rel)
            fake = os.path.join(bin_, "ssh")
            with open(fake, "w") as f:      # drop the ssh options and host, run the remote command here (GNU tar flags need gtar or GNU tar)
                f.write('#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\nexec sh -c "$1"\n')
            os.chmod(fake, 0o755)
            if subprocess.run(["tar", "--version"], capture_output=True, text=True).stdout.find("GNU") < 0:
                self.skipTest("local tar is not GNU tar (--ignore-failed-read)")
            lines = "CLOSE_WRITE,CLOSE|%s/companion/a.json\nCREATE,ISDIR|%s/companion/fonts/1\nMOVED_TO|%s/companion/gone.json\n" % (src, src, src)
            subprocess.run([sys.executable, os.path.join(ROOT, "devtools", "mirror-batch.py"), src, dest], input=lines.encode(),
                           env=dict(os.environ, SSH_CMD=fake), check=True, timeout=20)
            self.assertTrue(os.path.isfile(os.path.join(dest, "companion", "fonts", "1", "g.png")))
        finally:
            for d in (src, dest, bin_):
                shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
