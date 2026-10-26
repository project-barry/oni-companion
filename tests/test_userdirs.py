"""User folder detection: Linux build folder and Proton prefix (synthetic temp trees)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from oni_companion import config, sources  # noqa: E402

LINUX = ".config/unity3d/Klei/Oxygen Not Included"
PROTON = ".local/share/Steam/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded"


def touch(path, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{}")
    os.utime(path, (mtime, mtime))


class UserDirs(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._t.name)
        self.env = {"HOME": self.home}
        os.makedirs(os.path.join(self.home, ".local/share/Steam/steamapps"))

    def tearDown(self):
        self._t.cleanup()

    def d(self, rel):
        return os.path.join(self.home, rel)

    def test_none(self):
        self.assertIsNone(sources.default_user_dir(self.env))

    def test_linux_only(self):
        touch(self.d(LINUX + "/cloud_save_files/1/Col/Col.sav"), 1000)
        self.assertEqual(sources.default_user_dir(self.env), self.d(LINUX))
        self.assertEqual(sources.user_dir_kind(self.d(LINUX)), "linux")

    def test_proton_only(self):
        touch(self.d(PROTON + "/companion/live/live.json"), 1000)
        self.assertEqual(sources.default_user_dir(self.env), self.d(PROTON))
        self.assertEqual(sources.user_dir_kind(self.d(PROTON)), "proton")

    def test_newest_activity_wins(self):
        touch(self.d(LINUX + "/cloud_save_files/1/Col/Col.sav"), 5000)
        touch(self.d(PROTON + "/companion/live/live.json"), 1000)
        self.assertEqual(sources.default_user_dir(self.env), self.d(LINUX))
        touch(self.d(PROTON + "/cloud_save_files/1/Col/auto_save/a.sav"), 9000)
        self.assertEqual(sources.default_user_dir(self.env), self.d(PROTON))

    def test_export_counts_as_activity(self):
        touch(self.d(LINUX + "/cloud_save_files/1/Col/Col.sav"), 1000)
        touch(self.d(PROTON + "/companion/export/gamedata-1-base.json"), 2000)
        self.assertEqual(sources.default_user_dir(self.env), self.d(PROTON))

    def test_tie_prefers_proton(self):
        os.makedirs(self.d(LINUX))
        os.makedirs(self.d(PROTON))
        self.assertEqual(sources.default_user_dir(self.env), self.d(PROTON))

    def test_other_steam_library(self):
        lib = os.path.join(self.home, "sdcard")
        sa = os.path.join(lib, "steamapps")
        os.makedirs(sa)
        with open(self.d(".local/share/Steam/steamapps/libraryfolders.vdf"), "w") as f:
            f.write('"libraryfolders" { "0" { "path" "%s" } }' % lib)
        u = os.path.join(sa, "compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded")
        touch(os.path.join(u, "companion/live/live.json"), 1000)
        self.assertEqual(sources.default_user_dir(self.env), u)

    def test_config_reports_kind_and_env_wins(self):
        touch(self.d(PROTON + "/companion/live/live.json"), 1000)
        cfg = config.load(env=self.env, data_dir=self.d("data"))
        self.assertEqual(cfg.user_dir, self.d(PROTON))
        self.assertEqual(cfg.user_dir_kind, "proton")
        cfg = config.load(env=dict(self.env, ONI_USER_DIR=self.d(LINUX)), data_dir=self.d("data"))
        self.assertEqual(cfg.user_dir_kind, "linux")


if __name__ == "__main__":
    unittest.main()
