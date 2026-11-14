#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(message)


package = json.loads((root / "package.json").read_text())
version = package["version"]
tracked = sorted(name for name in subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0") if name)

require(f"docs/releases/{version}.md" in tracked, "Release notes are not tracked")
require(f"\n## {version} " in (root / "CHANGELOG.md").read_text(encoding="utf-8"), "CHANGELOG has no entry for this version")

prefix = f"Ayaneo3-Decky-{version}-source/"
with tarfile.open(root / "dist" / f"Ayaneo3-Decky-{version}-source.tar.gz", "r:gz") as archive:
    members = archive.getmembers()
    require(sorted(member.name for member in members) == [prefix + name for name in tracked], "Source archive does not match tracked files")
    for member in members:
        require(member.isfile() and member.mode == 0o644 and member.mtime == 0, f"Unexpected source member: {member.name}")
        require(archive.extractfile(member).read() == (root / member.name[len(prefix):]).read_bytes(), f"Outdated source: {member.name}")

with zipfile.ZipFile(root / "dist" / "Ayaneo3-Decky.zip") as archive:
    require(sorted(archive.namelist()) == sorted("ayaneo3-decky/" + name for name in package["files"]), "Unexpected plugin ZIP members")
    for name in package["files"]:
        require(name == "dist/index.js" or name in tracked, f"Plugin file is not tracked: {name}")
        require(archive.read("ayaneo3-decky/" + name) == (root / name).read_bytes(), f"Outdated plugin file: {name}")

for line in (root / "dist/SHA256SUMS").read_text().splitlines():
    expected, name = line.split("  ", 1)
    require("/" not in name and "\\" not in name, "Unsafe checksum path")
    require(hashlib.sha256((root / "dist" / name).read_bytes()).hexdigest() == expected, f"Checksum differs: {name}")

print(json.dumps({"result": "passed", "version": version, "source_files": len(tracked), "zip_members": len(package["files"])}))
