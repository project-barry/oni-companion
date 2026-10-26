#!/bin/sh
# Install the standalone ONI Companion service for the current user. Never uses sudo.
#   core        -> ~/.local/share/oni-companion/core
#   user units  -> ~/.config/systemd/user (oni-companion.service + oni-companion.path)
# The path unit watches the mod's companion/live folder in the native Linux user folder and in the Proton
# prefix (each only if the game's folder exists) and starts the service on the mod's first write.
# Options: --no-enable  write the files, do not touch systemd's state
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)/oni_companion
[ -d "$SRC" ] || { echo "install: cannot find the oni_companion folder next to this script" >&2; exit 1; }
[ "$(id -u)" -ne 0 ] || { echo "install: run as your normal user, not root" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "install: python3 is needed" >&2; exit 1; }
python3 -c 'import os,sys; sys.exit(0 if sys.version_info>=(3,9) and hasattr(os,"pidfd_open") else 1)' \
  || { echo "install: needs Linux with Python 3.9 or newer (os.pidfd_open)" >&2; exit 1; }

ENABLE=1
[ "${1:-}" = "--no-enable" ] && ENABLE=0

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/oni-companion"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NATIVE="${ONI_NATIVE_USER_DIR:-$HOME/.config/unity3d/Klei/Oxygen Not Included}"
PROTON="${ONI_PROTON_USER_DIR:-$HOME/.local/share/Steam/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded}"

# The core (a copy, so Barry or a git checkout can move without breaking the service).
mkdir -p "$DATA"
rm -rf "$DATA/core.new"
mkdir -p "$DATA/core.new"
cp -R "$SRC" "$DATA/core.new/oni_companion"
find "$DATA/core.new" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$DATA/core"
mv "$DATA/core.new" "$DATA/core"

# The watched folders. A path unit needs the folder to exist; the mod's own folder tree is the same.
WATCH=""
for base in "$NATIVE" "$PROTON"; do
  if [ -d "$base" ]; then
    mkdir -p "$base/companion/live"
    WATCH="$WATCH
PathModified=$base/companion/live"
  fi
done
if [ -z "$WATCH" ]; then
  echo "install: no Oxygen Not Included user folder found (looked in:" >&2
  echo "  $NATIVE" >&2
  echo "  $PROTON )" >&2
  echo "Start the game once, then run this again." >&2
  exit 1
fi

mkdir -p "$UNITS"
cp "$HERE/oni-companion.service" "$UNITS/oni-companion.service"
{
  echo "[Unit]"
  echo "Description=Start ONI Companion when the game's mod writes its first file"
  echo
  echo "[Path]"
  echo "Unit=oni-companion.service"
  echo "MakeDirectory=no"
  # PathModified fires on any entry created, renamed or changed in the folder (the mod writes live.json by rename).
  echo "$WATCH" | sed '1{/^$/d}'
  echo
  echo "[Install]"
  echo "WantedBy=default.target"
} > "$UNITS/oni-companion.path"

if [ "$ENABLE" = 1 ]; then
  systemctl --user daemon-reload
  systemctl --user enable --now oni-companion.path
fi
echo "ONI Companion installed. It starts with the game and ends with it."
echo "  core:  $DATA/core"
echo "  units: $UNITS/oni-companion.service, oni-companion.path"
