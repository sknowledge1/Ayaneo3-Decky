# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pluginpath import ROOT
from ay3_modules import GENERIC, ModuleError, ModuleManager, RuntimeJournal, SysfsModules, check_id


class Clock:
    now = 100.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class MemoryJournal:
    def __init__(self, previous=None):
        self.previous, self.saved = previous, []
        self.closed = threading.Event()
    def acquire(self):
        return self.previous
    def save(self, phase):
        self.saved.append(phase)
    def close(self):
        self.closed.set()


class FakeHardware:
    def __init__(self):
        self.attached, self.powered, self.identity = "both", True, "device-1"
        self.ids = ["0x44", "0x50"]
        self.calls, self.error, self.conflicting = [], "", False
        self.eject_error = self.power_error = None
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.after_eject = lambda: None
        self.snapshot_hook = lambda: None

    def snapshot(self):
        self.snapshot_hook()
        identified = self.attached == "both" and self.powered and not self.error and not self.conflicting
        return {"attached": self.attached, "powered": self.powered,
                "hid": self.identity if identified else None,
                "error": self.error or ("Conflicting module controller" if self.conflicting else ""),
                "plain": self.conflicting and not self.error, "conflict": self.conflicting}

    def check_device(self):
        pass

    def prefer_old_enumeration(self, identity):
        pass

    def eject(self, identity, side, allowed):
        if not allowed():
            raise ModuleError("stopped")
        self.calls.append(("eject", side))
        self.entered.set()
        if not self.release.wait(2):
            raise ModuleError("fixture wait exceeded")
        if self.eject_error:
            raise self.eject_error
        self.after_eject()

    def power(self, enabled, identity, allowed):
        if not allowed() or self.conflicting or (enabled and self.attached != "both") or (not enabled and identity != self.identity):
            raise ModuleError("Power precondition changed")
        self.calls.append(("power", enabled))
        if self.power_error:
            raise self.power_error
        self.powered = enabled


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.io, self.journal, self.clock = FakeHardware(), MemoryJournal(), Clock()
        self.manager = ModuleManager(self.io, self.journal, self.clock)
        await self.manager.poll_once()

    async def asyncTearDown(self):
        self.io.release.set()
        self.manager.close()
        await asyncio.to_thread(self.journal.closed.wait, 2)

    async def finish_pop(self, side="left"):
        accepted = await self.manager.pop(side)
        self.assertTrue(accepted["ok"], accepted)
        await self.manager.operation

    async def test_status_is_a_copy_and_names_no_modules(self):
        status = self.manager.status()
        self.assertEqual((status["api_version"], status["phase"], status["attached"]), (5, "ready", "both"))
        self.assertFalse({"left", "right", "operation_id"} & set(status))
        status["phase"] = "mutated"
        self.assertEqual(self.manager.status()["phase"], "ready")
        self.io.ids[0] = "0x7f"
        await self.manager.poll_once()
        self.assertTrue(self.manager.status()["can_pop"])

    async def test_release_ack_power_order_and_no_replay(self):
        await self.finish_pop("both")
        self.assertEqual(self.io.calls, [("eject", "both"), ("power", False)])
        self.assertEqual(self.journal.saved[-3:], ["ejecting", "acknowledged", "waiting"])
        await self.manager.poll_once()
        self.assertEqual(sum(x[0] == "eject" for x in self.io.calls), 1)

    async def test_all_three_sides_and_duplicate_requests(self):
        for side in ["left", "right", "both"]:
            self.io.attached, self.io.powered = "both", True
            await self.manager.poll_once()
            self.io.release.clear()
            replies = await asyncio.gather(self.manager.pop(side), self.manager.pop(side))
            self.assertEqual([r["ok"] for r in replies], [True, False])
            task = self.manager.operation
            self.io.release.set()
            await task
        self.assertEqual([c[1] for c in self.io.calls if c[0] == "eject"], ["left", "right", "both"])

    async def test_invalid_sides_and_stale_sample_never_write(self):
        for side in [None, True, 1, [], {}, "Left", "both\n", "../eject"]:
            self.assertFalse((await self.manager.pop(side))["ok"])
        self.clock.advance(3.1)
        self.assertFalse((await self.manager.pop("left"))["ok"])
        self.assertFalse(self.io.calls)

    async def test_fresh_preflight_catches_disconnection(self):
        self.io.attached = "right"
        await self.finish_pop()
        self.assertFalse(self.io.calls)
        self.assertIn("changed before the release started", self.manager.status()["error"])

    async def test_failed_ack_preserves_power_and_visible_error(self):
        self.io.eject_error = PermissionError("firmware rejected release")
        await self.finish_pop()
        await self.manager.poll_once()
        self.assertEqual(self.io.calls, [("eject", "left")])
        self.assertTrue(self.io.powered)
        self.assertEqual(self.manager.status()["error"], GENERIC)
        self.assertIn("rejected", self.manager.status()["diagnostic"])

    async def test_late_ack_after_deadline_cannot_cut_power(self):
        self.io.after_eject = lambda: self.clock.advance(36)
        await self.finish_pop()
        self.assertEqual(self.io.calls, [("eject", "left")])
        self.assertIn("did not finish", self.manager.status()["error"])
        self.assertEqual(self.manager.status()["diagnostic"], "")

    async def test_timeout_keeps_busy_until_blocking_write_finishes(self):
        self.manager.EJECT_SECONDS = 0.03
        self.io.release.clear()
        await self.manager.pop("right")
        task = self.manager.operation
        await asyncio.sleep(0.07)
        self.assertTrue(self.manager.status()["busy"])
        self.assertFalse((await self.manager.pop("both"))["ok"])
        self.io.release.set()
        await task
        self.assertEqual(self.io.calls, [("eject", "right")])
        self.assertFalse(self.manager.status()["busy"])

    async def test_unload_during_ack_skips_later_power_cut_and_retains_lock(self):
        self.io.release.clear()
        await self.manager.pop("left")
        self.assertTrue(await asyncio.to_thread(self.io.entered.wait, 1))
        self.manager.close()
        self.assertFalse(self.journal.closed.is_set())
        self.io.release.set()
        self.assertTrue(await asyncio.to_thread(self.journal.closed.wait, 1))
        self.assertEqual(self.io.calls, [("eject", "left")])

    async def test_conflict_and_changed_identity_after_ack_prevent_power_cut(self):
        self.io.after_eject = lambda: setattr(self.io, "identity", "new-device")
        await self.finish_pop()
        self.assertTrue(self.io.powered)
        self.assertEqual(self.io.calls, [("eject", "left")])

    async def test_competing_writer_appearing_during_ack_prevents_power_cut(self):
        self.io.after_eject = lambda: setattr(self.io, "conflicting", True)
        await self.finish_pop()
        self.assertTrue(self.io.powered)
        self.assertEqual(self.io.calls, [("eject", "left")])

    async def test_post_ack_journal_failure_prevents_power_cut(self):
        original = self.journal.save
        def fail_after_ack(phase):
            if phase == "acknowledged":
                raise OSError("journal storage failed")
            original(phase)
        with patch.object(self.journal, "save", side_effect=fail_after_ack):
            await self.finish_pop()
        self.assertTrue(self.io.powered)
        self.assertEqual(self.io.calls, [("eject", "left")])
        self.assertIn("journal storage failed", self.manager.status()["diagnostic"])

    async def test_slow_old_snapshot_cannot_replace_ejecting_state(self):
        entered, release = threading.Event(), threading.Event()
        def hold_poll():
            entered.set()
            if not release.wait(1):
                raise RuntimeError("fixture poll wait exceeded")
        self.io.snapshot_hook = hold_poll
        polling = asyncio.create_task(self.manager.poll_once())
        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
        self.io.release.clear()
        await self.manager.pop("both")
        task = self.manager.operation
        self.io.snapshot_hook = lambda: None
        release.set()
        await polling
        self.assertEqual(self.manager.status()["phase"], "ejecting")
        self.assertFalse(self.manager.status()["can_pop"])
        self.io.release.set()
        await task

    async def test_reconnect_timeout_reports_error_and_then_accepts_late_driver(self):
        self.io.powered = False
        await self.manager.poll_once()
        self.clock.advance(1)
        await self.manager.poll_once()
        self.io.error = "HID not yet present"
        await self.manager.poll_once()
        self.assertEqual(self.manager.status()["phase"], "activating")
        self.clock.advance(16)
        await self.manager.poll_once()
        self.assertEqual(self.manager.status()["phase"], "error")
        self.assertFalse(self.manager.status()["can_pop"])
        self.assertEqual((self.manager.status()["status_error"], self.manager.status()["diagnostic"]), (GENERIC, "HID not yet present"))
        self.io.error = ""
        await self.manager.poll_once()
        self.assertTrue(self.manager.status()["can_pop"])
        self.assertEqual(self.manager.status()["diagnostic"], "")
        self.assertEqual(self.io.calls, [("power", True)])

    async def test_recovery_waits_for_stable_both_and_identifies_new_device(self):
        await self.finish_pop()
        self.io.attached = "right"
        await self.manager.poll_once()
        self.assertEqual((self.manager.status()["attached"], self.manager.status()["powered"]), ("right", False))
        self.io.attached = "both"
        await self.manager.poll_once()
        self.clock.advance(0.5)
        await self.manager.poll_once()
        self.assertFalse(self.io.powered)
        self.io.attached = "right"
        await self.manager.poll_once()
        self.io.attached = "both"
        await self.manager.poll_once()
        self.clock.advance(1)
        await self.manager.poll_once()
        self.assertTrue(self.io.powered)
        self.io.identity, self.io.ids = "device-2", ["0x04", "0x10"]
        await self.manager.poll_once()
        self.assertTrue(self.manager.status()["can_pop"])

    async def test_startup_after_crash_recovers_power_without_replaying_eject(self):
        self.manager.close()
        await asyncio.to_thread(self.journal.closed.wait, 1)
        self.journal = MemoryJournal({"phase": "power_off_pending", "side": "both"})
        self.manager = ModuleManager(self.io, self.journal, self.clock)
        self.io.powered = False
        await self.manager.poll_once()
        self.assertIn("No release command", self.manager.status()["notice"])
        self.clock.advance(1)
        await self.manager.poll_once()
        self.assertEqual(self.io.calls, [("power", True)])

    async def test_power_recovery_has_bounded_retries(self):
        self.io.powered = False
        self.io.power_error = PermissionError("power denied")
        await self.manager.poll_once()
        for _ in range(8):
            self.clock.advance(2)
            await self.manager.poll_once()
        self.assertEqual(len(self.io.calls), 3)
        self.assertIn("did not come back", self.manager.status()["status_error"])

    async def test_conflicts_block_release_and_automatic_power_recovery(self):
        self.io.conflicting, self.io.powered = True, False
        for _ in range(3):
            self.clock.advance(2)
            await self.manager.poll_once()
        self.assertFalse(self.io.calls)
        self.assertFalse((await self.manager.pop("left"))["ok"])

    async def test_io_and_journal_errors_fail_closed(self):
        with patch.object(self.io, "snapshot", side_effect=OSError("driver absent")):
            await self.manager.poll_once()
        self.assertIsNone(self.manager.status()["powered"])
        self.assertFalse((await self.manager.pop("both"))["ok"])
        self.manager.initialized = False
        with patch.object(self.journal, "acquire", side_effect=ValueError("corrupt record")):
            await self.manager.poll_once()
        self.assertFalse(self.io.calls)
        self.assertIn("corrupt", self.manager.status()["diagnostic"])

    async def test_monitor_runs_without_any_panel_calls(self):
        self.io.powered = False
        self.manager.STABLE_SECONDS = 0
        self.manager.RECOVERY_SECONDS = self.manager.POLL_SECONDS = 0.01
        await self.manager.start()
        for _ in range(100):
            if self.io.powered:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.io.powered)
        self.assertEqual(self.io.calls, [("power", True)])


class IdTests(unittest.TestCase):
    def test_malformed_values_are_not_missing_modules(self):
        check_id("0x44")
        for raw in [None, 0, "", "44", "0x444", "0x-1", "0xgg"]:
            with self.assertRaises(ModuleError):
                check_id(raw)


@unittest.skipUnless(os.name == "posix", "Linux sysfs/open semantics required")
class SysfsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.sys, self.proc, self.home = self.base / "sys", self.base / "proc", self.base / "home"
        self.proc.mkdir()
        self.ec = self.sys / "devices/platform/ayaneo-ec"
        self.driver = self.sys / "bus/hid/drivers/hid-ayaneo"
        self.dmi = self.sys / "class/dmi/id"
        for path in [self.ec, self.driver, self.dmi, self.home]:
            path.mkdir(parents=True, exist_ok=True)
        (self.dmi / "sys_vendor").write_text("AYANEO\n")
        (self.dmi / "product_name").write_text("AYANEO 3\n")
        (self.ec / "controller_modules").write_text("both\n")
        (self.ec / "controller_power").write_text("1\n")
        self.device = self.add_device("0004")
        self.io = SysfsModules(self.sys, self.proc, self.home)
    def tearDown(self):
        self.temp.cleanup()
    def add_device(self, index):
        device = self.sys / "devices/usb" / ("0003:1C4F:0002." + index)
        device.mkdir(parents=True)
        (device / "driver").symlink_to(self.driver, target_is_directory=True)
        (self.driver / device.name).symlink_to(device, target_is_directory=True)
        for attr, text in {"uevent": "HID_ID=0003:00001C4F:00000002\n", "module_left": "0x44\n", "module_right": "0x50\n", "eject": ""}.items():
            (device / attr).write_text(text)
        return device
    def test_snapshot_and_actual_fixture_write_order(self):
        result = self.io.snapshot()
        self.assertEqual((Path(result["hid"]).name, result["error"]), (self.device.name, ""))
        self.io.eject(result["hid"], "left", lambda: True)
        self.assertEqual((self.device / "eject").read_text(), "left")
        self.io.power(False, result["hid"], lambda: True)
        self.assertEqual((self.ec / "controller_power").read_text().strip(), "0")
    def test_composite_hid_functions_do_not_mask_module_interface(self):
        for index in ("0001", "0002"):
            device = self.add_device(index)
            for attribute in ("module_left", "module_right", "eject"):
                (device / attribute).unlink()
        result = self.io.snapshot()
        self.assertEqual(result["error"], "")
        self.assertEqual(result["hid"], str(self.device))
        self.io.eject(result["hid"], "left", lambda: True)
        self.assertEqual((self.device / "eject").read_text(), "left")
    def test_incomplete_module_interface_still_blocks_discovery(self):
        device = self.add_device("0005")
        (device / "eject").unlink()
        self.assertIn("missing the required", self.io.snapshot()["error"])
        with self.assertRaises(ModuleError):
            self.io.eject(str(self.device), "left", lambda: True)
        self.assertEqual((self.device / "eject").read_text(), "")
    def test_composite_without_module_controls_is_unavailable(self):
        for attribute in ("module_left", "module_right", "eject"):
            (self.device / attribute).unlink()
        self.assertIn("required", self.io.snapshot()["error"])
        self.assertIsNone(self.io.snapshot()["hid"])
    def test_missing_multiple_wrong_identity_and_malformed_ids(self):
        (self.device / "module_left").write_text("bogus")
        self.assertIn("invalid module ID", self.io.snapshot()["error"])
        (self.device / "module_left").write_text("0x44")
        self.add_device("0005")
        self.assertIn("More than one", self.io.snapshot()["error"])
        (self.dmi / "product_name").write_text("AYANEO 2")
        with self.assertRaises(ModuleError):
            self.io.check_device()
    def test_hotplug_changes_identity_and_aborts_old_power_cut(self):
        identity = self.io.discover()
        (self.driver / self.device.name).unlink()
        self.assertIn("required", self.io.snapshot()["error"])
        self.add_device("0008")
        with self.assertRaises(ModuleError):
            self.io.power(False, identity, lambda: True)
        self.assertTrue(self.io.ec_state()[1])
    def test_symlinked_power_attribute_and_escaped_hid_are_rejected(self):
        victim = self.base / "victim"
        victim.write_text("protected")
        (self.ec / "controller_power").unlink()
        (self.ec / "controller_power").symlink_to(victim)
        with self.assertRaises(OSError):
            self.io._write(self.ec / "controller_power", "0", lambda: True)
        self.assertEqual(victim.read_text(), "protected")
        (self.driver / self.device.name).unlink()
        (self.driver / self.device.name).symlink_to(self.home)
        with self.assertRaises(ModuleError):
            self.io.discover()
    def test_malformed_ec_and_stopped_write_fail_closed(self):
        (self.ec / "controller_power").write_text("unknown")
        with self.assertRaises(ModuleError):
            self.io.ec_state()
        (self.ec / "controller_power").write_text("1")
        with self.assertRaises(ModuleError):
            self.io.eject(self.io.discover(), "both", lambda: False)
        self.assertEqual((self.device / "eject").read_text(), "")
    def test_controller_port_prefers_old_enumeration(self):
        port = self.sys / "devices/usb1/1-0:1.0/usb1-port1"
        port.mkdir(parents=True)
        (port / "quirks").write_text("00000000")
        usb = self.sys / "devices/usb1/1-1"
        (usb / "1-1:1.2").mkdir(parents=True)
        (usb / "idVendor").write_text("1c4f")
        (usb / "idProduct").write_text("0002")
        (usb / "port").symlink_to(port, target_is_directory=True)
        hid = usb / "1-1:1.2/0003:1C4F:0002.0009"
        hid.mkdir()
        self.io.prefer_old_enumeration(str(hid))
        self.assertEqual((port / "quirks").read_text(), "1")
        (usb / "idProduct").write_text("1234")
        (port / "quirks").write_text("00000000")
        self.io.prefer_old_enumeration(str(hid))
        self.assertEqual((port / "quirks").read_text(), "00000000")
        self.io.prefer_old_enumeration(str(self.device))
        self.assertEqual((port / "quirks").read_text(), "00000000")
    def test_competing_ogui_and_hhd_detected_without_running_commands(self):
        plugin = self.home / ".local/share/opengamepadui/plugins"
        plugin.mkdir(parents=True)
        (plugin / "ayaneo-modules.zip").touch()
        self.assertTrue(self.io.snapshot()["conflict"])
        (plugin / "ayaneo-modules.zip").unlink()
        process = self.proc / "55"
        process.mkdir()
        (process / "comm").write_text("python3")
        (process / "cmdline").write_bytes(b"python3\0-m\0hhd\0")
        self.assertIn("Handheld Daemon", self.io.conflict())

    def test_status_polls_reuse_the_process_scan_but_writes_always_scan(self):
        self.assertFalse(self.io.snapshot()["conflict"])
        process = self.proc / "55"
        process.mkdir()
        (process / "comm").write_text("hhd")
        (process / "cmdline").write_bytes(b"hhd\0")
        self.assertFalse(self.io.snapshot()["conflict"])
        with self.assertRaises(ModuleError):
            self.io.eject(self.io.discover(), "left", lambda: True)
        self.assertTrue(self.io.snapshot()["conflict"])
        self.io.CONFLICT_SECONDS = 0
        (process / "comm").write_text("bash")
        (process / "cmdline").write_bytes(b"bash\0")
        self.assertFalse(self.io.snapshot()["conflict"])


@unittest.skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0, "Root in isolated Linux container required")
class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "runtime"
        self.journal = RuntimeJournal(self.directory, "test-boot")
    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()
    def test_atomic_progress_exclusive_ownership_and_boot_scope(self):
        self.assertIsNone(self.journal.acquire())
        other = RuntimeJournal(self.directory, "test-boot")
        with self.assertRaises(BlockingIOError):
            other.acquire()
        self.journal.save("acknowledged")
        self.assertEqual(self.journal.acquire()["phase"], "acknowledged")
        self.journal.close()
        other.boot_id = "next-boot"
        self.assertIsNone(other.acquire())
        other.close()
    def test_corrupt_record_and_insecure_files_are_not_overwritten(self):
        self.journal.acquire()
        self.journal.save("waiting")
        record = self.directory / "state.json"
        record.write_text("{broken")
        with self.assertRaises(ValueError):
            self.journal.acquire()
        self.assertEqual(record.read_text(), "{broken")
        record.chmod(0o666)
        with self.assertRaises(ModuleError):
            self.journal.acquire()
    def test_failed_atomic_replace_preserves_previous_record(self):
        self.journal.acquire()
        self.journal.save("waiting")
        before = (self.directory / "state.json").read_bytes()
        with patch("ay3_common.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.journal.save("ready")
        self.assertEqual((self.directory / "state.json").read_bytes(), before)
        self.assertEqual([path.name for path in self.directory.iterdir() if path.name.startswith(".")], [])

    def test_invalid_schema_is_preserved_and_symlink_is_not_followed(self):
        self.journal.acquire()
        self.journal.save("ready")
        record = self.directory / "state.json"
        valid = json.loads(record.read_text())
        for change in [{"version": True}, {"phase": {}}, {"boot_id": None}]:
            content = json.dumps({**valid, **change})
            record.write_text(content)
            with self.assertRaises(ModuleError):
                self.journal.acquire()
            self.assertEqual(record.read_text(), content)
        record.unlink()
        outside = self.directory.parent / "outside"
        outside.write_text(json.dumps(valid))
        record.symlink_to(outside)
        with self.assertRaises(OSError):
            self.journal.acquire()
        self.assertEqual(json.loads(outside.read_text()), valid)


if __name__ == "__main__":
    unittest.main()
