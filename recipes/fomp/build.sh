#!/bin/bash
# fomp: meson. One bundle, fomp.lv2, with every plugin (Fons Adriaensen's
# MCP, VCO, filter and reverb LADSPA plugins, ported to LV2 by drobilla).
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2
build=$(mktemp -d) stage=$(mktemp -d)

meson setup "$build" "$src" --prefix=/usr -Dlv2dir=/lv2 \
  --buildtype=release -Dtests=disabled
meson compile -C "$build" -j "$JOBS"
DESTDIR="$stage" meson install -C "$build"

cp -a "$stage/lv2/fomp.lv2" "$out/"
cp "$src/COPYING" "$src/AUTHORS" "$out/"
