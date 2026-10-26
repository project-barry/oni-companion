# Credits

## Reference code

- **python-oni-save-parser** by mithro, Apache License 2.0
  (https://github.com/mithro/python-oni-save-parser). Used as a reference
  for the save file format. Any code ported from it keeps its license notice.
- **oni-save-parser** by RoboPhred, MIT License
  (https://github.com/RoboPhred/oni-save-parser). Used as a reference for
  the save format (save version 7.17). Any code ported from it keeps its
  license notice.

No code has been ported yet. When code is ported, this file and the source
file headers name the source and its license.

## Links only

- **Oxygen Not Included Wiki** (https://oxygennotincluded.wiki.gg). Content
  is CC BY-NC-SA. This project does not copy or scrape wiki text or images.
  The app shows links that open the wiki page in a browser.

## Ideas only

- **oni-db.com** (https://oni-db.com). No data or code is copied. The
  "produced by / used by" links are an idea taken from that site's layout.

## Save format

- The save file format was cross-checked against
  [mithro/python-oni-save-parser](https://github.com/mithro/python-oni-save-parser)
  (Apache-2.0) and [RoboPhred/oni-save-parser](https://github.com/RoboPhred/oni-save-parser)
  (MIT). No code was ported; the reader in `core/oni_companion/save/` is
  written from scratch.

## Game

- Oxygen Not Included is made by Klei Entertainment. This project is not
  affiliated with or endorsed by Klei Entertainment. "Oxygen Not Included"
  and related names are trademarks of Klei Entertainment.
- No Klei data, text, art or code is in this repo. Game data is read from
  the user's own copy of the game at run time.

## Game art, style and fonts (v1.1)

- Game art (building, element, critter, plant, food, item icons and
  duplicant portraits), the game's panel and button images, and its colors
  are Klei's. This project does not include, copy or convert them.
- The ONI Companion Link mod renders them at run time from the user's own
  copy of the game. The PNG files and the theme are written to the user's
  game folder on the user's device. They are not part of the repo, the app
  or any release.
- Test fixtures use placeholder shapes made for this project, not game art.

## Game fonts (v1.2)

- The app's text uses the game's own fonts, read at run time from the
  user's copy of the game by the core. Nothing is copied into the repo, the
  app or a release. The core caches them on the user's device.
- **Noto Sans** (body text), from the game's `StreamingAssets/fonts/`.
  Noto Sans is licensed under the SIL Open Font License 1.1.
- **Economica** (Regular, Bold, Italic, Bold Italic) and **League Spartan**
  (Bold), read from the game's asset file. Both are licensed under the SIL
  Open Font License 1.1.
- **Graystroke** (header text) is Klei's. The mod exports its glyph atlas
  from the user's game. The repo does not include or convert it.
- When a font is missing, the app uses a fallback. No font file is shipped
  with the app.

## Game text and icons (v1.3)

- The overlay and tool buttons, their icons, the build-menu material
  choices, the game's priority buttons, the names of the DLC and the
  Codex's title are Klei's. The app shows them from the user's own copy of
  the game. The mod reads the names and icons at run time, and the icons go
  through the art sync like the rest of the game art. Nothing is copied into
  the repo, the app or a release.
- The bundled ONI Companion Link mod is this project's own code. It contains
  no Klei art, text or data; it is copied into the game's mods folder only
  when the user asks for it.

## Pairing, identity and discovery (v1.4)

- **QR codes.** The pairing QR code uses the public QR Code model (ISO/IEC
  18004). The mod draws it with a small encoder written for this project. No
  QR library is copied into the mod.
- **System tools the core calls** (not bundled, not copied; the user's system
  provides them): the `openssl` command, used to make the service's
  self-signed certificate (OpenSSL 3.x, Apache License 2.0), and the
  `avahi-publish-service` command from avahi (LGPL-2.1), used to announce the
  service when avahi runs. The core falls back to its own responder otherwise.
- The mDNS / DNS-SD record format is the public standard (RFC 6762 and RFC
  6763). No code is copied.

## Android app (v1.4)

- The Android app is written for this project. Each third-party library it uses
  is listed here with its version and license before the app is released.
  No third-party library is listed yet, because the v1.4 docs were written
  before any library was added to `clients/android/`. Update this section with
  each one.
- The Android SDK and the build tools are Google's, under their own license
  terms. They are used on the build machine only and are not in the repo or the
  APK.

## App icon

- `clients/barry/icon.svg` is original art made for this project. It does
  not use the game's logo.
