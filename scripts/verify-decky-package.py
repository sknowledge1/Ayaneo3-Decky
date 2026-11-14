#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]

package = json.loads((root / "package.json").read_text())
version, expected = package["version"], set(package["files"])
path = root / "dist" / "Ayaneo3-Decky.zip"
with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temporary:
    assert archive.testzip() is None, "ZIP CRC failure"
    names = archive.namelist()
    assert len(names) == len(set(names)) == len(expected), "Duplicate or missing archive member"
    assert set(names) == {"ayaneo3-decky/" + name for name in expected}, "Unexpected archive member"
    for item in archive.infolist():
        assert item.external_attr >> 16 == 0o100644, "Unexpected permissions or symlink"
        relative = item.filename.removeprefix("ayaneo3-decky/")
        assert archive.read(item) == (root / relative).read_bytes(), f"Outdated payload: {relative}"
    manifest = json.loads(archive.read("ayaneo3-decky/plugin.json"))
    metadata = json.loads(archive.read("ayaneo3-decky/package.json"))
    assert manifest["name"] == "Ayaneo 3 Decky" and manifest["flags"] == ["root"]
    assert metadata["name"] == "ayaneo3-decky" and metadata["version"] == version
    assert metadata["license"] == "GPL-3.0-or-later"
    # Without it Decky runs dist/index.js as a plain script and the panel fails with "Unexpected token 'export'".
    assert metadata.get("type") == "module", 'package.json must keep "type": "module"'
    assert "Version 3" in archive.read("ayaneo3-decky/LICENSE").decode()
    assert not any("LICENSE." in name or "/vendor/" in name for name in names), "Only the GPL licence is shipped"
    frontend = archive.read("ayaneo3-decky/dist/index.js").decode()
    for marker in ['title: "Fan"', 'title: "Joystick Lighting"', 'title: "Magic Modules"', "Pop both modules", "deckyLoaderAPIInit",
                   *(f'callable("{name}")' for name in ("get_status", "set_config", "get_led_status", "set_led_config", "get_modules_status", "pop_module"))]:
        assert marker in frontend, f"Missing frontend feature: {marker}"
    assert "@decky/api" not in frontend
    archive.extractall(temporary)
    plugin = Path(temporary) / "ayaneo3-decky"
    code = """
import importlib.util, pathlib, sys
plugin = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(plugin / 'py_modules'))
spec = importlib.util.spec_from_file_location('packaged_plugin', plugin / 'main.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
instance = module.Plugin()
assert not hasattr(instance, '_ready')
assert set(module.SUBSYSTEMS) == {'modules', 'fans', 'leds'}
assert all(callable(getattr(instance, name)) for name in
           ('get_modules_status', 'pop_module', 'get_status', 'set_config', 'get_led_status', 'set_led_config'))
print('Packaged backend import: passed (hardware lifecycle not started)')
"""
    subprocess.run([sys.executable, "-I", "-B", "-c", code, str(plugin)], check=True)
print(json.dumps({"result": "passed", "members": len(expected), "version": version,
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
