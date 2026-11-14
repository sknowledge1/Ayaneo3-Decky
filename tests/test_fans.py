# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest

import pluginpath  # noqa: F401
from ay3_fans import FanController, FanHardware, QUIET_CURVE, interpolate, target_duty
from ay3_settings import DEFAULT_CONFIG, FanSettings


class FakeSys:

    def __init__(self, root):
        self.root = Path(root)
        dmi = self.root / "class/dmi/id"
        dmi.mkdir(parents=True)
        (dmi / "sys_vendor").write_text("AYANEO\n")
        (dmi / "product_name").write_text("AYANEO 3\n")
        self.fan = self.hwmon("hwmon6", "ayaneo_ec", {"pwm1": "214", "pwm1_enable": "2", "fan1_input": "2400"})
        self.cpu = self.hwmon("hwmon5", "k10temp", {"temp1_label": "Tctl", "temp1_input": "50000"})
        self.hwmon("hwmon4", "amdgpu", {"temp1_label": "edge", "temp1_input": "45000"})

    def hwmon(self, name, driver, files):
        path = self.root / "class/hwmon" / name
        path.mkdir(parents=True)
        (path / "name").write_text(driver + "\n")
        for key, value in files.items():
            (path / key).write_text(value + "\n")
        return path

    def read(self, name):
        return (self.fan / name).read_text().strip()

    def temperature(self, celsius):
        (self.cpu / "temp1_input").write_text(f"{int(celsius * 1000)}\n")


class CurveTests(unittest.TestCase):
    def test_interpolation_and_safety(self):
        self.assertEqual(interpolate(QUIET_CURVE, 30), 0)
        self.assertEqual(interpolate(QUIET_CURVE, 60), 20)
        self.assertEqual(interpolate(QUIET_CURVE, 99), 100)
        manual = {**DEFAULT_CONFIG, "mode": "manual", "percent": 10}
        self.assertEqual(target_duty(manual, 80), 10)
        self.assertEqual(target_duty(manual, 95), 100)
        curve = {**DEFAULT_CONFIG, "mode": "curve"}
        self.assertEqual(target_duty(curve, 40), 40)
        self.assertEqual(target_duty(curve, 60), 60)


class FanControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.sys = FakeSys(base / "sys")
        (base / "settings").mkdir(mode=0o755)
        self.settings = FanSettings(base / "settings")
        self.now = 0.0
        self.controller = self.make()

    def make(self):
        return FanController(FanHardware(self.sys.root), self.settings, clock=lambda: self.now, tick_seconds=3600)

    async def select(self, **changes):
        status = await self.controller.get_status()
        return await self.controller.set_config({**copy.deepcopy(DEFAULT_CONFIG), **changes})

    async def test_starts_in_automatic_and_reports_temperature(self):
        self.sys.fan.joinpath("pwm1_enable").write_text("1\n")
        await self.controller.start()
        status = await self.controller.get_status()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        self.assertEqual((status["api_version"], status["automatic"], self.controller.duty), (5, True, None))
        self.assertEqual(status["telemetry"], {"cpu_c": 50.0, "fan_rpm": 2400})
        self.assertTrue(status["can_configure"])
        self.controller.close()

    async def test_missing_or_bad_rpm_is_reported_as_unknown(self):
        self.sys.fan.joinpath("fan1_input").write_text("garbage\n")
        await self.controller.start()
        self.assertEqual((await self.controller.get_status())["telemetry"], {"cpu_c": 50.0, "fan_rpm": None})
        self.sys.fan.joinpath("fan1_input").unlink()
        self.assertEqual((await self.controller.get_status())["telemetry"]["fan_rpm"], None)
        self.controller.close()

    async def test_failed_handoff_to_firmware_is_reported(self):
        await self.controller.start()
        await self.select(mode="quiet")
        def refuse(final=False):
            raise OSError("write denied")
        self.controller.hardware.automatic = refuse
        await self.select(mode="auto")
        status = await self.controller.get_status()
        self.assertTrue(status["handoff_failed"])
        self.assertIn("could not be returned to automatic", status["fault"])
        del self.controller.hardware.automatic
        await self.controller._tick()
        status = await self.controller.get_status()
        self.assertEqual((status["handoff_failed"], status["fault"], self.sys.read("pwm1_enable")), (False, "", "2"))
        self.controller.close()

    async def test_sensor_fallback_never_claims_automatic_when_handoff_fails(self):
        await self.controller.start()
        await self.select(mode="quiet")
        def refuse(final=False):
            raise OSError("write denied")
        self.controller.hardware.automatic = refuse
        self.sys.cpu.joinpath("temp1_input").write_text("garbage\n")
        for _ in range(4):
            await self.controller._tick()
        status = await self.controller.get_status()
        self.assertTrue(status["handoff_failed"])
        self.assertIn("could not be returned to automatic", status["fault"])
        self.assertNotIn("is on automatic", status["fault"])
        del self.controller.hardware.automatic
        self.controller.close()

    async def test_setting_stays_applying_until_the_hardware_accepts_it(self):
        await self.controller.start()
        real = self.controller.hardware.set_duty
        def refuse_once(duty):
            self.controller.hardware.set_duty = real
            raise OSError("busy")
        self.controller.hardware.set_duty = refuse_once
        status = await self.select(mode="manual", percent=80)
        self.assertEqual((status["ok"], status["applying"], status["fault"]), (True, True, ""))
        await self.controller._tick()
        status = await self.controller.get_status()
        self.assertEqual((status["applying"], self.controller.duty), (False, 80))
        self.controller.close()

    async def test_faults_are_plain_and_raw_errors_go_to_diagnostic(self):
        await self.controller.start()
        def refuse(duty):
            raise OSError(5, "Input/output error", "/sys/class/hwmon/hwmon6/pwm1")
        self.controller.hardware.set_duty = refuse
        await self.select(mode="manual", percent=50)
        for _ in range(3):
            await self.controller._tick()
        status = await self.controller.get_status()
        self.assertIn("could not be controlled", status["fault"])
        self.assertNotIn("/sys/", status["fault"])
        self.assertIn("/sys/class/hwmon/hwmon6/pwm1", status["diagnostic"])
        del self.controller.hardware.set_duty
        self.controller.close()

    async def test_missing_fan_hardware_is_explained_plainly(self):
        import shutil
        shutil.rmtree(self.sys.fan)
        await self.controller.start()
        status = await self.controller.get_status()
        self.assertFalse(status["ok"])
        self.assertTrue(status["error"].startswith("Fan control is not available"))
        self.assertIn("ayaneo_ec", status["diagnostic"])
        self.controller.close()

    async def test_a_successful_save_clears_an_earlier_settings_read_problem(self):
        await self.controller.start()
        self.controller.settings_error = "Fan settings could not be read, so defaults are used."
        await self.select(mode="quiet")
        self.assertEqual((await self.controller.get_status())["settings_error"], "")
        self.controller.close()

    async def test_manual_curve_and_quiet_write_pwm_and_are_saved(self):
        await self.controller.start()
        status = await self.select(mode="manual", percent=50)
        self.assertEqual((self.sys.read("pwm1_enable"), self.sys.read("pwm1")), ("1", "128"))
        self.assertEqual((status["automatic"], self.controller.duty), (False, 50))
        self.assertEqual(self.settings.load()["mode"], "manual")
        await self.select(mode="quiet")
        self.assertEqual(self.settings.load()["mode"], "quiet")
        await self.select(mode="curve")
        self.assertEqual(self.controller.duty, 47)
        self.controller.close()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")

    async def test_duty_falls_gradually_and_safety_overrides(self):
        await self.controller.start()
        await self.select(mode="curve")
        self.sys.temperature(75)
        await self.controller._tick()
        self.assertEqual(self.controller.duty, 85)
        self.sys.temperature(40)
        await self.controller._tick()
        self.assertEqual(self.controller.duty, 83)
        self.sys.temperature(96)
        await self.controller._tick()
        self.assertEqual(self.controller.duty, 100)
        self.controller.close()

    async def test_user_changes_apply_at_once(self):
        await self.controller.start()
        await self.select(mode="manual", percent=100)
        await self.select(mode="manual", percent=20)
        self.assertEqual((self.controller.duty, self.sys.read("pwm1")), (20, "51"))
        await self.select(mode="manual", percent=90)
        await self.select(mode="quiet")
        self.assertEqual(self.controller.duty, 8)
        self.controller.close()

    async def test_sensor_failure_returns_to_automatic_then_recovers(self):
        await self.controller.start()
        await self.select(mode="manual", percent=30)
        (self.sys.cpu / "temp1_input").write_text("garbage\n")
        await self.controller._tick()
        self.assertEqual(self.sys.read("pwm1_enable"), "1")
        await self.controller._tick()
        await self.controller._tick()
        status = await self.controller.get_status()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        self.assertIn("temperature is unavailable", status["fault"])
        self.assertFalse(status["can_configure"])
        self.sys.temperature(55)
        await self.controller._tick()
        self.assertEqual((self.sys.read("pwm1_enable"), self.controller.fault), ("1", ""))
        self.controller.close()

    async def test_repeated_takeovers_stop_fighting(self):
        await self.controller.start()
        await self.select(mode="manual", percent=40)
        for _ in range(6):
            self.now += 1
            self.sys.fan.joinpath("pwm1_enable").write_text("2\n")
            await self.controller._tick()
        status = await self.controller.get_status()
        self.assertIn("Another program", status["fault"])
        self.assertTrue(status["automatic"])
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        await self.controller._tick()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        await self.select(mode="manual", percent=40)
        self.assertEqual(self.sys.read("pwm1_enable"), "1")
        self.controller.close()

    async def test_close_is_synchronous_and_final(self):
        await self.controller.start()
        await self.select(mode="manual", percent=60)
        self.assertEqual(self.sys.read("pwm1_enable"), "1")
        self.controller.close()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        await self.controller._tick()
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        self.controller.close()

    async def test_saved_selection_is_restored_on_start(self):
        self.settings.save({**DEFAULT_CONFIG, "mode": "manual", "percent": 70})
        await self.controller.start()
        self.assertEqual((self.sys.read("pwm1_enable"), self.sys.read("pwm1")), ("1", "178"))
        self.controller.close()

    async def test_automatic_reads_the_sensors_only_when_asked(self):
        controller = FanController(FanHardware(self.sys.root), self.settings, clock=lambda: self.now, tick_seconds=0.01)
        await controller.start()
        reads = []
        real = controller.hardware.temperature
        controller.hardware.temperature = lambda: reads.append(1) or real()
        await asyncio.sleep(0.08)
        self.assertEqual(reads, [])
        self.sys.temperature(61)
        status = await controller.get_status()
        self.assertEqual((status["telemetry"]["cpu_c"], len(reads)), (61.0, 1))
        await controller.set_config({**DEFAULT_CONFIG, "mode": "quiet"})
        self.sys.temperature(75)
        await asyncio.sleep(0.1)
        self.assertEqual(controller.duty, 35)
        controller.close()

    async def test_glitches_in_auto_do_not_count_against_the_next_mode(self):
        await self.controller.start()
        self.sys.cpu.joinpath("temp1_input").write_text("garbage\n")
        for _ in range(4):
            await self.controller.get_status()
        self.sys.temperature(50)
        await self.select(mode="manual", percent=40)
        self.sys.cpu.joinpath("temp1_input").write_text("garbage\n")
        await self.controller._tick()
        self.assertEqual((self.sys.read("pwm1_enable"), self.controller.fault), ("1", ""))
        self.controller.close()

    async def test_invalid_selection_and_wrong_device_are_refused(self):
        await self.controller.start()
        self.assertFalse((await self.controller.set_config({**DEFAULT_CONFIG, "mode": "turbo"}))["ok"])
        self.assertEqual(self.sys.read("pwm1_enable"), "2")
        self.controller.close()
        (self.sys.root / "class/dmi/id/product_name").write_text("AYANEO 2\n")
        other = self.make()
        await other.start()
        self.assertFalse((await other.get_status())["ok"])
        other.close()


if __name__ == "__main__":
    unittest.main()
