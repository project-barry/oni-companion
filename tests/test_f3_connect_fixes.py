"""F3: low findings of the v1.4 reviews: file modes, per-source code failures, plain HTTP off with the switch,
bounded request seq, standalone token file, two games at once."""
import json
import os
import stat
import sys
import tempfile
import shutil
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import lifetime, __main__ as main_mod  # noqa: E402
from oni_companion.server.errors import ApiError  # noqa: E402
from tests.test_k1_connect import Env, TestRequestFiles, utc_now, wait_for  # noqa: E402
from tests.test_k2_lifetime import fake_proc  # noqa: E402


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class TestStateFileModes(Env):
    def test_state_file_and_folders_are_owner_only(self):
        self.on()
        pd = os.path.join(self.svc.user, "companion", "pairing")
        sf = os.path.join(pd, "state.json")
        wait_for(lambda: os.path.exists(sf))
        self.assertEqual(mode(sf), 0o600)
        self.assertEqual(mode(pd), 0o700)
        self.assertEqual(mode(os.path.join(pd, "requests")), 0o700)
        self.assertIn(self.svc.connect.state()["code"]["display"].replace("-", ""),
                      open(sf).read().replace("-", ""))      # the mod (same user) can still read it


class TestPerSourceCode(Env):
    def test_pest_is_blocked_code_stays_and_others_pair(self):
        self.on()
        cm = self.svc.connect
        code = cm._code["code"]
        for _ in range(5):
            with self.assertRaises(ApiError) as e:
                cm.claim("10.0.0.9", "tls", "AAAAAAAA", "pest", "android")
            self.assertEqual(e.exception.code, "bad_code")
        self.assertEqual(cm._code["code"], code)
        with self.assertRaises(ApiError) as e:
            cm.claim("10.0.0.9", "tls", code, "pest", "android")        # right code, blocked source
        self.assertEqual(e.exception.code, "rate_limited")
        rep = cm.claim("10.0.0.5", "tls", code, "me", "android")        # another source pairs fine
        self.assertIn("deviceToken", rep)
        self.assertNotEqual(cm._code["code"], code)                     # a good claim burns the code
        # the pest's block ended with the old code
        with self.assertRaises(ApiError) as e:
            cm.claim("10.0.0.9", "tls", "AAAAAAAA", "pest", "android")
        self.assertEqual(e.exception.code, "bad_code")


class TestSwitchOff(Env):
    def test_switch_off_clears_plain_http(self):
        self.on(plain=True)
        cm = self.svc.connect
        self.assertTrue(cm.plain_http and cm.plain_port)
        self.lb("/connect/switch", "POST", {"enabled": False})
        self.assertFalse(cm.plain_http)
        st = self.on()
        self.assertFalse(st["plainHttp"])
        self.assertIsNone(st["plainHttpPort"])
        cfg = json.load(open(os.path.join(self.tmp, "a", "data", "connect", "config.json")))
        self.assertFalse(cfg["plainHttp"])


class TestSeqBound(TestRequestFiles):
    def test_huge_seq_does_not_lock_out_later_requests(self):
        p = self.req(5000000, type="set_enabled", enabled=True)
        r = self.done(5000000, p)
        self.assertEqual(r["state"], "failed")
        self.assertFalse(self.svc.connect.listening)
        p = self.req(1, type="set_enabled", enabled=True)
        self.assertEqual(self.done(1, p)["state"], "done")
        # a replayed old file still does not run
        p = self.req(1, type="set_enabled", enabled=False)
        wait_for(lambda: not os.path.exists(p))
        self.assertTrue(self.svc.connect.listening)


class TestStandaloneToken(unittest.TestCase):
    def test_token_goes_to_a_0600_file_not_stderr(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)

        class Svc:
            token = "secret-token-xyz"
            port = 4321

        class Cfg:
            data_dir = d
            host = "127.0.0.1"
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            main_mod._announce(Cfg, Svc)
        p = main_mod.token_path(Cfg)
        self.assertEqual(open(p).read(), "secret-token-xyz")
        self.assertEqual(mode(p), 0o600)
        self.assertNotIn("secret-token-xyz", err.getvalue())
        main_mod._remove_token_file(Cfg)
        self.assertFalse(os.path.exists(p))


class TestTwoGames(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc, True)
        fake_proc(self.proc, 10, ["FEXInterpreter", "/g/OxygenNotIncluded/OxygenNotIncluded"])
        wine = ["Z:\\g\\OxygenNotIncluded.exe"]
        fake_proc(self.proc, 31, ["reaper", "SteamLaunch", "AppId=457140", "--", "proton"])
        fake_proc(self.proc, 33, wine, ppid=31)
        with open(os.path.join(self.proc, "33", "environ"), "wb") as f:
            f.write(b"A=b\0STEAM_COMPAT_DATA_PATH=/mnt/sd/steamapps/compatdata/457140\0")
        self.prefix_user = "/mnt/sd/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/AppData/LocalLow/Klei/Oxygen Not Included"
        self.linux_user = "/home/u/.config/unity3d/Klei/Oxygen Not Included"

    def test_default_is_native_first(self):
        self.assertEqual(lifetime.find_game(self.proc, own_pid=999).kind, "native")
        self.assertEqual(len(lifetime.find_games(self.proc, own_pid=999)), 2)

    def test_active_folder_picks_the_game(self):
        g = lifetime.find_game(self.proc, own_pid=999, user_dir=self.prefix_user)
        self.assertEqual((g.pid, g.kind), (33, "proton"))
        g = lifetime.find_game(self.proc, own_pid=999, user_dir=lambda: self.linux_user)
        self.assertEqual((g.pid, g.kind), (10, "native"))

    def test_other_prefix_falls_back_to_first(self):
        other = "/x/compatdata/457140/pfx/drive_c/users/steamuser/AppData/LocalLow/Klei/Oxygen Not Included"
        self.assertEqual(lifetime.find_game(self.proc, own_pid=999, user_dir=other).pid, 10)

    def test_run_standalone_follows_the_active_game(self):
        seen = []
        orig = lifetime.wait_exit
        lifetime.wait_exit = lambda pid, stopper=None: (seen.append(pid), "exited")[1]
        self.addCleanup(setattr, lifetime, "wait_exit", orig)
        class Svc:
            def stop(self): pass
        lifetime.run_standalone(Svc, proc=self.proc, install_signals=False, user_dir=self.prefix_user)
        self.assertEqual(seen, [33])


if __name__ == "__main__":
    unittest.main()
