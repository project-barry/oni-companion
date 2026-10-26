import json
import os
import re
import unittest

from tests.jsonschema_mini import SchemaError, Validator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "contracts")
FIX = os.path.join(ROOT, "fixtures", "synthetic")
SCHEMAS = ["blocks.schema.json", "screen.schema.json", "api.schema.json",
           "mod-export.schema.json", "mod-live.schema.json", "mod-art-manifest.schema.json",
           "mod-command.schema.json", "mod-ack.schema.json", "theme.schema.json", "pairing.schema.json",
           "settings.schema.json", "mod-sync-status.schema.json", "font-atlas.schema.json"]
BLOCK_TYPES = {"heading", "text", "stats", "chips", "list", "grid", "ports", "phases",
               "progress", "table", "notice", "form", "link", "divider", "group", "image", "picker"}
KINDS = {"element", "building", "critter", "plant", "geyser", "food", "medicine",
         "recipe", "tech", "trait", "skill", "room", "codex", "dupe", "alert"}


def load_manifest():
    with open(os.path.join(FIX, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)["fixtures"]


def walk_blocks(blocks):
    for b in blocks:
        yield b
        if b.get("type") == "group":
            yield from walk_blocks(b["blocks"])


def walk_refs(node):
    if isinstance(node, dict):
        if set(node) == {"kind", "id"}:
            yield node
        for v in node.values():
            yield from walk_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_refs(v)


class ContractFiles(unittest.TestCase):
    def test_schemas_are_wellformed(self):
        v = Validator(CONTRACTS)
        for name in SCHEMAS:
            v.check_schema(name)

    def test_block_list_is_the_documented_one(self):
        v = Validator(CONTRACTS)
        defs = v.doc("blocks.schema.json")["$defs"]
        types = set()
        for name, d in defs.items():
            t = d.get("properties", {}).get("type", {}).get("const")
            if t and name not in ("Span",):
                types.add(t)
        self.assertEqual(types, BLOCK_TYPES)
        self.assertEqual(set(defs["Kind"]["enum"]), KINDS)

    def test_api_md_endpoints_have_fixtures(self):
        with open(os.path.join(CONTRACTS, "api.md"), encoding="utf-8") as f:
            text = f.read()
        section = text.split("## Endpoints")[1].split("### Screens")[0]
        endpoints = set()
        for m in re.finditer(r"^\| `((?:GET|POST|DELETE) [^`?]+)", section, re.M):
            endpoints.add(m.group(1).strip())
        self.assertEqual(len(endpoints), 38, endpoints)
        covered = {e["endpoint"] for e in load_manifest() if "endpoint" in e}
        self.assertEqual(endpoints, covered)

    def test_no_pairing_endpoints_in_v1_table(self):
        with open(os.path.join(CONTRACTS, "api.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Planned, not in v1", text)
        self.assertIsNone(re.search(r"/pair(/|\b)", text.split("## Planned")[0]))


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = Validator(CONTRACTS)
        cls.entries = load_manifest()

    def test_every_fixture_validates(self):
        for e in self.entries:
            if "schema" not in e:
                continue
            with open(os.path.join(FIX, e["path"]), encoding="utf-8") as f:
                data = json.load(f)
            errs = self.v.validate(data, e["schema"])
            self.assertEqual(errs, [], "%s: %s" % (e["path"], errs[:5]))

    def test_every_json_file_is_in_manifest(self):
        listed = {e["path"] for e in self.entries if e["path"].endswith(".json")}
        found = set()
        for d, _, fs in os.walk(FIX):
            for fn in fs:
                rel = os.path.relpath(os.path.join(d, fn), FIX)
                if fn.endswith(".json") and rel != "manifest.json":
                    found.add(rel)
        self.assertEqual(found, listed)

    def test_every_schema_has_a_fixture(self):
        used = {e["schema"].split("#")[0] for e in self.entries if "schema" in e}
        # blocks are covered through screens
        self.assertEqual(used, set(SCHEMAS) - {"blocks.schema.json"})

    def test_every_block_type_and_kind_appears(self):
        types, kinds = set(), set()
        for e in self.entries:
            if e.get("schema") not in ("screen.schema.json", "api.schema.json#/$defs/ColonyReply"):
                continue
            with open(os.path.join(FIX, e["path"]), encoding="utf-8") as f:
                scr = json.load(f)
            for b in walk_blocks(scr["blocks"]):
                types.add(b["type"])
            for r in walk_refs(scr):
                kinds.add(r["kind"])
        self.assertEqual(types, BLOCK_TYPES)
        self.assertEqual(kinds, KINDS)

    def test_no_real_paths_or_names(self):
        for e in self.entries:
            if "schema" not in e:
                continue
            with open(os.path.join(FIX, e["path"]), encoding="utf-8") as f:
                raw = f.read()
            self.assertNotIn("/Users/", raw)
            self.assertNotIn("konkr", raw.lower())


def sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def png_size(path):
    import struct
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


class V11Fixtures(unittest.TestCase):
    """The v1.1 fixtures tie together: manifest hashes, PNGs, ids, ack/command pairs."""

    @classmethod
    def setUpClass(cls):
        cls.comp = os.path.join(FIX, "companion")
        with open(os.path.join(cls.comp, "art", "manifest.json"), encoding="utf-8") as f:
            cls.art = json.load(f)

    def test_art_manifest_matches_files(self):
        self.assertTrue(self.art["files"])
        for f in self.art["files"]:
            path = os.path.join(self.comp, "art", f["path"])
            self.assertEqual(os.path.getsize(path), f["size"], f["path"])
            self.assertEqual(sha(path), f["sha256"], f["path"])
            self.assertEqual(png_size(path), (f["width"], f["height"]), f["path"])
            self.assertTrue(f["path"].startswith("%d/%s/" % (self.art["build"], f["kind"])))

    def test_reply_png_fixture_is_a_png(self):
        for e in load_manifest():
            if e.get("image") == "png":
                png_size(os.path.join(FIX, e["path"]))

    def test_theme_files_exist(self):
        with open(os.path.join(self.comp, "theme", "100001", "theme.json"), encoding="utf-8") as f:
            th = json.load(f)
        for s in th["slices"]:
            self.assertEqual(png_size(os.path.join(self.comp, "theme", "100001", s["file"])),
                             (s["width"], s["height"]))

    def test_dupe_portraits_follow_live_v2(self):
        with open(os.path.join(FIX, "mod", "live-running-v2.json"), encoding="utf-8") as f:
            live = json.load(f)
        hashes = {d["id"]: d["appearanceHash"] for w in live["worlds"] for d in w["dupes"]}
        portraits = {f["id"]: f["appearanceHash"] for f in self.art["files"] if f["kind"] == "dupe"}
        self.assertEqual(hashes, portraits)

    def test_v1_live_fixture_stays_schema_1(self):
        with open(os.path.join(FIX, "mod", "live-running.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["schema"], 1)

    def test_ack_matches_command(self):
        self.assertTrue(os.path.exists(os.path.join(self.comp, "commands", "cmd-5.json")))
        self.assertTrue(os.path.exists(os.path.join(self.comp, "acks", "ack-5.json")))

    def test_onopen_only_in_the_onopen_page(self):
        with open(os.path.join(FIX, "screens", "dupe-page.json"), encoding="utf-8") as f:
            self.assertNotIn("onOpen", json.load(f))
        with open(os.path.join(FIX, "screens", "dupe-page-onopen.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["onOpen"][0]["action"], "focus")

    def test_no_game_art_words(self):
        with open(os.path.join(self.comp, "art", "manifest.json"), encoding="utf-8") as f:
            for fl in json.load(f)["files"]:
                self.assertTrue(fl["id"].startswith("Synth") or fl["id"].startswith("d"), fl["id"])


class Negatives(unittest.TestCase):
    """The contracts must reject bad data, otherwise the fixtures prove nothing."""

    @classmethod
    def setUpClass(cls):
        cls.v = Validator(CONTRACTS)

    def ok(self, data, schema="screen.schema.json"):
        return self.v.validate(data, schema)

    def screen(self, *blocks):
        return {"schema": 1, "title": "T", "blocks": list(blocks)}

    def test_unknown_block_type_rejected(self):
        self.assertTrue(self.ok(self.screen({"type": "sparkle"})))

    def test_layout_fields_rejected(self):
        self.assertTrue(self.ok(self.screen({"type": "divider", "color": "red"})))
        self.assertTrue(self.ok(self.screen({"type": "heading", "text": "x", "fontSize": 20})))

    def test_table_max_6_columns(self):
        t = {"type": "table", "columns": list("abcdefg"), "rows": []}
        self.assertTrue(self.ok(self.screen(t)))

    def test_bad_ref_kind(self):
        b = {"type": "list", "items": [{"title": "x", "ref": {"kind": "spaceship", "id": "a"}}]}
        self.assertTrue(self.ok(self.screen(b)))

    def test_external_link_must_be_https(self):
        self.assertTrue(self.ok(self.screen({"type": "link", "label": "x", "url": "http://example.com"})))
        self.assertTrue(self.ok(self.screen({"type": "link", "label": "x", "url": "javascript:alert(1)"})))

    def test_schema_version(self):
        self.assertTrue(self.ok({"schema": 2, "title": "T", "blocks": []}))

    def test_live_running_needs_fields(self):
        bad = {"schema": 1, "seq": 1, "state": "running", "writtenAt": "2026-01-01T00:00:00Z", "modVersion": "1"}
        self.assertTrue(self.ok(bad, "mod-live.schema.json"))
        menu = dict(bad, state="menu")
        self.assertEqual(self.ok(menu, "mod-live.schema.json"), [])

    def test_amount_needs_element_or_tag(self):
        self.assertTrue(self.ok({"kg": 1}, "mod-export.schema.json#/$defs/Amount"))
        self.assertTrue(self.ok({"kg": 1, "element": "a", "tag": "b"}, "mod-export.schema.json#/$defs/Amount"))
        self.assertEqual(self.ok({"kg": 1, "tag": "b"}, "mod-export.schema.json#/$defs/Amount"), [])

    def test_bad_datetime(self):
        self.assertTrue(self.ok({"seq": 1}, "api.schema.json#/$defs/Events"))
        self.assertTrue(self.ok({"schema": 1, "title": "T", "asOf": "yesterday", "blocks": []}))

    def test_error_codes(self):
        self.assertTrue(self.ok({"error": {"code": "teapot", "message": "x"}}, "api.schema.json#/$defs/Error"))

    def test_v11_negatives(self):
        v = self.ok
        # art must be a core path, not a URL or a file path
        for bad in ("https://example.com/a.png", "/tmp/a.png", "/api/v1/art/dupe/a?token=x"):
            self.assertTrue(v(self.screen({"type": "image", "art": bad})), bad)
        self.assertTrue(v(self.screen({"type": "image", "art": "/api/v1/art/dupe/d1", "size": "huge"})))
        self.assertTrue(v(self.screen({"type": "image"})))
        self.assertTrue(v(self.screen({"type": "grid", "cards": [{"title": "x", "badges": [{"level": "red", "label": "x"}]}]})))
        self.assertTrue(v(self.screen({"type": "list", "items": [{"title": "x", "actions": [{"id": "Focus", "label": "x"}]}]})))
        self.assertTrue(v({"schema": 1, "title": "T", "blocks": [], "onOpen": [{"args": {}}]}))
        self.assertTrue(v({"schema": 1, "title": "T", "blocks": [], "refreshOn": ["nope"]}))
        # commands: allow list of one, no extra fields
        cmd = {"schema": 1, "seq": 1, "createdAt": "2026-01-01T00:00:00Z", "type": "focus", "target": {"kind": "dupe", "id": "d1"}}
        self.assertEqual(v(cmd, "mod-command.schema.json"), [])
        self.assertTrue(v(dict(cmd, type="delete"), "mod-command.schema.json"))
        self.assertTrue(v(dict(cmd, path="/etc/passwd"), "mod-command.schema.json"))
        self.assertTrue(v(dict(cmd, target={"kind": "building", "id": "x"}), "mod-command.schema.json"))
        self.assertTrue(v({"schema": 1, "seq": 1, "state": "expired", "ackedAt": "2026-01-01T00:00:00Z"}, "mod-ack.schema.json"))
        self.assertTrue(v({"values": {"zoomToDupeOnSelect": "yes"}}, "api.schema.json#/$defs/SettingsPost"))
        self.assertTrue(v({"schema": 1, "zoomToDupeOnSelect": 1}, "settings.schema.json"))
        self.assertTrue(v({"seq": 1, "state": "running"}, "api.schema.json#/$defs/ActionStatus"))
        self.assertTrue(v({"colors": {}}, "theme.schema.json#/$defs/Colors"))
        # live: schema 3 and bad severity are rejected; schema 1 map and schema 2 list both pass
        base = {"schema": 3, "seq": 1, "state": "menu", "writtenAt": "2026-01-01T00:00:00Z", "modVersion": "1"}
        self.assertTrue(v(base, "mod-live.schema.json"))
        self.assertTrue(v({"severity": "terrible", "id": "a", "name": "b"}, "mod-live.schema.json#/$defs/StatusItem"))
        self.assertTrue(v({"id": "a", "name": "b", "category": "Metal", "amount": 1, "unit": "lb"}, "mod-live.schema.json#/$defs/ResourceItem"))

    def test_validator_rejects_unsupported_keywords(self):
        v = Validator(CONTRACTS)
        v.docs["x.json"] = {"patternProperties": {}}
        with self.assertRaises(SchemaError):
            v.validate({}, "x.json")


if __name__ == "__main__":
    unittest.main()


class V12Fixtures(unittest.TestCase):
    """The v1.2 fixtures tie together: alerts, commands, speed, sync, fonts. Synthetic only."""

    @classmethod
    def setUpClass(cls):
        cls.comp = os.path.join(FIX, "companion")

    def j(self, *parts):
        with open(os.path.join(FIX, *parts), encoding="utf-8") as f:
            return json.load(f)

    def test_command_allow_list_has_a_fixture_each(self):
        v = Validator(CONTRACTS)
        allowed = set()
        for d in v.doc("mod-command.schema.json")["$defs"].values():
            allowed.add(d["properties"]["type"]["const"])
        used = set()
        for fn in os.listdir(os.path.join(self.comp, "commands")):
            used.add(self.j("companion", "commands", fn)["type"])
        self.assertEqual(allowed, {"focus", "art_request", "alert_activate", "alert_dismiss",
                                   "set_speed", "sync_assets", "overlay_set", "tool_select",
                                   "build_select"})
        self.assertEqual(used, allowed)

    def test_alert_links_and_refs_line_up(self):
        live = self.j("mod", "live-running-v2.json")
        alerts = {a["id"]: a for w in live["worlds"] for a in w["alerts"]}
        for a in alerts.values():
            self.assertEqual([l["index"] for l in a.get("links", [])],
                             list(range(len(a.get("links", [])))))
            for l in a.get("links", []):
                self.assertIn('<link="%d">' % l["index"], a["tooltipMarkup"])
        self.assertTrue(any(a.get("dismissable") for a in alerts.values()))
        self.assertTrue(any(not a.get("dismissable") for a in alerts.values()))
        for name in ("colony-alerts.json", "alert-page.json", "alert-page-dismissable.json"):
            scr = self.j("screens", name)
            for r in walk_refs(scr):
                if r["kind"] == "alert":
                    self.assertIn(r["id"], alerts)
            for node in _walk(scr):
                args = node.get("args") if isinstance(node, dict) else None
                if args and "alertId" in args:
                    self.assertIn(args["alertId"], alerts)
                    if "link" in args:
                        self.assertLess(args["link"], len(alerts[args["alertId"]]["links"]))

    def test_dismiss_is_long_press_and_only_for_dismissable(self):
        live = self.j("mod", "live-running-v2.json")
        dism = {a["id"]: a.get("dismissable", False) for w in live["worlds"] for a in w["alerts"]}
        scr = self.j("screens", "colony-alerts.json")
        found = 0
        for node in _walk(scr):
            if isinstance(node, dict) and node.get("id") == "alert_dismiss":
                found += 1
                self.assertTrue(dism[node["args"]["alertId"]])
        self.assertGreaterEqual(found, 1)
        trig = [n.get("trigger") for n in _walk(scr) if isinstance(n, dict) and n.get("id") == "alert_dismiss"]
        self.assertEqual(trig, ["longPress"])

    def test_sync_status_counts(self):
        for name in ("status.json", "status-done.json"):
            st = self.j("companion", "sync", name)
            self.assertLessEqual(st["done"], st["total"])
        self.assertEqual(self.j("companion", "sync", "status-done.json")["done"],
                         self.j("companion", "sync", "status-done.json")["total"])

    def test_theme_roles_and_icons_point_at_listed_things(self):
        th = self.j("api", "theme-v12.json")
        names = {f["name"] for f in self.j("api", "fonts.json")["fonts"]}
        for role in th["font"]["roles"].values():
            self.assertIn(role["font"], names)
        for ic in th["icons"]:
            self.assertEqual(ic["art"], "/api/v1/art/ui/" + ic["name"])
        mod = self.j("companion-v12", "theme", "100001", "theme.json")
        self.assertEqual({i["name"] for i in mod["icons"]}, {i["name"] for i in th["icons"]})
        for i in mod["icons"]:
            self.assertEqual(png_size(os.path.join(FIX, "companion-v12", "theme", "100001", i["file"])),
                             (i["width"], i["height"]))

    def test_font_atlas_fixture_is_consistent(self):
        at = self.j("companion", "fonts", "100001", "graystroke.json")
        w, h = at["atlas"]["width"], at["atlas"]["height"]
        self.assertEqual(png_size(os.path.join(self.comp, "fonts", "100001", at["atlas"]["file"])), (w, h))
        codes = [g["unicode"] for g in at["glyphs"]]
        self.assertEqual(codes, sorted(codes))
        for g in at["glyphs"]:
            self.assertLessEqual(g["x"] + g["w"], w)
            self.assertLessEqual(g["y"] + g["h"], h)

    def test_synthetic_font_is_a_valid_sfnt(self):
        import struct
        with open(os.path.join(self.comp, "fonts", "100001", "SynthSans.ttf"), "rb") as f:
            data = f.read()
        ver, n = struct.unpack(">IH", data[:6])
        self.assertEqual(ver, 0x00010000)
        tables = {}
        for i in range(n):
            tag, _cs, off, ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
            self.assertLessEqual(off + ln, len(data))
            tables[tag.decode()] = (off, ln)
        for need in ("cmap", "head", "hhea", "hmtx", "maxp", "name"):
            self.assertIn(need, tables)
        off, _ = tables["head"]
        self.assertEqual(struct.unpack(">I", data[off + 12:off + 16])[0], 0x5F0F3CF5)
        whole = data + b"\0" * (-len(data) % 4)
        self.assertEqual(sum(struct.unpack(">%dI" % (len(whole) // 4), whole)) & 0xFFFFFFFF, 0xB1B0AFBA)
        off, ln = tables["name"]
        self.assertIn("Synth Sans".encode("utf-16-be"), data[off:off + ln])

    def test_no_klei_names_in_font_fixtures(self):
        for d, _, fs in os.walk(os.path.join(self.comp, "fonts")):
            for fn in fs:
                if fn.endswith(".json"):
                    raw = open(os.path.join(d, fn), encoding="utf-8").read().lower()
                    for bad in ("klei", "graystroke regular", "noto"):
                        self.assertNotIn(bad, raw)


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


class V14Pairing(unittest.TestCase):
    """v1.4 contracts tie together: QR text, mDNS TXT keys, state and request files, the secrets rule."""

    @classmethod
    def setUpClass(cls):
        cls.v = Validator(CONTRACTS)

    def load(self, rel):
        with open(os.path.join(FIX, rel), encoding="utf-8") as f:
            return json.load(f)

    def test_qr_text_is_compact_valid_payload(self):
        st = self.load("companion/pairing/state.json")
        text = st["qrText"]
        self.assertLessEqual(len(text.encode("utf-8")), 400)
        payload = json.loads(text)
        self.assertEqual(text, json.dumps(payload, separators=(",", ":")))
        self.assertEqual(self.v.validate(payload, "pairing.schema.json#/$defs/QrPayload"), [])
        self.assertEqual(payload["f"], st["identity"]["fingerprint"])
        self.assertEqual(payload["i"], st["identity"]["instanceId"])
        self.assertEqual(payload["c"], st["code"]["display"].replace("-", ""))
        self.assertEqual(payload["a"], [a["address"] for a in st["addresses"]])
        self.assertEqual(payload, self.load("pairing/qr-payload.json"))

    def test_mdns_txt_has_only_the_four_keys_and_matches_identity(self):
        txt = self.load("pairing/mdns-txt.json")
        self.assertEqual(set(txt), {"id", "name", "api", "core"})
        ident = self.load("api/identity.json")
        self.assertEqual(txt["id"], ident["instanceId"])
        self.assertEqual(txt["name"], ident["name"])
        self.assertEqual(txt["core"], ident["coreVersion"])

    def test_off_state_has_no_secrets(self):
        st = self.load("companion/pairing/state-off.json")
        self.assertFalse(st["enabled"])
        self.assertEqual((st["addresses"], st["code"], st["qrText"]), ([], None, None))

    def test_fingerprint_tag_is_fingerprint_start(self):
        for rel in ("api/identity.json", "companion/pairing/state.json"):
            d = self.load(rel)
            ident = d.get("identity", d)
            self.assertEqual(ident["fingerprintTag"], ident["fingerprint"][:4].upper())

    def test_state_never_holds_a_device_token(self):
        raw = open(os.path.join(FIX, "companion/pairing/state.json"), encoding="utf-8").read()
        self.assertNotIn("deviceToken", raw)
        self.assertNotIn("token", raw.lower())

    def test_request_files_match_their_names(self):
        d = os.path.join(FIX, "companion/pairing/requests")
        types = set()
        for fn in os.listdir(d):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                r = json.load(f)
            self.assertEqual(fn, "req-%d.json" % r["seq"])
            types.add(r["type"])
        self.assertEqual(types, {"set_enabled", "new_code", "remove_device", "reset_identity", "set_plain_http"})
