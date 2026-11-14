# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import fcntl
import json
import os
from pathlib import Path
import stat

from ay3_common import atomic_write

MAX_BYTES = 16384
ANCHORS = (40, 55, 65, 75, 95)
DEFAULT_CONFIG = {"mode": "auto", "percent": 60, "curve": [40, 50, 70, 85, 100]}
LED_EFFECTS = {"off", "solid", "breathing", "cycle"}


def percent(value):
    return type(value) is int and 0 <= value <= 100


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"mode", "percent", "curve"}:
        raise ValueError("Fan control requires one complete configuration.")
    if not isinstance(config["mode"], str) or config["mode"] not in {"auto", "manual", "curve", "quiet"}:
        raise ValueError("Unsupported fan mode.")
    if not percent(config["percent"]):
        raise ValueError("Fan duty must be an integer from 0 to 100 percent.")
    values = config["curve"]
    if not isinstance(values, list) or len(values) != 5 or any(not percent(value) for value in values) or values != sorted(values) or values[-1] != 100:
        raise ValueError("The five fan percentages must increase and end at 100 percent.")
    return copy.deepcopy(config)


def validate_led_config(config):
    if not isinstance(config, dict) or set(config) != {"effect", "color", "brightness"}:
        raise ValueError("Lighting requires one complete configuration.")
    if not isinstance(config["effect"], str) or config["effect"] not in LED_EFFECTS:
        raise ValueError("Unsupported lighting effect.")
    color = config["color"]
    if not isinstance(color, list) or len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
        raise ValueError("Colour requires three RGB values from 0 to 255.")
    if not percent(config["brightness"]):
        raise ValueError("Brightness must be from 0 to 100 percent.")
    return copy.deepcopy(config)


class Settings:
    def __init__(self, name, validate, directory=None):
        configured = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR") if directory is None else directory
        self.path = Path(configured) if configured else None
        self.name, self.validate = name, validate

    def _directory(self):
        if self.path is None:
            raise ValueError("Decky's persistent settings directory is unavailable.")
        descriptor = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        if os.fstat(descriptor).st_mode & 0o022:
            os.close(descriptor)
            raise ValueError("Decky's settings directory is writable by other users.")
        return descriptor

    def _trusted(self, info, directory):
        # Decky gives settings files to the desktop user, even for root plugins.
        return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and
                info.st_uid in {os.geteuid(), os.fstat(directory).st_uid})

    def _read(self, directory):
        try:
            fd = os.open(self.name + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if not self._trusted(info, directory) or info.st_size > MAX_BYTES:
                raise ValueError("Saved settings are not a small, private, regular file.")
            body = os.read(fd, MAX_BYTES + 1)
        finally:
            os.close(fd)
        if len(body) > MAX_BYTES:
            raise ValueError("Saved settings are too large.")
        data = json.loads(body)
        if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1 or
                set(data) != {"version", "config"}):
            raise ValueError("Saved settings are corrupt or unsupported; the file was preserved.")
        return None if data["config"] is None else self.validate(data["config"])

    def load(self):
        directory = self._directory()
        try:
            return self._read(directory)
        finally:
            os.close(directory)

    def save(self, config):
        config = self.validate(config)
        directory = self._directory()
        lock = None
        try:
            lock = os.open(self.name + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=directory)
            if not self._trusted(os.fstat(lock), directory):
                raise ValueError("Settings lock is not trusted.")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._read(directory)
            encoded = (json.dumps({"version": 1, "config": config}, separators=(",", ":"), allow_nan=False) + "\n").encode()
            if len(encoded) > MAX_BYTES:
                raise ValueError("Settings exceed their size limit.")
            atomic_write(directory, self.name + ".json", encoded)
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)


def FanSettings(directory=None):
    return Settings("fan-settings", validate_config, directory)


def LedSettings(directory=None):
    return Settings("led-settings", validate_led_config, directory)
