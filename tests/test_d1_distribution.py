"""D1 (v1.3): where a Workshop copy of the mod can be found (verified in the game's code: Steam keeps a zip in
<steamapps>/workshop/content/457140/<id>/, the game copies it to <user>/mods/Steam/<id>), every mod state on
synthetic folders, the ask-first install, and the release zip. No real game folder is touched."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.oni_companion import modstate  # noqa: E402

YAML = "title: ONI Companion Link\nstaticID: OniCompanionLink\n"
ON = {"label": {"distribution_platform": 0, "id": "OniCompanionLink"}, "enabledForDlc": [""], "staticID": "OniCompanionLink"}


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-d1-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bundled = os.path.join(self.tmp, "bundle")
        os.makedirs(self.bundled)
        for n, b in (("OniCompanionLink.dll", "x"), ("mod.yaml", YAML), ("mod_info.yaml", "version: 0.4.0\n")):
            open(os.path.join(self.bundled, n), "w").write(b)
        self.home = os.path.join(self.tmp, "home")               # an empty home: no real Steam library is seen
        os.makedirs(self.home)
        self.env = {"HOME": self.home}
        # a Proton layout: <lib>/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded
        self.steamapps = os.path.join(self.tmp, "lib", "steamapps")
        self.user = os.path.join(self.steamapps, "compatdata", "457140", "pfx", "drive_c", "users", "steamuser",
                                 "Documents", "Klei", "OxygenNotIncluded")
        os.makedirs(self.user)

    def ms(self, **kw):
        return modstate.ModState(self.user, lambda: kw.get("meta", {}), lambda: kw.get("live"),
                                 lambda lv: bool(kw.get("fresh")), self.bundled, env=self.env)

    def workshop_zip(self, item="3600000001", name="OniCompanionLink.zip", yaml=YAML):
        d = os.path.join(self.steamapps, "workshop", "content", "457140", item)
        os.makedirs(d)
        with zipfile.ZipFile(os.path.join(d, name), "w") as z:
            z.writestr("OniCompanionLink/mod.yaml", yaml)
        return d

    def mods_json(self, mods):
        os.makedirs(os.path.join(self.user, "mods"), exist_ok=True)
        json.dump({"version": 1, "mods": mods}, open(os.path.join(self.user, "mods", "mods.json"), "w"))


class WorkshopCopy(Synthetic):
    def test_downloaded_zip_in_the_proton_library_is_found(self):
        d = self.workshop_zip()
        st = self.ms().compute()
        self.assertEqual(st["copies"], ["workshop"])
        self.assertFalse(st["install"]["available"])
        self.assertIn("Workshop", st["install"]["reason"])
        self.assertEqual(modstate.find_copies(self.user, self.env)["workshop"], [d])

    def test_other_workshop_item_is_not_ours(self):
        self.workshop_zip(yaml="staticID: SomeoneElse\n")
        self.assertEqual(self.ms().compute()["copies"], [])

    def test_a_broken_zip_is_ignored(self):
        d = os.path.join(self.steamapps, "workshop", "content", "457140", "1")
        os.makedirs(d)
        open(os.path.join(d, "x.zip"), "w").write("not a zip")
        self.assertEqual(self.ms().compute()["copies"], [])

    def test_workshop_copy_after_the_game_copied_it(self):
        p = os.path.join(self.user, "mods", "Steam", "3600000001")
        os.makedirs(p)
        open(os.path.join(p, "mod.yaml"), "w").write(YAML)
        self.assertEqual(self.ms().compute()["copies"], ["workshop"])

    def test_mods_json_steam_entry_counts(self):
        self.mods_json([dict(ON, label={"distribution_platform": 1, "id": "3600000001"})])
        st = self.ms().compute()
        self.assertEqual(st["copies"], ["workshop"])
        self.assertFalse(st["install"]["available"])

    def test_install_refuses_with_a_workshop_copy_and_writes_nothing(self):
        self.workshop_zip()
        with self.assertRaises(ValueError):
            self.ms().install()
        self.assertFalse(os.path.exists(os.path.join(self.user, "mods")))

    def test_env_override_folder(self):
        d = os.path.join(self.tmp, "elsewhere", "9")
        os.makedirs(d)
        with zipfile.ZipFile(os.path.join(d, "m.zip"), "w") as z:
            z.writestr("mod.yaml", YAML)
        env = dict(self.env, ONI_WORKSHOP_DIR=os.path.dirname(d))
        self.assertEqual(modstate.find_copies(self.user, env)["workshop"], [d])


class States(Synthetic):
    def test_every_state_names_its_steps(self):
        st = self.ms().compute()                                          # nothing there
        self.assertEqual(st["state"], "missing")
        self.assertTrue(st["install"]["available"])
        self.assertTrue(any("Install the game mod" in s for s in st["steps"]))
        self.assertTrue(any("Workshop" in s for s in st["steps"]))
        self.ms().install()
        st = self.ms().compute()                                          # copied, game never listed it
        self.assertEqual(st["state"], "disabled")
        self.assertTrue(any("Mods menu" in s for s in st["steps"]))
        self.mods_json([dict(ON, enabledForDlc=[])])
        self.assertEqual(self.ms().compute()["state"], "disabled")
        self.mods_json([ON])
        st = self.ms(meta={"exportFiles": ["g.json"]}).compute()
        self.assertEqual(st["state"], "no_live")
        self.assertTrue(any("Player.log" in s for s in st["steps"]))
        live = {"modVersion": "0.4.0"}
        self.assertEqual(self.ms(live=live, fresh=True).compute()["state"], "ok")
        st = self.ms(live={"modVersion": "0.3.2"}, fresh=True).compute()
        self.assertEqual((st["state"], st["compat"]["problem"]), ("version_mismatch", "mod_too_old"))
        st = self.ms(live={"modVersion": "0.4.0", "requiresCore": {"min": "9.0"}}, fresh=True).compute()
        self.assertEqual(st["compat"]["problem"], "app_too_old")
        st = self.ms(live={"modVersion": "0.4.0", "requiresCore": {"min": "1.0", "max": "1.0.1"}}, fresh=True).compute()
        self.assertEqual(st["compat"]["problem"], "app_too_new")
        st = self.ms(live={"modVersion": "9.0.0"}, fresh=True).compute()
        self.assertEqual(st["compat"]["problem"], "mod_too_new") if "max" in modstate.SUPPORTS_MOD else None

    def test_install_never_touches_mods_json_or_other_folders(self):
        self.mods_json([])
        before = open(os.path.join(self.user, "mods", "mods.json")).read()
        os.makedirs(os.path.join(self.user, "mods", "Local", "Other"))
        self.ms().install()
        self.assertEqual(open(os.path.join(self.user, "mods", "mods.json")).read(), before)
        self.assertEqual(sorted(os.listdir(os.path.join(self.user, "mods", "Local"))), ["OniCompanionLink", "Other"])
        self.assertEqual(os.listdir(os.path.join(self.user, "mods", "Local", "Other")), [])

    def test_missing_game_folder_and_missing_bundle(self):
        ms = modstate.ModState(os.path.join(self.tmp, "nope"), lambda: {}, lambda: None, lambda lv: False, self.bundled,
                               env=self.env)
        with self.assertRaises(ValueError):
            ms.install()
        ms = modstate.ModState(self.user, lambda: {}, lambda: None, lambda lv: False, None, env=self.env)
        self.assertFalse(ms.compute()["install"]["available"])
        with self.assertRaises(ValueError):
            ms.install()


class ReleaseZip(Synthetic):
    def run_script(self, out, build):
        return subprocess.run(["sh", os.path.join(ROOT, "mod", "release-zip.sh"), out],
                              env=dict(os.environ, MOD_BUILD_DIR=build), capture_output=True, text=True)

    def test_zip_holds_only_our_files_and_the_instructions(self):
        out = os.path.join(self.tmp, "out")
        r = self.run_script(out, self.bundled)
        self.assertEqual(r.returncode, 0, r.stderr)
        z = zipfile.ZipFile(os.path.join(out, "OniCompanionLink.zip"))
        names = sorted(z.namelist())
        self.assertEqual(names, ["OniCompanionLink/OniCompanionLink.dll", "OniCompanionLink/README.txt",
                                 "OniCompanionLink/mod.yaml", "OniCompanionLink/mod_info.yaml"])
        txt = z.read("OniCompanionLink/README.txt").decode()
        for needle in ("mods/Local", "Mods menu", "restart", "Workshop"):
            self.assertIn(needle, txt)

    def test_unbuilt_mod_stops_with_a_message(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        r = self.run_script(os.path.join(self.tmp, "out2"), empty)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("build", r.stderr)


if __name__ == "__main__":
    unittest.main()
