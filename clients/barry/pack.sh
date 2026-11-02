#!/bin/sh
# Pack ONI Companion for Barry: vendors the core, checks, zips.
# Usage: clients/barry/pack.sh [OUT_DIR]   (default: clients/barry/dist)
# Needs ../barry-launcher-apps (tools/barry-app). Klei data never goes in.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
TOOL=${BARRY_APP_TOOL:-$REPO/../barry-launcher-apps/tools/barry-app}
OUT=${1:-$HERE/dist}
[ -f "$TOOL" ] || { echo "barry-app not found: $TOOL (set BARRY_APP_TOOL)" >&2; exit 1; }
[ -d "$REPO/core/oni_companion" ] || { echo "core/oni_companion is missing" >&2; exit 1; }
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/oni-companion"
mkdir -p "$APP"
cp "$HERE/barry-app.json" "$HERE/main.qml" "$HERE/service.py" "$HERE/icon-symbolic.svg" "$APP/"
cp -R "$HERE/qml" "$APP/qml"
cp -R "$REPO/core/oni_companion" "$APP/oni_companion"
# v1.3: the built game mod (our own code, no Klei content) travels inside the app so it can offer "Install the game mod".
MODB="$REPO/mod/build/OniCompanionLink"
if [ -f "$MODB/OniCompanionLink.dll" ] && [ -f "$MODB/mod.yaml" ] && [ -f "$MODB/mod_info.yaml" ]; then
  mkdir -p "$APP/oni_companion/bundled_mod/OniCompanionLink"
  cp "$MODB/OniCompanionLink.dll" "$MODB/mod.yaml" "$MODB/mod_info.yaml" "$APP/oni_companion/bundled_mod/OniCompanionLink/"
else
  echo "note: mod/build/OniCompanionLink is not built (run mod/build.sh); the app will have no mod to install" >&2
fi
cp "$REPO/LICENSE" "$APP/" 2>/dev/null || true
cp "$REPO/CREDITS.md" "$APP/" 2>/dev/null || true
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$APP" \( -name '*.pyc' -o -name '.DS_Store' -o -name .gitkeep -o -name '* 2*' \) -delete
python3 "$TOOL" check "$APP"
mkdir -p "$OUT"
( cd "$STAGE" && python3 "$TOOL" pack oni-companion )
mv "$STAGE"/*.zip "$OUT/"
ls -l "$OUT"/*.zip
