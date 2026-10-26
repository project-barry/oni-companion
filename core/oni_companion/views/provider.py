"""The views object the server calls (see server/stub_views.py for the method list).

make_views(ctx) is the single boundary. ctx gives .cfg (user_dir, game_dir), .colony and .bus.
The game data is loaded on first use and again when the bus reports a `gamedata` change.
Game data stays out of the repo: it is read from the user's own install at run time.
"""
import os
import threading

from .. import __version__
from .. import config as oni_config
from ..art import decorate
from .. import modstate
from .. import pad as pad_rules
from .. import theme as oni_theme
from ..gamedata import load_dataset
from ..server.errors import ApiError
from ..colony import parse_iso as colony_parse_iso
from ..settings import Settings, SettingsError
from ..tools.names import tag_names
from ..tools import DataProblem, ToolError, UnknownTool, form_screen, list_tools, run_tool
from . import alerts as alert_view
from . import buildings as buildings_view
from . import colony as colony_view
from . import entry as entry_view
from . import listing
from . import pad as pad_view
from . import resources as resources_view
from . import settings_view
from .lookup import Lookup

TOOL_DATA_KEYS = {"elements": "element", "buildings": "building", "critters": "critter", "plants": "plant",
                  "geysers": "geyser", "foods": "food", "medicines": "medicine", "recipes": "recipe"}


def make_views(ctx):
    v = Views(ctx)
    v.start_history()
    return v


class Views:
    def __init__(self, ctx, lookup=None, config=None):
        self.ctx = ctx
        self._cfg = config
        self._cfg_auto = False             # True when this object built the config itself (then it follows ctx.cfg.user_dir)
        self._lk = lookup
        self._error = None
        self._lock = threading.Lock()
        self._seq = 0
        self._tool_data = None
        self.history = resources_view.ResourceHistory()
        self.art_for = None                 # optional callable (artKind, id) -> art path; set by the art lane
        store = getattr(ctx, "art", None)
        if store is not None and getattr(store, "ui_lookup", None) is None:
            store.ui_lookup = self._ui_image
        self._fixed = lookup is not None    # a lookup handed in (tests, previews) is never reloaded

    # ---- data
    def _config(self):
        cc = getattr(self.ctx, "cfg", None)
        if self._cfg is None or (self._cfg_auto and getattr(cc, "user_dir", None)
                                 and self._cfg.user_dir != cc.user_dir):
            # the first time, and again when the service follows the game into another ONI folder (plan 4.3)
            self._cfg = oni_config.load(game_dir=getattr(cc, "game_dir", None) or None,
                                        user_dir=getattr(cc, "user_dir", None) or None)
            self._cfg_auto = True
            if not self._fixed:
                self._lk = None
                self._error = None
        return self._cfg

    def _theme_dir(self):
        """Theme files come from the core's shared copy when the service keeps one (plan 4.3), else from the ONI folder."""
        f = getattr(self.ctx, "theme_root", None)
        return f() if callable(f) else self._config().companion_dir

    def _stale(self):
        bus = getattr(self.ctx, "bus", None)
        if bus is None:
            return False
        if not self._seq:
            self._seq = bus.seq
            return False
        r = bus.wait(self._seq, 0)
        self._seq = r["seq"]
        return "gamedata" in r["changed"]

    def lookup(self):
        """Lookup over the merged dataset, or ApiError(no_data)."""
        with self._lock:
            if self._fixed:
                return self._lk
            if self._stale():
                self._lk = None
                self._error = None
            if self._lk is None and self._error is None:
                cfg = self._config()
                try:
                    ds = load_dataset(cfg)
                    self._lk = Lookup(ds, cfg.assets_dir)
                    self._tool_data = None
                except FileNotFoundError as e:
                    self._error = str(e)
            if self._lk is None:
                raise ApiError("no_data", "ONI game files were not found.")
            return self._lk

    def _tooldata(self, lk):
        if self._tool_data is None:
            self._tool_data = {k: list(lk.kinds.get(kind, {}).values()) for k, kind in TOOL_DATA_KEYS.items()}
            self._tool_data["constants"] = dict(lk.meta.get("constants") or {})      # numbers the game defines (o2 tool)
            self._tool_data["names"] = tag_names(lk, self._config().assets_dir)      # diet tags in the game's words
        return self._tool_data

    def _art(self, screen, entry=None):
        """Adds art paths (nothing when the mod rendered no art) and removes the builders' art hooks."""
        return decorate(screen, getattr(self.ctx, "art", None), entry)

    @staticmethod
    def _src(lk):
        return "mod-export" if lk.meta.get("exportFiles") else "yaml"

    # ---- API
    def status(self):
        sf = self.ctx.colony.status_fields()
        game, cache = {"found": False}, {"state": "error"}
        mod = {"present": sf["livePresent"], "version": None, "exportFiles": [], "liveFresh": sf["liveFresh"]}
        try:
            lk = self.lookup()
        except ApiError:
            cache["message"] = "ONI game files were not found."
        else:
            m = lk.meta
            build = m.get("steamBuildId")
            if isinstance(build, str) and build.isdigit():
                build = int(build)
            game = {"found": True, "build": build if isinstance(build, int) else None,
                    "dlcInstalled": m.get("dlcInstalled") or [], "dlcExported": m.get("dlcExported") or [],
                    "dlcMissingExport": m.get("dlcMissingExport") or []}
            cache = {"state": "ready"}
            if m.get("builtAt"):
                cache["builtAt"] = m["builtAt"]
            mod["present"] = bool(m.get("exportFiles")) or sf["livePresent"]
            mod["version"] = m.get("modVersion")
            mod["exportFiles"] = list(m.get("exportFiles") or [])
        out = {"apiVersion": 1, "coreVersion": __version__, "game": game, "mod": mod, "cache": cache,
               "colony": sf["colony"], "newestSave": sf["newestSave"]}
        cfg = self._config()
        if cfg.user_dir:
            out["userDir"] = {"kind": cfg.user_dir_kind, "path": cfg.user_dir}
        out["modState"] = self.mod_state()
        return out

    # ---- v1.3: game mod state, tabs, Actions, Buildings
    def _meta(self):
        try:
            return self.lookup().meta
        except ApiError:
            return {}

    def _fresh_any(self, live):
        """The mod wrote recently: a running colony (the Colony model's rule) or a recent menu write."""
        col = getattr(self.ctx, "colony", None)
        if not isinstance(live, dict) or col is None:
            return False
        if col.live_fresh(live):
            return True
        written = col.clock() - (colony_parse_iso(live.get("writtenAt", "")) or 0)
        return live.get("state") == "menu" and written <= 15

    def _folders(self):
        fn = getattr(self.ctx, "all_user_dirs", None)
        if callable(fn):
            try:
                return fn() or []
            except Exception:
                pass
        return getattr(getattr(self.ctx, "cfg", None), "user_dirs", None) or []

    def _modstate(self):
        col = getattr(self.ctx, "colony", None)
        return modstate.ModState(self._config().user_dir, self._meta, lambda: col.read_live() if col else None,
                                 self._fresh_any,
                                 self.ctx.bundled_mod if hasattr(self.ctx, "bundled_mod") else modstate.bundled_dir(),
                                 folders=self._folders())

    def mod_state(self):
        return self._modstate().compute()

    def mod_install(self, body):
        if not isinstance(body, dict) or set(body) - {"confirm", "values"}:
            raise ApiError("bad_request", "Body must be {\"confirm\":true}.")
        if isinstance(body.get("values"), dict):
            body = body["values"]
        if body.get("confirm") is not True:
            raise ApiError("bad_request", "Ask the user first, then send {\"confirm\":true}.")
        ms = self._modstate()
        try:
            res = ms.install_all()
        except ValueError as e:
            raise ApiError("unavailable", str(e))
        except OSError:
            raise ApiError("unavailable", "The game's mods folder cannot be written.")
        bus = getattr(self.ctx, "bus", None)
        if bus is not None:
            bus.publish("status")
        act = self._config().user_dir
        paths = res["installed"]
        path = next((p for p in paths if p.startswith(os.path.join(act, "mods"))), paths[0]) if act else paths[0]
        return {"installed": True, "path": path, "paths": paths, "skipped": res["skipped"], "modState": ms.compute()}

    def tabs(self):
        label = "Database"
        try:
            label = self.lookup().codex_label
        except ApiError:
            pass
        return {"tabs": [
            {"id": "colony", "label": "Colony", "path": "colony"},
            {"id": "resources", "label": "Resources", "path": "resources"},
            {"id": "buildings", "label": "Buildings", "path": "buildings"},
            {"id": "actions", "label": "Actions", "path": "pad", "needsLive": True},
            {"id": "codex", "label": label, "path": "kinds", "excludeKinds": ["building"], "includesTools": True},
            {"id": "settings", "label": "Settings", "path": "settings"}]}

    def _avail(self):
        ctrl = getattr(self.ctx, "controls", None)
        if ctrl is not None:
            return pad_rules.live_ok(ctrl.availability())
        col = getattr(self.ctx, "colony", None)
        live = col.read_live() if col else None
        return (True, None) if col and col.live_fresh(live) else (False, pad_rules.NOT_RUNNING)

    def _live(self):
        col = getattr(self.ctx, "colony", None)
        return col.read_live() if col else None

    def pad(self):
        lk = self.lookup()
        return self._art(pad_view.pad_screen(pad_rules.Catalog(lk), self._live(), self._avail(), self._has_ui))

    def buildings(self):
        lk = self.lookup()
        return self._art(buildings_view.buildings_screen(pad_rules.Catalog(lk), self._live(), self._avail()))

    def validate_command(self, ctype, fields):
        """Checks an overlay_set / tool_select / build_select body against the game's lists before the command goes
        out. Raises ApiError (bad_request / not_found) with the reason in plain language."""
        cat = pad_rules.Catalog(self.lookup())
        if ctype == "overlay_set":
            mode = fields["mode"]
            if mode == pad_rules.NONE_MODE:
                return
            o = cat.overlay(mode)
            if o is None:
                raise ApiError("bad_request", "That overlay is not in the game.")
            ok, why = cat.item_state(o)
            if not ok:
                raise ApiError("bad_request", why)
        elif ctype == "tool_select":
            if "tool" in fields:
                t = cat.tool(fields["tool"])
                if t is None:
                    raise ApiError("bad_request", "That tool is not in the game.")
                ok, why = cat.item_state(t)
                if not ok:
                    raise ApiError("bad_request", why)
        elif ctype == "build_select":
            b = cat.building(fields["buildingId"])
            if b is None or not buildings_view.in_menu(cat, b["id"]) and cat.menu:
                raise ApiError("not_found", "That building is not in the build menu.")
            live = self._live()
            ok, why = pad_rules.unlock_state(cat, b, live)
            if not ok:
                raise ApiError("bad_request", why)
            mats = fields.get("materials")
            if mats:
                try:
                    pad_rules.validate_materials(cat, b, mats, pad_rules.world_stock(live))
                except ValueError as e:
                    raise ApiError("bad_request", str(e))

    def home(self):
        lk = self.lookup()
        return self._art(listing.home_screen(lk, self.ctx.colony.facts(), self.status(), list_tools()))

    def search(self, q, kind, limit):
        lk = self.lookup()
        if kind and kind not in lk.kinds:
            raise ApiError("bad_request", "Unknown kind.")
        return lk.index.search(q, kind, limit)

    def kinds(self):
        return {"kinds": self.lookup().index.kind_counts()}

    def list_kind(self, kind, dlc, sort):
        lk = self.lookup()
        if kind not in lk.kinds:
            raise ApiError("not_found", "Unknown kind.")
        return self._art(listing.list_screen(lk, kind, dlc, sort or "name"))

    def _entry(self, kind, id_):
        lk = self.lookup()
        e = lk.get(kind, id_) if kind in lk.kinds else None
        if e is None:
            raise ApiError("not_found", "Not available.")
        return lk, e

    def entry(self, kind, id_):
        if kind == "dupe":
            return self._dupe_page(id_)
        if kind == "alert":
            return self._alert_page(id_)
        lk, e = self._entry(kind, id_)
        bctx = None
        if kind == "building" and e.get("source") == "mod-export":
            bctx = {"cat": pad_rules.Catalog(lk), "live": self._live(), "avail": self._avail()}
        return self._art(entry_view.entry_screen(lk, kind, e, bctx), (kind, e["id"]))

    def raw(self, kind, id_):
        lk, e = self._entry(kind, id_)
        data = dict(e)
        if kind == "codex":
            data["title"] = e["name"]
            data["text"] = "\n\n".join(p["text"] for p in e.get("paragraphs") or [])
        return {"kind": kind, "id": e["id"], "name": e.get("name") or e["id"], "dlc": list(e.get("dlc") or []),
                "source": "mod-export" if e.get("source") == "mod-export" else "yaml", "data": data}

    def _art_dupe(self):
        """callable(dupe dict) -> art URL path or None (None when the mod rendered no art). ctx.art_for_dupe
        overrides it (tests)."""
        hook = getattr(self.ctx, "art_for_dupe", None)
        if hook:
            return hook
        store = getattr(self.ctx, "art", None)
        if store is None:
            return None
        return lambda d: store.url_for("dupe", str(d["id"])) if d.get("id") not in (None, "") else None

    def _art_for(self):
        if self.art_for:
            return self.art_for
        store = getattr(self.ctx, "art", None)
        return store.url_for if store is not None else None

    def colony(self, world):
        lk = self.lookup()
        try:
            facts = self.ctx.colony.facts(world)
        except KeyError:
            raise ApiError("not_found", "Unknown world.")
        scr = self._art(colony_view.colony_screen(lk, facts, world, lk.meta.get("constants"), self._art_dupe(),
                                              self._alert_ctx(self.ctx.colony.facts())))
        scr["raw"] = facts
        return scr

    def start_history(self):
        """Record a resource snapshot on every `colony` event. One daemon thread waiting on the bus
        (event driven, no timer); it ends when the bus closes."""
        bus = getattr(self.ctx, "bus", None)
        colony = getattr(self.ctx, "colony", None)
        if bus is None or colony is None:
            return None

        def run():
            since = bus.seq
            while not getattr(bus, "_closed", False):
                r = bus.wait(since, 60)
                since = r["seq"]
                if "colony" in r["changed"]:
                    try:
                        self.history.record(colony.facts())
                    except Exception:
                        pass
        t = threading.Thread(target=run, name="oni-res-history", daemon=True)
        t.start()
        return t

    def resources(self, world, q):
        lk = self.lookup()
        facts = self.ctx.colony.facts()
        self.history.record(facts)
        try:
            return resources_view.resources_screen(lk, facts, self.history, world, q, self._art_for())
        except KeyError:
            raise ApiError("not_found", "Unknown world.")

    def _ui_image(self, name):
        """GET /art/ui/<name>: a 9-slice PNG of the current game theme, or None."""
        try:
            return oni_theme.load(self._theme_dir()).image_path(name)
        except Exception:
            return None

    def theme(self):
        out = oni_theme.reply(self._theme_dir())
        fonts = getattr(self.ctx, "fonts", None)
        if fonts is not None:
            try:
                entries, _ = fonts.ensure()
                if entries:
                    out["font"] = dict(out["font"], roles=fonts.roles())
            except Exception:
                pass            # fonts are an extra: the theme still serves
        return out


    def _alert_ctx(self, facts):
        """(ids shown as dismissing, has_ui(name)) for the alert views."""
        acts = getattr(self.ctx, "actions", None)
        present = set()
        for w in facts.get("worlds") or []:
            present.update(a.get("id") for a in w.get("alerts") or [])
        dismissing = acts.dismissing(present) if acts is not None and hasattr(acts, "dismissing") else set()
        return dismissing, self._has_ui

    def _has_ui(self, name):
        try:
            return self._ui_image(name) is not None
        except Exception:
            return False

    def _alert_page(self, id_):
        facts = self.ctx.colony.facts()
        a = alert_view.find_alert(facts, id_) if facts.get("source") == "mod-live" else None
        if a is None:
            raise ApiError("not_found", "That alert is gone.")
        dismissing, has_ui = self._alert_ctx(facts)
        return self._art(alert_view.alert_screen(a, dismissing, has_ui))

    def _dupe_page(self, id_):
        lk = self.lookup()
        scr = colony_view.dupe_screen(lk, self.ctx.colony.facts(), id_, self._settings().get("zoomToDupeOnSelect"),
                                      lk.meta.get("constants"), self._art_dupe())
        if scr is None:
            raise ApiError("not_found", colony_view.NO_DUPE)
        return self._art(scr)

    # ---- settings (owned by the core, shared by every front end)
    def _settings(self):
        st = getattr(self.ctx, "settings", None)
        if st is None:
            st = self.ctx.settings = Settings(None)      # tests and previews: in memory
        return st

    def settings(self, local=True):
        return settings_view.settings_screen(self._settings().values(), self.status(), self._dlc_name, local=local)

    def _dlc_name(self, dlc_id):
        try:
            return self.lookup().dlc_name(dlc_id)
        except ApiError:
            return dlc_id

    def settings_save(self, values, local=True):
        try:
            self._settings().update(values)
        except SettingsError as e:
            raise ApiError("bad_request", str(e))
        return self.settings(local=local)

    def tools(self):
        return list_tools()

    def tool_form(self, id_):
        lk = self.lookup()
        try:
            return self._art(form_screen(id_, self._tooldata(lk), self._src(lk), lk.as_of))
        except UnknownTool:
            raise ApiError("not_found", "Unknown tool.")

    def tool_run(self, id_, values):
        lk = self.lookup()
        try:
            return self._art(run_tool(id_, values, self._tooldata(lk), self._src(lk), lk.as_of))
        except UnknownTool:
            raise ApiError("not_found", "Unknown tool.")
        except ToolError as e:
            raise ApiError("bad_request", e.message)
        except DataProblem as e:
            raise ApiError("no_data", str(e))
