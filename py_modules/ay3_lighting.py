# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import copy
from pathlib import Path

from ay3_common import API_VERSION, Takeovers, is_ayaneo3, not_saved, read, write
from ay3_settings import LedSettings, validate_led_config

DRIVER_EFFECTS = {"solid": "monocolor", "breathing": "breathe", "cycle": "rainbow"}
DEFAULT_CONFIG = {"effect": "solid", "color": [255, 255, 255], "brightness": 30}


class LedHardware:
    def __init__(self, root=Path("/sys")):
        self.root = Path(root)
        self.maxima = {}

    def check_device(self):
        if not is_ayaneo3(self.root):
            raise ValueError("Lighting controls require an AYANEO 3.")

    def find(self):
        found = []
        for led in sorted((self.root / "class/leds").glob("*:rgb:joystick_rings")):
            try:
                if (led / "device/driver").resolve(strict=True).name == "hid-ayaneo":
                    found.append(led)
            except OSError:
                continue
        if len(found) > 1:
            raise ValueError("More than one joystick-ring LED was found; lighting is disabled.")
        return found[0] if found else None

    def native_brightness(self, led, config):
        if config["effect"] == "off":
            return 0
        if led not in self.maxima:
            self.maxima = {led: int(read(led / "max_brightness"))}
        return round(config["brightness"] * self.maxima[led] / 100)

    def matches(self, led, config):
        brightness = int(read(led / "brightness"))
        if config["effect"] == "off":
            return brightness == 0
        if read(led / "effect") != DRIVER_EFFECTS[config["effect"]] or brightness != self.native_brightness(led, config):
            return False
        return config["effect"] == "cycle" or [int(v) for v in read(led / "multi_intensity").split()] == config["color"]

    def apply(self, led, config):
        if config["effect"] != "off":
            write(led / "effect", DRIVER_EFFECTS[config["effect"]])
            write(led / "multi_intensity", " ".join(str(v) for v in config["color"]))
        write(led / "brightness", str(self.native_brightness(led, config)))


# The kernel forgets the ring setting when the modules reconnect or the device sleeps, so it is re-applied.
class LedController:
    def __init__(self, hardware=None, settings=None, clock=None, tick_seconds=2.0):
        self.hardware = hardware if hardware is not None else LedHardware()
        self.settings = settings if settings is not None else LedSettings()
        self.clock = clock or asyncio.get_running_loop().time
        self.tick_seconds = tick_seconds
        self.lock = asyncio.Lock()
        self.task = None
        self.config = None
        self.state = "unconfigured"
        self.fault = self.settings_error = self.save_error = self.diagnostic = ""
        self.verified = None
        self.takeovers = Takeovers()
        self.yielded = self.find_failed = False

    async def start(self):
        await asyncio.to_thread(self.hardware.check_device)
        try:
            self.config = await asyncio.to_thread(self.settings.load)
        except (OSError, ValueError) as error:
            self.settings_error = "Saved lighting settings could not be read. Choose an effect to set the rings."
            self.diagnostic = str(error)
        async with self.lock:
            await self._tick()
        self.task = asyncio.create_task(self._loop())

    def close(self):
        if self.task is not None:
            self.task.cancel()
            self.task = None

    async def _loop(self):
        while True:
            await asyncio.sleep(self.tick_seconds)
            async with self.lock:
                await self._tick()

    async def _tick(self):
        try:
            led = await asyncio.to_thread(self.hardware.find)
            self.find_failed = False
        except (OSError, ValueError) as error:
            self.state, self.fault, self.find_failed, self.diagnostic = "failed", "The joystick rings could not be found.", True, str(error)
            return
        if led is None:
            self.verified = None
            self.state = "unavailable" if self.config is not None else "unconfigured"
            return
        if self.config is None:
            self.state = "unconfigured"
            return
        if self.yielded:
            return
        try:
            if await asyncio.to_thread(self.hardware.matches, led, self.config):
                self.verified, self.state, self.fault = led, "applied", ""
                return
            if self.verified == led and self.takeovers.hit(self.clock()):
                self.yielded, self.state = True, "failed"
                self.fault = "Another program keeps changing the lighting. Choose an effect to take it back."
                return
            await asyncio.to_thread(self.hardware.apply, led, self.config)
            if not await asyncio.to_thread(self.hardware.matches, led, self.config):
                raise OSError("the rings did not accept the setting")
            self.verified, self.state, self.fault = led, "applied", ""
        except (OSError, ValueError) as error:
            self.verified, self.state = None, "failed"
            self.fault, self.diagnostic = "Lighting could not be applied.", str(error)

    async def set_config(self, config):
        try:
            config = validate_led_config(config)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        async with self.lock:
            self.config, self.yielded, self.verified = config, False, None
            self.takeovers.clear()
            await self._tick()
            if self.state == "unavailable":
                self.fault = ""
            try:
                await asyncio.to_thread(self.settings.save, config)
                self.save_error = self.settings_error = ""
            except (OSError, ValueError) as error:
                self.save_error, self.diagnostic = not_saved(self.state == "applied"), str(error)
            if self.state == "failed":
                return {"ok": False, "error": self.fault, "state": self._status()}
            return self._status()

    def _status(self):
        return {"ok": True, "api_version": API_VERSION, "status": self.state,
                "config": copy.deepcopy(self.config or DEFAULT_CONFIG),
                "can_configure": self.state != "unavailable" and not self.find_failed,
                "fault": self.fault, "diagnostic": self.diagnostic,
                "save_error": self.save_error, "settings_error": self.settings_error}

    async def get_status(self):
        async with self.lock:
            return self._status()
