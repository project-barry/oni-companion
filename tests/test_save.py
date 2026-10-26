"""Tests for core/oni_companion/save.

The synthetic tests build a tiny save from made-up bytes (no Klei data).
The real-save tests run only when fixtures/real holds saves (gitignored).
"""
import glob
import json
import os
import struct
import sys
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from oni_companion.save import header as H                      # noqa: E402
from oni_companion.save import kserial as K                     # noqa: E402
from oni_companion.save.colony_from_save import colony_from_save, sdbm_lower  # noqa: E402
from tests.jsonschema_mini import Validator                     # noqa: E402

CONTRACTS = os.path.join(ROOT, "contracts")


# ---- tiny save builder -------------------------------------------------------

def s(text):
    b = text.encode()
    return struct.pack("<i", len(b)) + b


def i32(*v):
    return struct.pack("<%di" % len(v), *v)


def f32(*v):
    return struct.pack("<%df" % len(v), *v)


INT, FLOAT, BOOL, STRING, LIST_STR, VEC2I = 6, 10, 3, 12, 0x94, 14


def ti(code, *extra):
    return bytes([code]) + b"".join(extra)


def template(name, fields):
    out = s(name) + i32(len(fields), 0)
    for fname, t in fields:
        out += s(fname) + t
    return out


def templates_blob():
    t = [
        template("GameClock", [("cycle", ti(INT)), ("timeSinceStartOfCycle", ti(FLOAT))]),
        template("ClusterManager", [("activeWorldIdx", ti(INT))]),
        template("WorldContainer", [("id", ti(INT)), ("worldOffset", ti(VEC2I)), ("worldSize", ti(VEC2I)),
                                    ("overrideName", ti(STRING)), ("worldType", ti(STRING)),
                                    ("isStartWorld", ti(BOOL))]),
        template("KPrefabID", [("InstanceID", ti(INT))]),
        template("MinionIdentity", [("name", ti(STRING))]),
        template("MinionModifiers", []),
        template("StateMachineController", []),
        template("Klei.AI.Traits", [("TraitIds", ti(0x94, b"\x01", ti(STRING)))]),
        template("MinionResume", [("MasteryBySkillID", ti(0x93, b"\x02", ti(STRING), ti(BOOL))),
                                  ("currentRole", ti(STRING))]),
        template("PrimaryElement", [("ElementID", ti(13, s("SimHashes"))), ("Units", ti(FLOAT))]),
        template("Pickupable", []),
    ]
    return i32(len(t)) + b"".join(t)


def behavior(name, data):
    return s(name) + i32(len(data)) + data


def instance(pos, behaviors):
    return (f32(*pos) + f32(0, 0, 0, 1) + f32(1, 1, 1) + b"\x00"
            + i32(len(behaviors)) + b"".join(behaviors))


def group(name, instances):
    blob = b"".join(instances)
    return s(name) + i32(len(instances), len(blob)) + blob


def amounts(d):
    out = i32(len(d))
    for k, v in d.items():
        out += s(k) + i32(4) + f32(v)
    return out + i32(0)


def minion(name, iid, pos, stress, dead=False):
    state = b"root.dead.ground" if dead else b"root.alive"
    sm = b"DeathMonitor+Instance" + b"\xff\xff\xff\xff" + i32(len(state)) + state
    return instance(pos, [
        behavior("KPrefabID", i32(iid)),
        behavior("StateMachineController", sm),
        behavior("MinionModifiers", amounts({"HitPoints": 90.0, "Stress": stress, "Calories": 2500000.0, "Breath": 80.0})),
        behavior("Klei.AI.Traits", list_blob(["Trait"])),
        behavior("MinionIdentity", s(name)),
        behavior("MinionResume", skills_blob({"Mining1": True}) + s("NoRole")),
    ])


def list_blob(items):
    body = b"".join(s(x) for x in items)
    return i32(len(body), len(items)) + body


def skills_blob(d):
    # dictionary: [byteLength][count] values first, then keys
    vals = b"".join(b"\x01" if v else b"\x00" for v in d.values())
    keys = b"".join(s(k) for k in d)
    return i32(len(vals) + len(keys), len(d)) + vals + keys


def build_save(minor=38, major=7, compressed=True, dupes=2):
    info = {"numberOfCycles": 41, "numberOfDuplicants": dupes, "baseName": "Test Colony",
            "isAutoSave": True, "saveMajorVersion": major, "saveMinorVersion": minor,
            "clusterId": "clusters/Test", "colonyGuid": "00000000-0000-0000-0000-000000000001",
            "dlcIds": [""]}
    hdr = json.dumps(info).encode()
    clock = i32(41) + f32(150.0)
    save_game = instance((0, 0, 0), [behavior("GameClock", clock), behavior("ClusterManager", i32(0))])
    world = instance((-1, 0, 0), [behavior("WorldContainer",
                                           i32(0) + i32(0, 0) + i32(100, 100) + s("") + s("STRINGS.WORLDS.TEST_WORLD.NAME") + b"\x01")])
    rock = lambda kg, pos: instance(pos, [behavior("PrimaryElement", i32(sdbm_lower("Rock")) + f32(kg)),
                                          behavior("Pickupable", b"")])
    groups = [
        group("SaveGame", [save_game]),
        group("Asteroid", [world]),
        group("Minion", [minion("Test Dupe A", 7, (10.5, 20.0, -25.5), 12.0),
                         minion("Test Dupe B", 8, (11.5, 20.0, -25.5), 0.0),
                         minion("Test Gone", 9, (12.5, 20.0, -25.5), 100.0, dead=True)][:dupes + 1]),
        group("Rock", [rock(100.0, (5.5, 5.0, 0)), rock(50.0, (6.5, 5.0, 0))]),
    ]
    body = (s("world") + s("Klei.SaveFileRoot") + b"\x00" * 8
            + i32(7, minor, len(groups)) + b"".join(groups) + s("Game+GameSaveData"))
    tpl = templates_blob()
    rest = tpl + (zlib.compress(body) if compressed else body)
    return struct.pack("<IIII", 744825, len(hdr), 1, 1 if compressed else 0) + hdr + rest


# ---- tests ---------------------------------------------------------------------

class HeaderTests(unittest.TestCase):
    def test_parse(self):
        h = H.parse_header(build_save())
        self.assertEqual((h.build, h.header_version, h.compressed), (744825, 1, True))
        self.assertEqual((h.cycles, h.cycle, h.dupe_count), (41, 42, 2))
        self.assertEqual(h.dlc_ids, [])
        self.assertEqual(h.save_version, (7, 38))

    def test_dlc_ids(self):
        info = {"dlcIds": ["", "EXPANSION1_ID"]}
        raw = json.dumps(info).encode()
        h = H.parse_header(struct.pack("<IIII", 1, len(raw), 1, 1) + raw)
        self.assertEqual(h.dlc_ids, ["EXPANSION1_ID"])

    def test_bad_input(self):
        for bad in (b"", b"abc", struct.pack("<IIII", 1, 9999, 1, 1) + b"{}",
                    struct.pack("<IIII", 1, 4, 1, 1) + b"nope"):
            with self.assertRaises(H.SaveFormatError):
                H.parse_header(bad)


class KSerialTests(unittest.TestCase):
    def test_templates_and_dictionary_layout(self):
        h, templates, body = K.split_save(build_save())
        self.assertIn("MinionResume", templates)
        p = K.Parser(templates)
        data = skills_blob({"A": True, "B": False}) + s("NoRole")
        fields, extra = p.template_data(data, templates["MinionResume"])
        self.assertEqual(fields["MasteryBySkillID"], {"A": True, "B": False})
        self.assertEqual(extra, b"")

    def test_truncated_data_raises_kserial_error(self):
        _, templates, _ = K.split_save(build_save())
        p = K.Parser(templates)
        with self.assertRaises(K.KSerialError):
            p.template_data(b"\x01\x00", templates["GameClock"])

    def test_uncompressed_body(self):
        _, _, body = K.split_save(build_save(compressed=False))
        self.assertTrue(body.startswith(s("world")))


class ColonyTests(unittest.TestCase):
    def setUp(self):
        self.v = Validator(CONTRACTS)

    def test_full(self):
        c = colony_from_save(build_save())
        self.assertEqual((c["source"], c["level"], c["warnings"]), ("save", "full", []))
        live = c["live"]
        self.assertEqual(live["cycle"], 42)
        self.assertAlmostEqual(live["timeOfDay"], 0.25)
        world = live["worlds"][0]
        self.assertEqual(world["name"], "Test World")
        self.assertEqual([d["name"] for d in world["dupes"]], ["Test Dupe A", "Test Dupe B"])
        self.assertEqual(c["deadDupes"], ["Test Gone"])
        d = world["dupes"][0]
        self.assertEqual((d["stress"], d["skills"], d["traits"]), (12.0, ["Mining1"], ["Trait"]))
        self.assertAlmostEqual(d["calories"]["value"], 2500.0)
        self.assertEqual(world["resources"], {"Rock": 150.0})

    def test_live_block_validates(self):
        live = colony_from_save(build_save())["live"]
        self.assertEqual(self.v.validate(live, "mod-live.schema.json"), [])

    def test_header_only_validates(self):
        live = colony_from_save(build_save(major=8))["live"]
        self.assertEqual(self.v.validate(live, "mod-live.schema.json"), [])

    def test_unknown_major_falls_back(self):
        c = colony_from_save(build_save(major=8))
        self.assertEqual((c["source"], c["level"]), ("header", "header"))
        self.assertEqual(c["live"]["cycle"], 42)
        self.assertTrue(c["warnings"])

    def test_newer_minor_still_reads_with_warning(self):
        c = colony_from_save(build_save(minor=99))
        self.assertEqual(c["level"], "full")
        self.assertTrue(any("newer" in w for w in c["warnings"]))

    def test_damaged_body_falls_back(self):
        raw = bytearray(build_save())
        raw[-20:] = b"\xff" * 20  # corrupt the zlib tail
        c = colony_from_save(bytes(raw))
        self.assertEqual(c["level"], "header")
        self.assertEqual(c["header"]["colonyName"], "Test Colony")
        self.assertTrue(any("not readable" in w for w in c["warnings"]))

    def test_truncated_file_falls_back(self):
        raw = build_save()
        c = colony_from_save(raw[:len(raw) // 2])
        self.assertEqual(c["level"], "header")

    def test_not_a_save(self):
        with self.assertRaises(H.SaveFormatError):
            colony_from_save(b"hello world, not a save file")


REAL = os.path.join(ROOT, "fixtures", "real", "user")
AUTOSAVES = sorted(glob.glob(os.path.join(REAL, "**", "auto_save", "*.sav"), recursive=True))


@unittest.skipUnless(AUTOSAVES, "no real saves under fixtures/real")
class RealSaveTests(unittest.TestCase):
    def test_every_save_reads_and_matches_header(self):
        v = Validator(CONTRACTS)
        for path in AUTOSAVES:
            with self.subTest(os.path.basename(path)):
                c = colony_from_save(path)
                self.assertEqual(c["level"], "full", c["warnings"])
                alive = sum(len(w["dupes"]) for w in c["live"]["worlds"])
                self.assertEqual(alive, c["header"]["dupeCount"])  # dead-dupe detection agrees with the game
                self.assertEqual(c["live"]["cycle"], c["header"]["cycle"])
                self.assertEqual(v.validate(c["live"], "mod-live.schema.json"), [])

    def test_stable_between_runs(self):
        path = AUTOSAVES[-1]
        a, b = colony_from_save(path), colony_from_save(path)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
