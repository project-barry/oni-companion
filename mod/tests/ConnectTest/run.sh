#!/bin/bash
# Offline check of ConnectModel.cs / LocalMode.cs / Json.cs / FileUtil.cs on the Mac Mini (dotnet + the game's Newtonsoft.Json.dll in ~/oni-mod-build/lib-win).
# Usage: mod/tests/ConnectTest/run.sh   (from the repo; copies sources and the synthetic fixtures to the Mini, runs, pulls the request files back and validates them here)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
MINI="${MINI_HOST:-build-mac}"; W='~/oni-mod-build/M11/conntest'
ssh "$MINI" "rm -rf $W && mkdir -p $W/src $W/fx"
scp -q "$HERE/ConnectTest.csproj" "$HERE/Program.cs" "$MINI:oni-mod-build/M11/conntest/"
scp -q "$HERE/../../src/ConnectModel.cs" "$HERE/../../src/LocalMode.cs" "$HERE/../../src/FileUtil.cs" "$HERE/../../src/Json.cs" "$HERE/../../src/Qr.cs" "$MINI:oni-mod-build/M11/conntest/src/"
scp -qr "$ROOT/fixtures/synthetic/companion" "$ROOT/fixtures/synthetic/companion-local" "$MINI:oni-mod-build/M11/conntest/fx/"
ssh "$MINI" "export DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec PATH=/opt/homebrew/bin:\$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1; cd $W && dotnet build -c Release -o bin -v q 2>&1 | grep -E "error" | sort -u || true && dotnet bin/ConnectTest.dll fx out"
OUT="$(mktemp -d)"; scp -qr "$MINI:oni-mod-build/M11/conntest/out/requests" "$OUT/"
python3 -I "$HERE/check.py" "$ROOT" "$OUT" ; rm -rf "$OUT"
