#!/bin/bash
# mda-lv2: meson. One bundle, mda.lv2, with every plugin and its presets.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2
build=$(mktemp -d) stage=$(mktemp -d)

meson setup "$build" "$src" --prefix=/usr -Dlv2dir=/lv2 \
  --buildtype=release -Dtests=disabled -Dlint=false -Ddev=false
meson compile -C "$build" -j "$JOBS"
DESTDIR="$stage" meson install -C "$build"

cp -a "$stage/lv2/mda.lv2" "$out/"
# Dual licensed, GPL-2.0-or-later or MIT (see README.md)
cp "$src"/LICENSES/GPL-2.0-or-later.txt "$src"/LICENSES/MIT.txt "$src/README.md" "$out/"
