#!/bin/bash
# guitarix: only the LV2 bundles the catalog lists, built without waf. The
# full waf build needs GTK, Boost, Faust and the rest of the app; each of
# these bundles is a single translation unit: the DSP that Faust generated
# is shipped in src/LV2/faust-generated (what waf uses when Faust is not
# installed) and #included, with headers from src/LV2/DSP. Flags as waf's release build:
# -O3 -DNDEBUG, -fvisibility=hidden, LV2_SO. No UI: the *_ui.cpp files are
# not built, the .ttl still declare them (not shipped, as for gxplugins).
# The modgui folders are kept: data only, no binary.
#   build.sh <source dir> <output dir>
set -euo pipefail
src=$1 out=$2
lv2=$src/src/LV2

# Bundle directory and source file, same name
bundles=(gxts9 gx_fuzzfacefm)

for b in "${bundles[@]}"; do
  dir=$lv2/$b.lv2 dest=$out/$b.lv2
  mkdir -p "$dest"
  # lv2.h is #included bare: lv2-dev puts it under lv2/core/
  g++ $CXXFLAGS -O3 -DNDEBUG -DLV2_SO -fPIC -fvisibility=hidden -shared \
    -I"$lv2/faust-generated" -I"$dir" -I"$lv2/DSP" -I"$lv2/DSP/tube_tables" \
    -I/usr/include/lv2/core \
    -Wl,-z,noexecstack -Wl,-z,relro,-z,now -Wl,--exclude-libs,ALL \
    -o "$dest/$b.so" "$dir/$b.cpp" -lm
  # What waf's MODGUI build does: @LIB_EXT@ -> .so, modgui.ttl kept
  sed 's/@LIB_EXT@/.so/g' "$dir/manifest.ttl.in" >"$dest/manifest.ttl"
  find "$dir" -maxdepth 1 -name '*.ttl' -exec cp {} "$dest/" \;
  if [ -d "$dir/modgui" ]; then cp -a "$dir/modgui" "$dest/"; fi
done

cp "$src/COPYING" "$out/"
