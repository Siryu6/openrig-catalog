# Building the plugins OpenRig publishes

Most plugins of the store are downloaded from their authors' releases
(`origin: upstream`). When a project publishes no Linux build for the
pedalboard's processors, OpenRig builds it from pinned sources and publishes
the binaries next to those exact sources (`origin: openrig-build`). This page
explains how.

## In short

```sh
pip install -r requirements.txt
tools/build_package.py mda-lv2 --arch x86_64     # podman or docker needed
tools/pin_build.py                               # dist/builds/*.json -> packages/*.yaml
tools/build_index.py --check
```

In GitHub Actions: push a tag `build-<package>-<version>` (or run the
*Build* workflow by hand). It builds both architectures, publishes the
release `<package>-<version>` and opens a PR that pins the artifacts.

## Recipes

One directory per package, named after `packages/<id>.yaml`:

| Path | What |
|---|---|
| `recipes/<id>/build.sh` | `build.sh <source dir> <output dir>`: builds, then copies the `.lv2` bundles and the license files to the output dir |
| `recipes/<id>/deps` | Optional. Debian packages the build needs, one per line |
| `recipes/<id>/patches/*.patch` | Optional. Applied in name order with `patch -p1` before the build |
| `recipes/<id>/DEFERRED` | Instead of `build.sh`: why the package cannot be built yet |

`build.sh` runs as root in a `debian:bookworm` container. It gets a writable
copy of the extracted sources (the archive's top directory), patched, and
these variables:

| Variable | Value |
|---|---|
| `OPENRIG_ARCH` | `x86_64` or `aarch64` |
| `CFLAGS`, `CXXFLAGS` | `-O2` and the target flags below |
| `JOBS` | Number of parallel jobs |
| `SOURCE_DATE_EPOCH` | Commit time of the catalog, for reproducible builds |

It must:

- build the DSP only: no UI, no JACK app, nothing that links X11, cairo,
  GTK or GL. Use the project's headless switch (`make mod` for GxPlugins,
  `BUILDOPENGL=no BUILDJACKAPP=no INLINEDISPLAY=no` for x42, and so on);
- not pick flags from the build machine (`/proc/cpuinfo`, `-march=native`):
  the flags come from `CFLAGS`/`CXXFLAGS`;
- keep the optimisation flags upstream chose (some use `-O3 -ffast-math`);
  never add `-ffast-math` ourselves. With `-ffast-math` on x86_64, glibc's
  `<math.h>` lets GCC call the vector math library `libmvec`, which is not
  in the whitelist: add `-U__FAST_MATH__` to the flags if the code never
  tests that macro (see `recipes/caps-lv2/build.sh`);
- copy every bundle the package provides, or at least those the catalog's
  `plugins/*.yaml` list, and the license text (`LICENSE`, `COPYING`...).

`tools/container_build.sh` then strips every `.so`.

Current recipes:

| Package | Build system | Bundles |
|---|---|---|
| `mda-lv2` | meson | `mda.lv2` (all plugins and presets) |
| `fomp` | meson | `fomp.lv2` (all plugins) |
| `airwindows-lv2` | meson | `Airwindows.lv2` (all plugins) |
| `caps-lv2` | make | the 27 `mod-caps-*.lv2`, with their MOD web UI files (HTML/CSS/PNG, no binary) |
| `gxplugins` | make (`make mod`) | the 43 `gx_*.lv2`, with MOD's `.ttl` (7 still declare an X11 UI, not shipped) |
| `x42-plugins` | make | `fil4.lv2` and `dpl.lv2` only, from the source tarball (never the x42-plugins.com binaries) |
| `guitarix` | `g++`, without waf | `gxts9.lv2` and `gx_fuzzfacefm.lv2` only, from the Faust code shipped pre-generated (the full waf build needs the whole app) |

## Build environment

The binaries must load on the OpenRig OS image: glibc 2.41, libstdc++ of
GCC 14 (up to `GLIBCXX_3.4.33`), and for plugins only libc, libm, libdl,
libpthread, libstdc++ and libgcc_s.

We build **natively** on GitHub's hosted runners, `ubuntu-24.04` (x86_64)
and `ubuntu-24.04-arm` (aarch64, free for public repositories), inside
`debian:bookworm`: glibc 2.36 and GCC 12. Binaries built against an older
glibc and libstdc++ run on newer ones, never the reverse, so bookworm is
old enough for the image while having current meson, lv2 and compilers.
Native builds avoid cross-compilation quirks in the projects' Makefiles,
which often test `uname -m` or `/proc/cpuinfo`.

The study first proposed a Buildroot external reusing the image's own
toolchain. It gives the exact ABI of the image, but costs a full toolchain
build per run and a Buildroot package per plugin. Since the checks below
catch any ABI drift, bookworm is the simpler start; Buildroot remains the
way to go if a plugin ever needs a library that has to match the image.

| Arch | Flags | Why |
|---|---|---|
| x86_64 | `-O2 -march=x86-64-v2 -mtune=generic` | The OS's x86 baseline (SSE4.2, POPCNT): any mini PC of the last decade |
| aarch64 | `-O2 -march=armv8-a -mtune=cortex-a76` | Runs on every 64-bit Pi (Pi 4's Cortex-A72 is ARMv8.0-A), tuned for the Pi 5's Cortex-A76 |

`-march=armv8.2-a` (Pi 5) would allow half-precision and dot-product
instructions and LSE atomics, which float DSP code barely uses, and would
make the binaries crash on a Pi 4. If the image ever drops the Pi 4, change
it in `tools/container_build.sh` and say so here.

`BUILD-INFO.txt` records the image digest, the compilers and the flags of
each build. To pin the image itself, replace `IMAGE` in
`tools/build_package.py` with a `debian@sha256:...` reference.

## Checks

`tools/check_elf.py` runs on every build, before anything is packed. It
reads the files and never loads them. For every ELF file of every bundle:

- 64-bit, and the ELF machine of the target (x86-64 or AArch64);
- `NEEDED` libraries only from the whitelist (and the dynamic loader);
  X11, xcb, GTK, cairo, pango, GL, glib, fftw, sndfile are named as UI or
  missing libraries;
- symbol versions it needs at most `GLIBC_2.41`, `GLIBCXX_3.4.33`,
  `CXXABI_1.3.15` (`readelf -V`, version needs only);
- no executable stack: glibc 2.41 refuses to `dlopen` such a library.

For every plugin the `.ttl` files describe: its `lv2:binary` is in the
bundle, no UI binary is left, and each `lv2:requiredFeature` is one the host
provides. The host's list is `SUPPORTED_FEATURES` in OpenRig's
[`src/plugins/lv2_features.rs`](https://github.com/Siryu6/OpenRig/blob/main/src/plugins/lv2_features.rs),
read from OpenRig's main branch on every build so it cannot drift; use
`--host-features path/to/lv2_features.rs` to check against a local branch.

Then, for the catalog's plugins of the package: their bundle is built, the
URI is in it, and the ports read from the build (`tools/extract_ports.py`)
are compared with `ports/<id>.json`. A difference is a warning: if the new
port layout is intended, update `ports/` (and check `ports_hash`, saved
presets depend on it).

To check bundles by hand:

```sh
tools/check_elf.py --arch aarch64 --package caps-lv2 path/to/bundles/
```

## Release layout

`tools/build_package.py <id> --arch <arch>` writes, for the release tag
`<id>-<version>`:

| File | What |
|---|---|
| `dist/release/<tag>/<tag>-<arch>.tar.xz` | `<tag>/` with the bundles, the license files and `BUILD-INFO.txt` |
| `dist/release/<tag>/<tag>-src.<ext>` | The upstream source tarball, byte for byte (its sha256 is `source.sha256`) |
| `dist/release/<tag>/<tag>-recipe.tar.xz` | `recipes/<id>/` and the scripts that ran the build |
| `dist/builds/<id>-<arch>.json` | The artifact entry: final download URL, sha256, size, format, root |

`BUILD-INFO.txt` gives the source URL and sha256, the URLs of the source
copy and of the recipe, the catalog commit of the recipe, the build image,
compilers, flags, and the sha256 of every shared object.

The archives are reproducible (sorted entries, fixed owner, times set to
the catalog commit). Downloads use direct
`https://github.com/Siryu6/openrig-catalog/releases/download/<tag>/<file>`
URLs: the device never calls the GitHub API.

A published file is never replaced: the indexes already signed pin its
sha256. To rebuild (new flags, a patch), give the package a new version,
for example `0.9.26-2`, and tag again.

## Source obligations

For every binary we publish, the same release carries:

- the exact source tarball we built from (a copy, not a link: if the
  upstream tag or file goes away, the sources stay available);
- the recipe, the patches and the scripts used to control the build;
- in the binary archive: the license text and `BUILD-INFO.txt`, which says
  where these sources are and that the build is unofficial.

This is GPLv2 §3 (its last paragraph: equivalent access to the source from
the same place) and GPLv3 §6(d) (the same, from a designated place). No written offer
is needed. The sources stay as long as the binaries are served: never
delete a release that an index still points to. MIT plugins (airwindows)
only require the license text, which is included as well.

The store must keep allowing any bundle copied by hand into the
pedalboard's LV2 folder (GPLv3 §6 *Installation Information*): the
signature protects the index, not the plugins.

## Adding a recipe

1. In `packages/<id>.yaml`, set `origin: openrig-build`, the source URL
   (a release tarball if the project has one, otherwise a tag or commit
   archive) and its sha256. Download it into a new empty directory, never
   run anything from it, and read its build system.
2. Write `recipes/<id>/build.sh` (and `deps`, `patches/` if needed).
3. Build and check: `tools/build_package.py <id> --arch x86_64`. Fix every
   error; read every warning.
4. Read the ports of the built bundle: `tools/extract_ports.py <plugin id>
   build/<id>/out-x86_64/<Bundle>.lv2`.
5. Open a PR. Once merged, push the tag `build-<id>-<version>`.

aarch64 builds need an aarch64 machine, or qemu-user binfmt for the
container engine; otherwise let the CI build them.

## Publishing and signing

1. Push `build-<id>-<version>`. The *Build* workflow builds both
   architectures, creates the release `<id>-<version>` with the binaries,
   the sources and the recipe, then opens the PR *Pin `<id>-<version>`*
   with the artifacts in `packages/<id>.yaml`.
2. Review and merge that PR. (PRs opened with the workflow's token do not
   trigger other workflows: close and reopen it to run the checks.)
3. On your machine, from an up-to-date `main`:

   ```sh
   tools/build_index.py
   OPENRIG_CATALOG_KEY=~/path/outside/the/repo/catalog.key tools/sign_index.sh
   ```

   `sign_index.sh` signs `dist/catalog-v1.json` with minisign (the trusted
   comment carries the serial), refuses a key stored inside the repository,
   checks the signature against `keys/catalog.pub`, and prints the
   `gh release upload catalog ...` command to run. The index is then at
   <https://github.com/Siryu6/openrig-catalog/releases/download/catalog/catalog-v1.json>.

The secret key never enters the repository or the CI.
