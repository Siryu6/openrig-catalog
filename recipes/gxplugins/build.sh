#!/bin/bash
# GxPlugins.lv2: one Makefile per plugin directory. "make mod" builds the
# DSP only (no X11/cairo UI) and the bundle with MOD's .ttl files, which
# declare no UI. SSE_CFLAGS/ARMCPU are forced empty: upstream picks them
# from the build machine's /proc/cpuinfo, we use the target flags instead.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2

build_one() {
  dir=$1 out=$2
  name=$(sed -n 's/^[[:space:]]*NAME = //p' "$dir/Makefile" | head -n1)
  make -C "$dir" mod SSE_CFLAGS= ARMCPU= >"$dir/build.log" 2>&1 || {
    cat "$dir/build.log" >&2
    echo "failed: $dir" >&2
    return 1
  }
  test -f "$dir/$name.lv2/$name.so"
  cp -a "$dir/$name.lv2" "$out/"
}
export -f build_one

find "$src" -mindepth 2 -maxdepth 2 -name Makefile -path '*.lv2/Makefile' -printf '%h\n' \
  | sort | xargs -P "$JOBS" -I{} bash -c 'build_one "$1" "$2"' _ {} "$out"

cp "$src/LICENSE" "$out/"
