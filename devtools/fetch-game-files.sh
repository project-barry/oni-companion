#!/usr/bin/env bash
# Copies ONI game data and save files from the Nova to this Mac.
# Read-only on the Nova (tar over ssh pulls only). Nothing is deleted locally.
# Usage: devtools/fetch-game-files.sh [--with-dlls]
#   --with-dlls  also copy Managed/{Assembly-CSharp,Assembly-CSharp-firstpass,0Harmony,netstandard}.dll
#                for the mod build. Only for the Mac Mini build, not for this Mac.
# Rerun after a game update. .bank files are never copied.
# The user folder is auto-detected (Proton prefix or Linux build); NOVA_USER=proton|linux or
# NOVA_USER_DIR=/abs/path overrides. Saves and companion/ land in <dest>/user/.
# Env: NOVA_HOST (default steamos@nova), ONI_LOCAL_DIR, SSH_CMD (test stub).
set -euo pipefail

NOVA="${NOVA_HOST:-steamos@nova}"
DEST="${ONI_LOCAL_DIR:-$HOME/Documents/Github/steamos-work/oni}"
SSH="${SSH_CMD:-ssh}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15)
WITH_DLLS=0

case "${1:-}" in
  "") ;;
  --with-dlls) WITH_DLLS=1 ;;
  -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

# Single-quote a string for the remote shell.
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
ssh_run() { "$SSH" "${SSH_OPTS[@]}" "$NOVA" "$1"; }

echo "Checking $NOVA"
REMOTE_HOME="$(ssh_run 'printf %s "$HOME"')" || { echo "Cannot reach $NOVA. Nothing copied." >&2; exit 1; }
GAME="$REMOTE_HOME/.local/share/Steam/steamapps/common/OxygenNotIncluded"
SA="$GAME/OxygenNotIncluded_Data/StreamingAssets"
MANAGED="$GAME/OxygenNotIncluded_Data/Managed"
MANIFEST="$REMOTE_HOME/.local/share/Steam/steamapps/appmanifest_457140.acf"

. "$(cd "$(dirname "$0")" && pwd)/nova-common.sh"
pick_userdir || { echo "No ONI user folder found on $NOVA. Saves not copied." >&2; USERDIR=""; USERKIND=none; }
echo "User folder ($USERKIND): ${USERDIR:-none}"

echo "Pulling StreamingAssets (codex, elements, strings, worldgen, dlc)"
mkdir -p "$DEST/OxygenNotIncluded_Data/StreamingAssets"
ssh_run "tar -C $(q "$SA") --exclude='*.bank' -cf - codex elements strings worldgen dlc" \
  | tar -C "$DEST/OxygenNotIncluded_Data/StreamingAssets" -xf -

echo "Pulling appmanifest_457140.acf"
ssh_run "cat $(q "$MANIFEST")" > "$DEST/appmanifest_457140.acf"

if [ -n "$USERDIR" ]; then
  echo "Pulling saves and companion files (auto_save is inside each colony)"
  mkdir -p "$DEST/user"
  ssh_run "cd $(q "$USERDIR") && tar -cf - \$(ls -d cloud_save_files save_files companion 2>/dev/null)" \
    | tar -C "$DEST/user" -xf -
fi

if [ "$WITH_DLLS" = 1 ]; then
  echo "Pulling Managed DLLs for the mod build"
  mkdir -p "$DEST/OxygenNotIncluded_Data/Managed"
  ssh_run "cd $(q "$MANAGED") && tar -cf - \$(ls Assembly-CSharp.dll Assembly-CSharp-firstpass.dll 0Harmony.dll netstandard.dll 2>/dev/null)" \
    | tar -C "$DEST/OxygenNotIncluded_Data/Managed" -xf -
fi

echo "Done. Local sizes:"
du -sh "$DEST/OxygenNotIncluded_Data/StreamingAssets"/* "$DEST/user"/* "$DEST/appmanifest_457140.acf" 2>/dev/null || true
