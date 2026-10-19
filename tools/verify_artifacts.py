#!/usr/bin/env python3
"""Download every artifact of packages/*.yaml and check its size and sha256.

    tools/verify_artifacts.py [package id]...

Artifacts stay where their authors publish them; this only checks that what
is there is still what the catalog pinned. Nothing is extracted or run.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def digest(url):
    sha, size = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "openrig-catalog"})
    with urllib.request.urlopen(request, timeout=60) as response:
        while chunk := response.read(1 << 20):
            sha.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), size


def main():
    wanted = set(sys.argv[1:])
    failed = 0
    for path in sorted((ROOT / "packages").glob("*.yaml")):
        pkg = yaml.safe_load(path.read_text())
        if wanted and pkg["id"] not in wanted:
            continue
        for arch, art in (pkg.get("artifacts") or {}).items():
            try:
                sha, size = digest(art["url"])
            except OSError as e:
                print(f"FAIL {pkg['id']} {arch}: {e}")
                failed += 1
                continue
            if sha != art["sha256"] or size != art["size"]:
                print(f"FAIL {pkg['id']} {arch}: changed upstream ({size} bytes, sha256 {sha})")
                failed += 1
            else:
                print(f"ok   {pkg['id']} {arch}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
