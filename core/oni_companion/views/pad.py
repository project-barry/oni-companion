"""Actions Screen (GET /pad): the game's overlays, its priority bar and its tools as grids of buttons.

All names, order, icons and availability come from the game through the export; what is active now comes from
live.json. Tapping the active overlay sends overlay_set None (the game goes back to no overlay), like the game.
Pages other than Settings never mention the mod, so a missing list only says it is not available yet.
"""
from .. import pad as P
from . import blocks as B
from .alerts import ui_path

NOT_YET = "Overlays and tools are not available yet. See Settings."
PRIORITIES = list(range(1, 10)) + [P.EMERGENCY]


def _button(action_id, label, args, active, enabled, reason):
    a = B.action(action_id, label, args)
    if active:
        a["active"] = True
    if not enabled:
        a["enabled"] = False
        a["reason"] = reason or P.NOT_AVAILABLE
    return a


def _icon(name, has_ui):
    return ui_path(name) if name and has_ui(name) else None


def pad_screen(cat, live, avail, has_ui):
    """cat: pad.Catalog. live: parsed live.json or None. avail: (ok, reason text). has_ui(name) -> bool."""
    live = live if isinstance(live, dict) else {}
    ok, why = avail
    cur_ov, cur_tool, cur_pri = live.get("activeOverlay"), live.get("activeTool"), live.get("priority")
    if not ok:
        cur_ov = cur_tool = cur_pri = None
    bl = []
    if not cat.overlays and not cat.tools:
        bl.append(B.notice("info", NOT_YET))
        return B.screen("Actions", bl, source="mod-export" if cat.lk.meta.get("exportFiles") else "none",
                        refresh_on=["pad", "gamedata", "status"])
    if not ok:
        bl.append(B.notice("info", why))
    if cat.overlays:
        cards = []
        for o in cat.overlays:
            en, reason = cat.item_state(o)
            if not ok:
                en, reason = False, why
            active = ok and o["id"] == cur_ov
            sub = o.get("hotkey")
            cards.append(B.card(o.get("name") or o["id"], subtitle=sub, art=_icon(o.get("icon"), has_ui),
                                actions=[_button("overlay_set", o.get("name") or o["id"],
                                                 {"mode": P.NONE_MODE if active else o["id"]}, active, en, reason)]))
        bl.append(_pad_grid(cards, "Overlays"))
    cards = []
    for n in PRIORITIES:
        active = ok and cur_pri == n
        label = "!" if n == P.EMERGENCY else str(n)
        cards.append(B.card(label, subtitle="Emergency" if n == P.EMERGENCY else None,
                            actions=[_button("tool_select", "Emergency" if n == P.EMERGENCY else "Priority %d" % n,
                                             {"priority": n}, active, ok, why)]))
    g = B.grid(cards, "Priority")
    g["variant"] = "priority"
    bl.append(g)
    if cat.tools:
        cards = []
        for t in cat.tools:
            en, reason = cat.item_state(t)
            if not ok:
                en, reason = False, why
            active = ok and t["id"] == cur_tool
            cards.append(B.card(t.get("name") or t["id"], subtitle=t.get("hotkey"), art=_icon(t.get("icon"), has_ui),
                                actions=[_button("tool_select", t.get("name") or t["id"], {"tool": t["id"]},
                                                 active, en, reason)]))
        bl.append(_pad_grid(cards, "Tools"))
    return B.screen("Actions", bl, source="mod-live" if live else "mod-export", as_of=live.get("writtenAt"),
                    refresh_on=["pad", "gamedata", "status"])


def _pad_grid(cards, title):
    g = B.grid(cards, title)
    g["variant"] = "pad"
    return g
