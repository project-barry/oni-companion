"""The Settings Screen (GET/POST /settings): the form for the core's settings, then what the core found.

The status part is the one the Barry Settings tab used to build itself in QML; every front end now gets
the same blocks from the core.
"""
from . import blocks as B

FIELDS = [
    {"kind": "toggle", "name": "zoomToDupeOnSelect", "label": "Zoom to duplicant when selected", "default": False},
]
ABOUT = ("ONI Companion %s. An unofficial companion for Oxygen Not Included. Not affiliated with Klei "
         "Entertainment. All game data is read from your own copy of the game while you use the app.")


def _yn(b):
    return "Yes" if b else "No"


MOD_STATE_TEXT = {"missing": ("Not installed", "bad"), "disabled": ("Switched off", "warn"),
                  "no_live": ("No live data", "warn"), "version_mismatch": ("Version does not fit", "warn"),
                  "ok": ("Working", "good")}
MOD_LEVEL = {"missing": "warn", "disabled": "warn", "no_live": "info", "version_mismatch": "warn", "ok": "info"}


def mod_blocks(ms, local=True):
    """The Companion Link mod section from status.modState: the state, the steps, the ask-first install button."""
    label, tone = MOD_STATE_TEXT.get(ms["state"], (ms["state"], "neutral"))
    comp = ms.get("compat") or {}
    rows = [B.stat("Game mod", label, tone=tone)]
    if comp.get("mod"):
        rows.append(B.stat("Version", comp["mod"]))
    if "workshop" in (ms.get("copies") or []):
        rows.append(B.stat("Installed from", "Steam Workshop"))
    elif "local" in (ms.get("copies") or []):
        rows.append(B.stat("Installed from", "This app"))
    bl = [B.stats(rows)]
    vers = ms.get("versions") or []
    if len(vers) > 1:
        bl.append(B.heading("Game versions"))
        vrows = []
        for v in vers:
            if v.get("copy") is None:
                txt, tone = "Off, not installed", "warn"
            elif v.get("crashDisabled"):
                txt, tone = "Switched off by a game error", "bad"
            elif v.get("enabled") is False:
                txt, tone = "Off", "warn"
            else:
                txt, tone = "On", "good"
            if v.get("installed") and v.get("copy"):
                txt += ", " + v["installed"]
            hint = v["path"]
            if v.get("library"):
                hint = "Library: %s" % v["library"]
            vrows.append(B.stat(v["label"], txt, tone=tone, hint=hint))
        bl.append(B.stats(vrows))
        if ms.get("updateBoth"):
            bl.append(B.notice("warn", "The versions differ. Update both."))
        for v in vers:
            if v.get("crashDisabled"):
                bl.append(B.notice("warn", "%s: the game switched the mod off after an error. Open the game's Mods menu, "
                                   "switch it on again and restart the game." % v["label"]))
            elif v.get("copy") and v.get("enabled") is False:
                bl.append(B.text("%s: turn the mod on in the game's Mods menu." % v["label"]))
    if ms["state"] != "ok":
        bl.append(B.notice(MOD_LEVEL.get(ms["state"], "info"), ms["summary"]))
        for i, step in enumerate(ms.get("steps") or [], 1):
            bl.append(B.text("%d. %s" % (i, step)))
    inst = ms.get("install") or {}
    if not local:
        pass                       # a paired device cannot install the mod: the core answers 403 local_only
    elif inst.get("available"):
        act = B.action("mod_install", "Install the game mod", {"confirm": True})
        tg = inst.get("targets") or [inst.get("target", "the game's mods folder")]
        if len(tg) > 1:
            lab = {v["path"]: v["label"] for v in vers}
            names = ["%s (%s)" % (lab.get(t.rsplit("/mods/Local/", 1)[0], "folder"), t) for t in tg]
            act["confirm"] = "Copy ONI Companion Link into all these game folders?\n%s" % "\n".join(names)
        else:
            act["confirm"] = "Copy ONI Companion Link into %s?" % tg[0]
        it = B.item("Install the game mod", subtitle="Copies the mod into the game's mods folder. Nothing else is changed.")
        it["actions"] = [act]
        bl.append(B.list_block([it]))
    elif inst.get("reason") and ms["state"] in ("missing", "disabled", "version_mismatch"):
        bl.append(B.text(inst["reason"]))
    return bl


def status_blocks(st, dlc_name=None, local=True):
    g, m, c, col = st.get("game") or {}, st.get("mod") or {}, st.get("cache") or {}, st.get("colony") or {}
    bl = [B.heading("Game")]
    build = g.get("build")
    bl.append(B.stats([
        B.stat("Game found", _yn(g.get("found")), tone="good" if g.get("found") else "bad"),
        B.stat("Game build", build if build is not None else "unknown"),
        B.stat("DLC installed", len(g.get("dlcInstalled") or [])),
        B.stat("DLC with numbers", len(g.get("dlcExported") or [])),
    ]))
    if g.get("dlcMissingExport"):
        nm = dlc_name or (lambda d: d)
        names = ", ".join(nm(d) for d in g["dlcMissingExport"])
        stop = "" if names.endswith(("!", ".", "?")) else "."
        bl.append(B.notice("warn", "Not loaded yet: %s%s Start a game once with them switched on and their content appears here."
                           % (names, stop), title="Some content is missing"))
    bl.append(B.heading("Companion Link mod"))
    if st.get("modState"):
        bl += mod_blocks(st["modState"], local)
    elif m.get("present"):
        live = bool(m.get("liveFresh"))
        bl.append(B.stats([
            B.stat("Mod installed", "Yes", tone="good"),
            B.stat("Version", m.get("version") or "unknown"),
            B.stat("Live data", "Live" if live else "Not live", tone="good" if live else "warn"),
        ]))
    else:
        bl.append(B.notice("info", "Install the ONI Companion Link mod for building numbers and live colony data."))
    bl.append(B.heading("Colony"))
    rows = [B.stat("Source", col.get("source") or "none")]
    if col.get("name"):
        rows.append(B.stat("Name", col["name"]))
    if col.get("cycle") is not None:
        rows.append(B.stat("Cycle", col["cycle"]))
    sv = st.get("newestSave")
    if sv:
        rows.append(B.stat("Newest save", ("Cycle %s" % sv["cycle"]) if sv.get("cycle") is not None else sv.get("name", ""),
                           hint=("File: " + sv["name"]) if sv.get("name") else None))
    bl.append(B.stats(rows))
    state = c.get("state") or "none"
    bl.append(B.stats([B.stat("State", state, tone="good" if state == "ready" else "bad" if state == "error" else "neutral")],
                      title="Data cache"))
    if c.get("message"):
        bl.append(B.notice("error" if state == "error" else "info", c["message"]))
    bl.append(B.heading("About"))
    bl.append(B.text(ABOUT % (st.get("coreVersion") or "")))
    bl.append(B.link("Oxygen Not Included on Steam", "https://store.steampowered.com/app/457140"))
    return bl


def settings_screen(values, status, dlc_name=None, local=True):
    fields = [dict(f, default=values.get(f["name"], f["default"])) for f in FIELDS]
    form = B.form("settings", fields, "Save", title="Colony", endpoint="/settings")
    return B.screen("Settings", [form] + status_blocks(status, dlc_name, local), refresh_on=["settings"])
