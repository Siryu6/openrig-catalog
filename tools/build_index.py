#!/usr/bin/env python3
"""Check the catalog and build the index OpenRig downloads.

    tools/build_index.py [--check] [--serial N] [--media-base URL] [--out FILE]

Reads families.yaml, packages/*.yaml, plugins/*.yaml, ports/*.json and
media/, and writes dist/catalog-v1.json. With --check, only reports what is
wrong. The index is not signed here: signing happens at publication, with a
key that never enters this repository.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 1
# How long a device trusts an index before showing it as stale
VALIDITY = timedelta(days=90)
MEDIA_BASE = "https://raw.githubusercontent.com/Siryu6/openrig-catalog/main/media/"
ORIGINS = {"upstream", "openrig-build"}
ARCHES = {"aarch64", "x86_64"}
FORMATS = {"tar.gz", "tar.xz", "tar.bz2", "zip", "deb"}
SUMMARY_MAX = 80
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

PACKAGE_FIELDS = {"id", "name", "version", "license", "homepage", "origin", "source", "artifacts"}
PLUGIN_FIELDS = {
    "id", "package", "uri", "bundle", "name", "author", "license", "family",
    "subcategory", "kind", "inspired_by", "tags", "summary", "description",
}
PICTURE_FIELDS = {"file", "source", "credit", "license"}
# What the app needs from a control port
CONTROL_FIELDS = (
    "index", "symbol", "name", "min", "max", "default", "unit",
    "properties", "scale_points", "designation",
)


class Problems(list):
    def add(self, where, message):
        self.append(f"{where}: {message}")


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def png_size(path):
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def check_fields(problems, where, data, required, optional=()):
    missing = required - data.keys()
    unknown = data.keys() - required - set(optional)
    if missing:
        problems.add(where, f"missing {', '.join(sorted(missing))}")
    if unknown:
        problems.add(where, f"unknown {', '.join(sorted(unknown))}")


def check_package(problems, path, pkg):
    where = f"packages/{path.name}"
    check_fields(problems, where, pkg, PACKAGE_FIELDS)
    if pkg.get("id") != path.stem:
        problems.add(where, "id must match the file name")
    if pkg.get("origin") not in ORIGINS:
        problems.add(where, f"origin must be one of {', '.join(sorted(ORIGINS))}")
    source = pkg.get("source") or {}
    if not str(source.get("url", "")).startswith("https://"):
        problems.add(where, "source.url must be an https URL")
    sha = source.get("sha256")
    if sha is not None and not SHA256.match(sha):
        problems.add(where, "source.sha256 must be a sha256 or null")
    for arch, art in (pkg.get("artifacts") or {}).items():
        if arch not in ARCHES:
            problems.add(where, f"unknown arch {arch}")
            continue
        if not str(art.get("url", "")).startswith("https://"):
            problems.add(where, f"{arch}: url must be an https URL")
        if not SHA256.match(str(art.get("sha256", ""))):
            problems.add(where, f"{arch}: sha256 is required for an artifact")
        if not isinstance(art.get("size"), int):
            problems.add(where, f"{arch}: size (bytes) is required")
        if art.get("format") not in FORMATS:
            problems.add(where, f"{arch}: format must be one of {', '.join(sorted(FORMATS))}")


def check_plugin(problems, path, plugin, packages, families, kinds):
    where = f"plugins/{path.name}"
    check_fields(problems, where, plugin, PLUGIN_FIELDS, optional={"picture"})
    if plugin.get("id") != path.stem or not ID.match(path.stem):
        problems.add(where, "id must match the file name (lowercase, digits, dashes)")
    if plugin.get("package") not in packages:
        problems.add(where, f"unknown package {plugin.get('package')}")
    family = plugin.get("family")
    if family not in families:
        problems.add(where, f"family must be one of {', '.join(families)}")
    elif plugin.get("subcategory") not in families[family]:
        problems.add(where, f"subcategory must be one of {', '.join(families[family])} (or add it to families.yaml)")
    if plugin.get("kind") not in kinds:
        problems.add(where, f"kind must be one of {', '.join(kinds)}")
    if not str(plugin.get("bundle", "")).endswith(".lv2"):
        problems.add(where, "bundle must be the .lv2 directory in the archive")
    if len(plugin.get("summary") or "") > SUMMARY_MAX:
        problems.add(where, f"summary is longer than {SUMMARY_MAX} characters")
    if not (plugin.get("description") or "").strip():
        problems.add(where, "description is empty")
    tags = plugin.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        problems.add(where, "tags must be a list of words")

    picture = plugin.get("picture")
    if picture is not None:
        check_fields(problems, f"{where} picture", picture, PICTURE_FIELDS, optional={"block_face"})
        file = ROOT / "media" / str(picture.get("file"))
        if not file.is_file():
            problems.add(where, f"media/{picture.get('file')} is missing")
        elif png_size(file) is None:
            problems.add(where, f"media/{picture.get('file')} is not a PNG")
        if not str(picture.get("source", "")).startswith("https://"):
            problems.add(where, "picture.source must link to the file in the project's sources")

    ports = ROOT / "ports" / f"{path.stem}.json"
    if not ports.is_file():
        problems.add(where, f"ports/{ports.name} is missing: run tools/extract_ports.py on the bundle")
    elif json.loads(ports.read_text()).get("uri") != plugin.get("uri"):
        problems.add(where, f"ports/{ports.name} describes another URI")


def picture_entry(picture, media_base):
    file = ROOT / "media" / picture["file"]
    width, height = png_size(file)
    entry = {
        "url": media_base + picture["file"],
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "w": width,
        "h": height,
        "source": picture["source"],
        "license": picture["license"],
        "credit": picture["credit"],
    }
    if picture.get("block_face"):
        entry["block_face"] = True
    return entry


def plugin_entry(plugin, media_base):
    ports = json.loads((ROOT / "ports" / f"{plugin['id']}.json").read_text())
    controls = [
        {k: p[k] for k in CONTROL_FIELDS if p.get(k) is not None}
        for p in ports["ports"]
        if p["type"] == "control" and p["direction"] == "in"
    ]
    entry = {k: plugin[k] for k in (
        "id", "uri", "bundle", "name", "author", "license", "family", "subcategory",
        "kind", "tags", "inspired_by", "summary", "description",
    )}
    entry["description"] = " ".join(entry["description"].split())
    entry["audio"] = ports["audio"]
    entry["required_features"] = ports["required_features"]
    entry["ports_hash"] = ports["ports_hash"]
    entry["controls"] = controls
    entry["media"] = {}
    if plugin.get("picture"):
        entry["media"]["picture"] = picture_entry(plugin["picture"], media_base)
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only check the catalog")
    parser.add_argument("--serial", type=int, help="index serial (default: YYYYMMDDHH, UTC)")
    parser.add_argument("--media-base", default=MEDIA_BASE, help="URL the media/ files are served from")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "catalog-v1.json")
    args = parser.parse_args()

    meta = load_yaml(ROOT / "families.yaml")
    families, kinds = meta["families"], meta["kinds"]
    problems = Problems()

    packages = {}
    for path in sorted((ROOT / "packages").glob("*.yaml")):
        pkg = load_yaml(path)
        check_package(problems, path, pkg)
        packages[path.stem] = pkg

    plugins, uris = [], {}
    for path in sorted((ROOT / "plugins").glob("*.yaml")):
        plugin = load_yaml(path)
        check_plugin(problems, path, plugin, packages, families, kinds)
        uri = plugin.get("uri")
        if uri in uris:
            problems.add(f"plugins/{path.name}", f"same URI as plugins/{uris[uri]}")
        uris[uri] = path.name
        plugins.append(plugin)

    used = {p.get("package") for p in plugins}
    for unused in sorted(packages.keys() - used):
        problems.add(f"packages/{unused}.yaml", "no plugin uses this package")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(f"{len(problems)} problem(s)")
    unbuilt = sorted(p for p in used if not packages[p].get("artifacts"))
    print(f"{len(plugins)} plugins in {len(used)} packages: OK"
          + (f" ({len(unbuilt)} not built yet: {', '.join(unbuilt)})" if unbuilt else ""))
    if args.check:
        return

    now = datetime.now(timezone.utc).replace(microsecond=0)
    index = {
        "schema": SCHEMA,
        "serial": args.serial or int(now.strftime("%Y%m%d%H")),
        "generated": now.isoformat().replace("+00:00", "Z"),
        "expires": (now + VALIDITY).isoformat().replace("+00:00", "Z"),
        "packages": [],
    }
    for pkg_id in sorted(used):
        pkg = packages[pkg_id]
        entry = {k: pkg[k] for k in ("id", "name", "version", "license", "homepage", "origin", "source")}
        entry["artifacts"] = pkg.get("artifacts") or {}
        entry["plugins"] = [
            plugin_entry(p, args.media_base)
            for p in sorted(plugins, key=lambda p: p["id"]) if p["package"] == pkg_id
        ]
        index["packages"].append(entry)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    print(f"{args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}: serial {index['serial']}")


if __name__ == "__main__":
    main()
