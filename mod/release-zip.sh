#!/bin/sh
# Builds the release zip of the game mod: our own DLL + the two yaml files + INSTALL text. No Klei content.
# Usage: mod/release-zip.sh [OUT_DIR]   (default: mod/dist-out). Needs the mod built first (mod/build.sh build).
# MOD_BUILD_DIR overrides the folder with the built files (default mod/build/OniCompanionLink).
# Never publishes anything.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/dist-out}
SRC=${MOD_BUILD_DIR:-$HERE/build/OniCompanionLink}
for f in OniCompanionLink.dll mod.yaml mod_info.yaml; do
  [ -f "$SRC/$f" ] || { echo "$SRC/$f is missing: run mod/build.sh build first" >&2; exit 1; }
done
mkdir -p "$OUT"
python3 -I - "$SRC" "$HERE/package/INSTALL.txt" "$OUT/OniCompanionLink.zip" <<'PY'
import sys, zipfile, os
src, readme, out = sys.argv[1:4]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("OniCompanionLink.dll", "mod.yaml", "mod_info.yaml"):   # a fixed list: nothing else goes in
        z.write(os.path.join(src, f), "OniCompanionLink/" + f)
    z.write(readme, "OniCompanionLink/README.txt")
PY
ls -l "$OUT/OniCompanionLink.zip"
