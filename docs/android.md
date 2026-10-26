# Android app (v1.4)

Status: **in development, UNTESTED on a device.** The app is native Kotlin with
Jetpack Compose. It is built on the Mac Mini, not on the Mac. Nothing in this
file has been run on a phone or on a dual-screen device yet. Items marked
UNTESTED were built but not checked.

The app is a **companion device**. It shows screens and sends commands. It
never runs the game, the mod or the service on a phone, except in local mode
on a dual-screen gaming device (see "Local mode" below).

## What the app does

- Finds ONI Companion services on the network, and lists each one with its
  device name and a short fingerprint tag, for example "spiffy-raccoon · 7F3A".
  Found services are marked **Paired** or **New**. Discovery only saves typing.
  Nothing it shows is trusted until the certificate check passes.
- Pairs by QR code (scan the code shown in the game's "Connect a phone"
  window) or by typing the address and the code. Pairing always needs the
  code.
- Pins each service's certificate fingerprint. The app sends its device token
  only inside a TLS session whose certificate matches the pinned fingerprint.
  Tokens are per service: a token for one gaming device does nothing at another.
- Shows the same screens as the Barry app: Colony, Resources, Buildings,
  Actions, Codex, speed controls, alerts, Show in game, and Settings.
- Draws the game's art and style when the service sends them. Without them it
  uses the glyph look.

## Where pairing happens

Pairing is turned on **on the gaming device**, never in the app. Open the
game's pause menu, then "Connect a phone". There you switch the connection on,
see the QR code and the one-time code, and remove paired devices. On the Thor,
Barry's Settings shows the same window.

The app cannot pair with a device that is not switched on, because the code
does not exist until the switch is on.

## Build on the Mac Mini

The Android SDK, sdkmanager and Gradle are on the Mac Mini (ssh `build-mac`).
The Mini has about 129 GB free. This Mac has little free space, so do not
build here or copy the SDK here.

Requirements on the Mini:

- **A Java runtime (JDK 17 or newer).** Not yet installed on the Mini as of
  2026-10-25. Install it first, then check with `java -version`.
- The `android-commandlinetools` cask, `sdkmanager`, and Gradle (installed).
- Accept the SDK licenses once: `yes | sdkmanager --licenses`.
- Install the SDK packages the project needs (platform and build tools
  named in the project's Gradle files).

Each build lane has its own folder on the Mini, so lanes do not overwrite
each other:

```sh
ssh build-mac
mkdir -p ~/oni-android/<lane>
# copy or clone the repo's clients/android/ into that folder, then:
cd ~/oni-android/<lane>
./gradlew assembleDebug     # debug APK
./gradlew assembleRelease   # release APK, when signing is set up
```

The APK is written under `app/build/outputs/apk/`. Copy the APK back to the
Mac only when it is needed, and never copy game files to the Mac.

UNTESTED until the first build on the Mini runs without error.

## Install and first start

1. Install the APK on the phone or the dual-screen device.
2. Allow the app's permissions when it asks (network access; storage only in
   local mode, see below).
3. On the gaming device, open "Connect a phone" and switch it on.
4. In the app, pick the service from the list (Paired or New), or scan the QR
   code.
5. A new pairing shows the fingerprint tag. Compare it with the tag in the
   gaming device's window. A typed address also needs this check.

Turning the switch off on the gaming device closes its network listener at
once. Turning it off also stops the app from reaching the service.

## Pairing and identity

- The service has a random instance id, a device name (adjective-animal, for
  example "sleepy-ant") and a self-signed certificate. The certificate's
  fingerprint is the real identity. The name is only a label.
- If a service you paired with shows up under the same name but a different
  fingerprint, the app says **"Can't verify this device"** and sends nothing.
- A service that moves to a new address is found again by its fingerprint.
  The phone pairs again only after the gaming device runs **Reset identity**.
- Removing a device on the gaming device revokes its token. Its next request
  gets 401, and the app asks to pair again.
- Pairing codes expire after 5 minutes, work once, and are replaced after
  5 wrong tries.

## Addresses: LAN, Tailscale, typed address

- The QR code lists the LAN address first and the Tailscale address next, when
  Tailscale is up. The app tries them in that order.
- Over Tailscale the connection uses HTTPS through `tailscale serve` when the
  gaming device runs it (VERIFY on SteamOS and PB-OS; UNTESTED).
- A typed address is `host:port` plus the code.

## Local mode on a dual-screen Android device

This is the default when the app runs on the same device as the game. For
example, an AYN Thor on stock Android, with the game on the top screen and the
app on the bottom screen. No network, no pairing, no mDNS. The app contains
the same logic as the core and reads and writes the mod's files itself.

Setup, once per emulator app:

1. The game runs inside an emulator app that runs Windows games (Winlator,
   GameHub, GameNative or similar; VERIFY which ones run ONI with local mods).
2. The app shows a setup screen. It creates the shared folder
   `ONICompanion/` in the phone's shared storage, with a `marker.json` file.
3. In the emulator app, map the shared storage as a drive (for example D: to
   `/storage/emulated/0/`). The screen shows the exact steps for each emulator.
   VERIFY per emulator; UNTESTED.
4. Grant the app access to the shared folder once. The app asks for the
   narrowest access that works: a folder picker, or all-files access. VERIFY
   which one works on the device; UNTESTED.
5. Start the game with the mod. The mod finds the marker and writes its files
   into `ONICompanion/companion/`. The setup screen goes away when fresh files
   arrive.

Rules that hold in local mode:

- The mod never takes a path from a command. It only looks for the marker
  folder.
- The app runs no background service when it is closed. It shows the game's
  last state until the mod writes again, and says so.
- On a dual-screen device the app opens on the bottom screen by default.
  Taps on the bottom screen must never pause the game or take its input.
  (VERIFY focus and input rules on the device; UNTESTED.)
- Art and fonts come from the user's own game files in the emulator's
  container when they can be read. If they cannot, the mod draws the art
  into the shared folder. (VERIFY; UNTESTED.)

Built, not tested: the dual-screen part (bottom-screen launch, input rules,
emulator drive mapping and folder access) needs a Thor running Android with
an emulator app, which was not available in this run.

## iPhone and iPad (web app, later)

The iOS web app is not part of this build. Its limits are set now, so the
design does not change later:

- Safari cannot pin a self-signed certificate, so an iPhone cannot check the
  service's identity on the LAN the way the Android app does.
- **Plain HTTP on the LAN** (the "Connect a phone" switch for iPhone, off by
  default): anyone who can watch the Wi-Fi traffic can read the device token.
  The window says this in one line when an iPhone pairs.
- **Tailscale:** real HTTPS through `tailscale serve`. This is the safer choice
  for iOS.
- iOS web apps cannot browse for services over mDNS. On an iPhone, discovery
  helps only after the first QR scan.
- The app is added to the Home Screen from Safari.

## Acceptance (from the v1.4 plan, section 6)

Each item is UNTESTED until run on a device:

1. With "Connect a phone" off, the service answers on the gaming device only.
2. A phone on the same Wi-Fi scans the code, pairs, and shows the live colony.
   Pause works from the phone.
3. The same over Tailscale from outside the home network.
4. An mDNS browser on the Mac sees "ONI Companion on <name>" while the switch
   is on, and not after it is off.
5. Removing the phone on the gaming device stops its next request (401).
6. Wrong codes are rate limited. An expired or used code is refused.
7. Two services on one network appear as two entries, and each pairs.
8. A fake service with a copied name and id shows "Can't verify" and gets no
   token.
9. After Reset identity, the old pairing stops working.
10. Dual-screen local mode (sections above) on a Thor running Android.

## Related

- `docs/architecture.md`: pairing, identity, discovery, service lifetime.
- `contracts/pairing.schema.json`: pairing files, QR payload, mDNS record,
  local-mode marker.
- `contracts/api.md`, v1.4 section: endpoints and the 401 rules.
