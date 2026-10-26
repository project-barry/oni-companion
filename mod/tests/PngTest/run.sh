#!/bin/bash
# Offline check of the PNG encoder. Run on a machine with dotnet (the Mac Mini): tests/PngTest/run.sh <workdir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${1:?workdir}"
mkdir -p "$W"; cp "$HERE/PngTest.csproj" "$W/"
python3 - "$HERE/../../src/Art.cs" "$HERE/Program.cs" "$W/Program.cs" <<'PY'
import sys,re
art=open(sys.argv[1]).read(); prog=open(sys.argv[2]).read()
png=art.split('// BEGIN PNG')[1].split('// END PNG')[0]
ds=art.split('public static byte[] Downscale')[1]
ds='public static byte[] Downscale'+ds.split('\n        }\n',1)[0]+'\n        }\n'
prog=prog.replace('//PNG_HERE',png).replace('//DOWNSCALE_HERE',ds)
open(sys.argv[3],'w').write(prog)
PY
cd "$W"
dotnet run -c Release -- "$W/out"
python3 "$HERE/check.py" "$W/out"
