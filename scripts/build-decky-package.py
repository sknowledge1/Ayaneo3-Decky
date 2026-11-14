#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
metadata = json.loads((root / "package.json").read_text())
output = root / "dist"
output.mkdir(exist_ok=True)
archive_path = output / "Ayaneo3-Decky.zip"
with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for relative in metadata["files"]:
        info = zipfile.ZipInfo("ayaneo3-decky/" + relative, (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (root / relative).read_bytes())
print(json.dumps({"file": str(archive_path), "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()}))
