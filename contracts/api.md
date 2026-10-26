# ONI Companion HTTP API v1 (with the v1.1, v1.2, v1.3 and v1.4 additions)

FROZEN. Changes go through the integrator (I0 for v1, I1 for v1.1, I2 for v1.2). v1.1 and v1.2 only add:
every v1 reply, field and endpoint keeps its meaning, and a v1 front end keeps working
(it shows an unknown block `type` as the "update the app" notice). Schemas: `screen.schema.json`,
`blocks.schema.json`, `api.schema.json`, `mod-export.schema.json`,
`mod-live.schema.json` (schema 1 and 2; v1.3 only adds optional fields), and for v1.1 `mod-art-manifest.schema.json`,
`mod-command.schema.json`, `mod-ack.schema.json`, `theme.schema.json`, `settings.schema.json`, and for v1.2 `mod-sync-status.schema.json` and `font-atlas.schema.json`. A synthetic example of every reply is in
`fixtures/synthetic/` (listed in `fixtures/synthetic/manifest.json`).

## Basics

- Base path `/api/v1`. All replies are `application/json; charset=utf-8`, except
  `GET /art/<kind>/<id>` on success, which is `image/png` (errors are still JSON).
- No other paths are served (no HTML, no other static files). `GET /fonts/<name>` serves only names listed by `GET /fonts`.
- Lists are wrapped in an object (`{"results":[...]}`) so fields can be added.
- Unknown query parameters are ignored. Unknown JSON fields in a request are ignored.
- Clients must ignore unknown fields in replies. A client must show an unknown
  block `type` as a plain notice ("Update the app to see this.") and keep rendering.
- Temperatures in replies are shown in Celsius unless a Screen says otherwise;
  the core formats display strings. Raw data (`/raw`) is in game units (see
  `mod-export.schema.json`).

## Auth

- Every request needs a token. Header `X-Oni-Token: <token>`.
- Barry mode also accepts header `X-Barry-Token: <token>` and query `?token=<token>`
  (the Barry runtime passes `BARRY_SERVICE_TOKEN`).
- Tokens are compared in constant time. A missing or wrong token gets HTTP 403
  with error code `bad_token` (never 401, never a hint which part was wrong).
- Barry mode binds `127.0.0.1` only. `--listen` with a non-loopback address
  exits with "not in v1" (v1.4: the network listener is opened by Connect a phone, not by `--listen`; device tokens
  and 401 are in the v1.4 section).

## Errors

Body: `{"error":{"code":"...","message":"..."}}` (`Error` in `api.schema.json`).

| HTTP | code | When |
|---|---|---|
| 400 | `bad_request` | bad query value, bad JSON body, bad form value |
| 403 | `bad_token` | token missing or wrong |
| 404 | `not_found` | unknown path, kind, id, tool |
| 503 | `no_data` | game not found and no cache, so nothing can be answered |
| 503 | `unavailable` | v1.1: an action needs the mod or a running colony and it is not there (game in the menu, mod missing); the message says which |
| 501 | `not_in_v1` | planned endpoints below |
| 500 | `internal` | bug; message is short, details go to the log |

## Endpoints

| Method + path | Returns |
|---|---|
| `GET /status` | `Status`: game found, build, DLC installed/exported, mod present + version, cache state, colony source, newest save, `userDir` (which user folder: linux, proton, ...) |
| `GET /home` | Screen: the start page (colony summary, search hint, kinds, tools) |
| `GET /search?q=&kind=&limit=` | `Search`. `limit` default 20, max 100. Empty `q` gives 400. `kind` optional filter |
| `GET /kinds` | `Kinds`: each kind with a label and a count |
| `GET /list/<kind>?dlc=&sort=` | Screen listing one kind. `dlc` = a DLC id or `base` to filter; `sort` = `name` (default) or `dlc` |
| `GET /entry/<kind>/<id>` | Screen for one entry (ids URL-encoded) |
| `GET /raw/<kind>/<id>` | `Raw` (the merged entry for custom views) |
| `GET /colony?world=` | `ColonyReply` (Screen + `raw`). `world` = world id; default = active world |
| `GET /tools` | `ToolList` |
| `GET /tools/<id>` | Screen with a `form` block (default values filled in) |
| `POST /tools/<id>` | Body `ToolPost` (`{"values":{...}}`); reply is a Screen with the result |
| `GET /events?since=<seq>&timeout=25` | `Events` (long-poll) |
| `GET /art/<kind>/<id>` | v1.1. `image/png` rendered by the mod from the user's own game |
| `POST /actions/<id>` | v1.1. Body `ActionPost`; reply `ActionSent` (`{seq}`) |
| `GET /actions/<seq>` | v1.1. `ActionStatus` |
| `GET /theme` | v1.1. `Theme` (`theme.schema.json`) |
| `GET /resources?world=&q=` | v1.1. Screen: the Resources tab |
| `GET /settings` | v1.1. Screen with a `form` block (`endpoint: "/settings"`) |
| `POST /settings` | v1.1. Body `SettingsPost`; reply is the settings Screen |
| `GET /controls` | v1.2. `Controls`: `{available, paused, speed, pending?}` |
| `POST /controls` | v1.2. Body `ControlsPost` (`{state, speed?}`); writes `set_speed`; reply `Controls` |
| `GET /sync` | v1.2. `Sync`: art & font sync progress and whether a sync is needed |
| `POST /sync` | v1.2. Body `SyncPost` (`{scope?}`); writes `sync_assets`; reply `Sync` |
| `GET /fonts` | v1.2. `FontList` |
| `GET /tabs` | v1.3. `TabList`: the tabs, named and ordered by the core |
| `GET /pad` | v1.3. Screen: the Actions tab (overlays, priority bar, tools) |
| `GET /buildings` | v1.3. Screen: the Buildings tab (the game's build menu, a Build button per building) |
| `POST /mod/install` | v1.3. Body `ModInstallPost`; reply `ModInstallReply`: copies the bundled mod after the user said yes |
| `GET /fonts/<name>` | v1.2. The font file (`font/ttf` or `font/otf` (OpenType-CFF files such as Economica are served as .otf, kind stays `ttf`), `image/png` or `application/json`; errors stay JSON) |
| `GET /identity` | v1.4. `Identity` (instance id, adjective-animal name, certificate fingerprint). Network listener: no token needed |
| `GET /connect` | v1.4, loopback only. `ConnectState` (switch, listener, addresses, code, QR text, devices) |
| `POST /connect/switch` | v1.4, loopback only. Body `ConnectSwitchPost`; Connect a phone on or off; reply `ConnectState` |
| `POST /connect/plain-http` | v1.4, loopback only. Body `ConnectSwitchPost`; the iOS plain-HTTP switch (default off); reply `ConnectState` |
| `POST /connect/code` | v1.4, loopback only. New one-time code; reply `ConnectDone` |
| `GET /connect/devices` | v1.4, loopback only. `ConnectDevices` |
| `DELETE /connect/devices/<deviceId>` | v1.4, loopback only. Remove (unpair) a device; its next request gets 401; reply `ConnectDone` |
| `POST /connect/reset-identity` | v1.4, loopback only. New instance id, name and key; unpairs everyone; switch goes off; reply `ConnectDone` |
| `POST /connect/claim` | v1.4, network listener, no token, rate limited. Body `ClaimPost`; reply `ClaimReply` (the device token) |

### Screens

A Screen reply always has `source` and `asOf` when the numbers depend on a source.
`refreshOn` tells the client which `/events` change names should make it re-fetch
the same URL. The colony Screen has `"refreshOn":["colony"]`; look-up Screens have
`["gamedata"]`. Static Screens (tools forms) have none.

### Events (long-poll)

- `since` = last `seq` the client saw (0 or missing = "give me the current seq now").
- If the current seq is greater than `since`, reply at once. Otherwise hold the
  request up to `timeout` seconds (default 25, max 60), then reply with `changed: []`.
- `changed` names: `colony` (live file or save changed), `gamedata` (export or game
  files changed, cache rebuilt), `status` (anything shown in `/status` changed),
  `action` (v1.1: an ack arrived or an action expired; ask `GET /actions/<seq>`),
  `settings` (v1.1: a setting was saved; Screens with `refreshOn:["settings"]` re-fetch),
  `art` (v1.2: the mod's art manifest gained images; a front end whose picture came back 404 asks for it again. Screens do not re-fetch for it),
  `controls` (v1.2: paused / speed / availability changed; re-fetch `GET /controls`),
  `sync` (v1.2: `companion/sync/status.json` changed, the sync need changed, or fonts were extracted; re-fetch `GET /sync`; after a finished sync also `GET /fonts` and `GET /theme`).
- The server wakes waiting requests within 100 ms of the file event. Event driven; no polling.

### Forms

A `form` block names a tool. Submit with `POST /tools/<tool>`:
`{"values":{"mass":{"value":5,"unit":"kg"},"element":"SynthWater","useKelvin":false}}`.
Value types per field kind are in `blocks.schema.json` (`Field`). Missing values take the
field default. A bad value gives 400 `bad_request` with the field name in `message`.
Tools take numbers from game data, never from constants in code.

### Ref kinds

`element, building, critter, plant, geyser, food, medicine, recipe, tech, trait, skill, room, codex`,
and (v1.1) `dupe`, and (v1.2) `alert`, which only `/entry` resolves.
Ids are the game's own ids. `codex` ids are the codex entry ids (file-level entries from the
game's codex files). A `Ref` always resolves with `GET /entry/<kind>/<id>`; if the entry is
missing (for example a DLC not exported) the reply is 404 `not_found` and clients show
"Not available".

### Data sources and fallbacks

| Case | Behavior |
|---|---|
| No mod export | look-up works from game YAML + strings (`source: "yaml"`); building pages hold a `notice` "Install the ONI Companion Link mod for numbers." |
| Mod export present | `source: "mod-export"`; DLC sets merged into a union, each entry tagged with `dlc` |
| No live file | colony from the newest save (`source: "save"`), then the save header (`"header"`), else `"none"` |
| Live file with `state: "menu"` | falls back to save data, `raw.state` is `"saved"` |

## v1.1 additions

All optional for a client; the core only sends them when it has the data.

### Art: `GET /art/<kind>/<id>`

- `kind` is an art kind: `building element critter plant seed egg food medicine item dupe`
  (catalog art, 128 px) and `dupe` (portraits, 256 px), plus `ui` (theme images, from `GET /theme`).
  Ids are the game's ids. `dupe/<id>` serves the portrait whose `appearanceHash` matches the
  duplicant's current hash in the live file, else the newest one.
- Same token rules as everything else; `?token=` works so an `Image` source can load it.
- The core serves only files listed in the mod's art `manifest.json` (and theme files for `ui`),
  never a path from the request. Missing entry or file: 404 `not_found`; the front end shows its
  v1 glyph. Without the mod there is never art, and no `art` field appears in any Screen.
- v1.2 on demand: when the mod's manifest says `onDemand`, a Screen also carries the art path of an item that has no image yet.
  A `GET` for it answers 404 and, once per item (at most 20 outstanding, none for a minute after a failure), the core sends the mod an
  `art_request` command. When the manifest lists the image the core publishes the `art` event; the front end asks again. Front ends
  should load images only for rows that are on screen.
- Screens carry `art` (an `ArtPath`, this URL path) on Refs, list items, cards, headings and
  `image` blocks. Art files are rendered from the user's own game on the user's device; the repo
  and the app contain none.

### Actions: `POST /actions/<id>`, `GET /actions/<seq>`

- A Screen offers buttons as `actions:[{id,label,args}]` on cards and list items. On tap the front
  end posts `args` as the body to `/actions/<id>`. v1.1 has one action: `focus`
  (`{"target":{"kind":"dupe","id":"<live dupe id>"},"select":true}`). One tap = one camera move,
  never a follow. `select` defaults to true (the game opens the duplicant's info panel).
- Reply `{"seq":n}` once the core has written `companion/commands/cmd-<n>.json`
  (see `mod-command.schema.json`). Result: `GET /actions/<n>` gives `state` `pending`, `done`,
  `failed` (with a short `message`) or `expired` (no ack within 10 s); each change also sends an
  `action` event.
- Game in the menu, mod missing or no inbox: 503 `unavailable`. Unknown action id: 404. Bad body: 400.
- The mod allow-lists `focus`, ignores commands older than 10 s and runs at most 1 per 250 ms.
- Screen `onOpen:[{action,args}]`: the front end runs these once when the user opens the page,
  by posting like a tap. Not on refresh, not on Back. The core adds it to a duplicant page only when
  the setting `zoomToDupeOnSelect` is on.

### Resources: `GET /resources?world=&q=`

A Screen (`refreshOn:["colony"]`): one collapsible `group` per category in the game's own order,
each titled with its total, holding a `list` of items (art, name, amount with unit in `badge`,
trend in `subtitle`; Refs to the look-up entry when there is one). `world` = world id (default active).
`q` = optional case-insensitive substring filter applied by the core. The Screen sets `filter`
(a text field the front end applies on the loaded rows) and `worldSwitcher`. Trends come from
snapshots the core keeps in memory only; first start shows "-". Without a live file it shows the
save's totals with `source:"save"` and a notice "from the last save".

### Theme: `GET /theme`

`Theme` (`theme.schema.json`): named color tokens, a font family, and 9-slice images (`art` =
`/api/v1/art/ui/<name>`, with `insets`). With no game theme the core replies
`source:"builtin"`, `slices:[]`.

### Settings: `GET /settings`, `POST /settings`

The core owns the settings and keeps them in `settings.json` (`settings.schema.json`) in its data
folder, written atomically. `GET` returns a Screen whose `form` has `endpoint:"/settings"`; a
front end submits `{"values":{...}}` there instead of `/tools/<tool>`. A save sends a `settings`
event. v1.1 has one setting: `zoomToDupeOnSelect` (toggle, default false).

### Colony and duplicant pages

`GET /colony` keeps its Screen + `raw` shape. Duplicant cards may carry `art`, `badges`
(`level` danger/warn/info, worst first), `meters`, and a `ref` `{kind:"dupe", id}`. The new Ref
kind `dupe` resolves with `GET /entry/dupe/<live dupe id>` to the complete duplicant page
(large `image`, every meter, status items and diseases, traits, skills, attributes, morale, and
the always-present "Show in game" `focus` action; `onOpen` only when the setting is on). `dupe` exists
only for `/entry`: it is not in `/search`, `/kinds`, `/list` or `/raw`. Examples:
`fixtures/synthetic/screens/colony-v11.json`, `dupe-page.json`, `dupe-page-onopen.json`.
Cards stay short: portrait, name, task, the stress, health and calories meters, and badges only
when something is wrong.

### Live file schema 2

`mod-live.schema.json` accepts `schema` 1 and 2. Schema 2 adds per duplicant `appearanceHash`,
`statusItems`, `diseases`, `stamina`, `bodyTempC`, `attributes`, and makes `worlds[].resources` a
list of `{id,name,category,amount,unit,kcal?}` (schema 1 keeps the id-to-kg map). The core reads
both.

## v1.2 additions

All optional for a client. Everything below is additive: v1.1 front ends keep working (an unknown
`trigger`, span field or event name is ignored).

### Alerts like the game

- `live.json` alerts carry `title`, `type` (the game's notification type), `tooltipMarkup` (the
  exact TextMeshPro string of the game's tooltip), `links` (one per highlighted line), `click`
  (what a click does) and `dismissable` (`mod-live.schema.json`, `Alert`).
- The core turns the markup into **spans**. Spans (`blocks.schema.json`, `Span`) gain optional
  `color` (a theme color token), `icon` (an `ArtPath` of kind `ui`: the inline `<sprite>`) and, on
  plain and bold spans, `action` (a tapped `<link>`: `alert_activate` with that link). Front ends
  render spans only; there is no markup parser in any front end.
- **Alert page:** the Ref kind `alert` resolves with `GET /entry/alert/<id>` (id = live alert id):
  the tooltip as spans, one `alert_activate` action per link, an "Open in game" action when the
  game's click does something, and a `dismiss` action when `dismissable`. 404 `not_found` once the
  alert is gone. The colony alert list (`variant:"alerts"`) items carry `ref {kind:"alert"}`.
- **Action `trigger`:** `tap` (default) or `longPress`. A long press (about 500 ms) on a row or card
  reveals its `longPress` actions as buttons; only a tap on the revealed button posts. The core
  puts `alert_dismiss` there, only for dismissable alerts. For a non-dismissable alert a long press
  has nothing to reveal and the row shows "This alert can't be dismissed in the game".
- **`POST /actions/alert_activate`** `{alertId, link?}` and **`POST /actions/alert_dismiss`**
  `{alertId}` work like `focus`: reply `{seq}`, result by `GET /actions/<seq>` and the `action`
  event. An alert that is gone gives a `failed` result with "Alert is gone". A dismissed alert
  leaves the app on the next `live.json`; until then the core marks it `dismissing`.
- Command allow list (`mod-command.schema.json`): `focus`, `art_request`, `alert_activate`,
  `alert_dismiss`, `set_speed`, `sync_assets`. Same limits: age 10 s, one per 250 ms, main thread,
  an ack each.

### Speed controls: `GET /controls`, `POST /controls`

- `GET /controls` -> `{available, reason?, paused?, speed?, pending?, asOf?}`. `available` is false
  in the menu, without the mod, or when `live.json` is older than the core's freshness limit
  (`reason` says which). It follows `live.json` (`paused`, `speed`); every change sends a
  `controls` event.
- `POST /controls` `{state:"pause"|"play"|"speed", speed?:1|2|3}` writes a `set_speed` command; the reply is
  `Controls` with `pending` set to what was sent, so a front end highlights the pressed button at once.
  It then follows the real state. `speed` selects a speed and keeps the pause state (the game's speed
  buttons); `speed` with `pause`, or state `speed` without one, is 400 `bad_request`; unavailable is 503
  `unavailable`. The mod writes `live.json` straight away after a speed change.
- Front ends show the game's four buttons on every page, dimmed when `available` is false: Pause (a toggle:
  `pause` while playing, `play` while paused; highlighted while paused) and 1, 2, 3 (`speed`; the selected
  speed is highlighted, paused or not). Icons come from `GET /theme` `icons` (`speedPause`, `speed1..3`),
  else plain icons.

### Art & font sync: `GET /sync`, `POST /sync`

- Nothing from the game is shipped. A sync draws the user's own game art, the theme and fonts at run
  time. `GET /sync` -> `Sync`: `state` (`idle|running|done|failed`), `done`, `total`, `current`,
  `errors`, plus `needed` / `neededReason` (`no_pack`, `new_build`, `new_dlc`), `suggestedScope`,
  `canStart` (false: show "Start Oxygen Not Included to sync") and `fonts`.
- `POST /sync` `{scope?:"full"|"missing"}` writes a `sync_assets` command (503 `unavailable` when
  `canStart` is false). The front end may leave the screen; the sync continues in the mod. Progress
  comes from the mod's `companion/sync/status.json` (`mod-sync-status.schema.json`, about every 250
  ms) and is announced with the `sync` event. The mod pauses the game while it runs and restores the
  previous speed after.

### Fonts: `GET /fonts`, `GET /fonts/<name>`

- `FontList`: the fonts the core has for this build, read from the user's own game and cached per
  build: Noto Sans (body), Economica and League Spartan (TTF data extracted from the game's asset
  file), and the Graystroke SDF atlas as two files (`sdfAtlasImage` PNG + `sdfAtlasTable` JSON,
  `font-atlas.schema.json`) exported by the mod. Empty until synced.
- `GET /theme` `font.roles` names a role (`body`, `header`, `title`) with a family, the `/fonts`
  entry that provides it and a fallback list. Front ends map roles to loaded fonts and fall back
  per role and per glyph; nothing breaks when a font is missing.

## v1.3 additions

All optional for a client; a v1.2 front end keeps working (an unknown block `type` shows the "update the app"
notice). Everything the new pages show comes from the game through the mod's export and live file; the core
only combines it. **Pages other than Settings never mention the mod.**

### Tabs: `GET /tabs`

`TabList`: Colony, Resources, Buildings, Actions, Codex, Settings, with `label` and `path`. Codex carries the
game's own word for its encyclopedia (from the game's strings, `STRINGS.UI.CODEX.TITLE`, shown as a title:
"Database"). Its `path` is `kinds`: the front end draws the look-up (`GET /kinds`, `/search`, `/list/<kind>`, `/entry`)
and the calculators (`GET /tools`) there, leaving out `excludeKinds` (buildings have their own tab).

### Actions tab: `GET /pad`, and the pad actions

A Screen (`refreshOn:["pad","gamedata","status"]`) with three grids: **Overlays** and **Tools** (`variant:"pad"`:
each card is one button, its `art` the game's icon when synced, its first action the tap) and **Priority**
(`variant:"priority"`: 1..9 then Emergency). A button action is `overlay_set {mode}`, `tool_select {tool}` or
`tool_select {priority}`. The action carries the game's state: `active` (highlighted: the active overlay, the
active tool, the current priority) and `enabled:false` + `reason` (greyed; the reason shows on tap or long press:
"Needs <DLC name>.", "The game is not running.", "Load a colony in the game first."). Tapping the active overlay
sends `mode:"None"`, like the game. Without lists in the export the Screen is one notice.

`POST /actions/overlay_set` `{mode}`, `POST /actions/tool_select` `{tool?, priority?}` (at least one; priority 1..9 or
`"emergency"`; priority alone changes only the priority) and `POST /actions/build_select`
`{buildingId, materials?, facadeId?}` work like `focus`: reply `{seq}`, result by `GET /actions/<seq>` and the
`action` event. The core refuses before writing: 400 for an overlay, tool or material the game does not list, a
building that is not unlocked (the reason as `message`: "Needs research: <tech>"), 404 for an unknown building,
503 when the game is not running. The mod acks with the game's own reason when the game refuses
("Not researched yet", "Not enough <material>").

### Buildings tab: `GET /buildings`, the Build button and the material picker

A Screen (`refreshOn:["build","gamedata","status"]`, `filter`): one collapsible `group` per tab of the game's
build menu, in the game's order, each a `list` in the game's order. Every row has a `ref` (the building page) and
a **Build** action (`build_select {buildingId}`, the game's default materials) with `enabled` / `reason`: enabled
by the game's own rule (live `unlockedBuildings`, else the completed research against the building's tech, else
the export's snapshot), greyed with "Needs research: <tech display name>" or "Needs <DLC name>." otherwise, and
greyed with "The game is not running." while no colony runs. Research finishing sends the `build` event.

A building page (`GET /entry/building/<id>`) for a building of the build menu starts with its Build button, or,
when the game lets the player choose materials, a **`picker`** block: per material slot the candidates in the
game's order with `needKg`, `haveKg` (the active world's stock), `enabled` (false = less than needed, shown
greyed, not selectable), `selected` (the pre-selection: the enabled candidate with most stock). A candidate the
stock list does not mention (not discovered) is not offered. The picker holds no state: the front end keeps the
selection and posts `action.id` with `action.args` plus `materials` (one option id per slot, in slot order). The
page re-fetches on `build` and, with a picker, on `colony` (the stock moves).

Building pages also change: **Automation** (a group, only when the game names the logic ports: the port's name and
description, then "Green signal: ..." and "Red signal: ..." with the `positive` / `negative` colors), **Flow**
only for gas, liquid, solid and power ports and converter rates (no logic ports, no empty cards), **Research**
(the tech's display name linked to its entry, with its cost), and no default storage capacity.

Integration clarifications (I3): a port text that already names the signal (for example "Green Signal: Open") is shown as
written; only texts without it get the "Green signal: " / "Red signal: " prefix. When an export has no
`ports[].name/greenText/redText`, Automation falls back to the game's own strings for a building with exactly one logic
port and one set of `LOGIC*` strings (the mod's fields win when present). A gas, liquid or solid port is dropped from Flow
when a converter already lists an element of that state in the same direction (power ports stay). `worlds[].stock` lists
discovered candidates only: an absent id means the game does not offer it. Critter diet `consumes[]` entries are
alternatives; a critter eats one of them.

### The game mod: `Status.modState`, `POST /mod/install`

`GET /status` gains `modState` (`ModState`): `state` is `missing`, `disabled`, `no_live`, `version_mismatch` or
`ok`, with a `summary`, plain-language `steps` for this setup, `copies` (`local`, `workshop`), `install`
(`available`, `reason`, `target`) and `compat`. Only the Settings Screen shows it (and names the mod).
- missing: no copy in the game's `mods` folder and the mod never wrote data. `disabled`: the game's `mods.json`
  does not enable it for the active content (the game's own rule: `enabledForDlc` contains `EXPANSION1_ID` with
  Spaced Out on, else `""`; the old `enabled` field is ignored). `no_live`: enabled but no recent data (steps
  point to the game's Player.log). `version_mismatch`: the mod is older than `compat.coreSupportsMod` or its
  `requiresCore` range excludes this app (`compat.problem`: `mod_too_old`, `mod_too_new`, `app_too_old`,
  `app_too_new`). Both sides declare a range: the app in `compat.coreSupportsMod`, the mod as `requiresCore` in
  its export and live file (inclusive dotted versions, no max = open). The mod also writes `contract` (3).
- The Settings Screen's install button is the action `mod_install` with `args {confirm:true}` and `confirm:
  "<question>"`: the front end asks the user, and posts only on Yes. `POST /mod/install` `{confirm:true}` (also
  `{values:{confirm:true}}`) copies the three files of the mod this app ships into `mods/Local/OniCompanionLink`
  (a fixed list; nothing else), never into a game folder without confirm (400). Not available (503
  `unavailable`, with the reason) when a Steam Workshop copy is subscribed (two copies would both load), when
  the newest version is already there or when the app ships no mod. The game must be restarted afterwards.
- v1.4.1, both versions: the install writes into EVERY detected ONI user folder (Linux and each Proton prefix),
  skipping a folder with a Workshop copy; the reply lists `paths` and `skipped`. `modState.versions` has one row per
  folder (`ModVersion`: kind, path, library, installed version, `enabled` for that folder's active DLC set,
  `crashDisabled`, `workshop`), `versionsSummary` the one-line form and `updateBoth` is true when the versions
  differ. ONI_USER_DIR / dev.json force one folder (and the install then touches only it). The Settings Screen on
  the network listener has no install button (403 `local_only`).

### Events and Screen fields

New event names: `pad` (live.json's `activeOverlay`, `activeTool` or `priority` changed, also when the player
changed them in the game) and `build` (what can be built changed: research finished, the game started or
stopped). New optional Screen fields and block fields are in `blocks.schema.json`: `Action.active`, `enabled`,
`reason`, `confirm`; `Grid.variant`; the `picker` block.

### Mod files (additive)

Export: `contract`, `requiresCore`, `dlcNames`, `overlays`, `tools`, `buildMenu`, `constants.toolNumbers`, and
per building `unlocked`, `dlcActive`, `lockReason`, `materials[].label` / `candidates`, `ports[].name` /
`description` / `greenText` / `redText`. Live: `contract`, `requiresCore`, `activeOverlay`, `activeTool`,
`priority`, `unlockedBuildings`, `worlds[].stock`. Commands `overlay_set {mode}`, `tool_select {tool?, priority?}`,
`build_select {buildingId, materials?, facadeId?}` with acks (`mod-command.schema.json`, `mod-ack.schema.json`).
The calculators read their game numbers from `constants` (the core passes them to every tool).

## v1.4 additions: other devices find and pair with the gaming device

ADDITIVE. Every v1..v1.3 reply, field and endpoint keeps its meaning, and the loopback listener (Barry, the Thor
bottom screen, the Android local mode) works exactly as before. Schemas: new `pairing.schema.json` (state and request
files, QR payload, mDNS TXT, local-mode marker); `api.schema.json` gains `Identity`, `ConnectState`,
`ConnectSwitchPost`, `ClaimPost`, `ClaimReply`, `ConnectDevices`, `ConnectDone`, `PairedDevice`, `PairingCode`,
`ConnectAddress`, the error codes below, the `connect` event and the optional `Status.connect`.
Fixtures: `fixtures/synthetic/api/connect-*.json`, `identity.json`, `companion/pairing/`, `pairing/`,
`companion-local/`. The old reserved pair-endpoint names (see Planned, below) stay 501 `not_in_v1` (the real endpoints are `/connect/*`).

### Two listeners

| Listener | Binds | Transport | Auth | Open |
|---|---|---|---|---|
| Loopback | `127.0.0.1` | plain HTTP | as in v1 (`X-Oni-Token` / `X-Barry-Token`, wrong = 403 `bad_token`) | as in v1 |
| Network | the LAN / Tailscale addresses | HTTPS with the service's own certificate | device token (below) | only while Connect a phone is ON; closed at once when it is switched off |
| Network, plain HTTP | same addresses, port + 1 | plain HTTP | device token | only while Connect a phone AND the iOS plain-HTTP switch (default off) are ON |

The TLS port is 47615 when free, else a free port chosen at switch-on; the plain-HTTP port is the TLS port + 1 when
free, else another free port. Both are in `ConnectState`. All `/connect*` endpoints except `claim` are
LOOPBACK ONLY: from the network listener they get 403 `local_only` (a paired device cannot list, add or remove
devices or turn the switch off). Everything else in the endpoint table above is served on the network listener
with the same replies and the same command allow list as on loopback. `POST /mod/install` and `POST /actions/mod_install` are LOOPBACK ONLY too (403 `local_only`): a paired device gets no
mod install. `POST /sync` stays as it is for a paired device; no endpoint gives file access.

### Identity (4.1)

On first start the service makes a random `instanceId` (UUID v4), an adjective-animal `name` (`spiffy-raccoon`,
lowercase letters and one dash, own word lists, real animals only) and a key pair with a self-signed certificate
(created with the system `openssl` command, EC P-256, 10 years, subject `CN=<instanceId>`; stored with mode 600 in the
service's data folder). `fingerprint` = SHA-256 of the DER certificate, lowercase hex; `fingerprintTag` = its first 4
hex digits uppercase. The fingerprint is the real identity; id and name are labels anyone could copy. The colony
name is NEVER broadcast or put in `Identity`, mDNS or the QR code. `POST /connect/reset-identity` makes all new
values, deletes every device token, switches Connect a phone off and keeps the plain-HTTP switch off.

### Discovery (mDNS / DNS-SD)

While Connect a phone is ON the service announces `_onicompanion._tcp`, instance name
`ONI Companion on <name>`, port = TLS port. TXT keys EXACTLY `id`, `name`, `api`, `core` (`MdnsTxt`); nothing
else. When `avahi-daemon` runs, the service registers through the `avahi-publish-service` command,
else it falls back to its own multicast responder. Off = unregistered at once.
Discovery is only a hint: a client that finds an entry compares the certificate fingerprint from a TLS
connection with its stored pairings (Paired / New / "Can't verify this device" if a known `id` shows another
fingerprint) and sends nothing secret before that check.

### QR code and typed pairing

The QR text is `QrPayload` as compact JSON (`v` 1, `t` "onic-pair", `a` addresses LAN first then Tailscale, `p` TLS
port, `c` the code without dash, `i` instance id, `f` fingerprint, `n` name, `x` expiry), at most 400 bytes.
`ConnectState.qrText` / `state.json qrText` carry the exact text; the mod only encodes it. A reader refuses `v` above
what it knows ("Update the app"). Typing the address instead: host:port + code; the app connects over TLS, reads the
certificate, shows `fingerprintTag` and the name, and the user compares them with the Connect a phone window before
`claim` is sent.

### Pairing: `POST /connect/claim`

Code: 8 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, shown `ABCD-EFGH`, valid 300 s, single use, made when
Connect a phone goes ON and by `POST /connect/code` / the mod's `new_code`. A wrong code counts a failure for the
current code and the source address; after 5 failures from one source (`failuresLeft` 0) that source is blocked (429) until the code ends, and the code stays the same for everybody else. A good claim
returns `ClaimReply`: `deviceToken` (32 random bytes, base64url, shown once; the service stores only its SHA-256 with
the `deviceId`, label, platform, `pairedAt`, `lastSeen`, transport) and burns the code. Errors: 403 `bad_code`
(wrong, expired or used; same body for all three), 429 `rate_limited` (see below), 400 `bad_request`. `claim`
works only on a network listener that is currently open. The client sends its token only inside a TLS session whose
certificate fingerprint equals the pinned one, never to a merely discovered address. Tokens are per service.

### Device token, 401 and rate limits

- Header on every request to the network listener: `X-Oni-Device: <deviceToken>`. Compared via SHA-256 in
  constant time against every stored hash.
- Network listener, token missing, malformed, unknown, removed or from before a Reset identity: HTTP **401**,
  code `unauthorized` (never a hint which). Only `GET /identity` and `POST /connect/claim` are open without it.
  Loopback keeps v1 behavior (403 `bad_token`); the headers `X-Oni-Token`, `X-Barry-Token` and `?token=` are
  ignored on the network listener (no token is ever put in a URL).
- Removing a device (`DELETE /connect/devices/<id>` or the mod's `remove_device`) closes its open long-polls and
  makes its next request 401.
- Per-device limits (token bucket, per `deviceId`): 20 requests/s sustained, burst 40; POST and DELETE 5/s, burst 10;
  at most 2 concurrent `GET /events` long-polls. Over the limit: 429 `rate_limited`, header `Retry-After: <s>`.
- Pairing limits (not tied to a device): at most 5 wrong codes per code, at most 10 failed claims per minute per
  source address and 30 per minute overall; over: 429 `rate_limited`. Unauthorized (401) requests are limited to
  30/min per source address.
- A `connect` event (`Events.changed`) fires when the device list, switch, code or addresses change (loopback
  clients such as Barry refresh the Settings window; a paired device receives it too but gets no data from it).
- `Status.connect` ({enabled, listening, devices}) is present on the loopback listener only.

### Files between the service and the mod (the mod stays files-only)

`<ONI user folder>/companion/pairing/state.json` (`pairing.schema.json#/State`), written by the SERVICE with the
write-tmp-then-rename rule on every change and at start, removed on a normal exit. The mod watches it and draws the
Connect a phone window (switch, QR from `qrText`, `code.display` large, `identity.name` large, addresses,
devices + Remove, `plainHttpNote`). It never holds a device token or a private key.
`<ONI user folder>/companion/pairing/requests/req-<seq>.json` (`#/Request`), written by the MOD with
write-tmp-then-rename (temp name `req-<seq>.json.tmp`, never matching `req-*.json`): `set_enabled`, `new_code`,
`remove_device`, `reset_identity` (needs `confirm: true`), `set_plain_http`. The service handles it, writes
`state.json lastRequest {seq,state,message?}` and deletes the file. A request older than 10 s or with `seq` not above
the newest handled one is dropped (`lastRequest` failed "Request too old"). The mod never starts the service and
opens no network connection; a switch request written while no service runs is lost after 10 s and the window then
says "The service starts when the game is running" (it starts on the mod's first write, below).

### Android local mode (4.2)

The APK embeds the same core logic and serves its own screens locally: no network listener, no mDNS, no pairing.
The shared folder is `<shared storage>/ONICompanion/` (Android `/storage/emulated/0/ONICompanion/`), created by the
APK with `marker.json` (`pairing.schema.json#/LocalMarker`) when the user sets up an emulator app. The emulator maps
shared storage as a Windows drive (D: to Z:). The mod looks for `<drive>:\ONICompanion\marker.json` (a fixed
name; the mod takes no path from any command or file) and, if found, uses `<drive>:\ONICompanion\companion\` as its
companion folder: the whole tree from `mod-*` schemas (`live.json`, `export-*`, `art/`, `fonts/`, `theme/`,
`commands/`, `acks/`, `sync/`) is the same, so the APK reads and writes it with the same rules as the core on a normal device
(commands: write temp then rename into `commands/`; acks and live freshness as in v1.1). The pairing folder is not
used in local mode. The setup screen shows the exact drive-mapping steps until `companion/live.json` in that folder is
fresh. The APK reads files through a granted folder (Storage Access Framework) or all-files access, whichever is
the least that works (VERIFY per emulator; untested). The user's game files for art and fonts: read from the
container when readable, else the mod draws art into the shared folder.

### Service lifetime (5.1)

The standalone service (and Barry's core for its network listener and mDNS) lives only while the game runs: it
starts when the mod makes its first write after a game launch (a systemd user path unit on the companion folder), finds the
game process and waits on it with `os.pidfd_open` + `select` (no polling), closes the listeners, stops the mDNS announcement,
removes `state.json` and exits when the game ends or crashes, and exits at once when it finds no game process at
start. The loopback listener ends with it (standalone) or stays up (Barry's core). Connect a phone is OFF on every
start of the service unless the user turned it on and the stored switch is ON (the stored switch survives; the network
listener is opened only after the game was found).

## Planned, not in v1 (names reserved; reply 501 `not_in_v1`)

SUPERSEDED by v1.4 (the real endpoints are `/connect/*`, above). These names stay reserved and answer 501 `not_in_v1`:

| Method + path | Meaning |
|---|---|
| `POST /pair/start` | device shows a one-time pairing code (Barry/Decky pairing screen) |
| `POST /pair/complete` | client sends the code and a label, gets a long-lived token (stored in the token set with its label) |
| `GET /pair/clients` | list paired clients |
| `DELETE /pair/clients/<label>` | revoke a client |

Also planned: standalone mode with LAN bind (`--mode standalone --listen host:port`),
and mDNS discovery `_onicompanion._tcp`. None of this is implemented or exposed in v1.
