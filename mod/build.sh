#!/bin/bash
# Build the mod on the Mac Mini (needs dotnet). Run from the Mac.
# Usage: mod/build.sh pull-libs | build
# ONI runs as the Windows build under Proton on the Nova, so build against its Managed/ DLLs (lib-win).
# Game DLLs are piped Nova -> Mini and never stored on this Mac.
set -euo pipefail
NOVA="${NOVA_HOST:-steamos@nova}"
MINI="${MINI_HOST:-build-mac}"
HERE="$(cd "$(dirname "$0")" && pwd)"
case "${1:-build}" in
  pull-libs)
    ssh "$NOVA" 'tar -C ~/.local/share/Steam/steamapps/common/OxygenNotIncluded/OxygenNotIncluded_Data/Managed -cf - .' \
      | ssh "$MINI" 'mkdir -p ~/oni-mod-build/lib-win && tar -C ~/oni-mod-build/lib-win -xf -' ;;
  build)
    rsync -a --delete --exclude lib --exclude bin --exclude obj --exclude build "$HERE/" "$MINI:oni-mod-build/src/"
    ssh "$MINI" 'export DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec PATH=/opt/homebrew/bin:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1; cd ~/oni-mod-build/src && rm -rf ~/oni-mod-build/out && dotnet build -c Release -o ~/oni-mod-build/out -p:LibDir=$HOME/oni-mod-build/lib-win/ && cp mod.yaml mod_info.yaml ~/oni-mod-build/out/'
    rm -rf "$HERE/build/OniCompanionLink"; mkdir -p "$HERE/build/OniCompanionLink"
    for f in OniCompanionLink.dll mod.yaml mod_info.yaml; do
      scp "$MINI:oni-mod-build/out/$f" "$HERE/build/OniCompanionLink/$f"
    done ;;
  build-both)
    # Both builds of the lane: Windows game DLLs (lib-win) and Linux game DLLs (lib). Usage: build.sh build-both [lane]  (default lane M11)
    LANE="${2:-M11}"
    ssh "$MINI" "mkdir -p ~/oni-mod-build/$LANE/src"
    rsync -a --delete --exclude lib --exclude bin --exclude obj --exclude build --exclude tests "$HERE/" "$MINI:oni-mod-build/$LANE/src/"
    for V in win linux; do
      if [ "$V" = win ]; then LIB='$HOME/oni-mod-build/lib-win/'; else LIB='$HOME/oni-mod-build/lib/'; fi
      ssh "$MINI" "export DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec PATH=/opt/homebrew/bin:\$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1; cd ~/oni-mod-build/$LANE/src && rm -rf obj bin ~/oni-mod-build/$LANE/out-$V && dotnet build -c Release -o ~/oni-mod-build/$LANE/out-$V -p:LibDir=$LIB && cp mod.yaml mod_info.yaml ~/oni-mod-build/$LANE/out-$V/"
    done ;;
esac
