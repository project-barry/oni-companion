# ONI Companion: Android client (v1.4, lane A1 foundation)

Native Kotlin + Jetpack Compose, package `io.github.projectbarry.onicompanion`, minSdk 26, open-source
dependencies only (OkHttp, kotlinx.serialization, ZXing; no Google Play Services).

What is here (A1):
- `net/`: `ApiClient` (all GET endpoints, POST, DELETE, `/events` long-poll), `Tls` (`PinnedTrustManager`
  accepts exactly one SHA-256 certificate fingerprint; the token header is only added to requests of a
  pinned client, so it cannot reach another server), `Prober` (reads a certificate fingerprint and the public
  `/identity`, sends no token or code).
- `pair/`: `QrParser` (QR payload, refuses `v` > 1), `Pairer` (claims the code inside the pinned session).
- `store/`: pairings encrypted with an AES-GCM key in the Android Keystore.
- `discovery/`: NsdManager browse of `_onicompanion._tcp`, `Classifier` (Paired / New / Can't verify / Checking).
- `screen/`: `ScreenParser` + `ui/ServiceScreen.kt` render a Screen's text blocks; A2 builds on `BlockView`.

Build and test (on the Mac Mini; needs JDK 17 and `ANDROID_HOME`):

    ./gradlew testDebugUnitTest assembleDebug

Debug builds only: `adb shell am start -n io.github.projectbarry.onicompanion/.MainActivity --es dev_manual HOST:PORT:CODE`
pre-fills typed pairing; `--es dev_loopback PORT:TOKEN` opens a plain-HTTP loopback service (use `adb reverse`).
`devtools/tls-front.py` is a dev stand-in for the v1.4 network listener in front of `devtools/mock-server.py`.

Not in A1: the other tabs (A2), local mode and the bottom screen (4.2), live QR camera test, mDNS on a real LAN.

A2 (screens): every block type, the six tabs from `/tabs` with a back stack per tab, speed bar, game-state header,
sync screen, Settings, game theme (colors, 9-slice skins, icons), game fonts and cached art. Code: `ui/Blocks.kt`,
`ui/Pages.kt`, `ui/Shell.kt`, `ui/Oni.kt`, `session/OniSession.kt`, `session/PageController.kt`.
Dual-screen, local mode and the emulator-app shared folder are A3's.

## Local mode (A3, plan 4.2)

The core runs inside the app (Chaquopy, Python 3.12, stdlib only; the Gradle build packages `core/` plus
`app/src/main/python/oni_local.py`). `local/` has the folder mirror (`SafTree`, `Mirror`), `LocalSession` and the
display helper. Build with `ONI_BUILD_PYTHON=/path/to/python3.13 ./gradlew testDebugUnitTest assembleDebug`.
Research and test notes: `docs/android-dual-screen.md`. Debug-only adb hooks: `--es dev_local_call 'GET /status'`
(answer in logcat tag OniLocal), `--es dev_bottom 1|0`. Test harness: `devtools/fake-mod-adb.py SERIAL`.
