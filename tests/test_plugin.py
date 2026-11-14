# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import unittest
from unittest.mock import patch

from pluginpath import ROOT


def load_main():
    spec = importlib.util.spec_from_file_location("plugin_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MessageTests(unittest.TestCase):
    def test_startup_failures_are_plain_with_details_kept_separately(self):
        main = load_main()
        failed = main.unavailable("Fan control", OSError(2, "No such file or directory", "/sys/class/hwmon/hwmon6/pwm1"))
        self.assertEqual(failed["error"], "Fan control is not available. Details are under Help & details.")
        self.assertIn("/sys/class/hwmon/hwmon6/pwm1", failed["diagnostic"])
        self.assertNotIn("starting", failed)
        starting = main.unavailable("Joystick lighting")
        self.assertEqual((starting["error"], starting["starting"]), ("Joystick lighting is starting.", True))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_module_failure_does_not_disable_fan_or_lighting(self):
        plugin = load_main()
        class Controller:
            async def start(self):
                pass

            async def get_status(self):
                return {"ok": True}

            def close(self):
                pass

        def broken():
            raise RuntimeError("module init failed")
        instance = plugin.Plugin()
        self.assertTrue((await instance.get_status())["starting"])
        with patch.dict(plugin.SUBSYSTEMS, {"modules": ("Magic Modules", broken), "fans": ("Fan control", Controller),
                                            "leds": ("Joystick lighting", Controller)}):
            await instance._main()
        failed = await instance.get_modules_status()
        self.assertEqual((failed["ok"], failed["diagnostic"]), (False, "module init failed"))
        self.assertNotIn("starting", failed)
        self.assertTrue((await instance.get_status())["ok"])
        self.assertTrue((await instance.get_led_status())["ok"])
        with self.assertRaises(StopIteration):
            instance._unload().send(None)


if __name__ == "__main__":
    unittest.main()
