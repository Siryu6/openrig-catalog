#!/bin/bash
# airwindows-lv2: meson. One bundle, Airwindows.lv2, with every plugin.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2
build=$(mktemp -d) stage=$(mktemp -d)

meson setup "$build" "$src" --prefix=/usr -Dlv2dir=/lv2 --buildtype=release
meson compile -C "$build" -j "$JOBS"
DESTDIR="$stage" meson install -C "$build"

cp -a "$stage/lv2/Airwindows.lv2" "$out/"
cp "$src/LICENSE" "$out/"
