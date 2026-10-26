"""Why the game cannot take a command or a sync right now (plan 4.3 item 5). The core decides; every front end shows
the same words. Stdlib only.

live_kind()   what live.json says: running | menu | paused is part of running | stopped | stale | none
Explainer     turns that plus mods.json and the running game process into {cause, message}
              (the old `reason` key of the Controls / Sync replies stays as it was, for older front ends):
  cause    menu | mod_off | mod_crashed | not_running | stale | no_mod
  message  the sentence to show
"menu" is only ever said when live.json says menu and is fresh. A mod that is off or was turned off by the game's crash
screen is named as such, never called "the menu".
"""
import os

from . import modstate
from . import sources

RUNNING_FRESH = 15
RUNNING_FRESH_PAUSED = 180
MENU_FRESH = 180

MSG_MENU = "The game is in the menu. Load a colony first."
MSG_MOD_OFF = "ONI Companion Link is off in the running game: turn it on in the game's Mods menu."
MSG_MOD_OFF_UNSURE = "ONI Companion Link is off for this version of the game: turn it on in the game's Mods menu."
MSG_CRASHED = ("ONI Companion Link is off in the running game: the game turned it off after a crash. "
               "Turn it on in the game's Mods menu.")
MSG_NOT_RUNNING = "The game is not running. Start Oxygen Not Included."
MSG_STALE = "The game is not sending data. Is it running?"
MSG_NO_MOD = "ONI Companion Link is not installed for this version of the game."
MSG_NO_DATA = "The game is running but ONI Companion Link has sent nothing yet. Load a colony."


def live_kind(state, written, paused, now):
    """state: live.json "state" (or None when there is no readable file); written: epoch seconds or None."""
    if state is None:
        return "none"
    if state == "stopped":
        return "stopped"
    if written is None:
        return "stale"
    age = now - written
    if state == "running":
        return "running" if age <= (RUNNING_FRESH_PAUSED if paused else RUNNING_FRESH) else "stale"
    if state == "menu":
        return "menu" if age <= MENU_FRESH else "stale"
    return "stale"


def mod_flag(user_dir, dlc_ids=None):
    """What mods.json says about the mod in this folder: on | off | crashed | none (no entry or no file).
    crashed = the entry's enabledForDlc was emptied AND the game logged an error naming the mod (an empty list alone is a plain toggle-off)."""
    entries, have_json = modstate.mods_json_entries(user_dir)
    if not entries:
        return "none"
    state = modstate.enabled_in_game(entries, dlc_ids if isinstance(dlc_ids, list) else None)
    if state is True or (state is None):
        modstate.crash_flag(user_dir, sources.user_dir_kind(user_dir), state)       # drops an old crash mark
        return "on"
    emptied = all(isinstance(m.get("enabledForDlc"), list) and not m["enabledForDlc"] for m in entries)
    if emptied and modstate.crash_flag(user_dir, sources.user_dir_kind(user_dir), False):
        return "crashed"            # an empty list alone is also a plain toggle-off: needs the game's own error as evidence
    return "off"


class Explainer:
    """user_dir(): the active ONI folder. game_here(): True/False/None (a game process of this folder runs / none runs /
    cannot tell). ran(): True when the mod ever wrote data in this folder. clock: time source."""

    def __init__(self, user_dir, game_here=None, clock=None):
        self.user_dir = user_dir
        self.game_here = game_here or (lambda: None)
        self.clock = clock

    def explain(self, kind, dlc_ids=None):
        """None when kind is running (nothing to explain), else {"cause", "message"}."""
        if kind == "running":
            return None
        if kind == "menu":
            return {"cause": "menu", "message": MSG_MENU}
        here = self.game_here()
        folder = self.user_dir()
        flag = mod_flag(folder, dlc_ids) if folder else "none"
        if here is False:
            return {"cause": "not_running", "message": MSG_NOT_RUNNING}
        if flag == "crashed":
            return {"cause": "mod_crashed", "message": MSG_CRASHED}
        if flag == "off":
            return {"cause": "mod_off", "message": MSG_MOD_OFF if here else MSG_MOD_OFF_UNSURE}
        if flag == "none" and here and not (folder and os.path.isdir(os.path.join(folder, "companion"))):
            return {"cause": "no_mod", "message": MSG_NO_MOD}
        if kind == "stale":
            return {"cause": "stale", "message": MSG_STALE}
        # none / stopped, mod switched on (or unknown), game running or unknown
        if here:
            return {"cause": "no_mod", "message": MSG_NO_DATA}
        return {"cause": "not_running", "message": MSG_NOT_RUNNING}
