# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import uuid

API_VERSION = 5
DETAILS = "Details are under Help & details."


def unavailable(label):
    return f"{label} is not available. {DETAILS}"


def not_saved(applied):
    return "Applied, but not saved for the next start." if applied else "Not saved for the next start."


def read(path, maximum=4096):
    with open(path, "rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError(f"{path} returned too much data.")
    return value.decode("utf-8", "strict").strip()


def write(path, value):
    with open(path, "w", encoding="ascii") as stream:
        stream.write(str(value))


def is_ayaneo3(root):
    dmi = Path(root) / "class/dmi/id"
    return read(dmi / "sys_vendor") == "AYANEO" and read(dmi / "product_name") == "AYANEO 3"


def atomic_write(directory, name, data):
    temporary = f".{name}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


class Takeovers:
    def __init__(self, limit=5, window=60.0):
        self.limit, self.window, self.times = limit, window, []

    def hit(self, now):
        self.times = [at for at in self.times if now - at < self.window] + [now]
        return len(self.times) > self.limit

    def clear(self):
        self.times = []
