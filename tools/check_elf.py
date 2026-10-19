#!/usr/bin/env python3
"""Check built LV2 bundles against what the OpenRig OS image can load.

    tools/check_elf.py --arch x86_64|aarch64 [--host-features FILE|URL]
                       [--package ID] DIR...

DIR is a bundle (*.lv2) or a directory holding bundles. For every ELF file
of every bundle:

- the ELF machine and class match --arch;
- NEEDED libraries are in the image's whitelist (libc, libm, libdl,
  libpthread, libstdc++, libgcc_s and the dynamic loader), so no X11, GTK,
  cairo, GL, fftw or sndfile;
- the symbol versions it needs are at most GLIBC_2.41 and GLIBCXX_3.4.33
  (glibc and GCC 14 of the image), read from readelf -V;
- it does not ask for an executable stack (glibc 2.41 refuses to dlopen it).

For every plugin the .ttl files describe: its lv2:binary is in the bundle,
no UI binary is left, and its lv2:requiredFeature are all provided by the
host. The host's list is SUPPORTED_FEATURES in OpenRig's
src/plugins/lv2_features.rs, read from OpenRig's main branch by default.

With --package, the catalog's plugins of that package must be in the
bundles, and their ports are compared with ports/<id>.json (differences
are reported as warnings: update ports/ with tools/extract_ports.py if the
new layout is intended).

Exits 1 if anything is wrong. Never loads or runs the plugins.
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_ports  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HOST_FEATURES_URL = "https://raw.githubusercontent.com/Siryu6/OpenRig/main/src/plugins/lv2_features.rs"

LV2 = Namespace("http://lv2plug.in/ns/lv2core#")
UI = Namespace("http://lv2plug.in/ns/extensions/ui#")

# ELF e_machine per catalog arch
MACHINES = {"x86_64": 62, "aarch64": 183}
LOADERS = {"x86_64": "ld-linux-x86-64.so.2", "aarch64": "ld-linux-aarch64.so.1"}
# The libraries of the OS image a plugin may link
ALLOWED = {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "libstdc++.so.6", "libgcc_s.so.1"}
# Named in the error so a UI left in the bundle is obvious
UI_LIBS = re.compile(r"^lib(X11|Xext|Xrandr|Xcursor|xcb|gtk|gdk|cairo|pango|GL|GLU|GLX|EGL|OpenGL|glib|gobject|fftw|sndfile)")
# Highest symbol version of each prefix the image provides
# (glibc 2.41, GCC 14: GLIBCXX_3.4.33, CXXABI_1.3.15)
MAX_VERSIONS = {
    "GLIBC": (2, 41),
    "GLIBCXX": (3, 4, 33),
    "CXXABI": (1, 3, 15),
    "GCC": (14, 0, 0),
}
VERSION_NAME = re.compile(r"Name: ((GLIBC|GLIBCXX|CXXABI|GCC)_([0-9][0-9.]*))")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, message):
        self.errors.append(f"{where}: {message}")

    def warn(self, where, message):
        self.warnings.append(f"{where}: {message}")


def host_features(source):
    """SUPPORTED_FEATURES of lv2_features.rs, from a file or a URL"""
    if re.match(r"^https?://", source):
        request = urllib.request.Request(source, headers={"User-Agent": "openrig-catalog"})
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode()
    else:
        text = Path(source).read_text()
    consts = dict(re.findall(r'const\s+([A-Z0-9_]+)\s*:\s*&str\s*=\s*"([^"]+)"\s*;', text))
    block = re.search(r"SUPPORTED_FEATURES\s*:\s*&\[&str\]\s*=\s*&\[(.*?)\];", text, re.S)
    if not block:
        sys.exit(f"{source}: SUPPORTED_FEATURES not found")
    features = set()
    # String literals, comments (skipped) and constant names, in order
    for m in re.finditer(r'"([^"\\]*)"|//[^\n]*|/\*.*?\*/|([A-Za-z_][A-Za-z0-9_]*)', block.group(1), re.S):
        literal, name = m.groups()
        if literal is not None:
            features.add(literal)
        elif name is not None:
            if name not in consts:
                sys.exit(f"{source}: cannot resolve {name} in SUPPORTED_FEATURES")
            features.add(consts[name])
    if not features:
        sys.exit(f"{source}: SUPPORTED_FEATURES is empty")
    return features


def elf_header(path):
    """(class, e_machine) of an ELF file, None if it is not one"""
    with path.open("rb") as f:
        head = f.read(20)
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return None
    endian = "<" if head[5] == 1 else ">"
    return head[4], struct.unpack(endian + "H", head[18:20])[0]


def readelf(*args):
    # LC_ALL=C: the parsing below expects readelf's English output
    env = {**os.environ, "LC_ALL": "C"}
    return subprocess.run(["readelf", "--wide", *args], check=True, capture_output=True, text=True, env=env).stdout


def version_tuple(text):
    return tuple(int(x) for x in text.split(".") if x)


def check_elf(report, path, arch, where):
    header = elf_header(path)
    if header is None:
        return False
    elf_class, machine = header
    if elf_class != 2 or machine != MACHINES[arch]:
        report.error(where, f"ELF class {elf_class} machine {machine}, expected 64-bit {arch} ({MACHINES[arch]})")
        return True

    dynamic = readelf("-d", str(path))
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dynamic)
    for lib in needed:
        if UI_LIBS.match(lib):
            report.error(where, f"links {lib}: a UI or a library the image does not have")
        elif lib not in ALLOWED and lib != LOADERS[arch]:
            report.error(where, f"links {lib}, not in the image's whitelist")
    if "(TEXTREL)" in dynamic:
        report.warn(where, "has text relocations")

    # Only what the file needs (.gnu.version_r), not the versions it defines
    needs = readelf("-V", str(path)).partition("Version needs section")[2]
    needs = needs.split("Version definition section")[0]
    for full, prefix, version in sorted(set(VERSION_NAME.findall(needs))):
        if version_tuple(version) > MAX_VERSIONS[prefix]:
            limit = ".".join(map(str, MAX_VERSIONS[prefix]))
            report.error(where, f"needs {full}, newer than the image's {prefix}_{limit}")

    for line in readelf("-l", str(path)).splitlines():
        if line.strip().startswith("GNU_STACK") and line.split()[-2].endswith("E"):
            report.error(where, "asks for an executable stack (glibc 2.41 refuses to load it)")
    return True


def bundles_of(paths):
    for path in paths:
        if path.suffix == ".lv2" and path.is_dir():
            yield path
        else:
            yield from sorted(p for p in path.iterdir() if p.suffix == ".lv2" and p.is_dir())


def local_file(bundle, uri):
    """Path in the bundle a file: URI of its .ttl points to, None if outside"""
    if not str(uri).startswith("file://"):
        return None
    path = Path(urllib.parse.unquote(str(uri)[len("file://"):]))
    try:
        path.resolve().relative_to(bundle.resolve())
    except ValueError:
        return None
    return path


def check_bundle(report, bundle, arch, features):
    elves = 0
    for path in sorted(p for p in bundle.rglob("*") if p.is_file() and not p.is_symlink()):
        elves += check_elf(report, path, arch, str(path.relative_to(bundle.parent)))

    graph = Graph()
    for ttl in sorted(bundle.rglob("*.ttl")):
        try:
            graph.parse(ttl, format="turtle")
        except Exception as e:  # rdflib raises many kinds
            report.error(str(ttl.relative_to(bundle.parent)), f"invalid Turtle: {e}")
    plugins = sorted(set(graph.subjects(RDF.type, LV2.Plugin)))
    if not plugins:
        report.error(bundle.name, "describes no lv2:Plugin")
    if not elves:
        report.error(bundle.name, "has no shared object")

    for plugin in plugins:
        where = f"{bundle.name} <{plugin}>"
        binary = graph.value(plugin, LV2.binary)
        file = local_file(bundle, binary) if binary is not None else None
        if file is None or not file.is_file():
            report.error(where, f"lv2:binary {binary} is not in the bundle")
        missing = sorted(str(f) for f in graph.objects(plugin, LV2.requiredFeature) if str(f) not in features)
        for feature in missing:
            report.error(where, f"requires {feature}, which the host does not provide")

    for ui in sorted(set(graph.objects(None, UI.ui))):
        binary = graph.value(ui, UI.binary)
        file = local_file(bundle, binary) if binary is not None else None
        if file is not None and file.is_file():
            report.error(f"{bundle.name} <{ui}>", f"UI binary {file.name} must be removed (headless only)")
        else:
            report.warn(f"{bundle.name} <{ui}>", "the .ttl still declares a UI (not shipped, hosts skip it)")
    return {str(p) for p in plugins}


def check_catalog(report, package, bundles):
    """The catalog's plugins of package are built, with the ports of ports/"""
    by_name = {b.name: b for b in bundles}
    for path in sorted((ROOT / "plugins").glob("*.yaml")):
        plugin = yaml.safe_load(path.read_text())
        if plugin.get("package") != package:
            continue
        where = f"plugins/{path.name}"
        bundle = by_name.get(plugin["bundle"])
        if bundle is None:
            report.error(where, f"bundle {plugin['bundle']} was not built")
            continue
        graph = Graph()
        for ttl in sorted(bundle.glob("*.ttl")):
            graph.parse(ttl, format="turtle")
        if (URIRef(plugin["uri"]), RDF.type, LV2.Plugin) not in graph:
            report.error(where, f"{plugin['uri']} is not in {bundle.name}")
            continue
        built = extract_ports.extract(plugin["uri"], [bundle])
        known_file = ROOT / "ports" / f"{plugin['id']}.json"
        if not known_file.is_file():
            report.warn(where, f"ports/{known_file.name} is missing")
            continue
        known = json.loads(known_file.read_text())
        for key in ("ports_hash", "required_features", "audio", "classes"):
            if built.get(key) != known.get(key):
                report.warn(where, f"{key} of the build differs from ports/{known_file.name}: "
                                   f"{json.dumps(built.get(key))} != {json.dumps(known.get(key))}")
        if built["ports_hash"] == known.get("ports_hash") and built["ports"] != known.get("ports"):
            report.warn(where, f"same port layout, but ranges, defaults or names differ from ports/{known_file.name}")


def check(paths, arch, features, package=None):
    report = Report()
    bundles = list(bundles_of(paths))
    if not bundles:
        report.error(" ".join(map(str, paths)), "no .lv2 bundle")
    for bundle in bundles:
        check_bundle(report, bundle, arch, features)
    if package:
        check_catalog(report, package, bundles)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("dirs", nargs="+", type=Path)
    parser.add_argument("--arch", required=True, choices=sorted(MACHINES))
    parser.add_argument("--host-features", default=HOST_FEATURES_URL,
                        help="lv2_features.rs of OpenRig, a file or a URL (default: OpenRig main)")
    parser.add_argument("--package", help="also check the catalog's plugins of this package")
    args = parser.parse_args()

    report = check(args.dirs, args.arch, host_features(args.host_features), args.package)
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    if report.errors:
        sys.exit(f"{len(report.errors)} problem(s)")
    print(f"{len(list(bundles_of(args.dirs)))} bundle(s) OK for {args.arch}")


if __name__ == "__main__":
    main()
