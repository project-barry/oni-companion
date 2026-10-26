# ONI Companion: iOS client

Planned, not in v1 (the Barry app is the first front end).

- Same model as Android: a client of the standalone server, paired with a
  code, rendering the same blocks with the same long-poll.
- Distribution: a free Apple ID sideload expires after 7 days. TestFlight and
  the App Store need the paid Apple Developer Program.
- Info.plist: needs `NSLocalNetworkUsageDescription` (the local-network
  prompt) and an ATS exception (`NSAllowsLocalNetworking`) for plain HTTP
  on the local network. Use HTTPS when the device is reached over Tailscale.
- App Store review may question an unofficial companion that uses the game's
  name. TestFlight or private installs avoid that question.

## v1.1 features

The v1.1 features come through the same standalone server endpoints, as on
Android. The app adds no logic of its own:

- **Art:** `GET /art/<kind>/<id>` returns PNG. Pass the token as `?token=`
  for image views. A 404 shows the glyph. The local-network rule above applies.
- **Actions and onOpen:** post `args` to `/actions/<id>` on tap. Run a
  Screen's `onOpen` once when the page opens, not on refresh or Back.
- **Theme:** `GET /theme` gives named color tokens and 9-slice images. Map
  them to SwiftUI styles. Without a game theme, use the built-in dark theme.
- **Settings:** render `GET /settings` and post to `POST /settings`.

Art is never bundled in the app. It comes from the gaming device, which
rendered it from the user's own game. Do not add game art or fonts to the
app or to TestFlight builds.

See `docs/architecture.md` and `contracts/api.md`.
