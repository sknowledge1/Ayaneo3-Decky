# SPDX-License-Identifier: GPL-3.0-or-later
from ay3_common import unavailable as not_available
from ay3_fans import FanController
from ay3_lighting import LedController
from ay3_modules import ModuleManager

SUBSYSTEMS = {"modules": ("Magic Modules", ModuleManager), "fans": ("Fan control", FanController),
              "leds": ("Joystick lighting", LedController)}


def unavailable(label, error=None):
    if error is None:
        return {"ok": False, "starting": True, "error": f"{label} is starting.", "diagnostic": ""}
    return {"ok": False, "error": not_available(label), "diagnostic": str(error)}


class Plugin:
    async def _main(self):
        self._ready, self._failed = {}, {}
        for name, (_, factory) in SUBSYSTEMS.items():
            try:
                controller = factory()
                await controller.start()
                self._ready[name] = controller
            except Exception as error:
                self._failed[name] = error

    async def _unload(self):
        # Must not await: Decky stops this event loop at the first await and kills the plugin 5 s later.
        ready = getattr(self, "_ready", {})
        for name in ("fans", "leds", "modules"):
            if name in ready:
                ready[name].close()

    async def _call(self, name, method, *args):
        controller = getattr(self, "_ready", {}).get(name)
        if controller is None:
            return unavailable(SUBSYSTEMS[name][0], getattr(self, "_failed", {}).get(name))
        return await getattr(controller, method)(*args)

    async def get_modules_status(self):
        return await self._call("modules", "get_status")

    async def pop_module(self, side: str):
        return await self._call("modules", "pop", side)

    async def get_status(self):
        return await self._call("fans", "get_status")

    async def set_config(self, config: dict):
        return await self._call("fans", "set_config", config)

    async def get_led_status(self):
        return await self._call("leds", "get_status")

    async def set_led_config(self, config: dict):
        return await self._call("leds", "set_config", config)
