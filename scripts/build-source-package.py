#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
version = json.loads((root / "package.json").read_text())["version"]
files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
files = sorted(path for path in files if path)
if not files:
    raise SystemExit("Stage the candidate source before packaging it.")
output = root / "dist"
output.mkdir(exist_ok=True)
source = output / f"Ayaneo3-Decky-{version}-source.tar.gz"
prefix = f"Ayaneo3-Decky-{version}-source/"
with source.open("wb") as destination, gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as compressed:
    with tarfile.open(fileobj=compressed, mode="w") as archive:
        for relative in files:
            path = root / relative
            if not path.is_file() or path.is_symlink():
                raise SystemExit(f"Unsupported source member: {relative}")
            body = path.read_bytes()
            info = tarfile.TarInfo(prefix + relative)
            info.size, info.mode, info.mtime = len(body), 0o644, 0
            archive.addfile(info, io.BytesIO(body))
artifacts = [output / "Ayaneo3-Decky.zip", source]
checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts)
(output / "SHA256SUMS").write_text(checksums)
print(json.dumps({"source": str(source), "members": len(files), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}))
