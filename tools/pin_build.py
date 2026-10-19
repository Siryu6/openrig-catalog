#!/usr/bin/env python3
"""Pin the artifacts built by tools/build_package.py in packages/*.yaml.

    tools/pin_build.py [dist/builds/<package>-<arch>.json]...

With no argument, takes every dist/builds/*.json. Each one replaces the
artifact of its arch in packages/<package>.yaml (url, sha256, size, format,
root), so that tools/build_index.py publishes it. The rest of the file,
comments included, is left as it is. Refuses a build of another version
than the one the package declares, or of another source.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ("url", "sha256", "size", "format", "root")


def artifacts_block(artifacts):
    lines = ["artifacts:"] if artifacts else ["artifacts: {}"]
    for arch in sorted(artifacts):
        lines.append(f"  {arch}:")
        for key in FIELDS:
            if key in artifacts[arch]:
                lines.append(f"    {key}: {artifacts[arch][key]}")
    return lines


def replace_artifacts(text, artifacts):
    """Swap the top-level artifacts: block of a package file"""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("artifacts:")), None)
    if start is None:
        return text.rstrip("\n") + "\n" + "\n".join(artifacts_block(artifacts)) + "\n"
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    # Keep blank lines that separate the block from what follows
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines[start:end] = artifacts_block(artifacts)
    return "\n".join(lines) + "\n"


def main():
    files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / "dist" / "builds").glob("*.json"))
    if not files:
        sys.exit("no dist/builds/*.json: run tools/build_package.py first")
    builds = {}
    for f in files:
        build = json.loads(f.read_text())
        builds.setdefault(build["package"], []).append(build)

    for package, entries in sorted(builds.items()):
        path = ROOT / "packages" / f"{package}.yaml"
        pkg = yaml.safe_load(path.read_text())
        if pkg.get("origin") != "openrig-build":
            sys.exit(f"{path.name}: origin is not openrig-build")
        artifacts = dict(pkg.get("artifacts") or {})
        for build in entries:
            if build["version"] != str(pkg["version"]):
                sys.exit(f"{package} {build['arch']}: built version {build['version']}, "
                         f"{path.name} declares {pkg['version']}")
            if build.get("source_sha256") != pkg["source"].get("sha256"):
                sys.exit(f"{package} {build['arch']}: built from another source than {path.name} pins")
            artifacts[build["arch"]] = {k: build[k] for k in FIELDS}
        text = replace_artifacts(path.read_text(), artifacts)
        if yaml.safe_load(text)["artifacts"] != artifacts:
            sys.exit(f"{path.name}: could not rewrite the artifacts block, edit it by hand")
        path.write_text(text)
        print(f"{path.relative_to(ROOT)}: {', '.join(sorted(b['arch'] for b in entries))} pinned")


if __name__ == "__main__":
    main()
