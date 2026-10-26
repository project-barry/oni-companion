#!/bin/sh
# Remove what install.sh added. Never uses sudo. Leaves the game's folders and the mod alone.
set -eu
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/oni-companion"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NATIVE="${ONI_NATIVE_USER_DIR:-$HOME/.config/unity3d/Klei/Oxygen Not Included}"
PROTON="${ONI_PROTON_USER_DIR:-$HOME/.local/share/Steam/steamapps/compatdata/457140/pfx/drive_c/users/steamuser/Documents/Klei/OxygenNotIncluded}"
[ "${1:-}" = "--no-systemctl" ] && SC=0 || SC=1

if [ "$SC" = 1 ]; then
  systemctl --user disable --now oni-companion.path 2>/dev/null || true
  systemctl --user stop oni-companion.service 2>/dev/null || true
fi
rm -f "$UNITS/oni-companion.path" "$UNITS/oni-companion.service"
[ "$SC" = 1 ] && systemctl --user daemon-reload 2>/dev/null || true
rm -rf "$DATA/core" "$DATA/core.new"
rmdir "$DATA" 2>/dev/null || true       # only if nothing else (settings, identity) lives there
# The empty watch folder install.sh may have made (the mod makes it too; rmdir only removes empty ones).
for base in "$NATIVE" "$PROTON"; do
  rmdir "$base/companion/live" 2>/dev/null || true
done
echo "ONI Companion removed."
