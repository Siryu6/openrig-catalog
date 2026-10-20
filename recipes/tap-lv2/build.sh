#!/bin/bash
# tap-lv2 (MOD port of Tom Szilagyi's TAP plugins): plain make, one bundle
# per plugin (tap-<name>.lv2). Makefile.mk keeps upstream's -O3 -ffast-math;
# NOOPT=true drops its x86-only -msse -msse2 -mfpmath=sse, so the same
# recipe builds on aarch64 (the flags come from CFLAGS).
# The bundles keep their modgui (HTML/CSS/PNG for MOD's web UI): data
# only, no binary, referenced by manifest.ttl.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2

# With -ffast-math, glibc's <math.h> on x86_64 declares SIMD variants of
# the math functions and GCC then links libmvec, which the image does not
# list. TAP never tests __FAST_MATH__ itself: undefining it only drops
# those declarations. (Environment: Makefile.mk appends to CFLAGS.)
export CFLAGS="$CFLAGS -U__FAST_MATH__"
make -C "$src" -j "$JOBS" NOOPT=true all
# Each bundle installs to $INSTALL_PATH/tap-<name>.lv2
make -C "$src" install NOOPT=true INSTALL_PATH="$out"

cp "$src/COPYING" "$src/CREDITS" "$out/"
