#!/bin/bash
# caps-lv2 (MOD port of CAPS): plain make, one bundle per plugin
# (plugins/mod-caps-*.lv2). The per-plugin Makefiles set their own
# optimisation (-O3 -ffast-math, upstream's choice) after our flags.
# The bundles keep their modgui (HTML/CSS/PNG for MOD's web UI): data
# only, no binary, referenced by manifest.ttl.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2

# With -ffast-math, glibc's <math.h> on x86_64 declares SIMD variants of
# the math functions and GCC then links libmvec, which the image does not
# list. caps never tests __FAST_MATH__ itself: undefining it only drops
# those declarations. (Environment, not a make argument: the Makefiles
# append their own flags to CXXFLAGS.)
export CXXFLAGS="$CXXFLAGS -U__FAST_MATH__"
make -C "$src" -j "$JOBS" build
# Each bundle installs to $LV2_DEST/<bundle>
make -C "$src" install LV2_DEST="$out"

cp "$src/COPYING" "$out/"
