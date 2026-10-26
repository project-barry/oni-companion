"""C11: TextMeshPro markup -> spans, the alert strip and the alert page, alert_activate / alert_dismiss.

Markup here is synthetic (the mirror's live.json carries no tooltipMarkup yet: mod 0.2.4 predates it). The
fixtures in fixtures/synthetic/mod/live-running-v2.json hold the contract's examples.
"""
import json
import os
import shutil
import tempfile
import unittest

from tests.jsonschema_mini import Validator
from core.oni_companion import colony as colony_mod
import core.oni_companion.server  # noqa: F401  (import order)
from core.oni_companion.actions import ActionService
from core.oni_companion.colony import Colony
from core.oni_companion.server.errors import ApiError
from core.oni_companion.views import alerts as av
from core.oni_companion.views import blocks as B
from core.oni_companion.views import richtext as rt
from core.oni_companion.views.provider import Views
from tests.test_c4_views import AS_OF, CONTRACTS, FakeCtx, load_json, synthetic_lookup

V = Validator(CONTRACTS)
HAS_UI = lambda name: True            # noqa: E731
NO_UI = lambda name: False            # noqa: E731


def spans(markup, **kw):
    return rt.to_spans(markup, **kw)


class Markup(unittest.TestCase):
    def ok(self, sp):
        node = {"schema": 1, "title": "t", "blocks": [{"type": "text", "spans": sp or [{"type": "plain", "text": "x"}]}]}
        self.assertEqual(V.validate(node, "screen.schema.json"), [])

    def test_plain_and_bold(self):
        sp = spans("<b>Low air</b>\nplain")
        self.assertEqual(sp, [{"type": "bold", "text": "Low air"}, {"type": "plain", "text": "\nplain"}])
        self.ok(sp)

    def test_unknown_tags_dropped_text_kept(self):
        sp = spans('<size=80%>small</size> <style="KLink">k</style> <nobr>n</nobr><i>it</i><u>u</u><align=center>c')
        self.assertEqual("".join(s["text"] for s in sp), "small k nituc")
        self.assertTrue(all(s["type"] == "plain" for s in sp))

    def test_less_than_that_is_not_a_tag_stays(self):
        self.assertEqual(spans("a < b and 5<6 > 3")[0]["text"], "a < b and 5<6 > 3")
        self.assertEqual(spans("x <3 y")[0]["text"], "x <3 y")

    def test_line_breaks(self):
        self.assertEqual(spans("a<br>b\r\nc")[0]["text"], "a\nb\nc")

    def test_trailing_newlines_trimmed_empty_input(self):
        self.assertEqual(spans("hi\n\n  ")[0]["text"], "hi")
        for e in ("", "   ", None, 5, [], "<b></b>"):
            self.assertEqual(spans(e), [])

    def test_color_tokens(self):
        cases = {"#F48C8C": "negative", "#FF0000": "negative", "red": "negative", "#E8B44A": "warning", "orange": "warning",
                 "yellow": "warning", "#4cc38a": "positive", "green": "positive", "#5aa9ff": "info", "#80f": "info",
                 "#98A2B3": "textDim", "grey": "textDim", "#FFFFFF": None, "white": None, "#000000": None,
                 "#FF000010": None, "#FF0000FF": "negative", "nonsense": None, "#12": None, "#GGGGGG": None, "": None}
        for v, want in cases.items():
            self.assertEqual(rt.color_token(v), want, v)
        sp = spans('<color=#F48C8C>bad</color> ok <color="#4cc38a">good</color>')
        self.assertEqual([(s["text"], s.get("color")) for s in sp], [("bad", "negative"), (" ok ", None), ("good", "positive")])
        self.ok(sp)

    def test_nested_color_and_unclosed(self):
        sp = spans("<color=red>a<color=green>b</color>c")
        self.assertEqual([(s["text"], s.get("color")) for s in sp], [("a", "negative"), ("b", "positive"), ("c", "negative")])
        self.assertEqual(spans("</color></b></link>text")[0]["text"], "text")

    def test_links_become_actions(self):
        def act(i):
            return B.action("alert_activate", "L" + str(i), {"alertId": "a", "link": int(i)})
        sp = spans('x <link="0"><b>Ada</b> breathes</link> y <link="1">Bea</link>', link_action=act)
        acts = [(s["text"], s["action"]["args"]["link"]) for s in sp if "action" in s]
        self.assertEqual(acts, [("Ada", 0), (" breathes", 0), ("Bea", 1)])
        self.assertTrue(all(s.get("color") == "info" for s in sp if "action" in s))      # looks tappable
        self.ok(sp)
        self.assertFalse(any("action" in s for s in spans('<link="0">x</link>')))        # no resolver: plain text
        self.assertFalse(any("action" in s for s in spans('<link="0">x</link>', link_action=lambda i: None)))
        self.assertFalse(any("action" in s for s in spans('<link="0">x</link>', link_action=lambda i: 1 / 0)))

    def test_sprite(self):
        sp = spans('go <sprite name="oxygen"> now <sprite=3> <sprite name="../x">', sprite_icon=lambda n: "/api/v1/art/ui/sprite-" + n)
        icons = [s["icon"] for s in sp if "icon" in s]
        self.assertEqual(icons, ["/api/v1/art/ui/sprite-oxygen"])                         # index form and bad name dropped
        self.ok(sp)
        self.assertEqual([s["text"] for s in spans('<sprite name="o">a', sprite_icon=lambda n: None)], ["a"])

    def test_noparse(self):
        self.assertEqual(spans("<noparse><b>x</b></noparse><b>y</b>")[0]["text"], "<b>x</b>")

    def test_caps_and_hostile_input(self):
        big = "<b>" * 5000 + "x" + "</b>" * 5000
        self.assertEqual(spans(big)[0]["text"], "x")
        many = "".join("<color=red>a</color><color=green>b</color>" for _ in range(2000))
        self.assertLessEqual(len(spans(many)), rt.MAX_SPANS)
        self.assertLessEqual(sum(len(s["text"]) for s in spans("a" * 100000)), rt.MAX_CHARS)
        for h in ("<", ">", "<>", "<b", "<color=", "<link=\"", "\x00<b>\x07z</b>", "<sprite name=>", "&lt;b&gt;"):
            self.ok(spans(h) or None)
        self.assertEqual(spans("\x00\x07z")[0]["text"], "z")

    def test_plain_text_for_titles(self):
        self.assertEqual(rt.plain_text('<b>Low</b> <color=red>air</color>\n(2)'), "Low air (2)")
        self.assertEqual(rt.plain_text(None), "")
        self.assertEqual(len(rt.plain_text("x" * 1000)), 200)


def alert(**kw):
    a = {"id": "a1", "level": "bad", "text": "Low air", "cycle": 12, "count": 2, "title": "Low air (2)", "type": "bad",
         "tooltipMarkup": '<b>Low air</b>\n<link="0"><color=#F48C8C>Ada</color></link> is holding her breath\n'
                          '<link="1"><color=#F48C8C>Bea</color></link> is short\n<sprite name="oxygen"> Build one',
         "links": [{"index": 0, "label": "Ada is holding her breath", "kind": "focus"},
                   {"index": 1, "label": "Bea is short", "kind": "none"}],
         "click": {"kind": "focus"}, "dismissable": False}
    a.update(kw)
    return a


class Pages(unittest.TestCase):
    def check(self, scr):
        self.assertEqual(V.validate(scr, "screen.schema.json"), [])
        json.dumps(scr, allow_nan=False)

    def test_page_with_links_open_and_no_dismiss(self):
        scr = av.alert_screen(alert(), (), HAS_UI)
        self.check(scr)
        self.assertEqual(scr["title"], "Low air (2)")
        self.assertEqual(scr["refreshOn"], ["colony", "action"])
        sp = scr["blocks"][0]["spans"]
        acts = [s["action"]["args"] for s in sp if "action" in s]
        self.assertEqual(acts, [{"alertId": "a1", "link": 0}])        # link 1 has kind none: no action
        self.assertIn("/api/v1/art/ui/sprite-oxygen", [s.get("icon") for s in sp])
        ids = [a["id"] for a in B_actions(scr)]
        self.assertEqual(ids.count("alert_activate"), 1)               # Open in game (the link action sits on its span)
        self.assertNotIn("alert_dismiss", ids)

    def test_no_open_button_when_click_none_and_no_art_when_missing(self):
        scr = av.alert_screen(alert(click={"kind": "none"}, links=[], tooltipMarkup="Hello <sprite name=\"x\">"), (), NO_UI)
        self.check(scr)
        self.assertEqual(B_actions(scr), [])
        self.assertEqual(scr["blocks"][0]["spans"], [{"type": "plain", "text": "Hello"}])

    def test_screen_click_text(self):
        scr = av.alert_screen(alert(click={"kind": "screen", "target": "research"}), (), None)
        item = [b for b in scr["blocks"] if b["type"] == "list"][0]["items"][0]
        self.assertEqual(item["subtitle"], "Opens the Research screen in the game")

    def test_dismiss_only_when_dismissable_and_dismissing_state(self):
        d = alert(dismissable=True, click={"kind": "none"})
        scr = av.alert_screen(d, (), None)
        self.check(scr)
        a = B_actions(scr)
        self.assertEqual([(x["id"], x.get("danger")) for x in a], [("alert_dismiss", True)])
        self.assertNotIn("trigger", a[0])                                # on the page it is an ordinary button
        scr2 = av.alert_screen(d, {"a1"}, None)
        self.check(scr2)
        self.assertEqual(B_actions(scr2), [])
        self.assertIn(av.DISMISSING, json.dumps(scr2, ensure_ascii=False))

    def test_fallback_when_markup_missing(self):
        scr = av.alert_screen({"id": "x", "level": "info", "text": "Plain only"}, (), None)
        self.check(scr)
        self.assertEqual(scr["blocks"][0]["spans"][0]["text"], "Plain only")

    def test_non_numeric_link_ids_follow_order(self):
        a = alert(links=[{"index": 0, "label": "A", "kind": "focus"}, {"index": 1, "label": "B", "kind": "focus"}],
                  tooltipMarkup='<link="BuildingA">one</link> <link="BuildingB">two</link> <link="BuildingA">again</link>')
        sp = av.alert_spans(a, None)
        self.assertEqual([s["action"]["args"]["link"] for s in sp if "action" in s], [0, 1, 0])

    def test_strip_items(self):
        alerts = [alert(), alert(id="a2", level="warning", title="No Research Focus", type="minorBad", count=1,
                                dismissable=True), alert(id="a3", level="info", title="<b>Hi</b>", dismissable=True)]
        items = av.alert_items(alerts, {"a3"}, lambda n: n == "alertBad")
        self.assertEqual([i["title"] for i in items], ["Low air (2)", "No Research Focus", "Hi"])
        self.assertEqual(items[0]["ref"], {"kind": "alert", "id": "a1"})
        self.assertEqual(items[0]["badge"], "x2")
        self.assertEqual(items[0]["art"], "/api/v1/art/ui/alertBad")
        self.assertNotIn("art", items[1])
        self.assertNotIn("actions", items[0])                              # not dismissable
        self.assertEqual(items[1]["actions"][0]["trigger"], "longPress")
        self.assertEqual(items[2]["subtitle"], av.DISMISSING)
        self.assertNotIn("actions", items[2])
        self.check(B.screen("t", [B.list_block(items, variant="alerts")]))

    def test_real_style_ids_with_bars_and_spaces(self):
        a = {"id": "0|warning|New Printables are available", "level": "warning", "text": "New Printables are available",
             "cycle": 420, "count": 1}
        items = av.alert_items([a], (), None)
        self.assertEqual(items[0]["title"], "New Printables are available")
        self.assertEqual(items[0]["ref"]["id"], a["id"])
        self.check(av.alert_screen(a, (), None))


def B_actions(scr):
    out = []
    for b in B.walk_blocks(scr["blocks"]):
        for it in b.get("items") or []:
            out += it.get("actions") or []
    return out


class Provider(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="oni-c11-")
        self.live = os.path.join(self.tmp, "live.json")
        d = load_json("mod", "live-running-v2.json")
        d["writtenAt"] = colony_mod.iso(__import__("time").time())
        with open(self.live, "w") as f:
            json.dump(d, f)
        self.ctx = FakeCtx(self.live)
        self.views = Views(self.ctx, lookup=synthetic_lookup())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_colony_strip_and_pages(self):
        scr = self.views.colony(None)
        self.assertEqual(V.validate(scr, "screen.schema.json"), [])
        items = [b for b in scr["blocks"] if b.get("variant") == "alerts"][0]["items"]
        self.assertEqual({i["ref"]["id"] for i in items}, {"a1", "a2", "a3"})
        for i in items:
            page = self.views.entry("alert", i["ref"]["id"])
            self.assertEqual(V.validate(page, "screen.schema.json"), [])
        self.assertEqual(self.views.entry("alert", "a3")["blocks"][-1]["items"][0]["actions"][0]["id"], "alert_dismiss")

    def test_gone_alert_is_404(self):
        with self.assertRaises(ApiError) as cm:
            self.views.entry("alert", "nope")
        self.assertEqual(cm.exception.code, "not_found")

    def test_fixtures_are_what_the_core_builds(self):
        want = load_json("screens", "alert-page-dismissable.json")
        got = self.views.entry("alert", "a3")
        self.assertEqual(got["blocks"][1], want["blocks"][1])           # the Dismiss list
        self.assertEqual(got["blocks"][0]["spans"][0], want["blocks"][0]["spans"][0])


class Actions(unittest.TestCase):
    def setUp(self):
        import time
        self.tmp = tempfile.mkdtemp(prefix="oni-c11a-")
        self.comp = os.path.join(self.tmp, "companion")
        os.makedirs(os.path.join(self.comp, "live"))
        self.now = time.time()
        d = load_json("mod", "live-running-v2.json")
        d["writtenAt"] = colony_mod.iso(self.now)
        self.write_live(d)
        self.events = []
        self.svc = ActionService(self.comp, self.events.append, expire=5, clock=lambda: self.now)

    def write_live(self, d):
        with open(os.path.join(self.comp, "live", "live.json"), "w") as f:
            json.dump(d, f)

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cmd(self, seq):
        with open(os.path.join(self.comp, "commands", "cmd-%d.json" % seq)) as f:
            return json.load(f)

    def ack(self, seq, state="done", message=None):
        d = {"schema": 1, "seq": seq, "ackedAt": colony_mod.iso(self.now), "state": state}
        if message:
            d["message"] = message
        p = os.path.join(self.comp, "acks", "ack-%d.json" % seq)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(d, f)
        self.svc.handle_file(p)

    def test_activate_main_and_link_commands_validate(self):
        s1 = self.svc.post("alert_activate", {"alertId": "a1"})["seq"]
        s2 = self.svc.post("alert_activate", {"alertId": "a1", "link": 1})["seq"]
        self.assertEqual(self.cmd(s1)["type"], "alert_activate")
        self.assertNotIn("link", self.cmd(s1))
        self.assertEqual(self.cmd(s2)["link"], 1)
        for s in (s1, s2):
            self.assertEqual(V.validate(self.cmd(s), "mod-command.schema.json"), [])

    def test_bad_bodies(self):
        bads = [({}, "bad_request"), ({"alertId": ""}, "bad_request"), ({"alertId": 5}, "bad_request"),
                ({"alertId": "a1", "link": -1}, "bad_request"), ({"alertId": "a1", "link": True}, "bad_request"),
                ({"alertId": "a1", "link": "0"}, "bad_request"), ({"alertId": "a1", "link": 9}, "bad_request"),
                ({"alertId": "a1", "path": "/x"}, "bad_request"), ({"alertId": "zzz"}, "not_found"), ([], "bad_request")]
        for b, code in bads:
            with self.assertRaises(ApiError) as cm:
                self.svc.post("alert_activate", b)
            self.assertEqual(cm.exception.code, code, b)
        self.assertFalse(os.path.exists(os.path.join(self.comp, "commands")))

    def test_dismiss_rules(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.post("alert_dismiss", {"alertId": "a1"})                     # not dismissable
        self.assertEqual((cm.exception.code, str(cm.exception.message)), ("bad_request", "Can't be dismissed."))
        with self.assertRaises(ApiError):
            self.svc.post("alert_dismiss", {"alertId": "a3", "link": 0})
        seq = self.svc.post("alert_dismiss", {"alertId": "a3"})["seq"]
        self.assertEqual(V.validate(self.cmd(seq), "mod-command.schema.json"), [])
        self.assertNotIn("link", self.cmd(seq))

    def test_dismissing_lifecycle(self):
        present = {"a1", "a2", "a3"}
        self.assertEqual(self.svc.dismissing(present), set())
        seq = self.svc.post("alert_dismiss", {"alertId": "a3"})["seq"]
        self.assertEqual(self.svc.dismissing(present), {"a3"})                    # pending
        self.ack(seq)
        self.assertEqual(self.svc.dismissing(present), {"a3"})                    # done, game has not dropped it yet
        self.assertEqual(self.svc.dismissing({"a1", "a2"}), set())                # gone from live.json: state ends
        seq = self.svc.post("alert_dismiss", {"alertId": "a3"})["seq"]
        self.ack(seq, "failed", "Can't be dismissed")
        self.assertEqual(self.svc.dismissing(present), set())                     # failed: back to normal

    def test_dismissing_stuck_and_expired(self):
        present = {"a3"}
        seq = self.svc.post("alert_dismiss", {"alertId": "a3"})["seq"]
        self.ack(seq)
        self.now += 25
        self.assertEqual(self.svc.dismissing(present), set())                     # done but never left: not stuck forever
        d = load_json("mod", "live-running-v2.json")
        d["writtenAt"] = colony_mod.iso(self.now)
        self.write_live(d)
        seq = self.svc.post("alert_dismiss", {"alertId": "a3"})["seq"]
        self.svc._expire(seq)
        self.assertEqual(self.svc.dismissing(present), set())

    def test_unavailable_in_menu(self):
        d = load_json("mod", "live-menu.json")
        d["writtenAt"] = colony_mod.iso(self.now)
        self.write_live(d)
        with self.assertRaises(ApiError) as cm:
            self.svc.post("alert_activate", {"alertId": "a1"})
        self.assertEqual(cm.exception.code, "unavailable")

    def test_allow_list(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.post("set_speed", {})
        self.assertEqual(cm.exception.code, "not_found")


class MalformedAlerts(unittest.TestCase):
    BAD = [{"count": "3"}, {"count": None}, {"level": {}}, {"type": ["x"]}, {"cycle": "5"}, {"cycle": None},
           {"click": {"kind": "screen", "target": ["research"]}}, {"click": {"kind": "screen", "target": 7}},
           {"count": True}, {"id": "b2"}]

    def test_nothing_raises_and_pages_validate(self):
        for kw in self.BAD:
            a = alert(**kw)
            items = av.alert_items([a, "junk", None], has_ui=HAS_UI)
            self.assertEqual(len(items), 1, kw)
            scr = av.alert_screen(a, has_ui=HAS_UI)
            self.assertEqual(V.validate(scr, "screen.schema.json"), [], kw)


if __name__ == "__main__":
    unittest.main()
