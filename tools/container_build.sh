#!/bin/bash
# Runs one recipe inside the build container (debian:bookworm).
#
#   container_build.sh <recipe dir> <source dir> <output dir> <arch>
#
# Called by tools/build_package.py, which mounts the extracted sources and
# the recipe read-only. This script copies the sources to a scratch
# directory, applies the recipe's patches, sets the compiler flags of the
# target, runs the recipe's build.sh, strips every shared object and leaves
# the bundles, the license files and build-env.txt in <output dir>.
#
# The flags are defined here and only here, so every recipe gets the same.

set -euo pipefail

recipe=$1 src=$2 out=$3 arch=$4

case "$arch" in
  x86_64)
    want_machine=x86_64
    arch_flags="-march=x86-64-v2 -mtune=generic"
    ;;
  aarch64)
    want_machine=aarch64
    # Baseline ARMv8.0-A so the binaries also run on a Pi 4 (Cortex-A72);
    # tuned for the Pi 5 (Cortex-A76). See docs/BUILDING.md.
    arch_flags="-march=armv8-a -mtune=cortex-a76"
    ;;
  *)
    echo "unknown arch: $arch" >&2
    exit 2
    ;;
esac

if [ "$(uname -m)" != "$want_machine" ]; then
  echo "this container runs on $(uname -m), not $want_machine: build natively" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
deps=(build-essential pkg-config lv2-dev patch)
if [ -f "$recipe/deps" ]; then
  # One Debian package per line, # comments allowed
  while read -r dep; do
    dep=${dep%%#*}
    dep=${dep//[[:space:]]/}
    [ -n "$dep" ] && deps+=("$dep")
  done < "$recipe/deps"
fi
apt-get update -qq
apt-get install -y -qq --no-install-recommends "${deps[@]}" >/dev/null

work=$(mktemp -d /tmp/openrig-build.XXXXXX)
cp -a "$src" "$work/src"
if [ -d "$recipe/patches" ]; then
  for p in "$recipe"/patches/*.patch; do
    [ -e "$p" ] || continue
    echo "applying $(basename "$p")"
    patch -d "$work/src" -p1 --forward --batch < "$p"
  done
fi
mkdir -p "$work/out"

export OPENRIG_ARCH=$arch
export CFLAGS="-O2 $arch_flags"
export CXXFLAGS="-O2 $arch_flags"
export CPPFLAGS=""
export LDFLAGS=""
export JOBS=${JOBS:-$(nproc)}
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-0}

bash "$recipe/build.sh" "$work/src" "$work/out"

# Strip what the recipe did not, without touching the .ttl files
find "$work/out" -type f -name '*.so' -exec strip --strip-unneeded {} +

{
  echo "image: $(. /etc/os-release && echo "$PRETTY_NAME")"
  echo "glibc: $(ldd --version | head -n1)"
  echo "cc: $(gcc --version | head -n1)"
  echo "cxx: $(g++ --version | head -n1)"
  echo "binutils: $(ld --version | head -n1)"
  echo "cflags: $CFLAGS"
  echo "cxxflags: $CXXFLAGS"
  echo "packages: ${deps[*]}"
} > "$work/out/build-env.txt"

cp -a "$work/out/." "$out/"
if [ -n "${HOST_UID:-}" ]; then
  chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$out"
fi
rm -rf "$work"
