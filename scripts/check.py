#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest

root = Path(__file__).resolve().parents[1]
os.chdir(root)
if sys.platform != "linux" or os.geteuid() != 0:
    raise SystemExit("Run as UID 0 inside the isolated rootless Linux container.")
if {path.name for path in Path("/sys").iterdir()} - {"fs"}:
    raise SystemExit("Mask /sys with a read-only tmpfs before running this gate.")
if Path("/sys/fs").exists() and {path.name for path in Path("/sys/fs").iterdir()} - {"cgroup"}:
    raise SystemExit("Only the container cgroup may remain under masked sysfs.")

suite = unittest.defaultTestLoader.discover(str(root / "tests"))
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped:
    raise SystemExit("Every Python test must pass without skips on Linux.")

def run(*args):
    subprocess.run(args, check=True, cwd=root)

help_text = subprocess.check_output(["node", "--help"], text=True)
isolation = "--test-isolation=none" if "  --test-isolation" in help_text else "--experimental-test-isolation=none"
run("node", "--test", isolation, *[str(path) for path in sorted((root / "tests").glob("test_*.mjs"))])
run("node", "scripts/build-frontend.mjs")
run("node", "--check", "dist/index.js")
run(sys.executable, "-B", "scripts/build-decky-package.py")
run(sys.executable, "-B", "scripts/verify-decky-package.py")
archive = root / "dist" / "Ayaneo3-Decky.zip"
first = archive.read_bytes()
run("node", "scripts/build-frontend.mjs")
run(sys.executable, "-B", "scripts/build-decky-package.py")
assert archive.read_bytes() == first, "Package build is not reproducible"
report = {"result": "passed", "python_tests": result.testsRun, "python_skips": len(result.skipped),
          "python": platform.python_version(), "node": subprocess.check_output(["node", "--version"], text=True).strip(),
          "zip_sha256": hashlib.sha256(first).hexdigest(), "zip_bytes": len(first),
          "reproducible_zip": True, "sysfs_masked": True, "physical_validation": "not run"}
(root / "dist/checks.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
