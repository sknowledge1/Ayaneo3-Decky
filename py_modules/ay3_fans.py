# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import copy
from pathlib import Path
import threading

from ay3_common import API_VERSION, Takeovers, is_ayaneo3, not_saved, read, unavailable, write
from ay3_settings import ANCHORS, DEFAULT_CONFIG, FanSettings, validate_config

SAFETY_C = 95.0
QUIET_CURVE = ((45, 0), (55, 15), (65, 25), (75, 35), (85, 55), (90, 75), (95, 100))
STEP_DOWN = 2
FAILURE_LIMIT = 3
HANDOFF_FAULT = "The fan could not be returned to automatic control. Retrying."
TAKEOVER_FAULT = "Another program keeps changing the fan, so it is on automatic. Choose a mode to try again."
UNAVAILABLE = unavailable("Fan control")


def interpolate(points, temperature):
    if temperature <= points[0][0]:
        return points[0][1]
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        if temperature <= t1:
            return round(d0 + (d1 - d0) * (temperature - t0) / (t1 - t0))
    return points[-1][1]


def target_duty(config, temperature):
    if temperature >= SAFETY_C:
        return 100
    if config["mode"] == "manual":
        return config["percent"]
    if config["mode"] == "quiet":
        return interpolate(QUIET_CURVE, temperature)
    return interpolate(list(zip(ANCHORS, config["curve"])), temperature)


class FanHardware:
    def __init__(self, root=Path("/sys")):
        self.root = Path(root)
        self.fan = self.sensor = None
        self.write_lock = threading.Lock()  # Orders worker-thread writes with the final hand-back.
        self.stopped = False

    def find(self):
        if not is_ayaneo3(self.root):
            raise ValueError("Fan controls require an AYANEO 3.")
        fans, sensors = [], []
        for hwmon in sorted((self.root / "class/hwmon").glob("hwmon*")):
            try:
                name = read(hwmon / "name")
            except OSError:
                continue
            if name == "ayaneo_ec" and (hwmon / "pwm1").is_file() and (hwmon / "pwm1_enable").is_file():
                fans.append(hwmon)
            elif name == "k10temp":
                for label in sorted(hwmon.glob("temp*_label")):
                    if read(label) == "Tctl":
                        sensors.append(hwmon / label.name.replace("_label", "_input"))
        if len(fans) != 1:
            raise ValueError("The AYANEO fan interface (ayaneo_ec) was not found.")
        if len(sensors) != 1:
            raise ValueError("The CPU temperature sensor (k10temp Tctl) was not found.")
        self.fan, self.sensor = fans[0], sensors[0]

    def temperature(self):
        value = int(read(self.sensor)) / 1000
        if not -20 <= value <= 125:
            raise ValueError("The CPU temperature reading is out of range.")
        return value

    def rpm(self):
        try:
            value = int(read(self.fan / "fan1_input"))
        except (OSError, ValueError):
            return None
        return value if 0 <= value <= 20000 else None

    def automatic(self, final=False):
        with self.write_lock:
            self.stopped = self.stopped or final
            write(self.fan / "pwm1_enable", 2)

    def set_duty(self, duty):
        with self.write_lock:
            if self.stopped:
                raise OSError("fan control is shutting down")
            claimed = read(self.fan / "pwm1_enable") != "1"
            if claimed:
                write(self.fan / "pwm1_enable", 1)
            write(self.fan / "pwm1", round(duty * 255 / 100))
            return claimed


class FanController:
    def __init__(self, hardware=None, settings=None, clock=None, tick_seconds=1.0):
        self.hardware = hardware if hardware is not None else FanHardware()
        self.settings = settings if settings is not None else FanSettings()
        self.clock = clock or asyncio.get_running_loop().time
        self.tick_seconds = tick_seconds
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.lock = asyncio.Lock()
        self.task = None
        self.duty = self.temperature = None
        self.handoff_failed = self.applied = self.claimed = self.yielded = False
        self.takeovers = Takeovers()
        self.failures = 0
        self.fault = self.hardware_error = self.save_error = self.settings_error = self.diagnostic = ""

    async def start(self):
        async with self.lock:
            try:
                await asyncio.to_thread(self.hardware.find)
                # A killed earlier run may have left the fan on manual.
                await asyncio.to_thread(self.hardware.automatic)
            except (OSError, ValueError) as error:
                self.hardware_error, self.diagnostic = UNAVAILABLE, str(error)
            try:
                saved = await asyncio.to_thread(self.settings.load)
                if saved is not None:
                    self.config = saved
            except (OSError, ValueError) as error:
                self.settings_error = "Fan settings could not be read, so defaults are used."
                self.diagnostic = str(error)
            await self._tick()
        self.task = asyncio.create_task(self._loop())

    def close(self):
        if self.hardware.fan is not None:
            try:
                self.hardware.automatic(final=True)
            except OSError:
                pass
        self.duty, self.claimed = None, False
        if self.task is not None:
            self.task.cancel()
            self.task = None

    async def _loop(self):
        while True:
            await asyncio.sleep(self.tick_seconds)
            if self.config["mode"] != "auto" or self.handoff_failed:
                async with self.lock:
                    await self._tick()

    async def _release(self):
        self.duty = None
        if self.hardware.fan is None:
            return
        try:
            await asyncio.to_thread(self.hardware.automatic)
            if self.handoff_failed:
                self.fault = ""
            self.claimed = self.handoff_failed = False
        except OSError as error:
            self.handoff_failed = True
            self.fault, self.diagnostic = HANDOFF_FAULT, str(error)

    async def _yield(self):
        self.yielded = True
        await self._release()
        if not self.handoff_failed:
            self.fault = TAKEOVER_FAULT

    async def _failed(self, message, error):
        self.diagnostic = str(error)
        self.failures += 1
        if self.config["mode"] != "auto" and (self.failures >= FAILURE_LIMIT or self.hardware.stopped):
            await self._release()
            if not self.handoff_failed:
                self.fault = message

    async def _tick(self, smooth=True):
        if self.hardware.fan is None:
            try:
                await asyncio.to_thread(self.hardware.find)
                self.hardware_error = ""
            except (OSError, ValueError) as error:
                self.hardware_error, self.diagnostic = UNAVAILABLE, str(error)
                return
        try:
            self.temperature = await asyncio.to_thread(self.hardware.temperature)
        except (OSError, ValueError) as error:
            await self._failed("CPU temperature is unavailable, so the fan is on automatic until it can be read again.", error)
            if self.fault or self.config["mode"] == "auto":
                self.temperature = None
            return
        if self.config["mode"] == "auto":
            if self.handoff_failed:
                await self._release()
            self.duty = None
            return
        if self.yielded:
            if self.handoff_failed:
                await self._yield()
            return
        target = target_duty(self.config, self.temperature)
        if smooth and self.duty is not None and target < self.duty and self.temperature < SAFETY_C:
            target = max(target, self.duty - STEP_DOWN)
        try:
            reclaimed = await asyncio.to_thread(self.hardware.set_duty, target)
        except OSError as error:
            await self._failed("The fan could not be controlled, so it is on automatic for now.", error)
            return
        self.failures = 0
        if reclaimed and self.claimed and self.takeovers.hit(self.clock()):
            await self._yield()
            return
        self.claimed, self.handoff_failed, self.applied = True, False, True
        self.duty = target
        self.fault = ""

    async def set_config(self, config):
        try:
            config = validate_config(config)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        async with self.lock:
            if self.hardware_error:
                return {"ok": False, "error": self.hardware_error, "diagnostic": self.diagnostic}
            self.config, self.fault = config, ""
            self.applied = self.yielded = False
            self.failures = 0
            self.takeovers.clear()
            if config["mode"] == "auto":
                await self._release()
            await self._tick(smooth=False)
            if self.fault:
                return {"ok": False, "error": self.fault, "state": await self._report()}
            try:
                await asyncio.to_thread(self.settings.save, config)
                self.save_error = self.settings_error = ""
            except (OSError, ValueError) as error:
                self.save_error, self.diagnostic = not_saved(config["mode"] == "auto" or self.applied), str(error)
            return await self._report()

    async def _report(self):
        if self.hardware_error:
            return {"ok": False, "error": self.hardware_error, "diagnostic": self.diagnostic}
        mode = self.config["mode"]
        rpm = await asyncio.to_thread(self.hardware.rpm)
        return {"ok": True, "api_version": API_VERSION,
                "automatic": mode == "auto" or self.duty is None,
                "can_configure": self.temperature is not None,
                "config": copy.deepcopy(self.config),
                "handoff_failed": self.handoff_failed, "diagnostic": self.diagnostic,
                "applying": mode != "auto" and not self.applied and not self.fault,
                "telemetry": {"cpu_c": self.temperature, "fan_rpm": rpm} if self.temperature is not None else None,
                "fault": self.fault, "save_error": self.save_error, "settings_error": self.settings_error}

    async def get_status(self):
        async with self.lock:
            if self.config["mode"] == "auto":
                await self._tick()
            return await self._report()
