"""List Screens (GET /list/<kind>) and the Home Screen."""
from . import blocks as B


def list_screen(lk, kind, dlc=None, sort="name"):
    rows = lk.index.list_kind(kind, dlc, sort)
    label = lk.kind_label(kind)
    sub = "%d entries" % len(rows)
    if dlc:
        sub += ", " + ("base game" if dlc == "base" else lk.dlc_name(dlc))
        if dlc == "base":
            unk = sum(1 for r in lk.index.list_kind(kind) if r.get("dlcKnown") is False)
            if unk:
                sub += " (%d with unknown DLC left out)" % unk

    def it(e):
        return B.item(e.get("name") or e["id"], B.ref(kind, e["id"]), lk.index.subtitle(kind, e) or None,
                      lk.dlc_badge(e))
    bl = []
    if not rows:
        bl.append(B.notice("info", "Nothing to show yet." if kind in ("critter", "plant", "recipe") else "Nothing to show."))
    elif sort == "dlc":
        groups = {}
        for e in rows:
            key = tuple(e.get("dlc") or [])
            groups.setdefault(key, []).append(e)
        for key in sorted(groups, key=lambda k: (len(k), k)):
            title = ", ".join(lk.dlc_name(d) for d in key) if key else "Base game"
            bl.append(B.group("%s (%d)" % (title, len(groups[key])), [B.list_block([it(e) for e in groups[key]])]))
    else:
        bl.append(B.list_block([it(e) for e in rows]))
    src = "mod-export" if any(e.get("source") == "mod-export" for e in rows) else "yaml"
    return B.screen(label, bl, subtitle=sub, source=src, as_of=lk.as_of, back="home", refresh_on=["gamedata"])


def home_screen(lk, facts, status, tools):
    """The Codex page (GET /home): the game's encyclopedia without buildings (they have their own tab) and the
    calculators as a section. Titled with the game's own word for it."""
    title = lk.codex_label
    bl = [B.heading(title)]
    bl.append(B.list_block([B.item(k["label"], subtitle="%d entries" % k["count"], badge=str(k["count"]))
                            for k in lk.index.kind_counts() if k["kind"] != "building"]))
    bl.append(B.heading("Tools"))
    bl.append(B.list_block([B.item(t["title"], subtitle=t["summary"]) for t in tools["tools"]]))
    bl.append(B.notice("info", "Search from the %s tab." % title))
    return B.screen(title, bl, source="mod-export" if lk.meta.get("exportFiles") else "yaml", as_of=lk.as_of,
                    refresh_on=["gamedata"])
