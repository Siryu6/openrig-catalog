#!/bin/bash
# Sign dist/catalog-v1.json with the catalog's minisign key, on the owner's
# machine. The key never enters this repository nor the CI.
#
#   OPENRIG_CATALOG_KEY=~/.config/openrig/catalog.key tools/sign_index.sh
#
# Writes dist/catalog-v1.json.minisig (its trusted comment carries the
# index serial), checks it against keys/catalog.pub when that file exists,
# then prints the command that publishes both files.

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
index="$root/dist/catalog-v1.json"

if ! command -v minisign >/dev/null; then
  echo "minisign is not installed (https://jedisct1.github.io/minisign/)" >&2
  exit 1
fi
if [ -z "${OPENRIG_CATALOG_KEY:-}" ]; then
  echo "set OPENRIG_CATALOG_KEY to the path of the secret key" >&2
  exit 1
fi
if [ ! -f "$OPENRIG_CATALOG_KEY" ]; then
  echo "OPENRIG_CATALOG_KEY does not point to a file" >&2
  exit 1
fi
# Resolved, symlinks included, so a link to a key in the repo is refused too
key=$(python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$OPENRIG_CATALOG_KEY")
root=$(python3 -I -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$root")
case "$key/" in
  "$root"/*)
    echo "the secret key is inside the repository: move it out (and never commit it)" >&2
    exit 1
    ;;
esac
if [ ! -f "$index" ]; then
  echo "dist/catalog-v1.json is missing: run tools/build_index.py" >&2
  exit 1
fi

serial=$(python3 -I -c 'import json, sys; print(int(json.load(open(sys.argv[1]))["serial"]))' "$index")

# minisign asks for the key's password on the terminal
minisign -S -s "$key" -m "$index" -t "openrig-catalog serial $serial"

if [ -f "$root/keys/catalog.pub" ]; then
  minisign -V -p "$root/keys/catalog.pub" -m "$index" -q
  echo "signature checked against keys/catalog.pub"
fi

echo "signed serial $serial. To publish:"
echo "  gh release upload catalog dist/catalog-v1.json dist/catalog-v1.json.minisig --clobber --repo Siryu6/openrig-catalog"
echo "served at https://github.com/Siryu6/openrig-catalog/releases/download/catalog/catalog-v1.json"
