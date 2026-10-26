#!/bin/bash
# Offline check of the QR encoder on the Mac Mini (dotnet + a venv with segno, opencv-python-headless, numpy at ~/oni-mod-build/M11/v).
# Usage: mod/tests/QrTest/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MINI="${MINI_HOST:-build-mac}"
W='~/oni-mod-build/M11/qrtest'
ssh "$MINI" "mkdir -p $W/src $W/tests/QrTest"
scp -q "$HERE/QrTest.csproj" "$HERE/Program.cs" "$HERE/check.py" "$HERE/cases.txt" "$MINI:oni-mod-build/M11/qrtest/tests/QrTest/"
scp -q "$HERE/../../src/Qr.cs" "$MINI:oni-mod-build/M11/qrtest/src/"
ssh "$MINI" "export DOTNET_ROOT=/opt/homebrew/opt/dotnet/libexec PATH=/opt/homebrew/bin:\$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1; cd $W/tests/QrTest && dotnet build -c Release -o bin -v q >/dev/null && dotnet bin/QrTest.dll cases.txt out.txt && for k in 0 1 2 3 4 5 6 7; do dotnet bin/QrTest.dll cases.txt o\$k.txt \$k; done && ~/oni-mod-build/M11/v/bin/python check.py cases.txt"
