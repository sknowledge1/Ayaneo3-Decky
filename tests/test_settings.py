# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pluginpath  # noqa: F401
from ay3_settings import FanSettings, DEFAULT_CONFIG


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = FanSettings(self.root)
        self.path = self.root / "fan-settings.json"

    def test_reads_have_no_defaults_or_files_to_apply(self):
        self.assertIsNone(self.store.load())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_atomic_saved_selection_preserves_custom_values(self):
        config = {**copy.deepcopy(DEFAULT_CONFIG), "mode": "quiet", "percent": 43, "curve": [20, 35, 60, 85, 100]}
        self.store.save(config)
        self.assertEqual(self.store.load(), config)
        self.assertEqual(json.loads(self.path.read_text()), {"version": 1, "config": config})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_replace_failure_preserves_old_bytes(self):
        self.store.save(DEFAULT_CONFIG)
        original = self.path.read_bytes()
        with patch("ay3_settings.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError): self.store.save(DEFAULT_CONFIG)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["fan-settings.json", "fan-settings.lock"])

    def test_corrupt_unsupported_or_invalid_state_is_preserved(self):
        for index, content in enumerate(["{", "null", "[]", "{}", '{"version":2}', "x" * 16385]):
            self.path.write_text(content)
            self.path.chmod(0o600)
            with self.assertRaises(ValueError): self.store.load()
            with self.assertRaises(ValueError): self.store.save(DEFAULT_CONFIG)
            self.assertEqual(self.path.read_text(), content)

    def test_symlinks_insecure_permissions_and_nonregular_files_are_rejected(self):
        target = self.root / "target"
        target.write_text("unchanged")
        self.path.symlink_to(target)
        with self.assertRaises(OSError): self.store.load()
        with self.assertRaises(OSError): self.store.save(DEFAULT_CONFIG)
        self.assertEqual(target.read_text(), "unchanged")
        self.path.unlink()
        self.store.save(DEFAULT_CONFIG)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): self.store.load()
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(ValueError): self.store.load()

    def test_symlinked_directory_and_busy_lock_cannot_write(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): FanSettings(alias).save(DEFAULT_CONFIG)
        with patch("ay3_settings.fcntl.flock", side_effect=BlockingIOError()):
            with self.assertRaises(BlockingIOError): self.store.save(DEFAULT_CONFIG)
        self.assertFalse(self.path.exists())

    @unittest.skipUnless(os.geteuid() == 0, "requires root to reproduce Decky chown")
    def test_decky_host_owned_settings_and_lock_are_supported(self):
        self.store.save(DEFAULT_CONFIG)
        for path in (self.root, self.path, self.root / "fan-settings.lock"):
            os.chown(path, 1000, 1000)
        self.assertEqual(self.store.load(), DEFAULT_CONFIG)
        self.store.save({**DEFAULT_CONFIG, "percent": 65})
        os.chown(self.path, 1000, 1000)
        self.store.save(DEFAULT_CONFIG)
        os.chown(self.path, 1001, 1001)
        with self.assertRaises(ValueError): self.store.load()

    def test_unknown_fields_are_rejected_and_the_file_preserved(self):
        self.store.save(DEFAULT_CONFIG)
        data = json.loads(self.path.read_text())
        self.assertEqual(set(data), {"version", "config"})
        for changed in ({**data, "unknown": 1}, {**data, "config": {**data["config"], "extra": 1}}):
            content = json.dumps(changed)
            self.path.write_text(content)
            with self.assertRaises(ValueError): self.store.load()
            self.assertEqual(self.path.read_text(), content)


if __name__ == "__main__": unittest.main()
