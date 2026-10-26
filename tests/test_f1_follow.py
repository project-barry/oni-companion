"""F1 (plan 4.3): one device, two ONI user folders (Linux build and Windows build under Proton, the latter on an SD card).
The service follows the running game, keeps one art/font/theme copy per build + DLC set, and names the real cause when the
mod is off. Synthetic folders only; no device, no game files. The game process is a fake (and a fake /proc tree)."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion import cause, lifetime, sources  # noqa: E402
from oni_companion.follow import Follower  # noqa: E402
from oni_companion.server.service import Service, ServiceConfig  # noqa: E402
from oni_companion.server.stub_views import StubViews  # noqa: E402
from oni_companion.shared import SharedStore  # noqa: E402
from tests.test_c3_server import TOKEN, atomic_write, http  # noqa: E402

BUILD, DLC = 100001, ["DLC_ALPHA_ID"]
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic image bytes"
LINUX_REL = ".config/unity3d/Klei/Oxygen Not Included"
PROTON_REL = "steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded"


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def wait_for(fn, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


class TwoFolders(unittest.TestCase):
    """HOME with the Linux folder, and an SD-card Steam library (named in libraryfolders.vdf) with the Proton folder."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="oni-f1-"))
        self.home = os.path.join(self.tmp, "home")
        self.sd = os.path.join(self.tmp, "sd")
        self.linux = os.path.join(self.home, LINUX_REL)
        self.proton = os.path.join(self.sd, PROTON_REL)
        steamapps = os.path.join(self.home, ".local/share/Steam/steamapps")
        os.makedirs(steamapps)
        os.makedirs(os.path.join(self.sd, "steamapps"))
        with open(os.path.join(steamapps, "libraryfolders.vdf"), "w") as f:
            f.write('"libraryfolders"\n{\n "0"\n {\n  "path"  "%s"\n }\n "1"\n {\n  "path"  "%s"\n }\n}\n'
                    % (os.path.join(self.home, ".local/share/Steam"), self.sd))
        for d in (self.linux, self.proton):
            os.makedirs(os.path.join(d, "companion", "live"))
        self.env = {"HOME": self.home}
        self.svc = None
        self.game = None                      # what the fake process finder returns

    def tearDown(self):
        if self.svc:
            self.svc.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers
    def live(self, folder, state="running", age=0, paused=False, build=BUILD, dlc=DLC):
        doc = {"schema": 1, "modVersion": "0.5.0", "state": state, "paused": paused, "build": build, "dlcIds": dlc,
               "cycle": 5, "writtenAt": iso(time.time() - age), "worlds": []}
        atomic_write(os.path.join(folder, "companion", "live", "live.json"), json.dumps(doc))

    def mods_json(self, folder, enabled_for):
        entry = {"label": {"id": "OniCompanionLink", "distribution_platform": 0}, "staticID": "OniCompanionLink",
                 "enabledForDlc": enabled_for}
        os.makedirs(os.path.join(folder, "mods"), exist_ok=True)
        atomic_write(os.path.join(folder, "mods", "mods.json"), json.dumps({"version": 1, "mods": [entry]}))

    def crash_log(self, folder):
        """Player.log of the Windows (Proton) build with a game-logged error that names the mod (the evidence of a crash)."""
        up = os.path.dirname(os.path.dirname(os.path.dirname(folder)))
        d = os.path.join(up, "AppData", "LocalLow", "Klei", "Oxygen Not Included")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "Player.log"), "w") as f:
            f.write("ERROR in OniCompanionLink: exception\n")

    def proton_game(self):
        return lifetime.GameProcess(10, "proton", ["x"], prefix=os.path.join(self.sd, "steamapps/compatdata/457140"))

    def native_game(self):
        return lifetime.GameProcess(11, "native", ["x"])

    def follower(self, **kw):
        kw.setdefault("env", self.env)
        kw.setdefault("find", lambda proc: self.game)
        return Follower(**kw)

    def art(self, folder, build=BUILD, dlc=DLC, names=("Gas",), render_rev=1):
        art = os.path.join(folder, "companion", "art")
        files = []
        for n in names:
            p = os.path.join(art, str(build), "building", n + ".png")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(PNG)
            files.append({"kind": "building", "id": n, "path": "%d/building/%s.png" % (build, n), "size": len(PNG),
                          "sha256": "ab" * 32})
        doc = {"schema": 1, "modVersion": "0.5.0", "build": build, "dlcIds": dlc, "writtenAt": iso(time.time()),
               "files": files, "onDemand": True, "renderRev": render_rev}
        atomic_write(os.path.join(art, "manifest.json"), json.dumps(doc))

    def sync_done(self, folder, build=BUILD, dlc=DLC):
        doc = {"schema": 1, "modVersion": "0.5.0", "state": "done", "scope": "full", "build": build, "dlcIds": dlc,
               "done": 3, "total": 3, "current": None, "errors": 0, "startedAt": iso(time.time() - 5),
               "updatedAt": iso(time.time()), "elapsedMs": 5000}
        atomic_write(os.path.join(folder, "companion", "sync", "status.json"), json.dumps(doc))

    def start(self, **kw):
        kw.setdefault("find", lambda proc: self.game)
        cfg = ServiceConfig(user_dir=None, token=TOKEN, views_factory=lambda ctx: StubViews(ctx), follow=True,
                            shared=True, data_dir=os.path.join(self.tmp, "data"), follow_env=self.env,
                            auto_saves=True, connect_opts={"autostart": False}, **kw)
        self.svc = Service(cfg).start()
        return self.svc

    def get(self, path):
        return http(self.svc, path)

    def raw(self, path):
        import urllib.error
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.svc.port, path), headers={"X-Oni-Token": TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            e.read()
            e.close()
            return e.code, b""


class TestDiscovery(TwoFolders):
    def test_both_folders_found_sd_card_included(self):
        self.assertEqual(sources.user_dir_paths(self.env), [self.proton, self.linux])

    def test_prefix_to_user_dir(self):
        compat = os.path.join(self.sd, "steamapps/compatdata/457140")
        self.assertEqual(sources.proton_user_dir_in_prefix(compat), self.proton)
        self.assertEqual(sources.proton_user_dir_in_prefix(compat + "/pfx"), self.proton)
        self.assertIsNone(sources.proton_user_dir_in_prefix(os.path.join(self.tmp, "nothing")))


class TestProcessPrefix(unittest.TestCase):
    """The Proton prefix comes from the game process itself (fake /proc)."""

    def setUp(self):
        self.proc = tempfile.mkdtemp(prefix="oni-f1-proc-")

    def tearDown(self):
        shutil.rmtree(self.proc, ignore_errors=True)

    def add(self, pid, ppid, args, env=None):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d)
        with open(os.path.join(d, "cmdline"), "wb") as f:
            f.write(b"\0".join(a.encode() for a in args) + b"\0")
        with open(os.path.join(d, "stat"), "w") as f:
            f.write("%d (x) S %d 0 0\n" % (pid, ppid))
        with open(os.path.join(d, "environ"), "wb") as f:
            f.write(b"\0".join(("%s=%s" % kv).encode() for kv in (env or {}).items()) + b"\0")

    def game(self, env):
        self.add(100, 1, ["/x/reaper", "SteamLaunch", "AppId=457140", "--", "proton"])
        self.add(200, 100, ["Z:\\run\\media\\sd\\steamapps\\common\\OxygenNotIncluded\\OxygenNotIncluded.exe"], env)
        return lifetime.find_game(self.proc, own_pid=1)

    def test_compat_data_path_wins(self):
        g = self.game({"STEAM_COMPAT_DATA_PATH": "/run/media/sd/steamapps/compatdata/457140", "WINEPREFIX": "/other/pfx"})
        self.assertEqual((g.kind, g.pid, g.prefix), ("proton", 200, "/run/media/sd/steamapps/compatdata/457140"))

    def test_wineprefix(self):
        g = self.game({"WINEPREFIX": "/run/media/sd/steamapps/compatdata/457140/pfx"})
        self.assertEqual(g.prefix, "/run/media/sd/steamapps/compatdata/457140")

    def test_from_the_exe_path(self):
        g = self.game({})
        self.assertEqual(g.prefix, "/run/media/sd/steamapps/compatdata/457140")

    def test_native_has_no_prefix(self):
        self.add(300, 1, ["/usr/bin/fex", "/g/OxygenNotIncluded"])
        g = lifetime.find_game(self.proc, own_pid=1)
        self.assertEqual((g.kind, g.prefix), ("native", None))


class TestChoice(TwoFolders):
    def test_fresh_running_live_wins_over_everything(self):
        self.live(self.linux, "running")
        self.live(self.proton, "menu")
        self.game = self.proton_game()              # the process says Proton: a leftover Linux file (crash, kill) loses
        f = self.follower()
        self.assertEqual(f.choose(), (self.proton, "process"))

    def test_newest_running_of_two(self):
        self.live(self.linux, "running", age=8)
        self.live(self.proton, "running", age=1)
        self.assertEqual(self.follower().choose(), (self.proton, "live"))

    def test_stale_running_is_not_live(self):
        self.live(self.linux, "running", age=100)
        self.live(self.proton, "stopped")
        self.game = self.proton_game()
        self.assertEqual(self.follower().choose(), (self.proton, "process"))

    def test_process_proton_and_native(self):
        self.live(self.linux, "stopped")
        self.live(self.proton, "stopped")
        self.game = self.proton_game()
        self.assertEqual(self.follower().choose(), (self.proton, "process"))
        self.game = self.native_game()
        self.assertEqual(self.follower().choose(), (self.linux, "process"))

    def test_proton_prefix_unknown_with_one_prefix(self):
        self.live(self.linux, "stopped")
        self.game = lifetime.GameProcess(10, "proton", ["x"], prefix=None)
        self.assertEqual(self.follower().choose(), (self.proton, "process"))

    def test_fresh_menu_then_activity(self):
        self.live(self.linux, "stopped", age=500)
        self.live(self.proton, "menu", age=20)
        self.assertEqual(self.follower().choose(), (self.proton, "menu"))
        self.live(self.proton, "menu", age=500)
        os.utime(os.path.join(self.linux, "companion/live/live.json"), (time.time() + 50, time.time() + 50))
        self.assertEqual(self.follower().choose(), (self.linux, "activity"))

    def test_forced_folder_is_always_active(self):
        self.live(self.proton, "running")
        f = self.follower(forced=self.linux)
        self.assertEqual(f.evaluate(), self.linux)
        self.assertEqual(f.paths, [self.linux])

    def test_game_here(self):
        f = self.follower()
        f.active = self.linux
        self.assertFalse(f.game_here())
        self.game = self.proton_game()
        f.game(force=True)
        self.assertFalse(f.game_here(self.linux))
        self.assertTrue(f.game_here(self.proton))
        self.assertIsNone(self.follower(find=None).game_here())

    def test_switch_calls_back_once_per_change(self):
        seen = []
        self.live(self.linux, "running")
        f = self.follower(on_change=lambda o, n, w: seen.append((o, n, w)))
        f.evaluate()
        f.evaluate()
        self.live(self.linux, "stopped")
        self.live(self.proton, "running")
        f.evaluate()
        self.assertEqual(seen, [(None, self.linux, "live"), (self.linux, self.proton, "live")])

    def test_expiry_timer_switches_when_the_data_goes_stale(self):
        self.live(self.linux, "running", age=cause.RUNNING_FRESH - 0.6)
        self.live(self.proton, "stopped")
        os.utime(os.path.join(self.proton, "companion/live/live.json"), (time.time() - 900, time.time() - 900))
        seen = []
        f = self.follower(on_change=lambda o, n, w: seen.append(n))
        f.evaluate()
        self.assertEqual(f.active, self.linux)
        self.game = self.proton_game()
        wait_for(lambda: f.active == self.proton, timeout=4)       # a crash writes nothing: the timer decides
        self.assertEqual(f.active, self.proton)
        f.close()


class TestCause(TwoFolders):
    def ex(self, folder, here):
        return cause.Explainer(lambda: folder, lambda: here)

    def test_menu_only_for_a_fresh_menu(self):
        e = self.ex(self.linux, True)
        self.assertEqual(e.explain(cause.live_kind("menu", time.time(), False, time.time()))["cause"], "menu")
        for kind in ("stopped", "stale", "none"):
            self.assertNotEqual(e.explain(kind)["cause"], "menu")
            self.assertNotIn("menu", e.explain(kind)["message"].lower().replace("mods menu", ""))

    def test_live_kind(self):
        now = 1000.0
        self.assertEqual(cause.live_kind("running", now - 5, False, now), "running")
        self.assertEqual(cause.live_kind("running", now - 50, False, now), "stale")
        self.assertEqual(cause.live_kind("running", now - 50, True, now), "running")
        self.assertEqual(cause.live_kind("menu", now - 100, False, now), "menu")
        self.assertEqual(cause.live_kind("menu", now - 400, False, now), "stale")
        self.assertEqual(cause.live_kind("stopped", now, False, now), "stopped")
        self.assertEqual(cause.live_kind(None, None, False, now), "none")

    def test_mod_off_in_the_running_game(self):
        self.mods_json(self.proton, ["EXPANSION1_ID"])           # on for Spaced Out only; the base game runs
        r = self.ex(self.proton, True).explain("none", [])
        self.assertEqual(r["cause"], "mod_off")
        self.assertEqual(r["message"], "ONI Companion Link is off in the running game: turn it on in the game's Mods menu.")

    def test_mod_crashed_when_mods_json_was_emptied(self):
        self.mods_json(self.proton, [])
        self.crash_log(self.proton)
        r = self.ex(self.proton, True).explain("stopped", [])
        self.assertEqual(r["cause"], "mod_crashed")
        self.assertIn("after a crash", r["message"])
        self.assertIn("Mods menu", r["message"])

    def test_two_folders_two_answers(self):
        self.mods_json(self.linux, [""])                          # on
        self.mods_json(self.proton, [])                           # emptied
        self.crash_log(self.proton)
        self.assertEqual(self.ex(self.linux, True).explain("none", [])["cause"], "no_mod")
        self.assertEqual(self.ex(self.proton, True).explain("none", [])["cause"], "mod_crashed")

    def test_game_not_running(self):
        self.mods_json(self.linux, [""])
        self.assertEqual(self.ex(self.linux, False).explain("stopped")["cause"], "not_running")

    def test_stale_with_the_mod_on(self):
        self.mods_json(self.linux, [""])
        self.assertEqual(self.ex(self.linux, None).explain("stale")["cause"], "stale")

    def test_not_installed(self):
        shutil.rmtree(os.path.join(self.linux, "companion"))
        r = self.ex(self.linux, True).explain("none")
        self.assertEqual(r["cause"], "no_mod")
        self.assertIn("not installed", r["message"])


class TestServiceCauses(TwoFolders):
    def test_sync_and_controls_say_mod_off_not_menu(self):
        self.live(self.proton, "stopped")
        self.mods_json(self.proton, ["EXPANSION1_ID"])
        self.game = self.proton_game()
        self.start()
        self.assertEqual(self.svc.cfg.user_dir, self.proton)
        for path in ("/api/v1/sync", "/api/v1/controls"):
            st, d = self.get(path)
            self.assertEqual(st, 200)
            self.assertEqual(d["cause"], "mod_off", path)
            self.assertIn("ONI Companion Link is off in the running game", d["message"])
            self.assertNotEqual(d.get("reason"), "menu")
        st, d = self.get("/api/v1/sync")
        self.assertEqual((d["canStart"], d["reason"]), (False, "no_mod"))

    def test_crash_text_after_the_game_emptied_mods_json(self):
        self.live(self.proton, "stopped")
        self.mods_json(self.proton, [])
        self.crash_log(self.proton)
        self.game = self.proton_game()
        self.start()
        _st, d = self.get("/api/v1/sync")
        self.assertEqual(d["cause"], "mod_crashed")
        _st, c = self.get("/api/v1/controls")
        self.assertEqual((c["cause"], c["game"]["label"]), ("mod_crashed", "ONI Companion Link is off"))
        st, body = http(self.svc, "/api/v1/actions/focus", method="POST",
                        body={"target": {"kind": "dupe", "id": "d1"}})
        self.assertEqual(st, 503)
        self.assertIn("after a crash", body["error"]["message"])

    def test_menu_is_said_only_for_a_fresh_menu(self):
        self.live(self.linux, "menu", age=2)
        self.mods_json(self.linux, [""])
        self.game = self.native_game()
        self.start()
        _st, d = self.get("/api/v1/sync")
        self.assertEqual((d["reason"], d["cause"]), ("menu", "menu"))
        self.live(self.linux, "stopped")
        _st, d = self.get("/api/v1/sync")
        self.assertEqual(d["reason"], "no_mod")
        self.assertNotEqual(d["cause"], "menu")
        _st, c = self.get("/api/v1/controls")
        self.assertNotEqual(c.get("cause"), "menu")

    def test_stale_live_is_not_the_menu(self):
        self.live(self.linux, "running", age=300)
        self.mods_json(self.linux, [""])
        self.game = self.native_game()
        self.start()
        _st, d = self.get("/api/v1/sync")
        self.assertEqual(d["reason"], "no_mod")
        self.assertEqual(d["cause"], "stale")


class TestSharedStore(TwoFolders):
    def test_art_from_either_folder_lands_in_one_copy(self):
        self.art(self.linux, names=("Gas",))
        self.art(self.proton, names=("Gas", "Pump"))
        sh = SharedStore(os.path.join(self.tmp, "shared"))
        self.assertTrue(sh.import_folder(self.linux)["art"])
        self.assertTrue(sh.import_folder(self.proton)["art"])
        self.assertFalse(sh.import_folder(self.proton)["art"])               # nothing new: nothing changed
        d = sh.art_dir(BUILD, DLC)
        with open(os.path.join(d, "manifest.json")) as f:
            ids = sorted(e["id"] for e in json.load(f)["files"])
        self.assertEqual(ids, ["Gas", "Pump"])
        self.assertTrue(os.path.isfile(os.path.join(d, str(BUILD), "building", "Pump.png")))

    def test_one_pack_per_build_and_dlc_set(self):
        self.art(self.linux, dlc=[])
        self.art(self.proton, dlc=DLC)
        sh = SharedStore(os.path.join(self.tmp, "shared"))
        sh.import_folder(self.linux)
        sh.import_folder(self.proton)
        self.assertNotEqual(sh.art_dir(BUILD, []), sh.art_dir(BUILD, DLC))
        self.assertTrue(os.path.isfile(os.path.join(sh.art_dir(BUILD, []), "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(sh.art_dir(BUILD, DLC), "manifest.json")))

    def test_a_newer_render_revision_replaces_the_old_images(self):
        self.art(self.linux, names=("Gas", "Pump"), render_rev=1)
        self.art(self.proton, names=("Gas",), render_rev=2)
        sh = SharedStore(os.path.join(self.tmp, "shared"))
        sh.import_folder(self.linux)
        sh.import_folder(self.proton)
        with open(os.path.join(sh.art_dir(BUILD, DLC), "manifest.json")) as f:
            self.assertEqual([e["id"] for e in json.load(f)["files"]], ["Gas"])
        self.assertFalse(sh.import_folder(self.linux)["art"])               # an older renderer is not taken back

    def test_unsafe_manifest_entries_are_not_copied(self):
        self.art(self.linux)
        mp = os.path.join(self.linux, "companion/art/manifest.json")
        with open(mp) as f:
            m = json.load(f)
        m["files"].append({"kind": "building", "id": "Evil", "path": "%d/building/../../../x.png" % BUILD, "size": 3})
        m["files"].append({"kind": "building", "id": "Big", "path": "%d/building/Gas.png" % BUILD, "size": 9999})
        atomic_write(mp, json.dumps(m))
        outside = os.path.join(self.linux, "companion", "x.png")
        with open(outside, "wb") as f:
            f.write(PNG)
        sh = SharedStore(os.path.join(self.tmp, "shared"))
        sh.import_folder(self.linux)
        with open(os.path.join(sh.art_dir(BUILD, DLC), "manifest.json")) as f:
            self.assertEqual([e["id"] for e in json.load(f)["files"]], ["Gas"])

    def test_fonts_theme_and_the_finished_sync(self):
        for sub, files in (("fonts/%d" % BUILD, ("graystroke.json", "graystroke.png")),
                           ("theme/%d" % BUILD, ("theme.json", "panel.png"))):
            d = os.path.join(self.proton, "companion", sub)
            os.makedirs(d)
            for n in files:
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b"{}" if n.endswith(".json") else PNG)
        self.sync_done(self.proton)
        sh = SharedStore(os.path.join(self.tmp, "shared"))
        r = sh.import_folder(self.proton)
        self.assertTrue(r["fonts"] and r["theme"] and r["pack"])
        self.assertTrue(sh.has_pack(BUILD, DLC))
        self.assertFalse(sh.has_pack(BUILD, []))
        self.assertTrue(sh.has_theme())
        self.assertTrue(os.path.isfile(os.path.join(sh.fonts_root(), str(BUILD), "graystroke.png")))
        self.assertEqual(sh.latest_pack(BUILD)["dlcIds"], DLC)
        self.assertEqual(sh.latest_pack(BUILD + 1)["build"], BUILD)


class TestServiceFollows(TwoFolders):
    def test_active_folder_follows_the_live_file_and_commands_go_there(self):
        self.live(self.linux, "running")
        self.live(self.proton, "stopped")
        self.start()
        self.assertEqual(self.svc.cfg.user_dir, self.linux)
        seq = self.svc.bus.seq
        self.live(self.linux, "stopped")
        self.live(self.proton, "running")
        self.assertTrue(wait_for(lambda: self.svc.cfg.user_dir == self.proton))
        changed = self.svc.bus.wait(seq, 0)["changed"]
        for name in ("status", "colony", "controls", "sync", "art"):
            self.assertIn(name, changed)
        self.assertEqual(self.get("/api/v1/controls")[1]["available"], True)
        st, body = http(self.svc, "/api/v1/actions/focus", method="POST", body={"target": {"kind": "dupe", "id": "d1"}})
        self.assertEqual(st, 200, body)
        self.assertEqual(len(os.listdir(os.path.join(self.proton, "companion", "commands"))), 1)
        self.assertFalse(os.path.exists(os.path.join(self.linux, "companion", "commands")))
        # and back, without a restart
        self.live(self.proton, "stopped")
        self.live(self.linux, "running")
        self.assertTrue(wait_for(lambda: self.svc.cfg.user_dir == self.linux))
        st, body = http(self.svc, "/api/v1/actions/focus", method="POST", body={"target": {"kind": "dupe", "id": "d1"}})
        self.assertEqual(st, 200, body)
        self.assertEqual(len(os.listdir(os.path.join(self.linux, "companion", "commands"))), 1)

    def test_game_process_decides_while_no_live_file_runs(self):
        self.live(self.proton, "stopped")
        self.live(self.linux, "stopped")
        t = time.time() + 30
        os.utime(os.path.join(self.linux, "companion/live/live.json"), (t, t))        # Linux has the newest activity
        self.start()
        self.assertEqual(self.svc.cfg.user_dir, self.linux)
        seq = self.svc.bus.seq
        self.game = self.proton_game()
        self.svc._game_changed()                                 # what the game gate does when the game appears
        self.assertEqual(self.svc.cfg.user_dir, self.proton)
        self.assertIn("status", self.svc.bus.wait(seq, 0)["changed"])
        self.game = self.native_game()
        self.svc._game_changed()
        self.assertEqual(self.svc.cfg.user_dir, self.linux)

    def test_pairing_state_follows(self):
        self.live(self.linux, "running")
        self.start()
        self.svc.connect.game_running = True
        self.svc.connect.ensure_identity()
        self.svc.connect.write_state_file()
        self.assertTrue(os.path.isfile(os.path.join(self.linux, "companion/pairing/state.json")))
        self.live(self.linux, "stopped")
        self.live(self.proton, "running")
        self.assertTrue(wait_for(lambda: self.svc.cfg.user_dir == self.proton))
        self.assertTrue(wait_for(lambda: os.path.isfile(os.path.join(self.proton, "companion/pairing/state.json"))))
        self.assertFalse(os.path.exists(os.path.join(self.linux, "companion/pairing/state.json")))

    def test_dev_json_style_forced_folder_does_not_follow(self):
        self.live(self.linux, "stopped")
        self.live(self.proton, "running")
        cfg = ServiceConfig(user_dir=self.linux, token=TOKEN, views_factory=lambda ctx: StubViews(ctx), follow=False,
                            follow_env=self.env, connect_opts={"autostart": False})
        self.svc = Service(cfg).start()
        self.assertEqual(self.svc.cfg.user_dir, self.linux)
        time.sleep(0.3)
        self.assertEqual(self.svc.cfg.user_dir, self.linux)

    def test_no_new_sync_when_the_other_version_starts(self):
        # Linux: art drawn and a sync finished. Proton has nothing yet and no sync of its own.
        self.live(self.linux, "running")
        self.art(self.linux)
        self.sync_done(self.linux)
        self.live(self.proton, "stopped", build=BUILD, dlc=DLC)
        self.start()
        sh = self.svc.shared
        self.assertTrue(wait_for(lambda: sh.has_pack(BUILD, DLC)))
        st, d = self.get("/api/v1/sync")
        self.assertFalse(d["needed"], d)
        self.assertEqual(self.raw("/api/v1/art/building/Gas")[0], 200)
        # the game now runs as the other version
        self.live(self.linux, "stopped")
        self.live(self.proton, "running")
        self.assertTrue(wait_for(lambda: self.svc.cfg.user_dir == self.proton))
        st, d = self.get("/api/v1/sync")
        self.assertFalse(d["needed"], d)                          # no new sync asked for
        self.assertEqual(d["canStart"], True)
        self.assertEqual(self.raw("/api/v1/art/building/Gas"), (200, PNG))      # from the core's copy: Proton has none
        self.assertFalse(os.path.exists(os.path.join(self.proton, "companion", "art")))

    def test_needed_is_asked_per_build_and_dlc_set(self):
        self.live(self.linux, "running")
        self.sync_done(self.linux, dlc=[])
        self.start()
        self.assertTrue(wait_for(lambda: self.svc.shared.has_pack(BUILD, [])))
        _st, d = self.get("/api/v1/sync")
        self.assertEqual((d["needed"], d.get("neededReason")), (True, "new_dlc"))     # live shows DLC_ALPHA, the pack is base

    def test_art_arriving_in_the_other_folder_reaches_the_screens(self):
        self.live(self.linux, "running")
        self.start()
        self.assertEqual(self.raw("/api/v1/art/building/Gas")[0], 404)
        seq = self.svc.bus.seq
        self.art(self.proton)                                      # the Proton version draws while we follow Linux
        self.assertTrue(wait_for(lambda: self.svc.shared.has_theme() or
                                 os.path.isfile(os.path.join(self.svc.shared.art_dir(BUILD, DLC), "manifest.json"))))
        self.assertTrue(wait_for(lambda: "art" in self.svc.bus.wait(seq, 0)["changed"]))
        self.assertEqual(self.raw("/api/v1/art/building/Gas")[0], 200)


if __name__ == "__main__":
    unittest.main()
