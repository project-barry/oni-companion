"""v1.4 follow-up fixes: toggle-off is not a crash, a running game of another folder beats a stale 'running' live.json,
and the folder list for mod install is not a startup snapshot."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import cause, modstate  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from tests.test_c3_server import TOKEN  # noqa: E402
from tests.test_f1_follow import TwoFolders, PROTON_REL, wait_for  # noqa: E402


class TestToggleOffIsNotCrash(TwoFolders):
    def explain(self):
        return cause.Explainer(lambda: self.linux, lambda: True).explain("none", [])

    def test_empty_list_without_log_is_mod_off(self):
        self.mods_json(self.linux, [])
        self.assertEqual(cause.mod_flag(self.linux), "off")
        self.assertEqual(self.explain()["cause"], "mod_off")

    def test_empty_list_with_logged_error_is_crash_and_survives_restart(self):
        self.mods_json(self.linux, [])
        log_dir = os.path.join(self.home, ".config", "unity3d", "Klei", "Oxygen Not Included")
        os.makedirs(log_dir, exist_ok=True)
        log = os.path.join(log_dir, "Player.log")
        with open(log, "w") as f:
            f.write("ERROR at OniCompanionLink.Foo exception\n")
        old = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        try:
            self.assertEqual(cause.mod_flag(self.linux), "crashed")
            with open(log, "w") as f:                       # the game restarted and rewrote the log
                f.write("clean start\n")
            self.assertEqual(cause.mod_flag(self.linux), "crashed")
            self.mods_json(self.linux, [""])                # the user turned it on again
            self.assertEqual(cause.mod_flag(self.linux), "on")
            self.mods_json(self.linux, [])
            self.assertEqual(cause.mod_flag(self.linux), "off")
        finally:
            if old is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old


class TestRunningLiveVsProcess(TwoFolders):
    def test_stale_running_linux_loses_to_proton_process(self):
        self.live(self.linux, "running", age=60, paused=True)
        self.live(self.proton, "menu", age=5)
        self.game = self.proton_game()
        f = self.follower()
        self.assertEqual(f.evaluate(True), self.proton)
        self.assertEqual(f.why, "process")

    def test_fresh_running_linux_no_proton_file(self):
        self.live(self.linux, "running", age=10)
        self.game = self.proton_game()
        f = self.follower()
        self.assertEqual(f.evaluate(True), self.proton)

    def test_running_live_still_wins_when_its_game_runs(self):
        self.live(self.linux, "running", age=3)
        self.game = self.native_game()
        f = self.follower()
        self.assertEqual(f.evaluate(True), self.linux)
        self.assertEqual(f.why, "live")


class TestFolderListRefreshes(TwoFolders):
    def test_prefix_created_after_start_gets_the_mod(self):
        import shutil
        shutil.rmtree(self.proton)
        cfg = ServiceConfig(user_dir=None, token=TOKEN, views_factory=lambda ctx: StubViews(ctx), follow=True, shared=True,
                            data_dir=os.path.join(self.tmp, "data"), follow_env=self.env, auto_saves=True,
                            connect_opts={"autostart": False}, user_dirs=[self.linux])
        self.svc = Service(cfg).start()
        self.assertEqual(self.svc.all_user_dirs(), [self.linux])
        os.makedirs(os.path.join(self.proton, "companion"))
        self.assertEqual(self.svc.all_user_dirs(), [self.linux, self.proton])
        self.assertEqual(self.svc.cfg.user_dirs, [self.linux, self.proton])


if __name__ == "__main__":
    unittest.main()
