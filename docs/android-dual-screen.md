# Android dual-screen local mode (v1.4, plan 4.2)

Status: research done 2026-10-25 (web only, no Thor on Android, no emulator app in reach). Everything below marked
"UNVERIFIED" was not confirmed on a device. Sources are listed with what each one actually said; a claim without a
source here was not found.

## 1. Which Windows-game emulator apps run ONI

No source found says ONI runs, with or without mods, in Winlator, GameHub or GameNative.

What was read:
- GameNative 1.1.1 changelog (androidpctv.com/?p=57536): "Fix Oxygen Not Included Workshop mods by @Nightwalker743 in
  #1682". So GameNative has had a fix aimed at ONI Workshop mods. It does not say ONI runs well, or that Local mods
  load.
- A web search on GameHub 6.2.0 and mod support (androidauthority.com/gamehub-update-mod-support-3702532 appeared in the
  results; the page itself was NOT opened) suggests GameHub added mod support. Nothing ONI specific was read.
- Winlator: no ONI report found.

Consequence: the first test of ONI in each emulator app is a real-device job (UNTESTED). The mod's only requirement
from the emulator is that it can load a Local mod from `Documents/Klei/OxygenNotIncluded/mods/Local` inside the Wine
container (plan 4.2) and that Wine can see an Android shared-storage folder as a drive.

## 2. How each emulator maps Android shared storage to a Wine drive

| App | What was found | Source read |
|---|---|---|
| Winlator | Community guides say the container's `D:` is the phone's Downloads folder, and the container settings have a "Drives" section that can point a drive at another folder. Winlator 8 release notes list "Improved Drives on Container". One forum user says files moved to `C:` end up in an Android/data location other apps cannot read. These are third-party guides, not the project's docs (the project page on GitHub says nothing about drives). | Web search result summaries (techspot, allthings.how, korben.info, feuniverse.us, r/peggle thread); github.com/brunodev85/winlator README (no drive info) |
| GameNative | Each game runs in its own Wine container; the container config (`.container` JSON in the container root) has a "drives" field. A GitHub discussion (utkarshdalal/GameNative #237) says the data folder has been unreachable since Android 13. How shared storage is mapped by default was NOT found. | Web search result summary; deepwiki page returned HTTP 429 and was not read |
| GameHub | Nothing found about drive mapping. | none |

Design consequence (matches the contract in `contracts/api.md`, "Android local mode"): the mod probes the drive
letters D: to Z: for `\ONICompanion\marker.json`. The user, once per emulator, points a drive at the shared-storage
folder that holds `ONICompanion/`. The most likely working case (UNVERIFIED) is Winlator's Drives setting. The setup
screen therefore shows generic, honest steps (see section 4) and does not claim exact menu names for apps whose
menus were not read.

Wine itself does not map Android shared storage by default: WineHQ bug 46647 ("Wine doesn't configure/map drive
letters for internal and external media (/storage/emulated/0/) on Android") was closed ABANDONED, so every app has to
do its own mapping (source: web search result for that bug, page not opened).

## 3. The AYN Thor's bottom display on Android

What was read:
- Hardware (liliputing, droix review, as summarized by search): top 6 inch 120 Hz AMOLED, bottom 3.92 inch AMOLED
  1080x1240 at 60 Hz. (Matches our own firmware dig of the Thor.)
- AOSP "Activity launch policy" (source.android.com/docs/core/display/multi_display/activity-launch, summarized by
  search): `ActivityOptions.setLaunchDisplayId(int)` targets a display; by default an activity launches on the caller's
  display; a launch from a source not tied to a display (shell, Application context) goes to the display the user last
  interacted with; an existing activity with no extra flags surfaces on the display where it was last used.
- AOSP "Displays" (source.android.com/docs/core/display/multi_display/displays, read): since Android 10 displays have
  stable persistent ids (before that 0 = internal, 1 = external); a display-specific input event goes to the focused
  window of that display, other input goes to the focused display (the one the user last touched); Android 10 can allow
  one focused window per display but the page strongly recommends against it on regular devices.
- FreeRDP's `ExternalDisplayManager` (pub.freerdp.com, summarized by search) launches onto a second display with
  `FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_MULTIPLE_TASK` plus `setLaunchDisplayId`.
- Android's `ActivityOptions` reference page was fetched twice but the method text was in a part the fetch tool
  could not return. The behavior above is from the AOSP summary, not from that page.

NOT found for the Thor: the display ids, whether AYN's launcher claims the bottom screen, and how the emulator app
handles the second display. All UNVERIFIED until a Thor on Android is available.

Design decisions from this:
1. The app does not hard-code an id. It asks `DisplayManager.getDisplays()`, ignores the display of its own activity,
   picks the first `STATE_ON` display that is not the default display and is not presentation/private
   (`Display.FLAG_PRIVATE` unset), and launches `MainActivity` there with
   `ActivityOptions.makeBasic().setLaunchDisplayId(id)` and `NEW_TASK | MULTIPLE_TASK`.
2. The activity runs on the bottom screen without taking the game's input: taps go to the focused window of the
   display touched (AOSP "Displays" page), so a tap on the bottom screen focuses our window on that display, which is
   the intended design on Android 10+ without per-display focus. Whether the emulator app on the top screen keeps its
   gamepad focus (and the game does not pause on focus change) is exactly acceptance item 3 and is UNTESTED. The
   mitigation if it does: the activity sets `FLAG_NOT_FOCUSABLE`-free normal windows (nothing special), and the app
   never calls `requestFocus` on launch; no extra mitigation is built without a device to test.
3. `Show in game` and Pause go through command files, so they act on the game regardless of display.

## 4. What was built (lane A3)

### 4.1 Embedded Python (Chaquopy) instead of a Kotlin port

Decision: embed the core with Chaquopy.
- The core is about 10,800 lines of stdlib-only Python (colony, actions, art, fonts, views for every tab, search, pad,
  sync). A Kotlin port would be a second implementation of every page that has to stay equal to the first; local mode
  must have "the same features as the Barry version", and v1.3 pages change often.
- Chaquopy license: its license page (chaquo.com/chaquopy/license/, read) says "Since version 12.0.1, Chaquopy is now
  free and open-source, and all license restrictions have been removed." The page does not name the license; read the
  LICENSE in the Chaquopy repository before shipping a release APK.
- Costs: the APK grows by the Python runtime (see the build size in the report) and starts a Python interpreter at the
  first local-mode launch. Only arm64-v8a and x86_64 (emulator) are packaged.

### 4.2 Files, not a socket

`clients/android/app/src/main/python/oni_local.py` is the entry point. It builds the same `Service` the HTTP server
uses, minus the HTTP server and minus the file watcher, and exposes `call(method, path, body)`. Kotlin calls it
in-process. Nothing opens a port, so there is no pairing or token in local mode.

### 4.3 The shared folder (Storage Access Framework)

Least permission that works: the Storage Access Framework tree grant on the one folder `ONICompanion`, no all-files
access. Android docs (developer.android.com/training/data-storage/shared/documents-files, read): the app gets access
to any file in the picked directory and its sub-directories and nothing else; the grant can be made persistent with
`takePersistableUriPermission`; on Android 11+ `ACTION_OPEN_DOCUMENT_TREE` cannot be used on the storage root, the
SD-card root, `Download` or `Android/data`. A subfolder created at the root (`ONICompanion`) can be picked, so the
setup screen asks the user to create it in the picker (the app cannot create a root folder without a permission).
All-files access is not used (UNVERIFIED that SAF is enough on the Thor's Android; the same tree grant works on the
emulator, see Tested).

Because the Python core needs real paths, Kotlin mirrors the SAF tree into the app's private folder:
- shared to private: on a change notification (no polling) it copies
  changed files (by size and modified time) of `live/`, `acks/`, `sync/`, `export/`, `art/`, `fonts/`, `theme/` and
  tells Python which file changed (`touch`) or was removed. Observed on the emulator (the AOSP source was not read): a
  `ContentObserver` registered on a folder's children URI never fired for files written from outside the app. It
  fires only while a query cursor on that folder is kept open and the observer is registered on that cursor, so
  `SafTree.watch` keeps one open cursor per folder;
- private to shared: an inotify `FileObserver` on the private `commands/` folder (and `sync/` requests) writes each new
  command into the shared `commands/` folder as `*.tmp` and renames it, the rule the mod expects.
- Freshness: `oni_local.stale_in()` gives the seconds until `live.json` stops being fresh; Kotlin sets one timer for
  that moment and then tells clients to look again. No periodic poll.

### 4.4 Which mode opens

- `marker.json` in the granted folder plus fresh files (`companion/live/live.json` less than the freshness window old
  by `writtenAt`) selects local mode automatically.
- A saved grant with stale files opens local mode and shows "Last known state" (plan 4.2 lifetime).
- No grant: the Devices screen (A1) is the home, with a "This device (local mode)" entry that starts the setup
  screen. A phone never needs it.

### 4.5 Bottom screen

If `DisplayManager` reports a second display when the app starts from the launcher, `MainActivity` re-launches itself
on that display once (marker extra prevents loops) and finishes the first instance. A setting "Open on the bottom
screen" (on by default when a second display exists) turns it off.

### 4.6 Setup screen per emulator

Choices: Winlator, GameNative, GameHub, Other. Each shows numbered steps: create and pick `ONICompanion`, point a drive
letter (D: to Z:) at the shared-storage folder that contains `ONICompanion`, start ONI with the mod, wait until the
screen says the game is live. The wording avoids menu names that were not read in a source (see section 2).

## 5. Tested and untested

Tested on the Mac Mini, arm64 Android 14 emulator (AVD a3-test), debug APK 1.4.0-a3 (47 MB, two ABIs, unstripped),
with `devtools/fake-mod-adb.py` standing in for the mod (writes the synthetic export and a fresh live.json every 4 s
into `/sdcard/ONICompanion/companion/`, acks commands) and a simulated second display
(`settings put global overlay_display_devices 1080x1240/320`):
- Setup: Set up, Winlator, Choose folder, system picker, ALLOW. The grant is taken as persistable, `marker.json` is
  written by the app, the embedded Python 3.12 core starts and serves the Database page from the mod export alone.
- Mirror: live.json reaches the private copy within about 2 s of each write (cursor-based observers); the status
  reports `liveFresh` true; after the fake mod stops, `liveFresh` turns false after the 15 s window and the controls
  say "Game not running", with the stale timer firing the `status` event.
- Commands: `POST /controls {"state":"pause"}` wrote `cmd-N.json` into the shared `commands/`, the fake mod acked it
  and removed it, `GET /actions/N` returned `done`. No port was opened.
- Auto-select: after a restart with fresh files the service screen opens by itself; with stale files the Devices
  screen shows "Set up. The game is not writing now" with Open.
- Second display: launching from the shell (default display) re-launches the app on the overlay display (ids 2 and 3
  in two runs, nothing hard-coded) and the picker opens there too; with no second display it stays on display 0; with
  the switch off it stays on display 0.
- Focus (partial): with Android Settings on display 0 and the app on the overlay display, a tap on the overlay left
  Settings in state RESUMED (never paused); window focus moves to the tapped display, as the AOSP "Displays" page says.
- Python: `tests/test_a3_local_entry.py` (8 tests) and Kotlin `LocalMirrorTest` (6 tests: mirror down, deletions,
  commands up and consumed, expired command, freshness rule, marker check) pass.

UNTESTED (needs a Thor on Android or a real emulator app):
- ONI with the mod inside Winlator, GameNative or GameHub, and each app's drive mapping (section 2).
- The mod finding `ONICompanion` on a mapped drive (the drive probing lives in the mod lane, not here).
- Whether Wine writes to shared storage and whether the cursor observers see those writes (the emulator test wrote
  through adb).
- The Thor's real display ids, AYN launcher behavior on the bottom screen, whether the emulator app keeps its gamepad
  focus and the game keeps running when the bottom screen is touched (acceptance 3), and Show in game on a real game.
- Art and font sync into the shared folder when the container cannot be read (the code path is the core's own; no
  art was exchanged in this test).
- App going to the background and returning (code written: the session stops on onStop and restarts on onStart).
- Release build, size trimming (a release build with one ABI each should be much smaller), Android 15+ behavior.
