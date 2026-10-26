"""K2: service lifetime = the game's lifetime (plan 5.1), and the install scripts.

Fake-/proc tests run everywhere. Real-process tests (a child `sleep` named like the game, killed with
SIGKILL for the crash case) need Linux (os.pidfd_open) and are skipped elsewhere.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import lifetime  # noqa: E402

LINUX = sys.platform.startswith("linux") and hasattr(os, "pidfd_open")


def fake_proc(root, pid, args, ppid=1):
    d = os.path.join(root, str(pid))
    os.makedirs(d)
    with open(os.path.join(d, "cmdline"), "wb") as f:
        f.write(b"\0".join(a.encode() for a in args) + b"\0")
    with open(os.path.join(d, "stat"), "w") as f:
        f.write("%d (name with ) paren) S %d 1 1 0 -1 0\n" % (pid, ppid))


class FindGameFake(unittest.TestCase):
    def setUp(self):
        self.proc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proc, True)

    def test_nothing(self):
        fake_proc(self.proc, 10, ["bash"])
        fake_proc(self.proc, 11, ["inotifywait", "-m", "/home/u/.config/unity3d/Klei/Oxygen Not Included/saves"])
        fake_proc(self.proc, 12, ["python3", "-m", "oni_companion", "--mode", "standalone"])
        self.assertIsNone(lifetime.find_game(self.proc, own_pid=999))

    def test_native_under_fex(self):
        fake_proc(self.proc, 10, ["FEXInterpreter", "/home/u/.local/share/Steam/steamapps/common/OxygenNotIncluded/OxygenNotIncluded"])
        g = lifetime.find_game(self.proc, own_pid=999)
        self.assertEqual((g.pid, g.kind), (10, "native"))

    def test_native_direct(self):
        fake_proc(self.proc, 20, ["/games/OxygenNotIncluded/OxygenNotIncluded", "-logFile"])
        self.assertEqual(lifetime.find_game(self.proc, own_pid=999).pid, 20)

    def test_proton_needs_the_reaper(self):
        wine = ["Z:\\home\\u\\steamapps\\common\\OxygenNotIncluded\\OxygenNotIncluded.exe"]
        fake_proc(self.proc, 30, wine, ppid=1)          # no reaper above it: not ours
        self.assertIsNone(lifetime.find_game(self.proc, own_pid=999))
        fake_proc(self.proc, 31, ["reaper", "SteamLaunch", "AppId=457140", "--", "proton", "waitforexitandrun"])
        fake_proc(self.proc, 32, ["wineserver"], ppid=31)
        fake_proc(self.proc, 33, wine, ppid=32)         # grandchild of the reaper
        g = lifetime.find_game(self.proc, own_pid=999)
        self.assertEqual((g.pid, g.kind), (33, "proton"))

    def test_other_games_reaper_does_not_count(self):
        fake_proc(self.proc, 31, ["reaper", "SteamLaunch", "AppId=1234", "--"])
        fake_proc(self.proc, 33, ["OxygenNotIncluded.exe"], ppid=31)
        self.assertIsNone(lifetime.find_game(self.proc, own_pid=999))

    def test_pid_reuse_guard(self):
        fake_proc(self.proc, 40, ["OxygenNotIncluded"])
        g = lifetime.find_game(self.proc, own_pid=999)
        self.assertTrue(lifetime.still_game(self.proc, g))
        shutil.rmtree(os.path.join(self.proc, "40"))
        fake_proc(self.proc, 40, ["something-else"])
        self.assertFalse(lifetime.still_game(self.proc, g))


class NoGame(unittest.TestCase):
    def test_exits_at_once_and_builds_nothing(self):
        built = []
        rc = lifetime.run_standalone(lambda: built.append(1), find=lambda proc: None, install_signals=False)
        self.assertEqual(rc, 0)
        self.assertEqual(built, [])


@unittest.skipUnless(LINUX, "needs Linux pidfd_open")
class RealProcess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = os.path.join(self.tmp, "OxygenNotIncluded")      # a copy of sleep, named like the game
        shutil.copy(shutil.which("sleep"), self.exe)
        self.kids = []
        self.addCleanup(self._reap)

    def _reap(self):
        for p in self.kids:
            if p.poll() is None:
                p.kill()
            p.wait()

    def game(self, seconds="60"):
        p = subprocess.Popen([self.exe, seconds])
        self.kids.append(p)
        return p

    def test_find_real(self):
        p = self.game()
        g = lifetime.find_game()
        self.assertEqual((g.pid, g.kind), (p.pid, "native"))

    def test_find_none_after_exit(self):
        p = self.game()
        p.kill()
        p.wait()
        self.assertIsNone(lifetime.find_game())

    def test_wait_ends_on_normal_exit(self):
        p = self.game("0.3")
        t0 = time.monotonic()
        self.assertEqual(lifetime.wait_exit(p.pid), "exited")
        self.assertLess(time.monotonic() - t0, 3)

    def test_wait_ends_on_kill9(self):
        p = self.game()
        threading.Timer(0.3, lambda: p.send_signal(signal.SIGKILL)).start()
        t0 = time.monotonic()
        self.assertEqual(lifetime.wait_exit(p.pid), "exited")
        self.assertLess(time.monotonic() - t0, 3)

    def test_wait_on_dead_pid(self):
        p = self.game("0")
        p.wait()
        self.assertEqual(lifetime.wait_exit(p.pid), "exited")

    def test_stopper_wakes_the_wait(self):
        p = self.game()
        st = lifetime.Stopper()
        self.addCleanup(st.close)
        threading.Timer(0.2, st.set).start()
        self.assertEqual(lifetime.wait_exit(p.pid, st), "stopped")

    def test_gate_up_and_down_on_crash(self):
        events = []
        up, down = threading.Event(), threading.Event()
        gate = lifetime.GameGate([lambda: (events.append("up"), up.set())], [lambda: (events.append("down"), down.set())])
        self.addCleanup(gate.close)
        gate.poke(force=True)
        self.assertFalse(up.is_set())                  # no game yet
        p = self.game()
        gate.poke(force=True)
        self.assertTrue(up.wait(2))
        self.assertTrue(gate.game_running)
        p.send_signal(signal.SIGKILL)
        self.assertTrue(down.wait(3))
        self.assertEqual(events, ["up", "down"])
        self.assertFalse(gate.game_running)
        p2 = self.game()                               # second launch is followed again
        up.clear()
        gate.poke(force=True)
        self.assertTrue(up.wait(2))

    def test_poke_is_throttled(self):
        looks = []
        gate = lifetime.GameGate(find=lambda proc: looks.append(1))
        self.addCleanup(gate.close)
        for _ in range(50):
            gate.poke()
        self.assertEqual(len(looks), 1)

    def test_run_standalone_stops_service_when_game_is_killed(self):
        p = self.game()
        calls = []

        class Svc:
            on_game_down = [lambda: calls.append("down")]

            def stop(self):
                calls.append("stop")
        threading.Timer(0.3, lambda: p.send_signal(signal.SIGKILL)).start()
        rc = lifetime.run_standalone(lambda: (calls.append("start"), Svc())[1], install_signals=False)
        self.assertEqual((rc, calls), (0, ["start", "down", "stop"]))

    def _run_module(self, extra_env=None):
        env = dict(os.environ, ONI_USER_DIR=self.tmp, ONI_DATA_DIR=self.tmp, PYTHONPATH=os.path.join(ROOT, "core"))
        env.update(extra_env or {})
        return subprocess.Popen([sys.executable, "-m", "oni_companion", "--mode", "standalone", "--user-dir", self.tmp],
                                env=env, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    def test_module_without_game_exits_at_once(self):
        t0 = time.monotonic()
        m = self._run_module()
        self.assertEqual(m.wait(10), 0)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertIn(b"no game process", m.stderr.read())

    def test_module_follows_the_game_and_exits_on_crash(self):
        p = self.game()
        m = self._run_module()
        line = m.stderr.readline()
        while b"token" not in line and m.poll() is None:
            line = m.stderr.readline()
        self.assertIn(b"token", line)                   # it is serving
        self.assertIsNone(m.poll())
        p.send_signal(signal.SIGKILL)
        self.assertEqual(m.wait(10), 0)

    def test_module_exits_on_sigterm(self):
        self.game()
        m = self._run_module()
        line = m.stderr.readline()
        while b"token" not in line and m.poll() is None:
            line = m.stderr.readline()
        m.send_signal(signal.SIGTERM)
        self.assertEqual(m.wait(10), 0)


class InstallScripts(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.native = os.path.join(self.home, ".config/unity3d/Klei/Oxygen Not Included")
        os.makedirs(self.native)
        self.env = dict(os.environ, HOME=self.home, XDG_DATA_HOME="", XDG_CONFIG_HOME="")
        for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME"):
            self.env.pop(k)

    def run_sh(self, name, *args):
        return subprocess.run(["sh", os.path.join(ROOT, "core", "install", name)] + list(args),
                              env=self.env, capture_output=True, text=True)

    @unittest.skipUnless(LINUX, "install needs Linux")
    def test_install_and_uninstall(self):
        r = self.run_sh("install.sh", "--no-enable")
        self.assertEqual(r.returncode, 0, r.stderr)
        units = os.path.join(self.home, ".config/systemd/user")
        path = open(os.path.join(units, "oni-companion.path")).read()
        self.assertIn("PathModified=%s/companion/live" % self.native, path)
        self.assertNotIn("compatdata", path)           # no Proton prefix here
        svc = open(os.path.join(units, "oni-companion.service")).read()
        self.assertIn("--mode standalone", svc)
        core = os.path.join(self.home, ".local/share/oni-companion/core")
        self.assertTrue(os.path.isfile(os.path.join(core, "oni_companion/lifetime.py")))
        # the installed copy starts: no game -> exits at once
        out = subprocess.run([sys.executable, "-m", "oni_companion", "--mode", "standalone"],
                             env=dict(self.env, PYTHONPATH=core, ONI_USER_DIR=self.native), capture_output=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.run_sh("uninstall.sh", "--no-systemctl").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(units, "oni-companion.path")))
        self.assertFalse(os.path.exists(core))
        self.assertTrue(os.path.isdir(self.native))    # the game's folder stays

    @unittest.skipUnless(LINUX, "install needs Linux")
    def test_both_folders_and_never_root(self):
        proton = os.path.join(self.home, ".local/share/Steam/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded")
        os.makedirs(proton)
        self.assertEqual(self.run_sh("install.sh", "--no-enable").returncode, 0)
        path = open(os.path.join(self.home, ".config/systemd/user/oni-companion.path")).read()
        self.assertEqual(path.count("PathModified="), 2)
        self.assertNotIn("sudo", open(os.path.join(ROOT, "core/install/install.sh")).read().replace("never uses sudo", "").replace("Never uses sudo", ""))

    @unittest.skipUnless(LINUX, "install needs Linux")
    def test_no_game_folder_is_an_error(self):
        shutil.rmtree(self.native)
        r = self.run_sh("install.sh", "--no-enable")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Start the game once", r.stderr)


if __name__ == "__main__":
    unittest.main()
