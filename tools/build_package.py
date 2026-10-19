#!/usr/bin/env python3
"""Build an openrig-build package from its pinned sources, check it, pack it.

    tools/build_package.py <package id> [--arch x86_64|aarch64]
                           [--engine auto|podman|docker|none] [--source FILE]
                           [--host-features FILE|URL] [--jobs N]
    tools/build_package.py --list

1. downloads packages/<id>.yaml source.url (or takes --source) and checks
   its sha256 against source.sha256;
2. extracts it under build/<id>/ and runs recipes/<id>/build.sh in a
   debian:bookworm container (tools/container_build.sh), the sources
   mounted read-only;
3. checks the bundles with tools/check_elf.py;
4. writes the three files of the release <id>-<version> in
   dist/release/<id>-<version>/:
     <id>-<version>-<arch>.tar.xz     bundles, licenses, BUILD-INFO.txt
     <id>-<version>-src.<ext>         the exact upstream source tarball
     <id>-<version>-recipe.tar.xz     the recipe, its patches, the scripts
   and dist/builds/<id>-<arch>.json, the artifact entry for
   tools/pin_build.py (its url is the final release download URL).

The container must run natively: build aarch64 on an aarch64 machine (or
one with qemu-user binfmt). --engine none runs the recipe directly, for a
machine that already is the build environment.

--list prints the packages that have a recipe, as JSON, for the CI.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_elf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "docker.io/library/debian:bookworm"
REPO = os.environ.get("GITHUB_REPOSITORY", "Siryu6/openrig-catalog")
PLATFORMS = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}
LICENSE_NAMES = ("license", "licence", "copying", "gpl", "mit", "lgpl")
# The scripts that drive a build, shipped with the recipe (GPL: "the
# scripts used to control compilation and installation")
DRIVER_FILES = ("tools/build_package.py", "tools/container_build.sh", "tools/check_elf.py")


def log(message):
    print(f"==> {message}", flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def recipe_commit(package):
    commit = git("rev-parse", "HEAD") or "unknown"
    paths = [f"recipes/{package}", *DRIVER_FILES]
    if git("status", "--porcelain", "--", *paths):
        commit += "-dirty"
    return commit


def source_date_epoch():
    return int(os.environ.get("SOURCE_DATE_EPOCH") or git("log", "-1", "--format=%ct") or 0)


def buildable():
    """Packages built by OpenRig that have a recipe"""
    result = []
    for path in sorted((ROOT / "packages").glob("*.yaml")):
        pkg = yaml.safe_load(path.read_text())
        if pkg.get("origin") == "openrig-build" and (ROOT / "recipes" / pkg["id"] / "build.sh").is_file():
            result.append({"package": pkg["id"], "version": str(pkg["version"])})
    return result


def fetch_source(pkg, workdir, given):
    source = pkg["source"]
    want = source.get("sha256")
    if not want:
        sys.exit(f"packages/{pkg['id']}.yaml: source.sha256 is not pinned")
    name = Path(source["url"].split("?")[0]).name
    target = workdir / "download" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if given:
        shutil.copyfile(given, target)
    elif not (target.is_file() and sha256_file(target) == want):
        log(f"downloading {source['url']}")
        request = urllib.request.Request(source["url"], headers={"User-Agent": "openrig-catalog"})
        with urllib.request.urlopen(request, timeout=300) as response, target.open("wb") as f:
            shutil.copyfileobj(response, f)
    got = sha256_file(target)
    if got != want:
        sys.exit(f"{name}: sha256 {got}, packages/{pkg['id']}.yaml pins {want}: refusing to build")
    log(f"{name}: sha256 OK")
    return target


def extract(archive, dest):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        # "data" refuses absolute paths, links out of dest, devices, setuid
        tar.extractall(dest, filter="data")
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def source_suffix(name):
    for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst", ".tgz", ".zip"):
        if name.endswith(ext):
            return ext
    return Path(name).suffix


def engine_of(choice):
    if choice != "auto":
        return choice
    for engine in ("podman", "docker"):
        if shutil.which(engine):
            return engine
    sys.exit("no podman or docker: install one, or use --engine none inside a build environment")


def image_digest(engine):
    if engine == "none":
        return "none (ran in the current environment)"
    try:
        out = subprocess.run([engine, "image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE],
                             check=True, capture_output=True, text=True).stdout.strip()
        return out or IMAGE
    except (OSError, subprocess.CalledProcessError):
        return IMAGE


def run_recipe(engine, package, arch, src, out, jobs, epoch):
    recipe = ROOT / "recipes" / package
    script = ROOT / "tools" / "container_build.sh"
    env = {"JOBS": str(jobs), "SOURCE_DATE_EPOCH": str(epoch)}
    if engine == "none":
        subprocess.run(["bash", str(script), str(recipe), str(src), str(out), arch],
                       check=True, env={**os.environ, **env})
        return
    if engine != "podman":
        # Rootless podman maps the container's root to us; docker does not
        env.update(HOST_UID=str(os.getuid()), HOST_GID=str(os.getgid()))
    cmd = [engine, "run", "--rm", "--platform", PLATFORMS[arch],
           "-v", f"{src}:/openrig/src:ro",
           "-v", f"{recipe}:/openrig/recipe:ro",
           "-v", f"{script}:/openrig/container_build.sh:ro",
           "-v", f"{out}:/openrig/out"]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [IMAGE, "bash", "/openrig/container_build.sh", "/openrig/recipe", "/openrig/src", "/openrig/out", arch]
    log(" ".join(cmd))
    subprocess.run(cmd, check=True)


def tar_xz(target, members, epoch):
    """Reproducible tar.xz: sorted entries, fixed owner and time"""
    def add(tar, path, arcname):
        info = tar.gettarinfo(str(path), arcname)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = epoch
        if info.isdir():
            info.mode = 0o755
        elif info.isfile():
            info.mode = 0o755 if path.stat().st_mode & 0o100 else 0o644
        if info.isfile():
            with path.open("rb") as f:
                tar.addfile(info, f)
        else:
            tar.addfile(info)

    with tarfile.open(target, "w:xz", format=tarfile.PAX_FORMAT, preset=9) as tar:
        for path, arcname in members:
            add(tar, path, arcname)
            if path.is_dir():
                for sub in sorted(path.rglob("*")):
                    add(tar, sub, f"{arcname}/{sub.relative_to(path).as_posix()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", nargs="?")
    parser.add_argument("--list", action="store_true", help="print the packages that have a recipe (JSON)")
    parser.add_argument("--arch", choices=sorted(PLATFORMS),
                        default={"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine(), platform.machine()))
    parser.add_argument("--engine", default="auto", choices=("auto", "podman", "docker", "none"))
    parser.add_argument("--source", type=Path, help="use this file instead of downloading source.url (sha256 still checked)")
    parser.add_argument("--host-features", default=check_elf.HOST_FEATURES_URL,
                        help="OpenRig's lv2_features.rs, a file or a URL (default: OpenRig main)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = parser.parse_args()

    if args.list:
        print(json.dumps(buildable()))
        return
    if not args.package:
        parser.error("a package id is required")
    pkg_file = ROOT / "packages" / f"{args.package}.yaml"
    if not pkg_file.is_file():
        sys.exit(f"{pkg_file.relative_to(ROOT)}: no such package")
    pkg = yaml.safe_load(pkg_file.read_text())
    if pkg.get("origin") != "openrig-build":
        sys.exit(f"{args.package}: origin is {pkg.get('origin')}, only openrig-build packages are built here")
    if not (ROOT / "recipes" / args.package / "build.sh").is_file():
        sys.exit(f"recipes/{args.package}/build.sh: no recipe")

    package, version, arch = pkg["id"], str(pkg["version"]), args.arch
    tag = f"{package}-{version}"
    epoch = source_date_epoch()
    features = check_elf.host_features(args.host_features)
    engine = engine_of(args.engine)

    workdir = ROOT / "build" / package
    archive = fetch_source(pkg, workdir, args.source)
    src = extract(archive, workdir / "src")
    out = workdir / f"out-{arch}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    log(f"building {tag} for {arch} ({engine})")
    run_recipe(engine, package, arch, src, out, args.jobs, epoch)

    env_file = out / "build-env.txt"
    build_env = env_file.read_text() if env_file.is_file() else ""
    env_file.unlink(missing_ok=True)
    licenses = sorted(p for p in out.iterdir() if p.is_file() and p.name.lower().startswith(LICENSE_NAMES))
    if not licenses:
        sys.exit(f"recipes/{package}/build.sh: copy the license (LICENSE, COPYING...) to the output dir")

    log("checking the bundles")
    report = check_elf.check([out], arch, features, package)
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    if report.errors:
        sys.exit(f"{len(report.errors)} problem(s): nothing packed")

    release = ROOT / "dist" / "release" / tag
    release.mkdir(parents=True, exist_ok=True)
    root = tag
    bundles = sorted(p for p in out.iterdir() if p.is_dir() and p.suffix == ".lv2")
    objects = sorted(p for b in bundles for p in b.rglob("*.so"))
    src_name = f"{tag}-src{source_suffix(archive.name)}"
    recipe_name = f"{tag}-recipe.tar.xz"
    binary_name = f"{tag}-{arch}.tar.xz"
    info = "\n".join([
        f"package: {package} {version}",
        f"arch: {arch}",
        f"built by: https://github.com/{REPO} (unofficial build, not from the plugin's authors)",
        f"source: {pkg['source']['url']}",
        f"source sha256: {pkg['source']['sha256']}",
        f"source copy: https://github.com/{REPO}/releases/download/{tag}/{src_name}",
        f"recipe: https://github.com/{REPO}/releases/download/{tag}/{recipe_name}",
        f"recipe commit: {recipe_commit(package)}",
        f"build image: {image_digest(engine)}",
        build_env.rstrip(),
        f"date: {datetime.fromtimestamp(epoch, timezone.utc).isoformat()}",
        "",
        "sha256 of the shared objects:",
        *(f"  {sha256_file(p)}  {p.relative_to(out).as_posix()}" for p in objects),
        "",
    ])
    info_file = workdir / "BUILD-INFO.txt"
    info_file.write_text(info)

    members = [(p, f"{root}/{p.name}") for p in bundles + licenses]
    members.append((info_file, f"{root}/BUILD-INFO.txt"))
    binary = release / binary_name
    tar_xz(binary, members, epoch)

    shutil.copyfile(archive, release / src_name)
    recipe_dir = f"{tag}-recipe"
    tar_xz(release / recipe_name,
           [(ROOT / "recipes" / package, f"{recipe_dir}/recipes/{package}")]
           + [(ROOT / f, f"{recipe_dir}/{f}") for f in DRIVER_FILES],
           epoch)

    entry = {
        "package": package,
        "version": version,
        "arch": arch,
        "tag": tag,
        "url": f"https://github.com/{REPO}/releases/download/{tag}/{binary_name}",
        "sha256": sha256_file(binary),
        "size": binary.stat().st_size,
        "format": "tar.xz",
        "root": root,
        "source_sha256": pkg["source"]["sha256"],
        "recipe_commit": recipe_commit(package),
    }
    builds = ROOT / "dist" / "builds"
    builds.mkdir(parents=True, exist_ok=True)
    (builds / f"{package}-{arch}.json").write_text(json.dumps(entry, indent=1) + "\n")
    log(f"{binary.relative_to(ROOT)}: {entry['size']} bytes, {len(bundles)} bundle(s), sha256 {entry['sha256']}")
    log(f"dist/builds/{package}-{arch}.json written")


if __name__ == "__main__":
    main()
