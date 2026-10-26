# ONI Companion Link (game mod)

A Klei mod for Oxygen Not Included that writes files only (no sockets, nothing into saves):

- `<ONI user folder>/companion/export/gamedata-<build>-<dlcset>.json`: game numbers (`contracts/mod-export.schema.json`)
- `<ONI user folder>/companion/live/live.json`: live colony state (`contracts/mod-live.schema.json`)

`<ONI user folder>` is `Util.RootFolder()`, the same folder as `mods/`
(`~/.config/unity3d/Klei/Oxygen Not Included/` on Linux).

## Verified against the real game DLLs (build 744825, Steam buildid 24423041)

- Compiled directly against the game's own `Managed/` DLLs (Unity Mono, mscorlib 4.0.0.0): every type and
  member used exists. Target `net471`, C# 9.
- `mod_info.yaml`: `APIVersion: 2` (`Mod.MOD_API_VERSION`), `minimumSupportedBuild` is compared with
  `KleiVersion.ChangeList` (744825). `supportedContent` is deprecated and logs a warning, so it is left out
  (no DLC restriction). Local mods load from `mods/Local/<folder>` (`Global.cs`: `new Local("Local", ...)`).
- `build` in the files is `KleiVersion.ChangeList` (744825), not the Steam buildid.
- Output folder API: `Util.RootFolder()` (what `KMod.Manager.GetDirectory()` uses for `mods/`).

## v1.1 additions (lane M4; compiled, not run in the game)

- `live.json` schema 2: per duplicant `appearanceHash` (FNV-1a over all accessories, hat and clothing outfit), `statusItems`
  (the game's own list from `KSelectable.GetStatusItemGroup()`, severity = `StatusItem.notificationType`), `diseases`,
  `stamina`, `bodyTempC`, `attributes` (`Display.Skill`, ordered by name, as `CharacterContainer` does). `resources` is a list
  built like `AllResourcesScreen`: categories from `GameTags.MaterialCategories`/`CalorieCategories`/`UnitCategories` sorted by name,
  discovered resources only, "available" amounts, food in kcal.
- `constants` in the export: stress, calories, breath and body-temperature thresholds the game itself uses (bladder, stamina and
  health states are literals inside the game's lambdas and have no key).
- `Theme.cs` writes `companion/theme/<build>/theme.json` + `panel/header/button/buttonHover/buttonPressed/tab/tabActive.png` once
  per build and mod version, one small step per frame; sources are listed at the top of the file. Text on `panel` is `text` (black);
  `background` is the dark window color, so page-level text there should use `textTitle`.

## Not verified (needs the game running)

Everything at runtime: that the hooks fire, the numbers written, timing, load with/without saves.

## Design

- Hooks (Harmony postfixes, each in try/catch): `MainMenu.OnSpawn` and `Game.OnSpawn` run the export (skipped when
  a file for the same build, DLC set and mod version exists); `Game.Update` drives live writes; `Game.OnCleanUp`
  and `Application.quitting` write `"state":"menu"`; `SaveLoader.Save` and `NotificationManager` mark forced writes.
- Live writes: the main thread only gathers a plain snapshot (timed, `writeMs`); a worker thread serializes it, compares it
  with the last write and writes it (tmp file + rename). Built against the Windows build's Managed/ DLLs (`build.sh`). At most once per real second; forced at once (150 ms burst guard) on pause,
  cycle change, new alert or save. Nothing is written while paused and unchanged.
- Errors: a bad export entry or optional part is skipped and counted (log line); a failed export or 3 failed live
  writes in a row switch the mod off for the session. Log prefix `[OniCompanionLink]` in `Player.log`.
- DLC: one export per (build, active DLC set). Each entry carries `dlc` (the game's own required-DLC ids).
  Text is in the game's language, rich-text markup removed.

## Build

`mod/build.sh pull-libs` (once; pipes the DLLs Nova to Mini), `mod/build.sh build` (syncs `mod/` to the Mini,
`dotnet build`, brings back `mod/build/OniCompanionLink/`, gitignored). Game DLLs are never stored on the Mac
and never committed.

## Check produced files

`python3 mod/check_output.py <file>...` validates `gamedata-*.json` and `live.json` against the frozen schemas
(plus the requested top-level `constants`, as an in-memory overlay). `mod/tests/JsonSample` is an offline
check of the JSON writer.

## Art (v1.1, `src/Art.cs`)

Renders the game's own art on the user's device into `<companion>/art/<build>/<kind>/<id>.png` plus
`art/manifest.json` (`contracts/mod-art-manifest.schema.json`). Nothing of it is in the repo or the app.

- Catalog (building, element, critter, plant, seed, egg, food, medicine, item): `BuildingDef.GetUISprite` /
  `Def.GetUISprite`, blitted through a RenderTexture, 128 px long side. ON DEMAND ONLY (0.2.2, no catalog run): drawn when the core sends an
  `art_request {kind, id}` command, kept per game build. Each image carries a `srcKey` (see `Art.SrcKeyOf`; `Art.SrcKey(kind, id)` gives it without drawing).
- Duplicant portraits: the game's `FullBodyUIMinionWidget`, drawn by a private camera on black and on white
  (exact alpha), cropped, at most 256 px, `dupe/<id>-<appearanceHash>.png`; drawn for the loaded colony right after the world
  loads, and again only when the hash changes (at most one per second). `Art.AppearanceHash(MinionIdentity)` is the hash; `live.json` should use the same call.
- Main thread: requests are drawn from a queue with a 2 ms time box per frame; the theme writer and the portrait stage set-up
  are split into one small step per frame. A background thread encodes PNGs (own encoder), hashes and writes files (tmp + rename);
  the manifest is written after the PNGs, atomically, at most once a second (at once for a portrait), and each `art_request` is
  acked after the manifest lists its image. Log lines `art: ...` and `theme: ...` give the totals and the worst main-thread step.
- Offline check of the PNG encoder: `mod/tests/PngTest/run.sh <workdir>` (needs dotnet; compares every pixel).
- Not verified (needs the running game): all rendering, timing, the portrait stage.

## Commands (v1.1, `src/Commands.cs`)

- Inbox `companion/commands/cmd-N.json`, acks `companion/acks/ack-N.json` (`contracts/mod-command.schema.json`, `mod-ack.schema.json`).
- A `FileSystemWatcher` (Created, Changed, Renamed) only queues file names; `Game.Update` runs them on the main thread.
- Allow list: `focus` only (anything else: logged, ack `failed`). Older than 10 s (or dated 10 s ahead): refused. One command per 250 ms
  (the rest wait in the queue). Names must match `cmd-<digits>.json`, files over 4 KB are refused, a command never carries a path or code.
- `focus {kind:"dupe", id}`: id = `KPrefabID.InstanceID` as a decimal string (the same value `Live.cs` writes). Uses the game's own
  `GameUtil.FocusCameraOnWorld(world, pos, 10, callback, false)`: same world = one `CameraController.SetTargetPos` pan/zoom (which clears
  any follow target); other world = the game's star-wipe world switch, then the same move. `select` (default true) runs
  `SelectTool.Select` in the callback, so it sees the right world. `SetFollowTarget` is never called.
- Self-test: at start the mod writes `commands/.watcher-probe`; the log says `watcher self-test OK (<impl>, event after N ms)` or, after 5 s,
  a warning that the watcher gave no event. That line in `Player.log` is the proof that commands can arrive on that system.
- Not verified (needs the game): everything at runtime, including FileSystemWatcher under Proton and the star-wipe path.

## 0.2.4: smaller live steps on the first write

- The first live write had steps of 5 to 11 ms (duplicant status and details, resource catalog, edible chunk, category). They are split:
  status items 3 per step, details as name / skills / traits / appearance (4 slots per step) / diseases / attributes (6 per step),
  catalog 4 categories per step, edible calories 16 per step, resources 12 per step. The warn limit is now 2 ms.

## 0.2.3: live gather cost, theme cost

- The live gather is time-sliced: one write is a queue of small steps (one duplicant part, one resource category, one chunk of creatures);
  each frame runs steps until about 1.2 ms is used, no single step is allowed to pass 4 ms (logged by name when it does). Component
  lookups, skill/attribute lists, status item names and the resource category list are cached and refreshed on a slower clock.
  The first frames compile the gather code one method per frame. Serialization stays on the worker thread.
  Player.log: `live timing (main thread, per frame, gather only)` shows frames over 2 ms / 4 ms and each section's cost.
- The theme is rebuilt only when the game build or `RenderRev` changes (`renderRev` in theme.json). The style assets are read from the
  UI objects that hold them (one root per frame); the scan of all loaded objects runs only if one is missing, and is logged.
- New theme tokens: sectionHeader(+Text), tabBg/tabActiveBg, tabText/tabTextActive, alertBg/alertText/alertBadBg/alertBadText and a
  `sectionHeader` slice. The core checks text/background contrast and moves a failing text color to a readable one.

## Art & font sync (v1.2, lane S1)

`sync_assets {scope: full|missing}` (src/Sync.cs): draws the whole catalog from the user's own game with the game paused
(previous speed restored at the end, also after a failure), then refreshes the theme and exports the Graystroke atlas to
`companion/fonts/<build>/graystroke.png + graystroke.json`. Progress: `companion/sync/status.json` about every 250 ms.
Offline checks: `mod/tests/SyncStatusSample` (build on the Mini) + `python3 mod/check_output.py <files>` validate the
status and atlas JSON against the contracts. NOT yet run in the game. In-game check, with the user's OK to install:
start the app, tap "Start sync" (or Settings, "Re-sync art & fonts"); expect the game to pause, the count to climb, the
game to go on at its old speed; Player.log shows "sync: done in ... s" with the worst main-thread step; the
`fonts/<build>/graystroke.json` glyph count and the alpha/red range line in Player.log say whether the atlas export is sane.

## 0.3.0: v1.2 integration

- Merges alerts (`alert_activate`, `alert_dismiss`), `set_speed` + speed/alert icons in the theme, live pre-warm, and `sync_assets` (full-speed art + Graystroke atlas sync).
- Command allow list: `focus`, `art_request`, `alert_activate`, `alert_dismiss`, `set_speed`, `sync_assets`.
- Built against the Windows game DLLs; build not yet run in the game.

## v1.3 build menu data (lane M9; compiled, not run in the game)

`src/Build.cs` and `src/LiveBuild.cs`; the rules are read from the decompiled `PlanScreen`, `PlanBuildingToggle`, `MaterialSelector`
and `MaterialSelectionPanel` (header comment of `Build.cs`).

- Export: `buildMenu` (PLANORDER groups and subcategories, build order), per building `dlcActive`, `unlocked` (written for
  research-free buildings always, for the others only when a colony is loaded) and `lockReason` (tech id, name, cost), per
  material slot `label` and `candidates` (`MaterialSelector.GetValidMaterials`, sorted like the picker).
- Live: top-level `unlockedBuildings`; `worlds[].stock` (id -> kg, `GetAmount(tag, includeRelatedWorlds: true)`, discovered
  candidates only, so a missing id means "the game does not offer it"). `GameHashes.ResearchComplete` (also fired for POI
  unlocks) forces a live write.
- Command `build_select`: the game's own `PlanScreen.CopyBuildingOrder`, then `MaterialSelector.OnSelectMaterial` per slot.
  Acks: `Not researched yet: <tech>`, `Not available in this game`, `Not enough <material>` (the menu is still opened and the
  game keeps its choice for that slot), the game's own tooltip when the building cannot be placed now.

## 0.4.0: v1.3 integration (lane MI3; compiled against the Windows DLLs, NOT run in the game)

- Merges M8 (overlay and tool lists, `activeOverlay` / `activeTool` / `priority` in live, `overlay_set`, `tool_select`),
  M9 (build menu data, unlock state, material slots, stock, `build_select`), M10 (logic port texts, `dlcNames`) and the
  T1 export numbers (`constants.toolNumbers`).
- Command allow list: `focus`, `art_request`, `alert_activate`, `alert_dismiss`, `set_speed`, `sync_assets`,
  `overlay_set`, `tool_select`, `build_select`.
- Export and live now carry `contract: 3` and `requiresCore: {min: "1.3.0"}` (`Env.WriteCompat`); the menu-state live file too.
- Export sections `overlays` and `tools` are written (`Actions.ExportOverlays` / `ExportTools`).
- The first export of a game session with a colony always runs again (`world load`, and `pads ready` if the overlay and tool
  bars did not exist yet at `Game.OnSpawn`): the bars and the per-colony unlock state are missing from a main-menu export.
- `mod/check_output.py` no longer overlays `constants` (it is in the frozen schema).

### Player.log lines (prefix `[OniCompanionLink] `)

- `loading v0.4.0, output ...` at start.
- `export section overlays: N ms`, `export section tools: N ms`, `export section buildMenu: ...`, `export written [world load]` (and
  `[pads ready]` if the bars came later). Any `export section ... failed, writing empty` is a bug.
- `actions: N overlays, M tools` (once the bars exist).
- `commands: watching ...` and `commands: watcher self-test OK`.
- Bad signs: `actions: the game's overlay/tool members were not found`, `build info '...' failed`,
  `build_select: opening ... failed`, `commands: dropped command ... (not on the allow list)`, `ERROR`.

## v1.4 additions (lane M11, mod 0.5.0; compiled for both game builds, NOT run in the game)

- **Connect a phone window** (`src/ConnectWindow.cs`). A button "Connect a phone" is added to the pause menu: `PauseScreen` is a
  `KModalButtonMenu` whose `ButtonInfo` list `ConfigureButtonInfos()` (private) rebuilds on every show; a Harmony postfix inserts one entry
  after Options, drawn by the game's own button prefab. Pause is the entry point because the menu is modal, pauses the game, and the service
  starts with the mod's first write (the main menu would also do, but its buttons are plain `KButton`s made by `MainMenu.MakeButton`, not a list).
  The window clones the pause screen's title `LocText` and button prefab and reads `colorstyle_darkBG` / `colorstyle_title` from the game's own
  `KImage`s, so fonts, buttons and colors are the game's. Contents: on/off switch, QR code, the code in large print with a countdown, "New code",
  the adjective-animal name with the fingerprint tag, addresses and port, paired phones with Remove, the iPhone plain-http switch with its warning,
  Reset identity (the game's confirm dialog). Escape or Resume closes it.
- **Files only.** Reads `companion/pairing/state.json` (FileSystemWatcher sets a flag, no polling; `ConnectModel.cs`), writes
  `companion/pairing/requests/req-<seq>.json` atomically (temp name `req-<seq>.json.tmp`, then rename). seq = max(lastRequest.seq, highest req file) + 1.
  No network, no process started. A request with no answer after 12 s shows "The service starts when the game is running."
- **Budget.** Built in timed steps of at most ~1.5 ms a frame, then only changed values are written, once per state change; the countdown changes one
  label per second. A frame over 2 ms is logged (`connect window: a frame took ...`). Not measured in the game yet.
- **Our own QR encoder** (`src/Qr.cs`): byte mode, level M, versions 1 to 15 (15 holds 412 bytes; the contract's text limit is 400, and the
  fixture text needs version 11), standard mask penalty rules. `mod/tests/QrTest/run.sh` (Mac Mini): module-for-module identical to the segno
  reference encoder for all 8 masks at full capacity of every version, and decoded by OpenCV.
- **Android local mode** (`src/LocalMode.cs`, plan 4.2). Only when the Windows build runs under Wine (`ntdll.dll` exports `wine_get_version`):
  the first drive D: to Z: with `\ONICompanion\marker.json` (schema 1, app "oni-companion") becomes the companion folder
  `<drive>:\ONICompanion\companion`. Found once at load; start the game again after setting up the app. The pairing folder always stays in the
  user folder (no service reads it in local mode). Facts from the emulators' public source: Winlator and GameNative `Container.DEFAULT_DRIVES` =
  `D:` is the Android Download folder, `E:` the app's private storage; extra drives (up to 8) are added by the user. So the app can create
  `Download/ONICompanion` (found as `D:\ONICompanion` with the default setup) or the user maps a drive to `/storage/emulated/0`.
  GameHub is closed source: its mapping is not verified.
- **Build both:** `mod/build.sh build-both M11` (Windows DLLs from `~/oni-mod-build/lib-win` to `~/oni-mod-build/M11/out-win`, Linux DLLs from
  `~/oni-mod-build/lib` to `.../out-linux`). Offline checks: `tests/QrTest/run.sh`, `tests/ConnectTest/run.sh` (state parsing, request files
  validated against `pairing.schema.json`, drive probing).
