#!/bin/bash
# x42-plugins: only fil4 (parametric EQ) and dpl (digital peak limiter),
# built from the source tarball (never the x42-plugins.com binaries).
# Headless: no OpenGL UI, no JACK app, no inline display (which would link
# cairo and pango). Versions come from the tarball's gitversion.mak.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2
stage=$(mktemp -d)

set -a
. "$src/gitversion.mak"
set +a

headless=(BUILDOPENGL=no BUILDJACKAPP=no INLINEDISPLAY=no)
for p in fil4 dpl; do
  make -C "$src/$p.lv2" -j "$JOBS" "${headless[@]}" all
  make -C "$src/$p.lv2" "${headless[@]}" install-bin \
    DESTDIR="$stage" PREFIX=/usr LV2DIR=/lv2
  cp -a "$stage/lv2/$p.lv2" "$out/"
  # fil4 is GPL-2.0-or-later, dpl ships the GPL-3.0 text
  cp "$src/$p.lv2/COPYING" "$out/COPYING-$p"
done
