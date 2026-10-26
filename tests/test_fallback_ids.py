"""Skill ids from .pot links, and .pot entries merged into export entries (synthetic strings)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from oni_companion.gamedata.fallback import build_fallback  # noqa: E402
from oni_companion.gamedata.merge import merge  # noqa: E402

P = "STRINGS.DUPLICANTS.ROLES."
STR = {P + "JUNIOR_MINER.NAME": '<link="MINING1">Hard Digging</link>', P + "JUNIOR_MINER.DESCRIPTION": "Digs.",
       P + "BIONICS_A1.NAME": "Booster Processing I",
       "STRINGS.ROOMS.TYPES.REC_ROOM.NAME": "Recreation Room"}


class FallbackIds(unittest.TestCase):
    def test_skill_id_from_link(self):
        rows = {r["id"]: r for r in build_fallback(STR)["skill"]}
        self.assertIn("MINING1", rows)
        self.assertEqual(rows["MINING1"]["desc"], "Digs.")

    def test_merge_by_id_without_punctuation_and_by_name(self):
        exp = [{"data": {"dlcIds": [], "skills": [{"id": "Mining1", "name": "Hard Digging", "dlc": []},
                                                  {"id": "BionicsA1", "name": "Booster Processing I", "dlc": ["DLC3_ID"]}],
                         "rooms": [{"id": "RecRoom", "name": "Recreation Room", "dlc": []}]}, "name": "x"}]
        kinds = merge(build_fallback(STR), exp)
        self.assertEqual(sorted(kinds["skill"]), ["BionicsA1", "Mining1"])
        self.assertEqual(kinds["skill"]["BionicsA1"]["dlc"], ["DLC3_ID"])
        self.assertEqual(sorted(kinds["room"]), ["RecRoom"])
        self.assertNotIn("dlcKnown", kinds["skill"]["Mining1"])


if __name__ == "__main__":
    unittest.main()
