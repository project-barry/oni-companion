# Architecture

One Python core does all the logic. Front ends only draw what it sends.

```
 gaming device (Thor or another PB-OS device)                 other device
┌────────────────────────────────────────────────────────────────────┐
│ ONI game ── ONI Companion Link mod (C#)                            │
│   │ saves (.sav)     mod writes:  companion/export/gamedata-*.json  │
│   │                               companion/live/live.json (~1/s)  │
│   │                               companion/art/<build>/… (PNG)    │
│   │                               companion/theme/<build>/theme.json│
│   │ mod reads:       companion/commands/cmd-<seq>.json  ◀── core    │
│   │                  writes:        companion/acks/ack-<seq>.json  │
│   ▼                                                                │
│ core (Python stdlib, package oni_companion)                        │
│   sources → gamedata merge → index → views (blocks)                │
│   colony: mod live ▸ save parser ▸ save header                     │
│   resources (history in memory) · art · fonts · theme · settings    │
│   alerts (tooltip markup → spans) · controls · sync · actions       │
│   tools (calculators) · pad (Actions) · buildings · modstate        │
│   HTTP API /api/v1 (JSON, PNG art, long-poll events)               │
│     ├─ Barry service, 127.0.0.1, Barry token  ◀── Barry QML        │
│     └─ network listener, TLS, device token   ◀── Android APK (v1.4)│
│                                                  iOS web app (later)│
└────────────────────────────────────────────────────────────────────┘
```

## Rules

- All logic lives in the core: data, search, colony facts, calculators,
  resources and trends, the choice of art and theme, settings, and the text
  and order of each page.
- Front ends render **blocks** and send form values back. Blocks carry no
  pixel sizes, colors or fonts. Each front end lays them out for its width.
  Front ends map named theme tokens to their own widgets.
- A new front end needs about 15 block renderers, navigation and settings.
- Alert tooltips arrive as the game's own markup. The core turns them into
  spans (bold, theme colors, inline icons, links). Front ends render spans only.
- The mod only reads and writes files. It has no sockets and no network code.
  It never starts a process either. (v1.4: the "Connect a phone" window writes
  requests and reads the service's pairing state, and nothing more.)
- Event driven: file watches (inotify on Linux, kqueue on macOS) and
  long-poll requests. No polling loops. The mod watches its command inbox with
  a file system watcher, not a timer.
- Game art, the game's style and the game's fonts are never in the repo, the
  app or a release. The mod renders the art and style, and the core reads the
  fonts, from the user's own game, on the user's device, at run time.
- Front ends are API-driven. The phone front ends (Android APK, iOS web app)
  use the same endpoints as the Barry app. The iOS web app is a page the core
  serves; the user adds it to the Home Screen.

## Contracts

Files in `contracts/` are frozen. Changes go through the integrator.

| File | Holds |
|---|---|
| `api.md` | endpoints, auth, errors, long-poll events, art, actions, resources, theme, settings, alerts, controls, sync, fonts; v1.3: tabs, Actions (`/pad`), Buildings and Build, the game mod (`/mod/install`), new events |
| `screen.schema.json` | a Screen: title, blocks, source, asOf, refreshOn, onOpen |
| `blocks.schema.json` | the block types and the Ref kinds (v1.1: `image` block, `art`, `actions`, `badges`; v1.2: `alert` Ref, span `color`/`icon`/`action`, action `trigger`) |
| `settings.schema.json` | settings.json: `zoomToDupeOnSelect` (default false) |
| `theme.schema.json` | the `Theme` reply and the `ModTheme` file from the mod |
| `mod-export.schema.json` | the game-data file the mod writes |
| `mod-live.schema.json` | the live colony file the mod writes (schema 1 and 2) |
| `mod-art-manifest.schema.json` | `companion/art/manifest.json`, written last |
| `mod-command.schema.json` | `companion/commands/cmd-<seq>.json`, core to mod |
| `mod-ack.schema.json` | `companion/acks/ack-<seq>.json`, mod to core |
| `mod-sync-status.schema.json` | `companion/sync/status.json`, mod to core (v1.2) |
| `font-atlas.schema.json` | the Graystroke atlas table the mod exports (v1.2) |
| `pairing.schema.json` | v1.4: pairing state and requests (files), the QR payload, the mDNS TXT record, the Android local-mode marker |

Block types: heading, text, stats, chips, list, grid, ports, phases,
progress, table, notice, form, link, divider, group, and (v1.1) image. v1.3
adds a `picker` block (material choice for Build) and the `grid` variants
`pad` (Actions buttons) and `priority`; buttons carry `active`, `enabled` and
`reason`. A
front end shows any unknown type as a plain "Update the app to see this."
notice. The v1.1 fields (`art`, `badges`, `actions`, `onOpen`) are additive:
a v1 front end ignores them.

## Game files the core reads and writes

Everything below sits in the game's user folder, under `companion/`, on the
game's device. The core and the mod only use these paths.

| Path | Writer | Reader | Purpose |
|---|---|---|---|
| `export/gamedata-*.json` | mod | core | game numbers, one file per DLC set |
| `live/live.json` | mod | core | colony state, about once a second; v1.3: active overlay, tool and priority, unlocked buildings, world stock |
| `art/manifest.json` + `art/<build>/<kind>/<id>.png` | mod | core | rendered art, listed in the manifest |
| `theme/<build>/theme.json` + 9-slice PNGs | mod | core | game style tokens and images |
| `sdf/<build>/` (atlas PNG + table JSON) | mod | core | the game's Graystroke header font, once per build |
| `sync/status.json` | mod | core | art & font sync: state, done, total, current, errors (about every 250 ms) |
| `commands/cmd-<seq>.json` | core | mod | one command: `focus`, `art_request`, `alert_activate`, `alert_dismiss`, `set_speed`, `sync_assets`; v1.3: `overlay_set`, `tool_select`, `build_select` |
| `acks/ack-<seq>.json` | mod | core | the result of a command |
| `pairing/state.json` | service | mod | v1.4: Connect a phone state (switch, addresses, code, QR text, paired devices, last request result) |
| `pairing/requests/req-<seq>.json` | mod | service | v1.4: Connect a phone choices (switch, new code, remove device, reset identity, plain HTTP) |

The core reads the game's fonts (read-only) from `StreamingAssets/fonts/` and
from `sharedassets0.assets`, and caches them in its own data folder, per game
build. It never writes to the game folder.

Rules for these files:

- Every write is atomic: write a temporary file, then rename it.
- The core serves art only from paths listed in the manifest. It never uses a
  path from a request.
- The mod deletes a command file after it runs it, and ignores any command
  older than 10 s. It allows only the commands above (nine since v1.3), and
  runs at most one command per 250 ms. The mod checks each v1.3 command
  against its own lists (overlay, tool, building, material) and acks an
  unknown or locked one with the reason. `sync_assets` is the exception to the 250 ms pace: it runs
  the sync at full speed, pauses the game, and restores the previous speed.
- The mod writes `live.json` straight after a speed change, so the controls
  follow quickly. The same holds for the active overlay, tool and priority
  (v1.3), also when the player changes them in the game.
- Settings are not in the game folder. The core keeps them in its own data
  folder (`settings.json`).

## Core layout

Lines marked (v1.2) and (v1.3) are the modules of those versions.

```
core/oni_companion/
  config.py        paths, modes, environment overrides
  sources.py       game install, user folder, newest save, mod output
  gamedata/        game text and YAML readers, mod export merge, cache
  index.py         search and the "produced by / used by" links
  save/            save header and body parser
  live/            live file reader (freshness and seq), alerts
  colony.py        one Colony model; says which source it used
  resources.py     resource list by category, trends from in-memory snapshots
  art/             art manifest reader, /art route data, 404 fallback
  fonts/           run-time font extraction from the user's game, per build (v1.2)
  markup/          TextMeshPro tooltip markup → spans (v1.2)
  actions/         command inbox writer, action state (pending, done, failed, expired)
  controls.py      speed controls: paused, speed, available (v1.2)
  sync.py          art & font sync: needed detection, status, `sync` event (v1.2)
  theme.py         theme from the mod, or the built-in dark theme
  settings.py      settings.json: defaults, atomic save, `settings` event
  views/           builds Screens from blocks (colony, dupe page, resources, settings, alert page;
                   v1.3: buildings.py, pad.py, provider.py tabs and Build)
  pad.py           Actions tab: overlays, tools, priority grids (v1.3)
  modstate.py      game mod state (missing, disabled, no_live, version_mismatch, ok) and install (v1.3)
  tools/           calculators, one file each
  watch/           inotify (Linux) and kqueue (macOS) watchers
  server/          HTTP server, routes, token checks, long-poll events
  __main__.py      python3 -m oni_companion --mode barry|standalone
```

`devtools/push-commands.py` (planned, v1.1) is a developer script. It copies
new command files from the dev mirror to a game machine over ssh. It is not
part of the core.

## Modes

- **barry** (v1): reads `BARRY_SERVICE_PORT` and `BARRY_SERVICE_TOKEN`,
  binds `127.0.0.1`.
- **standalone** (v1.4): the same core as a service for devices without Barry,
  started as a systemd user service. Its network listener is opened and closed
  by "Connect a phone", not by `--listen` (v1.4 status: the design is in
  `contracts/api.md`; the code is in progress and UNTESTED).
- **standalone** also serves the iOS web app's page (later). The Android APK
  (native) calls the same API over the network listener.
- **Barry** (v1.4): its core keeps the loopback listener for the bottom screen.
  Its network listener and mDNS follow the same rule as standalone: on only while
  the game runs and "Connect a phone" is on.

## Gaming device and companion device (v1.4)

- The **gaming device** runs the game, the mod and the **service** (the core).
  The Thor is both: its bottom screen is the companion, so Barry runs the service
  there. A **companion device** (phone, tablet, browser) only shows screens and
  sends commands.
- **Connecting is done on the gaming device.** The game's pause menu has a
  "Connect a phone" window (on the Thor, also Barry's Settings). It holds the
  switch, the QR code, the one-time code, the addresses, the device name, and
  the paired devices with Remove. A device that is not paired cannot show the
  code it needs, so the companion never starts pairing.
- The **mod** stays files-only. The window writes requests to
  `pairing/requests/`; the service writes `pairing/state.json`, and the mod draws
  it. The mod draws the QR code itself from the payload text (our own encoder).
  The mod never holds a token or a private key.

### Service lifetime

- The service lives only while the game runs. It starts on the mod's first write
  after a game launch (a systemd user path unit watches the companion folder; the
  mod still starts nothing). A Steam launch-option wrapper is the fallback, only
  after asking the owner (VERIFY the path unit sees writes inside the Proton prefix).
- It finds the game process at start and waits on it with a process handle
  (`os.pidfd_open` and `select`). No polling. When the game exits, normally or by a
  crash, it closes the listeners, stops the mDNS announcement and exits.
- Started without a game, it exits at once.
- Code: `core/oni_companion/lifetime.py` (`find_game` reads /proc: native `OxygenNotIncluded` under FEX, or
  `OxygenNotIncluded.exe` below a Steam reaper with `AppId=457140`; `run_standalone`; `GameGate` for Barry's
  core). `core/install/install.sh` and `uninstall.sh` set up the user units, never with sudo. `--ignore-game`
  turns the rule off for development. UNTESTED against a real game process on the Nova.
- A systemd `BindsTo` rule is not enough on its own, because the game is not a
  systemd unit. The process-handle wait is the authority.

### Identity and pinning (4.1)

- On first start the service makes a random instance id (UUID, not from hardware
  or the account), an adjective-animal device name (for example "spiffy-raccoon"),
  and a self-signed certificate with its key. These live in the service's data
  folder. The certificate's SHA-256 fingerprint is the real identity. The id and
  the name are labels that anyone on the network can copy.
- The colony name, the player's name and the Steam name or id are never sent in
  discovery, the QR code or the identity.
- **Pairing binds a companion to one service.** The QR code carries the addresses,
  a one-time code, the id and the fingerprint. The companion pins the fingerprint
  and then talks only to a service that proves it holds the matching key. A typed
  pairing shows the fingerprint tag on both screens, and the user confirms they match.
- **No token goes to an impostor.** The device token is sent only inside a TLS
  session whose certificate matches the pinned fingerprint. Tokens are per
  service. The token is random and stored hashed.
- "Reset identity" makes new values, deletes every device token and turns the
  switch off. Everyone must pair again.

### Discovery

- While "Connect a phone" is on, the service announces `_onicompanion._tcp`. The TXT
  record holds exactly four keys: instance id, device name, API version and core
  version. Nothing else.
- When avahi runs, the service registers through avahi's command-line tool. Otherwise
  it uses its own small multicast responder. The switch off unregisters at once.
- Discovery is a hint. A client that finds a service checks the certificate first.
  A found service whose id is known but whose fingerprint differs is shown as
  "Can't verify this device" and gets nothing.
- Every device must pair. Being on the same Wi-Fi is never enough.

### Pairing and limits

- The code has 8 characters, is valid 5 minutes, works once, and is replaced after
  5 wrong tries. Pairing is rate limited per source address.
- A paired device may use the same API the Barry app has, with the same command
  allow list. It has no file access and cannot install the mod. Its requests are
  rate limited per device.
- Removing a device revokes its token at once; its next request gets 401.
- Transport: HTTPS with the service's pinned certificate on the LAN. Over Tailscale,
  HTTPS through `tailscale serve` when available (VERIFY on SteamOS and PB-OS).
- iPhone (later): Safari cannot pin a self-signed certificate. iOS users choose plain
  HTTP on the LAN (token readable by anyone on the Wi-Fi, off by default) or
  Tailscale (real HTTPS). The window says this in one line when an iPhone pairs.
  No project-run domain or certificate service is planned.

### Local mode on dual-screen Android (4.2)

- On a dual-screen Android device (for example the AYN Thor on stock Android), the
  game runs in a Windows-game emulator app on the top screen and the Android app
  runs on the bottom screen. This is the default, with no network, no mDNS and no
  pairing. The APK contains the core logic and reads and writes the mod's files
  directly.
- Emulator app sandboxing blocks other apps from its private storage. In local
  mode the mod writes its companion folder to shared storage, which the emulator
  maps as a drive. The mod finds that drive through a fixed marker folder
  (`ONICompanion/`, with `marker.json`) that the APK creates. The mod takes no
  path from any command.
- The app shows a one-time setup screen per emulator app until fresh files arrive.
- Built, not tested: bottom-screen launch and input rules, drive mapping per
  emulator and folder access. See `docs/android.md`.


### Linux and Windows (Proton) versions on one device (4.3)

The service watches every ONI user folder at once: the Linux build's, and one per Proton prefix in every Steam library
(SD cards included). `follow.py` picks the active one, without a restart:

1. a folder whose live.json says running and is fresh;
2. the folder of the running game process (`lifetime.find_game`; for Proton the compat folder comes from the process:
   `STEAM_COMPAT_DATA_PATH`, else `WINEPREFIX`, else the exe path in its command line);
3. a folder with a fresh menu live file;
4. the newest activity (the current folder stays on a tie).

`dev.json`, `ONI_USER_DIR` and `--user-dir` force one folder. A switch sends `status`, `colony`, `controls`, `sync`, `art`
(and more) events. Commands, the pairing state and request files, and sync all go to the active folder.

`shared.py` keeps one copy of finished art, fonts and theme per game build + DLC set in `<data>/shared`. Finished art
from any folder is copied in; the art, font and theme routes serve from it, so switching versions asks for no new sync,
and the sync `needed` check asks it for a finished pack.

`cause.py` names the real reason for a front end: `cause` (menu, mod_off, mod_crashed, not_running, stale, no_mod) and
`message` on Controls and Sync. "menu" is said only when a fresh live file says menu. A mod switched off, or emptied by
the game's crash screen (mods.json `enabledForDlc` empty), says so and points to the game's Mods menu.

Not done here: the mod install into every folder, per-version mod state in Settings, and seeding a folder's art from the
shared copy (needs the mod's manifest rules; VERIFY).

## Data sources and fallbacks

| Case | Result |
|---|---|
| No mod export | Codex from game text and element data; Buildings and Actions say the mod is needed |
| Mod export present | DLC sets merged into one union, each entry tagged with its DLC |
| No live file | colony from the newest save, then from the save header |
| Live file says `menu` | colony from save data |
| No art manifest | no `art` field in any Screen; front ends show the v1 glyph |
| Art file missing or not in the manifest | 404 `not_found`; the front end shows the glyph |
| No theme from the mod | `GET /theme` returns the built-in dark theme (`source: "builtin"`) |
| No live file, resources | the save's resource totals (no note on the page; the header says where the numbers come from) |
| No mod export, Buildings or Actions | the tab says what is missing; no Build button without the unlock data |
| Mod missing, disabled, stale or wrong version | Settings says which state and the steps; other pages do not name the mod |
| Game in the menu or no mod, action | 503 `unavailable` with a message saying which is missing |
| Live file schema 1 | still read: resources as the old id-to-kg map, no status items |
| No sync yet, or no fonts | the app uses its fallback fonts and the glyph art; `GET /sync` says `needed: true` |
| Font file missing or not extracted | the next role in the theme's fallback list; nothing breaks |
| Game not running with the mod, sync | `GET /sync` has `canStart: false`; the app says "Start Oxygen Not Included to sync" |

Every reply says its `source` and `asOf`. The core never invents data that
is missing; it says so.

## Commands and "show in game"

1. A front end taps a button on a Screen. The button carries `{id, label, args}`.
2. The front end posts `args` to `POST /actions/<id>`. The core writes
   `commands/cmd-<seq>.json` atomically and replies `{"seq": n}`.
3. The mod runs the command on the game's main thread, writes
   `acks/ack-<seq>.json`, and deletes the command file.
4. The core reads the ack and changes the action's state. `GET /actions/<seq>`
   gives `pending`, `done`, `failed` (with a message) or `expired` (no ack in
   10 s). Each change also sends an `action` event.

A `focus` command moves the camera once. It does not follow. A screen with
`onOpen` runs its actions once when the user opens the page, through the same
path. Front ends do not run them again on refresh or on Back. The core sets
`onOpen` only when the setting `zoomToDupeOnSelect` is on.

## Alerts (v1.2)

- Each live alert carries the game's own `title`, `type`, `tooltipMarkup`,
  `links` (one per highlighted line), `click` (the main click result) and
  `dismissable`. The app hard-codes nothing per alert.
- The core parses the markup into spans. A tapped link is an `alert_activate`
  with that link. The alert page (`/entry/alert/<id>`) has an "Open in game"
  action only when the game's click does something.
- Dismiss needs two steps: a long press reveals a "Dismiss" button, and only a
  tap on that button sends `alert_dismiss`. A non-dismissable alert says it
  cannot be dismissed in the game.
- Alert ids are the mod's instance ids, stable while the notification exists.
  An unknown id gives a `failed` result ("Alert is gone").

## Speed controls (v1.2)

- `GET /controls` gives `{available, paused, speed, pending?}`. `available` is
  false in the menu, without the mod, or with stale live data.
- `POST /controls` writes `set_speed`. The reply carries `pending`, so the app
  highlights the pressed button at once and then follows `live.json`.

## Art and font sync, fonts (v1.2)

- Nothing from the game is shipped. `GET /sync` says whether a sync is needed
  (no art pack, a new game build, or a new DLC set). `POST /sync` writes
  `sync_assets` with `full` or `missing`.
- During a sync the mod writes `sync/status.json`. The core turns it into the
  `sync` event. The mod runs the sync at full speed and restores the game
  speed afterwards.
- Fonts are read by the core from the user's game, cached per build, and
  served at `GET /fonts` and `GET /fonts/<name>`. The theme names a font role
  (`body`, `header`, `title`), not a file. Front ends fall back per role and
  per glyph.

## Settings

- `GET /settings` returns a Screen with a `form` block that posts to
  `/settings`. `POST /settings` saves and returns the Screen again.
- The core writes `settings.json` in its own data folder, atomically. Missing
  keys mean the defaults.
- A save sends a `settings` event. Screens with `refreshOn: ["settings"]`
  fetch again.

## Actions, Buildings and Build (v1.3)

- The overlay and tool lists, their order, icons, DLC need and availability
  come from the mod's export, which copies the game's own definitions. The
  app hard-codes none of them.
- `GET /pad` is the Actions tab: Overlays, Tools and Priority grids. Tapping an
  active overlay sends `mode: "None"`, like the game. `tool_select` activates
  the tool in the game; the player then drags on the game screen. Priority
  alone changes only the priority.
- `GET /buildings` (the Buildings tab) lists the buildings in build-menu
  order. A Build button is enabled when the game unlocks the building; a locked
  one is greyed and gives the research it needs (`unlocked`, `lockReason`).
  The state refreshes on a `build` event when research finishes.
- Build opens a `picker` block first: per material slot, the candidates with
  their art, the amount needed and the amount the colony has in the active
  world. Candidates the colony cannot cover are greyed. The core sends
  `build_select {buildingId, materials}`; the mod opens the game's build menu
  on that building with those materials. If a material became unavailable, the
  ack says so and the game keeps its own choice.
- Building pages: ports become an Automation section (the game's port names
  and signal texts) or a Flow section (real material and power ports only);
  empty sections are hidden; Research shows the tech's display name, linked to
  its Codex entry; internal capacities the game does not show are left out.
- The core builds every screen. The mod supplies only game facts and runs
  commands. Front ends draw the blocks and send `args` back.

## Speed targets (Thor)

- First cache build under 10 s; warm start under 1 s
- Search under 50 ms
- Live update from file event to client under 1.5 s
- Command from tap to the mod's ack: the mod runs one command per 250 ms at
  most, so a burst of taps waits. Target: the ack within 1 s when the game is
  running.
- Mod frame cost from art and style rendering: no frame over 4 ms because of
  the mod. The mod logs the worst frame.
- Cache keyed by game build, DLC sets and mod export hashes

These are targets. They are UNTESTED until measured on the device.
