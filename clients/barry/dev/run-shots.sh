#!/bin/sh
# Dev only: run-shots.sh OUT_DIR [SCALE] [SCRIPT.json]; log in OUT_DIR/log.txt
A="/Applications/Barry Simulator.app/Contents"
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$1"
PYTHONPATH="$A/Resources/site-packages${PYTHONPATH:+:$PYTHONPATH}" "$A/MacOS/python" "$HERE/shots.py" "$@" > "$1/log.txt" 2>&1 < /dev/null &
PID=$!
( sleep 80; kill $PID 2>/dev/null; pkill -f "mock-server.py --listen" 2>/dev/null ) &
wait $PID
pkill -f "mock-server.py --listen" 2>/dev/null
echo done
