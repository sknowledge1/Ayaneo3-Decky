# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from ay3_common import API_VERSION, DETAILS, atomic_write, is_ayaneo3, read

SIDES = {"left", "right", "both"}
ATTACHMENTS = {"none", "left", "right", "both"}
GENERIC = f"Magic Modules can't be controlled right now. {DETAILS}"
NOT_FINISHED = "The release did not finish. Check both modules, then try again."
CHANGED_BEFORE = "The modules changed before the release started. Try again."
NO_POWER = "The controller did not come back. Refit both modules or restart Decky."


class ModuleError(RuntimeError):
    pass


class UserError(ModuleError):
    pass


def describe(error):
    return (str(error), "") if isinstance(error, UserError) else (GENERIC, str(error))


def check_id(raw):
    if not isinstance(raw, str) or re.fullmatch(r"0x[0-9a-fA-F]{2}", raw) is None:
        raise ModuleError("The controller returned an invalid module ID.")


class SysfsModules:
    CONFLICT_SECONDS = 30.0

    def __init__(self, root=Path("/sys"), proc=Path("/proc"), user_home=None):
        self.root, self.proc = Path(root), Path(proc)
        self.ec = self.root / "devices/platform/ayaneo-ec"
        self.driver = self.root / "bus/hid/drivers/hid-ayaneo"
        self.user_home = user_home if user_home is not None else os.environ.get("DECKY_USER_HOME")
        self.scanned = None

    def check_device(self):
        if not is_ayaneo3(self.root):
            raise UserError("Magic Modules requires an AYANEO 3.")

    def ec_state(self):
        attached = read(self.ec / "controller_modules")
        power = read(self.ec / "controller_power")
        if attached not in ATTACHMENTS or power not in {"0", "1"}:
            raise ModuleError("The kernel returned invalid module attachment or power state.")
        return attached, power == "1"

    def conflict(self, fresh=True):
        now = time.monotonic()
        if fresh or self.scanned is None or now - self.scanned[0] >= self.CONFLICT_SECONDS:
            self.scanned = (now, self._scan())
        return self.scanned[1]

    def _scan(self):
        if not self.user_home:
            return "Cannot locate Decky's user home to check for competing module controls."
        plugins = Path(self.user_home) / ".local/share/opengamepadui/plugins"
        if any((plugins / name).exists() for name in ("ayaneo-modules", "ayaneo-modules.zip")):
            return "Remove the OpenGamepadUI Magic Modules plugin before using these module controls."
        for process in self.proc.iterdir():
            if not process.name.isdigit():
                continue
            try:
                comm = read(process / "comm", 256).lower()
                with open(process / "cmdline", "rb") as stream:
                    args = stream.read(4096).decode("utf-8", "replace").split("\0")
            except (FileNotFoundError, ProcessLookupError):
                continue
            names = {Path(arg).name.lower() for arg in args if arg}
            module_run = any(args[i:i + 2] == ["-m", "hhd"] for i in range(len(args) - 1))
            if comm in {"hhd", "hhd-local"} or names & {"hhd", "hhd-local", "hhd.py"} or module_run:
                return "Stop Handheld Daemon before using these module controls."
        return ""

    def discover(self):
        candidates = []
        if self.driver.is_dir():
            for entry in self.driver.iterdir():
                if re.fullmatch(r"0003:1C4F:0002\.[0-9A-Fa-f]+", entry.name) is None:
                    continue
                target = entry.resolve(strict=True)
                if not target.is_relative_to((self.root / "devices").resolve()) or target.name != entry.name:
                    raise ModuleError("The module driver points outside the expected device tree.")
                if (target / "driver").resolve(strict=True) != self.driver.resolve(strict=True):
                    raise ModuleError("The controller is no longer bound to the AYANEO driver.")
                attrs = dict(line.split("=", 1) for line in read(target / "uevent").splitlines() if "=" in line)
                if attrs.get("HID_ID") != "0003:00001C4F:00000002":
                    raise ModuleError("Unexpected controller identity; no module command was sent.")
                interfaces = [(target / name).is_file() for name in ("module_left", "module_right", "eject")]
                # The controller's keyboard and mouse interfaces bind to this driver too.
                if not any(interfaces):
                    continue
                if not all(interfaces):
                    raise ModuleError("The AYANEO driver is missing the required module interfaces.")
                candidates.append(str(target))
        if len(candidates) != 1:
            raise ModuleError("A single compatible hid-ayaneo module device is required." if not candidates else
                              "More than one AYANEO module device was found; controls are disabled.")
        return candidates[0]

    def prefer_old_enumeration(self, identity):
        # The controller ignores the first descriptor read after power returns; the old USB
        # enumeration scheme finds it in about 12 s instead of 32 s. Resets at boot.
        try:
            usb = Path(identity).resolve(strict=True).parent.parent
            if (read(usb / "idVendor", 16), read(usb / "idProduct", 16)) != ("1c4f", "0002"):
                return
            quirks = (usb / "port").resolve(strict=True) / "quirks"
            value = int(read(quirks, 16), 16)
            if not value & 1:
                with open(quirks, "w", encoding="ascii") as stream:
                    stream.write(format(value | 1, "x"))
        except (OSError, ValueError):
            pass

    def snapshot(self):
        attached, powered = self.ec_state()
        conflict = self.conflict(fresh=False)
        result = {"attached": attached, "powered": powered, "hid": None,
                  "error": conflict, "plain": bool(conflict), "conflict": bool(conflict)}
        if attached == "both" and powered and not conflict:
            try:
                identity = self.discover()
                values = [read(Path(identity) / f"module_{side}", 32) for side in ("left", "right")]
                for value in values:
                    check_id(value)
                if self.ec_state() != (attached, powered) or self.discover() != identity:
                    raise UserError("The modules changed. Checking again.")
                result["hid"] = identity
            except (OSError, ValueError, ModuleError) as error:
                result.update(error=str(error), plain=isinstance(error, UserError))
        return result

    def _write(self, path, value, allowed):
        if not path.parent.resolve(strict=True).is_relative_to((self.root / "devices").resolve(strict=True)):
            raise ModuleError("The module control is outside the expected device tree.")
        fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if not allowed():
                raise UserError(NOT_FINISHED)
            data = value.encode("ascii")
            if os.write(fd, data) != len(data):
                raise ModuleError("The kernel did not accept the complete module command.")
        finally:
            os.close(fd)

    def eject(self, identity, side, allowed):
        if side not in SIDES:
            raise ModuleError("Invalid module side.")
        if self.conflict() or self.ec_state() != ("both", True) or self.discover() != identity:
            raise UserError(CHANGED_BEFORE)
        self._write(Path(identity) / "eject", side, allowed)

    def power(self, enabled, identity, allowed):
        conflict = self.conflict()
        if conflict:
            raise UserError(conflict)
        attached, powered = self.ec_state()
        if enabled and attached != "both":
            raise UserError("Both modules must be fitted before the controller can be switched on.")
        if not enabled and self.discover() != identity:
            raise UserError("The controller changed during the release. Check both modules.")
        if powered != enabled:
            self._write(self.ec / "controller_power", "1" if enabled else "0", allowed)
        if self.ec_state()[1] != enabled:
            raise UserError(NO_POWER)


class RuntimeJournal:
    def __init__(self, directory=Path("/run/ayaneo3-decky-modules"), boot_id=None):
        self.directory, self.boot_id = Path(directory), boot_id
        self.dir_fd = self.lock_fd = None

    @staticmethod
    def _verify(info, directory=False):
        expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        if not expected or info.st_uid != 0 or info.st_mode & 0o077:
            raise ModuleError("Module runtime state must be private and root-owned.")

    def acquire(self):
        if os.geteuid() != 0:
            raise ModuleError("The module backend requires Decky's root setting.")
        if self.dir_fd is None:
            self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
            self.dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                self._verify(os.fstat(self.dir_fd), directory=True)
                self.lock_fd = os.open("owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                                       0o600, dir_fd=self.dir_fd)
                self._verify(os.fstat(self.lock_fd))
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                self.close()
                raise
        if self.boot_id is None:
            self.boot_id = read("/proc/sys/kernel/random/boot_id", 64)
        try:
            fd = os.open("state.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.dir_fd)
        except FileNotFoundError:
            return None
        try:
            self._verify(os.fstat(fd))
            raw = os.read(fd, 4097)
        finally:
            os.close(fd)
        if len(raw) > 4096:
            raise ModuleError("Module recovery record is too large; it was not overwritten.")
        data = json.loads(raw)
        if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1 or
                not isinstance(data.get("boot_id"), str) or not isinstance(data.get("phase"), str)):
            raise ModuleError("Module recovery record is invalid; it was not overwritten.")
        return data if data["boot_id"] == self.boot_id else None

    def save(self, phase):
        atomic_write(self.dir_fd, "state.json", json.dumps({"version": 1, "boot_id": self.boot_id, "phase": phase}).encode())

    def close(self):
        for name in ("lock_fd", "dir_fd"):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


class ModuleManager:
    POLL_SECONDS = 2.0
    RECOVERY_SECONDS = 0.5
    STABLE_SECONDS = 1.0
    STALE_SECONDS = 3.0
    EJECT_SECONDS = 35.0
    RECONNECT_SECONDS = 15.0

    def __init__(self, io=None, journal=None, clock=time.monotonic):
        self.io = io if io is not None else SysfsModules()
        self.journal = journal if journal is not None else RuntimeJournal()
        self.clock = clock
        self.stopping = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ayaneo-modules")
        self.monitor = self.operation = None
        self.initialized = self.polling = False
        self.sampled_at = self.both_since = self.activation_until = None
        self.restore_attempts = self.generation = 0
        self.restore_after = 0.0
        self.port_identity = None
        self.state = {"ok": True, "api_version": API_VERSION, "phase": "unavailable", "attached": "unknown",
                      "powered": None, "can_pop": False, "busy": False, "stale": True,
                      "error": "", "status_error": "", "diagnostic": "", "notice": ""}

    async def start(self):
        if self.monitor is None and not self.stopping.is_set():
            self.monitor = asyncio.create_task(self._monitor())

    async def get_status(self):
        return self.status()

    def _fail(self, key, error):
        self.state[key], detail = describe(error)
        if detail:
            self.state["diagnostic"] = detail

    def status(self):
        result = copy.deepcopy(self.state)
        result["stale"] = self.sampled_at is None or self.clock() - self.sampled_at > self.STALE_SECONDS
        result["can_pop"] = result["can_pop"] and not result["stale"] and not self.stopping.is_set()
        return result

    def _submit(self, function, *args):
        # Cancelling an await does not stop a blocking kernel write, so all I/O runs on one worker.
        future = asyncio.wrap_future(self.pool.submit(function, *args))
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return future

    def _initialize(self):
        self.io.check_device()
        old = self.journal.acquire()
        return "An earlier release was interrupted. No release command was repeated." if old and old["phase"] in {
            "ejecting", "acknowledged", "power_off_pending"} else ""

    async def _monitor(self):
        try:
            while not self.stopping.is_set():
                await self.poll_once()
                delay = self.RECOVERY_SECONDS if self.state["phase"] in {"ejecting", "waiting", "activating"} else self.POLL_SECONDS
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass

    async def poll_once(self):
        if self.stopping.is_set() or self.operation is not None or self.polling:
            return
        self.polling = True
        generation = self.generation
        try:
            if not self.initialized:
                self.state["notice"] = await asyncio.shield(self._submit(self._initialize))
                self.initialized = True
            snapshot = await asyncio.shield(self._submit(self.io.snapshot))
            if self.stopping.is_set() or generation != self.generation:
                return
            if snapshot["hid"] and snapshot["hid"] != self.port_identity:
                self.port_identity = snapshot["hid"]
                await asyncio.shield(self._submit(self.io.prefer_old_enumeration, snapshot["hid"]))
            previous_phase = self.state["phase"]
            self.sampled_at = self.clock()
            self.state.update(attached=snapshot["attached"], powered=snapshot["powered"], can_pop=False, status_error="")
            if snapshot["error"]:
                self._fail("status_error", (UserError if snapshot["plain"] else ModuleError)(snapshot["error"]))
            if snapshot["conflict"]:
                self.both_since = None
                self.state["phase"] = "error"
            elif snapshot["attached"] != "both":
                self.both_since = None
                self.restore_attempts = 0
                self.activation_until = None
                self.state["phase"] = "waiting"
            elif not snapshot["powered"]:
                self.state["phase"] = "waiting"
                if self.both_since is None:
                    self.both_since = self.clock()
                if self.restore_attempts >= 3:
                    self.state.update(phase="error", status_error=NO_POWER)
                elif self.clock() - self.both_since >= self.STABLE_SECONDS and self.clock() >= self.restore_after:
                    self.state.update(phase="activating", busy=True)
                    self.restore_attempts += 1
                    try:
                        await asyncio.shield(self._submit(self._restore_power))
                        self.activation_until = self.clock() + self.RECONNECT_SECONDS
                        self.both_since = None
                    except Exception as error:
                        self.restore_after = self.clock() + 2.0
                        self.state["phase"] = "error"
                        self._fail("status_error", error)
                    finally:
                        self.state["busy"] = False
            elif snapshot["error"]:
                self.both_since = None
                self.state["phase"] = "activating" if self.activation_until and self.clock() < self.activation_until else "error"
            else:
                self.both_since = None
                self.restore_attempts = 0
                self.activation_until = None
                if previous_phase != "ready":
                    await asyncio.shield(self._submit(self.journal.save, "ready"))
                if generation == self.generation and not self.stopping.is_set():
                    self.state.update(phase="ready", can_pop=True)
                    if previous_phase != "ready" and not self.state["error"]:
                        self.state["diagnostic"] = ""
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.sampled_at = self.both_since = None
            self.state.update(phase="unavailable", can_pop=False, attached="unknown", powered=None)
            self._fail("status_error", error)
        finally:
            self.polling = False

    def _restore_power(self):
        self.journal.save("activating")
        self.io.power(True, None, lambda: not self.stopping.is_set())

    async def pop(self, side):
        if type(side) is not str or side not in SIDES:
            return {"ok": False, "error": "Choose left, right, or both modules."}
        if self.operation is not None or not self.status()["can_pop"]:
            return {"ok": False, "error": "The modules are not ready yet. Wait a moment, then try again."}
        self.generation += 1
        self.state.update(phase="ejecting", busy=True, can_pop=False, error="", diagnostic="", notice="")
        self.operation = asyncio.create_task(self._execute(side))
        return {"ok": True, "status": self.status()}

    def _release(self, side, deadline, aborted):
        allowed = lambda: not self.stopping.is_set() and not aborted.is_set() and self.clock() < deadline
        snapshot = self.io.snapshot()
        if snapshot["attached"] != "both" or not snapshot["powered"] or not snapshot["hid"] or snapshot["error"]:
            raise UserError(CHANGED_BEFORE)
        self.journal.save("ejecting")
        self.io.eject(snapshot["hid"], side, allowed)
        if not allowed():
            raise UserError(NOT_FINISHED)
        self.journal.save("acknowledged")  # Power is not cut unless this is recorded.
        self.io.power(False, snapshot["hid"], allowed)
        self.journal.save("waiting")

    async def _execute(self, side):
        aborted = threading.Event()
        future = self._submit(self._release, side, self.clock() + self.EJECT_SECONDS, aborted)
        try:
            try:
                await asyncio.wait_for(asyncio.shield(future), self.EJECT_SECONDS)
            except asyncio.TimeoutError:
                # The write cannot be cancelled: keep ownership until it finishes.
                aborted.set()
                self.state.update(phase="error", error="The release is taking longer than expected. Still waiting…")
                try:
                    await asyncio.shield(future)
                except Exception:
                    pass
                raise UserError(NOT_FINISHED)
            self.both_since = None
            self.state["phase"] = "waiting"
        except asyncio.CancelledError:
            aborted.set()
            raise
        except Exception as error:
            self.state["phase"] = "error"
            self._fail("error", error)
        finally:
            self.sampled_at = None
            self.state.update(busy=False, can_pop=False)
            self.operation = None

    def close(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.state["can_pop"] = False
        for task in (self.monitor, self.operation):
            if task is not None:
                task.cancel()
        self.pool.submit(self.journal.close)  # Holds the lock until queued I/O drains.
        self.pool.shutdown(wait=False)
