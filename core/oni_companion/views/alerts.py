"""Colony alerts like the game (v1.2): the alert strip items and the alert page (/entry/alert/<id>).

Everything comes from the mod's live.json alert (title, type, tooltipMarkup, links, click, dismissable); nothing is
decided per alert here. The game's markup becomes spans in richtext.py. Actions:
- a tooltip <link> line   -> alert_activate {alertId, link}   (only when the game's link does something)
- "Open in game"          -> alert_activate {alertId}         (only when click.kind != none)
- "Dismiss"               -> alert_dismiss {alertId}          (only when dismissable; on the strip it is a longPress action)
"""
from . import blocks as B
from .richtext import plain_text, to_spans

TONE = {"bad": "bad", "warning": "warn", "info": "info"}
ORDER = {"bad": 0, "warning": 1, "info": 2}
# art name per NotificationType (theme icon names); an icon only picks a picture, never a behavior
# The game's alert list draws neutral, minor-bad and good alerts with a small white dot (the front end's plain bullet),
# and messages with an envelope (seen in the game, 2026-10-25); those types get no picture or the envelope here.
TYPE_ICON = {"bad": "alertBad", "duplicantThreatening": "alertThreatening", "event": "alertEvent",
             "messages": "alertMessage", "messageImportant": "alertMessageImportant", "tutorial": "alertTutorial"}
SCREEN_NAMES = {"research": "Research", "skills": "Skills", "schedule": "Schedule", "consumables": "Consumables",
                "priorities": "Priorities", "report": "Report", "codex": "Database", "starmap": "Starmap",
                "vitals": "Vitals", "database": "Database", "jobs": "Priorities"}
DISMISSING = "Dismissing…"
NOT_DISMISSABLE = "This alert can't be dismissed in the game."


def ui_path(name):
    return "/api/v1/art/ui/" + name


def alert_title(a):
    t = plain_text(a.get("title") or "") or plain_text(a.get("text") or "")
    return t or "Alert"


def _dismiss_action(aid):
    d = B.action("alert_dismiss", "Dismiss", {"alertId": aid})
    d["trigger"] = "longPress"
    d["danger"] = True
    return d


def _s(v):
    """A hashable string key or None: odd types from a buggy mod never reach a dict lookup."""
    return v if isinstance(v, str) else None


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def alert_items(alerts, dismissing=(), has_ui=None):
    """List items for the colony alert strip. has_ui(name) -> True when the theme has that picture."""
    out = []
    for a in sorted((x for x in alerts if isinstance(x, dict)), key=lambda x: ORDER.get(_s(x.get("level")), 3)):      # worst first, stable
        aid = a.get("id")
        gone = isinstance(aid, str) and aid in dismissing
        sub = DISMISSING if gone else (("Since cycle %d" % _int(a.get("cycle"))) if _int(a.get("cycle")) is not None else None)
        it = B.item(alert_title(a), B.ref("alert", aid) if isinstance(aid, str) and aid else None, subtitle=sub,
                    badge=("x%d" % _int(a.get("count"))) if (_int(a.get("count")) or 1) > 1 else None,
                    tone=TONE.get(_s(a.get("level"))))
        icon = TYPE_ICON.get(_s(a.get("type")))
        if icon and has_ui and has_ui(icon):
            it["art"] = ui_path(icon)
        if a.get("dismissable") is True and not gone and isinstance(aid, str) and aid:
            it["actions"] = [_dismiss_action(aid)]
        out.append(it)
    return out


def _row(title, subtitle, action):
    it = B.item(title, subtitle=subtitle)
    it["actions"] = [action]
    return it


def find_alert(facts, alert_id):
    for w in facts.get("worlds") or []:
        for a in w.get("alerts") or []:
            if a.get("id") == alert_id:
                return a
    return None


def _links_by_index(a):
    return {l["index"]: l for l in a.get("links") or [] if isinstance(l, dict) and isinstance(l.get("index"), int)}


def alert_spans(a, has_ui=None):
    aid = a["id"]
    links = _links_by_index(a)
    order = []                                  # link ids in order of appearance, for non-numeric <link> ids

    def link_action(link_id):
        idx = None
        if isinstance(link_id, str) and link_id.strip().isdigit():
            idx = int(link_id.strip())
        else:
            if link_id not in order:
                order.append(link_id)
            idx = sorted(links)[order.index(link_id)] if order.index(link_id) < len(links) else None
        l = links.get(idx)
        if not l or l.get("kind") == "none":
            return None
        return B.action("alert_activate", (l.get("label") or "Open")[:120], {"alertId": aid, "link": idx})

    def sprite_icon(name):
        n = "sprite-" + name
        return ui_path(n) if has_ui and has_ui(n) else None

    return to_spans(a.get("tooltipMarkup") or "", link_action, sprite_icon)


def alert_screen(a, dismissing=(), has_ui=None):
    aid = a["id"]
    bl = []
    dismissing = dismissing or ()
    spans = alert_spans(a, has_ui)
    if not spans:
        txt = plain_text(a.get("text") or a.get("title") or "")
        spans = [B.plain(txt)] if txt else []
    if spans:
        bl.append(B.text(*spans))
    click = a.get("click") if isinstance(a.get("click"), dict) else {}
    rows = []
    kind = click.get("kind")
    if kind in ("focus", "screen"):
        if kind == "screen":
            raw = _s(click.get("target")) or ""
            tgt = SCREEN_NAMES.get(raw, raw)
            sub = ("Opens the %s screen in the game" % tgt) if tgt else "Opens a screen in the game"
        else:
            sub = "Moves the camera, like a click in the game"
        rows.append(_row("Open in game", sub, B.action("alert_activate", "Open in game", {"alertId": aid})))
    if aid in dismissing:
        bl.append(B.notice("info", DISMISSING))
    elif a.get("dismissable") is True:
        d = B.action("alert_dismiss", "Dismiss", {"alertId": aid})
        d["danger"] = True
        rows.append(_row("Dismiss", "Dismisses it in the game too", d))
    if rows:
        bl.append(B.list_block(rows))
    sub = ("Cycle %d" % _int(a.get("cycle"))) if _int(a.get("cycle")) is not None else None
    return B.screen(alert_title(a), bl, subtitle=sub, source="mod-live", back="home",
                    refresh_on=["colony", "action"])
