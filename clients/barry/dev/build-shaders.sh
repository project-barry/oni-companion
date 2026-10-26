#!/bin/sh
# Dev only: compile shaders/*.vert|frag into qml/*.qsb (Qt Shader Tools). Needs pyside6-qsb on PATH
# (pip install PySide6-Addons; run on the Mac Mini, in a venv of your own).
# Usage: dev/build-shaders.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
for s in sdf.vert sdf.frag; do
  pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o "$HERE/qml/$s.qsb" "$HERE/shaders/$s"
done
