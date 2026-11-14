#!/bin/bash
# dragonfly-reverb (DPF): the LV2 DSP of the four reverbs only (make
# lv2_dsp), so nothing links DGL, OpenGL or X11. The .ttl files come from
# DPF's generator, built and run natively. DPF keeps upstream's -O3
# -ffast-math; the target flags come from CFLAGS/CXXFLAGS.
# The patch makes the pink noise of Plate (Tank) and Room build its
# pattern a sample at a time instead of 32768 samples in one audio block.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2

# With -ffast-math, glibc's <math.h> on x86_64 declares SIMD variants of
# the math functions and GCC then links libmvec, which the image does not
# list. Neither DPF's DSP code nor freeverb3 tests __FAST_MATH__.
export CFLAGS="$CFLAGS -U__FAST_MATH__" CXXFLAGS="$CXXFLAGS -U__FAST_MATH__"

for p in dragonfly-hall-reverb dragonfly-room-reverb dragonfly-plate-reverb dragonfly-early-reflections; do
  make -C "$src/plugins/$p" -j "$JOBS" lv2_dsp
done
make -C "$src/dpf/utils/lv2-ttl-generator"
(cd "$src" && dpf/utils/generate-ttl.sh)

cp -a "$src"/bin/*.lv2 "$out/"
cp "$src/LICENSE" "$out/"
