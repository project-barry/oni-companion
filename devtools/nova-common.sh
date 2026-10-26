# Sourced by fetch-game-files.sh and mirror-nova.sh. Needs ssh_run() and REMOTE_HOME.
# Which ONI user folder on the Nova? ONI runs as the Windows build under Proton (inside the
# compatdata prefix) or as the Linux build (~/.config/unity3d). Pick by newest save/companion activity.
# Choose with NOVA_USER=proton|linux|auto (default) or NOVA_USER_DIR=<absolute remote path>.
# Read only on the Nova.

REMOTE_USER_SCRIPT='
H="$HOME"; S="$H/.local/share/Steam"
libs="$S/steamapps"
[ -f "$S/steamapps/libraryfolders.vdf" ] && libs="$libs
$(sed -n "s/^[[:space:]]*\"path\"[[:space:]]*\"\(.*\)\"/\1\/steamapps/p" "$S/steamapps/libraryfolders.vdf")"
cands=""
for l in $libs; do
  for u in "$l"/compatdata/457140/pfx/drive_c/users/*/Documents/Klei/OxygenNotIncluded; do
    [ -d "$u" ] && case "$u" in */Public/*) ;; *) cands="$cands
proton|$u" ;; esac
  done
done
[ -d "$H/.config/unity3d/Klei/Oxygen Not Included" ] && cands="$cands
linux|$H/.config/unity3d/Klei/Oxygen Not Included"
echo "$cands" | while IFS="|" read -r kind dir; do
  [ -n "$dir" ] || continue
  t=$(find "$dir/companion" "$dir/cloud_save_files" "$dir/save_files" -type f \( -name "*.sav" -o -name "*.json" \) -printf "%T@\n" 2>/dev/null | sort -n | tail -1)
  echo "${t:-0}|$kind|$dir"
done'

# Sets USERDIR and USERKIND (or returns 1 when nothing is found).
pick_userdir() {
  local want="${NOVA_USER:-auto}" list line
  if [ -n "${NOVA_USER_DIR:-}" ]; then
    USERDIR="$NOVA_USER_DIR"; USERKIND=custom; return 0
  fi
  list="$(ssh_run "$REMOTE_USER_SCRIPT")" || return 1
  line="$(printf '%s\n' "$list" | awk -F'|' -v w="$want" 'NF==3 && (w=="auto" || $2==w) {print}' | sort -t'|' -k1,1nr | head -1)"
  [ -n "$line" ] || return 1
  USERKIND="$(printf '%s' "$line" | cut -d'|' -f2)"
  USERDIR="$(printf '%s' "$line" | cut -d'|' -f3-)"
}
