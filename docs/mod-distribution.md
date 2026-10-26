# How players get the game mod (plan 4.6)

Three routes, all the same mod (our own DLL + `mod.yaml` + `mod_info.yaml`; no Klei content, no network).

1. **Steam Workshop** (main route, NOT published yet: ask the owner first, needs a Steam account).
2. **The companion app** (`POST /mod/install {confirm:true}`, button in Settings): copies the three files into
   `<user folder>/mods/Local/OniCompanionLink`. Never silent (400 without confirm), refuses while a Workshop copy
   exists, never edits `mods.json`. `clients/barry/pack.sh` bundles `mod/build/OniCompanionLink` into the app zip.
3. **A zip on the releases page**: `mod/release-zip.sh [OUT]` -> `OniCompanionLink.zip` with unpack-here text.

## Where a Workshop copy lives (verified in the decompiled game, build 744825)
`KMod.Steam` reads the item with `SteamUGC.GetItemInstallInfo`: a zip inside Steam's content folder
`<steamapps>/workshop/content/457140/<item id>/`. The game then copies it to `<user folder>/mods/Steam/<item id>`
and lists it in `mods.json` with `distribution_platform: 1`. Same on Linux and under Proton (the Proton prefix sits
in a Steam library, so the same library holds the content folder). The core checks all three places
(`modstate.find_copies`), so two copies never both get installed. Untested on a real Workshop item (none exists).

## Workshop upload (preparation only)
The game contains no uploader. Klei ships a Steam tool, "Oxygen Not Included Uploader" (Steam library, enable
"Tools"). Source for the steps: the community modding wiki (https://github.com/Cairath/Oxygen-Not-Included-Modding/wiki/Publishing);
no current official Klei page was found, so confirm in the tool itself.
- Point it at the folder with the DLL (not a zip): only `OniCompanionLink.dll`, `mod.yaml`, `mod_info.yaml`.
- Fill name, description, thumbnail (our own image), tags Base Game and Spaced Out!.
- The first upload is private; the owner makes it public after reading the page. Keep a copy of the description.

### Workshop page text (draft)
Title: ONI Companion Link

An unofficial companion mod, not affiliated with or endorsed by Klei Entertainment.
It lets the free ONI Companion app (a separate app on your handheld or phone) show your colony, resources and
building data next to the game. The mod only writes files into the game's own user folder. It opens no network
connection and changes nothing in your saves. Subscribe, enable it in the Mods menu, restart the game.
If you installed it by hand or through the app first, remove that copy: two copies would both load.
