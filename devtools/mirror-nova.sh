#!/usr/bin/env bash
# Mirrors ONI save and companion files from the Nova into a local user folder.
# Default: ~/Library/Application Support/oni-companion/nova-user (set ONI_MIRROR_DIR to change it).
# Keep it OUT of iCloud Drive (Desktop & Documents): iCloud sees the rewrites as conflicts, makes
# "live 2.json" / "Bunker Cycle 428.sav" copies and can put old content back. Point dev.json's user_dir here.
# Event driven: ssh runs inotifywait -m on the Nova. Nothing is written on the Nova.
# Usage: devtools/mirror-nova.sh   (Ctrl-C stops it)
# Watches cloud_save_files (auto saves are inside it) and companion, if they exist at start.
# The user folder is auto-detected: the Proton prefix (Windows build) or ~/.config/unity3d (Linux build),
# whichever has the newest saves/companion files. NOVA_USER=proton|linux forces one,
# NOVA_USER_DIR=/abs/path names it. Files land in the mirror folder in the layout the core expects.
# Env: NOVA_HOST (default steamos@nova), ONI_MIRROR_DIR, SSH_CMD (test stub).
set -uo pipefail

NOVA="${NOVA_HOST:-steamos@nova}"
DEST="${ONI_MIRROR_DIR:-$HOME/Library/Application Support/oni-companion/nova-user}"
case "$DEST" in
  "$HOME/Documents"/*|"$HOME/Desktop"/*|*"/Mobile Documents/"*)
    echo "Warning: $DEST may be synced by iCloud, which breaks the mirror (conflict copies, old content back)." >&2 ;;
esac
SSH="${SSH_CMD:-ssh}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=20 -o ServerAliveCountMax=3)
SUBDIRS=(cloud_save_files save_files companion)  # auto_save sits inside each colony folder

# Single-quote a string for the remote shell.
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
ssh_run() { "$SSH" "${SSH_OPTS[@]}" "$NOVA" "$1"; }

REMOTE_HOME="$(ssh_run 'printf %s "$HOME"')" || { log "Cannot reach $NOVA. Retry later."; exit 1; }
. "$(cd "$(dirname "$0")" && pwd)/nova-common.sh"
pick_userdir || { log "No ONI user folder found on $NOVA (looked at Proton prefixes and ~/.config/unity3d). Retry later."; exit 1; }
log "user folder ($USERKIND): $USERDIR"

# Subdirectories that exist on the Nova now (the Nova is never written to).
existing() {
  ssh_run "cd $(q "$USERDIR") 2>/dev/null && for d in ${SUBDIRS[*]}; do [ -d \"\$d\" ] && echo \"\$d\"; done; true"
}

# Initial catch-up copy, so the mirror is complete before events arrive.
initial_sync() {
  local list="$1"
  log "initial copy: $list"
  # shellcheck disable=SC2086
  ssh_run "cd $(q "$USERDIR") && tar -cf - $list" | tar -C "$DEST" -xf - && log "initial copy done"
}

# Kill this script's own child processes (ssh, tar, pipes), not the whole process group.
kill_tree() {
  local c
  for c in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$c"; done
  kill "$1" 2>/dev/null
}
# Ends this script's watch on the Nova. Without it a dropped ssh leaves inotifywait running there.
# The [m] keeps pkill from matching its own command line.
cleanup_remote() {
  ssh_run "pkill -f 'inotifywait -m -r -q -e close_write,[m]oved_to' 2>/dev/null; true" >/dev/null 2>&1
}

trap 'trap - INT TERM; log "stopping"; for c in $(pgrep -P $$ 2>/dev/null); do kill_tree "$c"; done; cleanup_remote; exit 0' INT TERM

while :; do
  dirs="$(existing)" || dirs=""
  if [ -z "$dirs" ]; then
    log "no save folders on $NOVA yet, retry in 10 s"; sleep 10; continue
  fi
  if ! ssh_run 'command -v inotifywait >/dev/null && command -v stdbuf >/dev/null'; then
    log "inotifywait or stdbuf missing on the Nova. Install inotify-tools (ask first). Stopping."
    exit 1
  fi
  log "watching on $NOVA: $(echo $dirs | tr '\n' ' ')"
  # shellcheck disable=SC2086
  initial_sync "$(echo $dirs)"

  watch_list=""
  while IFS= read -r d; do watch_list="$watch_list $(q "$USERDIR/$d")"; done <<<"$dirs"
  # Event per finished write (close_write), rename into place (moved_to) or new folder (create, copied whole).
  # mirror-batch.py copies all events of 150 ms with one ssh (one ssh per file fell minutes behind during a sync).
  cleanup_remote  # drop any watch left from an earlier dropped connection
  # Run in the background and wait, so the stop trap runs at once on Ctrl-C.
  (
    ssh_run "stdbuf -oL inotifywait -m -r -q -e close_write,moved_to,create --format '%e|%w%f' --$watch_list" |
    SSH_CMD="$SSH" NOVA_HOST="$NOVA" python3 -u "$(cd "$(dirname "$0")" && pwd)/mirror-batch.py" "$USERDIR" "$DEST"
  ) &
  wait $!
  log "watch ended, reconnect in 5 s"
  sleep 5
done
