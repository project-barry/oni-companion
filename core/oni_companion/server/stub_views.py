"""Stub views, used until C4 (views/) lands. This is the one function boundary.

The routes call `load_views(ctx)`. It returns the object from
`oni_companion.views.provider.make_views(ctx)` if that module exists, else the
stub below. A views object has these methods (all return JSON-ready dicts and
raise ApiError/ViewError(code, message) for 400/404/503):

    status()                      -> api Status
    home()                        -> Screen
    search(q, kind, limit)        -> Search
    kinds()                       -> Kinds
    list_kind(kind, dlc, sort)    -> Screen
    entry(kind, id)               -> Screen
    raw(kind, id)                 -> Raw
    colony(world)                 -> ColonyReply (Screen + raw)
    resources(world, q)           -> Screen (v1.1)
    theme()                       -> Theme
    tools()                       -> ToolList
    tool_form(id)                 -> Screen
    tool_run(id, values)          -> Screen
    tabs()                        -> TabList (v1.3)
    pad()                         -> Screen: Actions (v1.3)
    buildings()                   -> Screen: Buildings (v1.3)
    mod_install(body)             -> ModInstallReply (v1.3)

ctx.colony is the Colony model (colony.py); ctx.bus the EventBus.
The stub answers from fixtures/synthetic when the repo checkout is present, and
from tiny inline replies otherwise. It is made-up data, never Klei data.
"""
import copy
import importlib
import json
import os

from .errors import ApiError


def load_views(ctx):
    try:
        mod = importlib.import_module("oni_companion.views.provider")
    except ImportError:
        return StubViews(ctx)
    return mod.make_views(ctx)


def _find_fixtures():
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(here, "fixtures", "synthetic")
        if os.path.isdir(cand):
            return cand
        here = os.path.dirname(here)
    return None


class StubViews:
    def __init__(self, ctx, fixtures=None):
        self.ctx = ctx
        self.fx = fixtures or _find_fixtures()

    def _load(self, rel, fallback):
        if self.fx:
            try:
                with open(os.path.join(self.fx, rel), encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
        return copy.deepcopy(fallback)

    @staticmethod
    def _screen(title, text):
        return {"schema": 1, "title": title,
                "blocks": [{"type": "notice", "level": "info", "text": text}]}

    def status(self):
        d = self._load("api/status-bare.json", {
            "apiVersion": 1, "coreVersion": "0.1.0", "game": {"found": False},
            "mod": {"present": False}, "cache": {"state": "none"},
            "colony": {"source": "none"}, "newestSave": None})
        sf = self.ctx.colony.status_fields()
        d["colony"] = sf["colony"]
        d["newestSave"] = sf["newestSave"]
        d["mod"] = {"present": sf["livePresent"], "liveFresh": sf["liveFresh"]}
        return d

    def home(self):
        return self._load("screens/home.json", self._screen("ONI Companion", "Stub home."))

    def _search_pool(self):
        return self._load("api/search.json", {"query": "", "results": []})["results"]

    def search(self, q, kind, limit):
        res = [r for r in self._search_pool()
               if q.lower() in r["name"].lower() and (not kind or r["kind"] == kind)]
        return {"query": q, "results": res[:limit], "truncated": len(res) > limit}

    def kinds(self):
        return self._load("api/kinds.json", {"kinds": []})

    def list_kind(self, kind, dlc, sort):
        if kind != "building":
            raise ApiError("not_found", "Unknown kind.")
        return self._load("screens/list-building.json", self._screen("Buildings", "Stub list."))

    def entry(self, kind, id_):
        fx = {"building": "screens/entry-building.json", "element": "screens/entry-element.json"}
        known = {(r["kind"], r["id"]) for r in self._search_pool()}
        if (kind, id_) not in known or kind not in fx:
            raise ApiError("not_found", "Not available.")
        return self._load(fx[kind], self._screen(id_, "Stub entry."))

    def raw(self, kind, id_):
        d = self._load("api/raw-building.json", None)
        if d is None or (d.get("kind"), d.get("id")) != (kind, id_):
            raise ApiError("not_found", "Not available.")
        return d

    def colony(self, world):
        try:
            facts = self.ctx.colony.facts(world)
        except KeyError:
            raise ApiError("not_found", "Unknown world.")
        scr = self._load("screens/colony.json", self._screen("Colony", "Stub colony."))
        scr["raw"] = facts
        scr["source"] = facts["source"]
        if "asOf" in facts:
            scr["asOf"] = facts["asOf"]
        else:
            scr.pop("asOf", None)
        if "colonyName" in facts:
            scr["title"] = facts["colonyName"]
        return scr

    def resources(self, world, q):
        return self._load("screens/resources.json", self._screen("Resources", "Stub resources."))

    def theme(self):
        return self._load("api/theme.json", {"schema": 1, "source": "builtin", "colors": {}, "font": {"family": "Noto Sans"}, "slices": []})

    def tools(self):
        return self._load("api/tools.json", {"tools": []})

    def tabs(self):
        return self._load("api/tabs.json", {"tabs": []})

    def pad(self):
        return self._load("screens/actions.json", self._screen("Actions", "Stub actions."))

    def buildings(self):
        return self._load("screens/buildings.json", self._screen("Buildings", "Stub buildings."))

    def mod_install(self, body):
        raise ApiError("unavailable", "Installing is not possible here.")

    def _tool_ids(self):
        return {t["id"] for t in self.tools()["tools"]}

    def tool_form(self, id_):
        if id_ not in self._tool_ids():
            raise ApiError("not_found", "Unknown tool.")
        return self._load("screens/tool-form.json", self._screen(id_, "Stub form."))

    def tool_run(self, id_, values):
        if id_ not in self._tool_ids():
            raise ApiError("not_found", "Unknown tool.")
        return self._load("screens/tool-result.json", self._screen(id_, "Stub result."))
