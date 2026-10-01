#!/usr/bin/env python3
"""ANK release helper - bumps module.prop/releases.json and stamps release metadata.

Usage:
  python tools/gen-update.py                      # show current version info
  python tools/gen-update.py --bump               # increment versionCode (module.prop + releases.json)
  python tools/gen-update.py --set-version "..."  # set version string in both files
  python tools/gen-update.py --changelog "..."    # set releases.json changelog
  python tools/gen-update.py --tag ank-testing    # set releases.json zipUrl for a GitHub release tag
  python tools/gen-update.py --sha256             # stamp sha256 of dist/ank-magisk.zip into releases.json
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PROP = os.path.join(ROOT, "magisk-module", "module.prop")
RELEASES = os.path.join(ROOT, "releases.json")
ZIP_PATH = os.path.join(ROOT, "dist", "ank-magisk.zip")


def read_prop():
    entries = []
    with open(MODULE_PROP, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                entries.append([k, v])
            else:
                entries.append(None)
    return entries


def write_prop(entries):
    lines = [f"{e[0]}={e[1]}" if e else "" for e in entries]
    with open(MODULE_PROP, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def prop_get(entries, key):
    for e in entries:
        if e and e[0] == key:
            return e[1]
    return None


def prop_set(entries, key, value):
    for e in entries:
        if e and e[0] == key:
            e[1] = str(value)
            return
    entries.append([key, str(value)])


def load_releases():
    with open(RELEASES, "r", encoding="utf-8") as f:
        return json.load(f)


def save_releases(data):
    with open(RELEASES, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
        f.write("\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="ANK release helper")
    ap.add_argument("--bump", action="store_true",
                    help="increment versionCode in module.prop and releases.json")
    ap.add_argument("--set-version", metavar="VERSION",
                    help="set version string in module.prop and releases.json")
    ap.add_argument("--changelog", metavar="TEXT",
                    help="set releases.json changelog")
    ap.add_argument("--tag", metavar="TAG",
                    help="set releases.json zipUrl for a GitHub release tag")
    ap.add_argument("--sha256", action="store_true",
                    help="stamp sha256 of dist/ank-magisk.zip into releases.json")
    args = ap.parse_args()

    if not any([args.bump, args.set_version, args.changelog, args.tag, args.sha256]):
        prop = read_prop()
        rel = load_releases()
        print(f"module.prop   : version={prop_get(prop, 'version')} "
              f"versionCode={prop_get(prop, 'versionCode')}")
        print(f"releases.json : version={rel.get('version')} "
              f"versionCode={rel.get('versionCode')}")
        print(f"releases.json : sha256={rel.get('sha256', '(not set)')}")
        return

    prop = read_prop()
    rel = load_releases()

    if args.bump:
        try:
            vc = int(prop_get(prop, "versionCode") or "0")
        except ValueError:
            vc = 0
        vc += 1
        prop_set(prop, "versionCode", vc)
        rel["versionCode"] = vc
        print(f"versionCode -> {vc}")

    if args.set_version:
        prop_set(prop, "version", args.set_version)
        rel["version"] = args.set_version
        print(f"version -> {args.set_version}")

    if args.changelog is not None:
        rel["changelog"] = args.changelog
        print("changelog updated")

    if args.tag:
        rel["zipUrl"] = (f"https://github.com/andrebarretoit/ank/releases/"
                         f"download/{args.tag}/ank-magisk.zip")
        print(f"zipUrl -> {rel['zipUrl']}")

    if args.sha256:
        if not os.path.isfile(ZIP_PATH):
            sys.exit(f"ERROR: {ZIP_PATH} not found - run python build_zip.py first")
        rel["sha256"] = sha256_file(ZIP_PATH)
        print(f"sha256 -> {rel['sha256']}")

    write_prop(prop)
    save_releases(rel)
    print("wrote magisk-module/module.prop and releases.json")


if __name__ == "__main__":
    main()
