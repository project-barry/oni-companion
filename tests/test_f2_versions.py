"""F2 (v1.4.1): the mod install and the mod state per ONI version (Linux + Proton on one device).

Synthetic two-folder trees only; nothing touches a real home folder.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.oni_companion import modstate  # noqa: E402
from core.oni_companion.server.errors import ApiError  # noqa: E402
from core.oni_companion.views import settings_view  # noqa: E402
from tests.jsonschema_mini import Validator  # noqa: E402

spec = importlib.util.spec_from_file_location("make_v13", os.path.join(ROOT, "devtools", "make-v13-fixtures.py"))
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)
V = Validator(os.path.join(ROOT, "contracts"))

ON = {"label": {"distribution_platform": 0, "id": "OniCompanionLink"}, "enabledForDlc": [""], "staticID": "OniCompanionLink"}


class Two(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-f2-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bundled = os.path.join(self.tmp, "bundle", "OniCompanionLink")
        os.makedirs(self.bundled)
        for n, body in (("OniCompanionLink.dll", "x"), ("mod.yaml", "staticID: OniCompanionLink\n"),
                        ("mod_info.yaml", "version: 0.5.0\n")):
            open(os.path.join(self.bundled, n), "w").write(body)
        self.linux = os.path.join(self.tmp, "home", ".config", "unity3d", "Klei", "Oxygen Not Included")
        self.proton = os.path.join(self.tmp, "sd", "steamapps", "compatdata", "457140", "pfx", "drive_c", "users",
                                   "steamuser", "Documents", "Klei", "OxygenNotIncluded")
        for d in (self.linux, self.proton):
            os.makedirs(os.path.join(d, "companion", "live"))
        self.env = {"HOME": os.path.join(self.tmp, "home"), "ONI_WORKSHOP_DIR": ""}

    def put(self, user, version="0.4.3", modsjson=None, workshop=False):
        p = os.path.join(user, "mods", "Steam" if workshop else "Local", "100001" if workshop else "OniCompanionLink")
        os.makedirs(p)
        open(os.path.join(p, "mod.yaml"), "w").write("staticID: OniCompanionLink\n")
        open(os.path.join(p, "mod_info.yaml"), "w").write("version: %s\n" % version)
        if modsjson is not None:
            json.dump({"version": 1, "mods": modsjson}, open(os.path.join(user, "mods", "mods.json"), "w"))

    def ms(self, active=None):
        return modstate.ModState(active or self.linux, lambda: {}, lambda: None, lambda lv: False, self.bundled,
                                 env=self.env, folders=[self.linux, self.proton])

    def test_state_per_version_and_summary(self):
        self.put(self.linux, "0.4.3", [ON])
        self.put(self.proton, "0.4.3", [dict(ON, enabledForDlc=[])])
        st = self.ms().compute()
        v = {r["kind"]: r for r in st["versions"]}
        self.assertEqual((v["linux"]["enabled"], v["linux"]["installed"], v["linux"]["active"]), (True, "0.4.3", True))
        self.assertEqual((v["proton"]["enabled"], v["proton"]["crashDisabled"], v["proton"]["active"]), (False, False, False))
        self.assertEqual(v["proton"]["library"], os.path.join(self.tmp, "sd"))
        self.assertIsNone(v["linux"]["library"])
        self.assertEqual(st["versionsSummary"], "Linux: on, 0.4.3 · Windows (Proton): off, 0.4.3")
        self.assertFalse(st["updateBoth"])
        self.assertEqual(V.validate(st, "api.schema.json#/$defs/ModState"), [])

    def test_version_mismatch_says_update_both(self):
        self.put(self.linux, "0.4.1", [ON])
        self.put(self.proton, "0.4.3", [ON])
        st = self.ms().compute()
        self.assertTrue(st["updateBoth"])
        texts = json.dumps(settings_view.mod_blocks(st))
        self.assertIn("Update both", texts)
        self.assertIn("Windows (Proton)", texts)

    def test_crash_disabled_needs_the_log_line(self):
        self.put(self.proton, "0.4.3", [dict(ON, enabledForDlc=[])])
        self.assertFalse({r["kind"]: r for r in self.ms().compute()["versions"]}["proton"]["crashDisabled"])
        log = os.path.join(self.tmp, "sd", "steamapps", "compatdata", "457140", "pfx", "drive_c", "users", "steamuser",
                           "AppData", "LocalLow", "Klei", "Oxygen Not Included")
        os.makedirs(log)
        open(os.path.join(log, "Player.log"), "w").write("ok\nNullReferenceException at OniCompanionLink.Foo\n")
        st = self.ms().compute()
        self.assertTrue({r["kind"]: r for r in st["versions"]}["proton"]["crashDisabled"])
        self.assertIn("switched the mod off after an error", json.dumps(settings_view.mod_blocks(st)))

    def test_install_writes_every_folder_and_skips_workshop(self):
        res = self.ms().install_all()
        self.assertEqual(len(res["installed"]), 2)
        for d in (self.linux, self.proton):
            self.assertEqual(sorted(os.listdir(os.path.join(d, "mods", "Local", "OniCompanionLink"))),
                             sorted(modstate.BUNDLED_FILES))
        self.assertEqual(self.ms().compute()["install"]["available"], False)
        # a Workshop copy in one folder: that one is skipped, the other still gets the mod
        shutil.rmtree(os.path.join(self.proton, "mods"))
        self.put(self.proton, "0.5.0", workshop=True)
        shutil.rmtree(os.path.join(self.linux, "mods"))
        res = self.ms().install_all()
        self.assertEqual(res["installed"], [os.path.join(self.linux, "mods", "Local", "OniCompanionLink")])
        self.assertEqual([s["path"] for s in res["skipped"]], [self.proton])
        self.assertFalse(os.path.exists(os.path.join(self.proton, "mods", "Local")))
        # nothing left to do: one plain reason
        with self.assertRaises(ValueError) as e:
            self.ms().install_all()
        self.assertIn("Workshop", str(e.exception))

    def test_confirm_text_lists_the_folders_and_network_has_no_button(self):
        st = self.ms().compute()
        scr = settings_view.settings_screen({}, {"game": {}, "mod": {}, "cache": {}, "colony": {}, "modState": st})
        acts = [b for b in json.dumps(scr).split('"id": "mod_install"')]
        self.assertEqual(len(acts), 2)
        conf = [a for a in _walk(scr) if a.get("id") == "mod_install"][0]["confirm"]
        self.assertIn(self.linux, conf)
        self.assertIn(self.proton, conf)
        net = settings_view.settings_screen({}, {"game": {}, "mod": {}, "cache": {}, "colony": {}, "modState": st}, local=False)
        self.assertEqual([a for a in _walk(net) if a.get("id") == "mod_install"], [])

    def test_views_install_reply_lists_the_folders(self):
        v, user = mk.make_views(os.path.join(self.tmp, "v"), None, mk.make_live(), self.bundled)
        cfg = v.ctx.cfg
        cfg.user_dir, cfg.user_dirs = self.linux, [self.linux, self.proton]
        v._cfg = cfg
        rep = v.mod_install({"confirm": True})
        self.assertEqual(len(rep["paths"]), 2)
        self.assertEqual(rep["path"], os.path.join(self.linux, "mods", "Local", "OniCompanionLink"))
        self.assertEqual(V.validate(rep, "api.schema.json#/$defs/ModInstallReply"), [])
        self.assertEqual(len(rep["modState"]["versions"]), 2)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for x in node.values():
            yield from _walk(x)
    elif isinstance(node, list):
        for x in node:
            yield from _walk(x)


if __name__ == "__main__":
    unittest.main()
