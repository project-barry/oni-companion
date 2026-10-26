"""Malformed items in a duplicant must be skipped, never break the Colony tab (audit finding)."""
import unittest

from core.oni_companion.views import colony as cv


class _Lk:
    def name(self, kind, i): return str(i)
    def ref(self, kind, i): return None
    def name_any(self, k, kinds): return str(k)
    def ref_any(self, k, kinds): return None


def _facts(d):
    return {"source": "mod-live", "colonyName": "C", "cycle": 1, "activeWorldId": 0,
            "worlds": [{"id": 0, "name": "W", "dupes": [d]}]}


class BadItems(unittest.TestCase):
    CASES = [
        {"id": 1, "name": "A", "statusItems": [None, "x", 5, {"severity": "bad", "name": "Hot"}]},
        {"id": 1, "name": "A", "stress": "hi"},
        {"id": 1, "name": "A", "stress": None, "health": "x", "calories": [1], "breath": 3, "diseases": [None, "x"]},
        {"id": 1, "name": "A", "statusItems": "oops", "attributes": [None, 3], "morale": "x", "traits": [None, 1],
         "skills": "s", "stamina": 4, "bladder": "q", "bodyTempC": "hot"},
        {"id": 1, "name": "A", "health": {"value": "a", "max": "b"}, "stress": float("nan")},
    ]

    def test_screen_and_page(self):
        for d in self.CASES:
            f = _facts(d)
            self.assertTrue(cv.colony_screen(_Lk(), f))
            self.assertTrue(cv.dupe_screen(_Lk(), f, 1))

    def test_good_item_kept(self):
        b = cv.status_badges(self.CASES[0])
        self.assertEqual([x["label"] for x in b], ["Too hot"])


if __name__ == "__main__":
    unittest.main()
