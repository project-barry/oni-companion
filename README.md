# ONI Companion

> This project was written with the help of AI (Claude). Review the code
> before you trust it.

**Not affiliated with Klei Entertainment.** "Oxygen Not Included" is a
trademark of Klei Entertainment. This repo contains no Klei data, text, art,
fonts or UI images. All game data, art and style come from your own copy of
the game, at run time.

A companion for Oxygen Not Included (ONI): a live colony view, resources, a
Buildings tab with Build buttons, an Actions tab for the game's overlays, tools
and priorities, the game's encyclopedia (Codex) with calculators, and a "show
in game" button that moves the game camera to a duplicant. One Python core serves thin front ends. The first
front end is the Barry app for the AYN Thor bottom screen. Phone front ends:
a native Android app (v1.4, in development, UNTESTED on a device) and an iOS
web app (later). A small C# mod,
"ONI Companion Link", exports exact game numbers and live state as files,
renders art from the running game, and runs the commands the app sends.

Status: in development. Nothing here is released yet.

## What it does

- **Connect a phone (v1.4):** turn it on in the game's pause menu, on the
  gaming device (not in the app). The app then finds the game device on your
  network or scans a QR code, and asks for a one-time code. Each phone is
  paired and can be removed at any time. Off by default, and the service only
  runs while the game runs. Details in `docs/architecture.md`. UNTESTED.
- **Buildings (v1.3):** every building in the game's build-menu order
  (Base, Oxygen, Power, Food, Plumbing and so on), with its power, heat,
  ports, materials, size and research. Each building has a **Build** button.
  It is greyed out, with the research it needs, until the game unlocks it.
  Tap Build to pick the building's materials from the same list the game
  shows (amount needed and amount in the colony), then the game's build menu
  opens with that building picked. You place it on the game screen.
- **Actions (v1.3):** the game's overlay buttons (Oxygen, Power, Temperature,
  and the rest, only those your DLC has) and its tool buttons (Dig, Cancel,
  Deconstruct, Mop, Sweep, Priority, and the rest). Tapping one switches the
  game to it, ready to drag on the game screen. The game's priority buttons
  (1 to 9 and Emergency) set the priority for the next tool. The active
  overlay, tool and priority follow the game, also when you change them there.
- **Codex (v1.3):** the game's own word for its encyclopedia (shown as the
  game shows it) holds elements, critters, plants, geysers, foods, medicines,
  recipes, the research tree, traits, skills and rooms. Its calculators are
  a section of this tab too. All installed DLC content is included and tagged
  by DLC.
- **Colony, live:** cycle and time, duplicants, alerts, and the world
  switcher. The Colony tab is an overview: each duplicant shows a portrait,
  three meters (stress, health, calories) and warning badges only when
  something is wrong. Badges come from the game's own status items, worst
  first. Tapping a duplicant opens its full page: every meter, status items,
  diseases, traits, skills, morale and current task.
- **Resources (v1.1):** every resource the colony has, grouped by the game's
  own categories with a total for each, filter, world switcher and a trend
  arrow. Trends are kept in memory while the core runs, so they start empty.
- **Show in game (v1.1):** "Show in game" on a duplicant's page pans and zooms
  the game camera to that duplicant once, and selects them so their info panel
  opens. It never follows the duplicant. Tap it again to catch up with them.
  Optional setting "Zoom to duplicant when selected" (off by default) zooms as
  soon as you open a duplicant from the Colony tab.
- **Game art (v1.1):** building, element, critter, plant, seed, egg, food,
  medicine and item icons, and duplicant portraits. The mod renders them from
  your game into PNG files on your device. The app ships none. Without the
  mod, every place falls back to the plain glyph look.
- **Game style (v1.1):** the app's panels, buttons, tabs and meters use colors
  and panel images taken from your game's own UI, once per game build. Without
  the mod it uses the built-in dark theme. The Barry theme is not changed.
- **Alerts (v1.2):** each alert shows the game's own tooltip text, colors and
  icons. Tap an alert to see its tooltip. Tap a highlighted line to do what the
  game does: move the camera to the building it names, or open the screen it
  names (such as Research). Long-press an alert, then tap "Dismiss", to dismiss
  it in the game too. Alerts the game does not let you dismiss say so.
- **Speed controls (v1.2):** Pause, Play, 1, 2 and 3 buttons at the top of every
  page, styled like the game's own. The bar shows the game's real speed, also
  when you change it in the game.
- **Game fonts (v1.2):** header and body text use the game's own fonts, read at
  run time from your copy of the game. If a font is missing, the app uses a
  fallback and nothing breaks.
- **Art and font sync (v1.2):** a "Sync art & fonts" screen copies the art,
  theme and fonts from your game, with progress. It runs once after install,
  again after a game update or a new DLC, and from a button in Settings.
- **Calculators (in Codex):** heat transfer, element state, geyser averages,
  oxygen per duplicant, critter ranch food, power budget. They take their
  numbers from game data, exported by the mod.

## Front ends

| Front end | Where it runs | Status |
|---|---|---|
| Barry app | AYN Thor bottom screen, under the game | in development (v1, v1.1, v1.2, v1.3) |
| Android app | a phone or tablet on the same network as the gaming device, or the bottom screen of a dual-screen Android device; native Kotlin and Compose (v1.4) | in development, UNTESTED on a device; see `docs/android.md` |
| iOS web app | iPhone or iPad; the core serves the web page, which you add to the Home Screen | later; iOS users choose plain HTTP or Tailscale |

Each front end only draws the screens that the core sends. Logic lives in
the core. The phone front ends use the core's network listener (HTTPS with the
service's own certificate, paired device token), which is open only while
"Connect a phone" is on. See `docs/architecture.md`.

## Install

The steps below are the planned release flow. None of them is tested yet.

Requirements: a copy of Oxygen Not Included on the device (Steam app 457140),
and Python 3.11 or newer. The core uses only the Python standard library.

**Barry app (planned release build):**

1. Get the `oni-companion` zip from a release.
2. Install it on the device with `barry-app install oni-companion.zip`.
3. Open the game link, or start the app from the Barry launcher.

**Game mod (ONI Companion Link), three ways:**

1. **Steam Workshop (main route, planned):** subscribe to "ONI Companion Link"
   in the Oxygen Not Included Workshop. Steam installs and updates it for the
   Linux and Proton builds. It is not published yet.
2. **The app's button:** in the app's Settings, "Install the game mod" copies
   the mod that comes inside the app into the game's mods folder
   (`mods/Local/OniCompanionLink`). It asks first. If a Workshop copy is
   already subscribed, the button is unavailable, because two copies would
   both load.
3. **Release zip (everyone else):** unzip `OniCompanionLink` into the game's
   mods folder. On Linux that is `~/.config/unity3d/Klei/Oxygen Not Included/mods/Local/`.
   With the Windows build under Proton, it is
   `steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded/mods/Local/`.

Then start the game, open Mods, enable "ONI Companion Link", and restart the
game. Settings in the app shows which state the mod is in and the steps for
your setup. Without the mod, the Codex still works from the game's text data,
and the Buildings tab, Actions tab and live pages ask you to install the mod.

**Phones and tablets (v1.4, UNTESTED):** install the Android app (build steps
in `docs/android.md`). In the game's pause menu, open "Connect a phone" and
switch it on. Scan the QR code in the app, or pick the device from the list and
type the code. Compare the short fingerprint tag on both screens. On iPhone, the
web app (later) needs plain HTTP on the LAN, which anyone on the Wi-Fi can read,
or Tailscale. Dual-screen Android devices can run the app in local mode, with
no pairing; see `docs/android.md`.

**Art and fonts (v1.2):** nothing from the game is in the app. After you
install the app, it shows "Sync art & fonts from your game" once the game runs
with the mod. Tap Sync and wait. The mod copies the art, the game style and
the fonts from your game, while the game is paused, then restores the speed.
A full sync takes several minutes. Later, the app asks again after a game
update or a new DLC, and Settings has a "Re-sync art & fonts" button. During
normal play the mod draws only what the app asks for, so the game keeps
running smoothly. UNTESTED until measured in the game.

The files go into the game's user folder, under `companion/`. Delete that folder to render them again. Synced fonts are cached in the app's data folder, per game build.

The mod writes nothing into your saves, so removing it leaves them as they
were. This is UNTESTED until checked in the game.

## Dev setup

```sh
git clone <this repo> oni-companion
cd oni-companion
python3 -m unittest            # contract and fixture tests
python3 devtools/mock-server.py  # planned: serves fixtures/synthetic for front-end work
```

- `contracts/` holds the frozen JSON Schemas and `api.md`. Read them first.
- `fixtures/synthetic/` holds made-up example data for tests and mocks,
  including placeholder PNGs (solid shapes), a synthetic theme and synthetic
  commands and acks. It has no Klei content and is committed.
- `fixtures/real/` is gitignored. It is a local link to your own game
  files and saves, used by the developer tools.
- Planned: `devtools/fetch-game-files.sh` copies the game's plain-text data from a
  machine that has the game. `devtools/mirror-nova.sh` (planned) mirrors the save and
  live folders into the dev data folder.
- Planned (v1.1): `devtools/push-commands.py` copies "show in game" command
  files from the dev mirror to a game machine, so the camera commands can be
  tested from a Mac.
- `mod/lib/` (the game's DLLs) is gitignored and never committed.
- The mod builds with `dotnet build` against those DLLs.

Do not commit game files, DLLs, saves, rendered art, theme images or built
zips. A planned release check will look for Klei art, sprites, fonts and UI
images in the repo and the zip. UNTESTED until that check exists.

## Layout

- `contracts/`: frozen API, screen, block and mod-file contracts
- `core/oni_companion/`: the Python core (data, save parser, server, tools,
  art, actions, resources, theme, settings)
- `mod/`: the C# mod, ONI Companion Link
- `clients/barry/`: the Barry app (QML and manifest)
- `clients/android/`: the Android app (native Kotlin and Compose, v1.4).
  Build notes and setup in `docs/android.md`.
- `clients/ios/`: the iOS web app (planned, notes only)
- `devtools/`: developer scripts
- `docs/`: architecture and notes
- `tests/`: unit and contract tests

## License

MIT. See `LICENSE`. Third-party references and credits are in `CREDITS.md`.
