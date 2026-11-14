# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import tempfile
import unittest

import pluginpath  # noqa: F401
from ay3_lighting import LedController, LedHardware
from ay3_settings import LedSettings

SOLID = {"effect": "solid", "color": [255, 0, 0], "brightness": 50}


class FakeRings:

    def __init__(self, root):
        self.root = Path(root)
        dmi = self.root / "class/dmi/id"
        dmi.mkdir(parents=True)
        (dmi / "sys_vendor").write_text("AYANEO\n")
        (dmi / "product_name").write_text("AYANEO 3\n")
        self.driver = self.root / "bus/hid/drivers/hid-ayaneo"
        self.driver.mkdir(parents=True)
        (self.root / "class/leds").mkdir(parents=True)
        self.index = 2
        self.plug()

    def plug(self):
        self.index += 1
        device = self.root / f"devices/0003:1C4F:0002.{self.index:04X}"
        device.mkdir(parents=True)
        (device / "driver").symlink_to(self.driver, target_is_directory=True)
        led = device / f"leds/0003:1C4F:0002.{self.index:04X}:rgb:joystick_rings"
        led.mkdir(parents=True)
        (led / "device").symlink_to(device, target_is_directory=True)
        for name, value in {"brightness": "0", "max_brightness": "255", "effect": "monocolor",
                            "effect_index": "monocolor breathe rainbow", "multi_intensity": "255 255 255"}.items():
            (led / name).write_text(value + "\n")
        self.led = self.root / "class/leds" / led.name
        self.led.symlink_to(led, target_is_directory=True)

    def unplug(self):
        self.led.unlink()

    def read(self, name):
        return (self.led / name).read_text().strip()


class LedControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.rings = FakeRings(base / "sys")
        (base / "settings").mkdir(mode=0o755)
        self.settings = LedSettings(base / "settings")
        self.now = 0.0
        self.controller = self.make()

    def make(self):
        return LedController(LedHardware(self.rings.root), self.settings, clock=lambda: self.now, tick_seconds=3600)

    async def select(self, config):
        status = await self.controller.get_status()
        return await self.controller.set_config(config)

    async def test_first_use_writes_nothing(self):
        await self.controller.start()
        status = await self.controller.get_status()
        self.assertEqual((status["api_version"], status["status"], status["can_configure"]), (5, "unconfigured", True))
        self.assertEqual((self.rings.read("brightness"), self.rings.read("multi_intensity")), ("0", "255 255 255"))
        self.controller.close()

    async def test_effects_map_to_the_driver_and_are_saved(self):
        await self.controller.start()
        status = await self.select(SOLID)
        self.assertEqual(status["status"], "applied")
        self.assertEqual([self.rings.read(n) for n in ("effect", "multi_intensity", "brightness")], ["monocolor", "255 0 0", "128"])
        await self.select({**SOLID, "effect": "breathing"})
        self.assertEqual(self.rings.read("effect"), "breathe")
        await self.select({**SOLID, "effect": "cycle"})
        self.assertEqual(self.rings.read("effect"), "rainbow")
        await self.select({**SOLID, "effect": "off"})
        self.assertEqual((self.rings.read("brightness"), self.rings.read("effect")), ("0", "rainbow"))
        self.assertEqual(self.settings.load()["effect"], "off")
        self.controller.close()

    async def test_reconnected_rings_get_the_saved_selection_again(self):
        await self.controller.start()
        await self.select(SOLID)
        self.rings.unplug()
        await self.controller._tick()
        status = await self.controller.get_status()
        self.assertEqual((status["status"], status["can_configure"]), ("unavailable", False))
        self.rings.plug()
        await self.controller._tick()
        self.assertEqual((self.rings.read("multi_intensity"), self.rings.read("brightness")), ("255 0 0", "128"))
        self.assertEqual((await self.controller.get_status())["status"], "applied")
        self.controller.close()

    async def test_save_failure_only_claims_applied_when_it_was(self):
        await self.controller.start()
        def refuse(config):
            raise OSError("read-only file system")
        self.settings.save = refuse
        status = await self.select(SOLID)
        self.assertEqual(status["save_error"], "Applied, but not saved for the next start.")
        self.rings.unplug()
        await self.controller._tick()
        status = await self.select({**SOLID, "effect": "breathing"})
        self.assertEqual((status["status"], status["save_error"]), ("unavailable", "Not saved for the next start."))
        self.controller.close()

    async def test_a_save_failure_is_not_hidden_by_an_earlier_settings_warning(self):
        await self.controller.start()
        self.controller.settings_error = "Saved lighting settings could not be read. Choose an effect to set the rings."
        def refuse(config):
            raise OSError("read-only file system")
        self.settings.save = refuse
        status = await self.select(SOLID)
        self.assertEqual((status["fault"], status["save_error"]), ("", "Applied, but not saved for the next start."))
        self.controller.close()

    async def test_saved_selection_applies_at_start(self):
        self.settings.save(SOLID)
        await self.controller.start()
        self.assertEqual(self.rings.read("multi_intensity"), "255 0 0")
        self.controller.close()

    async def test_repeated_outside_changes_stop_reapplying(self):
        await self.controller.start()
        await self.select(SOLID)
        for _ in range(6):
            self.now += 1
            (self.rings.led / "multi_intensity").write_text("0 0 255\n")
            await self.controller._tick()
        status = await self.controller.get_status()
        self.assertEqual(status["status"], "failed")
        self.assertIn("Another program", status["fault"])
        self.assertEqual(self.rings.read("multi_intensity"), "0 0 255")
        await self.select(SOLID)
        self.assertEqual(self.rings.read("multi_intensity"), "255 0 0")
        self.controller.close()

    async def test_invalid_selection_and_wrong_device_are_refused(self):
        await self.controller.start()
        self.assertFalse((await self.controller.set_config({**SOLID, "effect": "strobe"}))["ok"])
        self.assertEqual(self.rings.read("brightness"), "0")
        self.controller.close()
        (self.rings.root / "class/dmi/id/product_name").write_text("AYANEO 2\n")
        with self.assertRaises(ValueError):  # main.py reports it as "not available".
            await self.make().start()

    async def test_a_refused_setting_is_reported_as_not_applied(self):
        await self.controller.start()
        def refuse(led, config):
            raise OSError("write denied")
        self.controller.hardware.apply = refuse
        reply = await self.select(SOLID)
        self.assertEqual((reply["ok"], reply["error"], reply["state"]["status"]), (False, "Lighting could not be applied.", "failed"))
        self.assertEqual(self.settings.load(), SOLID)
        self.controller.close()


if __name__ == "__main__":
    unittest.main()
