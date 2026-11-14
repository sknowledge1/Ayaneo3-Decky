# How it works

Ayaneo 3 Decky is a [Decky Loader](https://decky.xyz) plugin. It needs nothing but Decky and its ZIP on a stock Bazzite install, because it drives the kernel interfaces Bazzite already ships:

| Part | Kernel interface |
| --- | --- |
| Fan | `ayaneo_ec` hwmon: `pwm1`, `pwm1_enable`, `fan1_input` |
| CPU temperature | `k10temp` `Tctl` |
| Joystick rings | `hid-ayaneo` LED `*:rgb:joystick_rings` with the firmware effects `monocolor`, `breathe`, `rainbow` |
| Magic Modules | `hid-ayaneo` attributes `module_left`, `module_right`, `eject`; `ayaneo-ec` attributes `controller_modules`, `controller_power` |

Decky runs the backend ([main.py](../main.py), [py_modules](../py_modules)) as root. The panel ([src](../src)) is plain JavaScript, joined into `dist/index.js` in the order listed in `package.json`.

## Fan

- **Auto** hands the fan to the firmware (`pwm1_enable` 2) and writes nothing else.
- **Quiet**, **Manual** and **Curve** take manual control and set `pwm1` every second. Quiet goes from 0% at 45 °C to 100% at 95 °C. Curve has points at 40, 55, 65, 75 and 95 °C; the last is always 100%.
- At 95 °C or above the fan runs at 100% in every mode except Auto.
- Duty rises at once and falls by at most 2% per second, so the fan winds down smoothly.
- Three failed temperature reads or fan writes in a row, or another program taking the fan back more than five times a minute, hand the fan to the firmware and say why.
- When Decky stops, the fan goes back to Auto. Decky stops the plugin's event loop at the first `await` in `_unload`, so shutdown is synchronous, fan first. Decky does not restart a backend that crashed; the panel then reports that the plugin is not responding.

## Joystick lighting

- Off, Solid, Breathe and Rainbow use the firmware effects; the firmware sets the speed. Both rings always share one setting.
- Nothing is written until the user chooses an effect. The choice is saved and put back whenever the rings stop showing it, for example after the modules are refitted or the device wakes. If another program keeps changing the rings, the plugin stops re-applying.
- The rings stay dark below a native level of 36/255 per channel, and the kernel scales colour by brightness. The panel's 1% is therefore the lowest level that lights the current colour; 0% and Off are off.

## Magic Modules

A release is one `eject` write followed by cutting controller power; refitting both modules turns power back on.

1. Pop needs a fresh status with both modules fitted and power on. The worker checks again just before writing: attachment, power, the controller's USB identity, and that no other module controller (Handheld Daemon, the OpenGamepadUI modules plugin) is present.
2. The plugin records the step in a root-only file under `/run/ayaneo3-decky-modules/`, writes `eject` once and waits for the kernel. It never retries `eject`, and never replays a recorded step after a restart.
3. Only after the eject succeeded, and only if that was recorded, it cuts controller power. A failed, interrupted or timed-out eject never leads to a power cut. Kernel writes cannot be cancelled, so all module I/O runs on one worker thread and Pop stays disabled until the write has finished.
4. Once both modules are fitted for one second, power is restored (at most three tries per refit). The controller reappears about 12 s later: the plugin sets the old USB enumeration scheme on the controller's port, without which Linux waits about 32 s.

The controller only takes up modules when it starts, so the power cut after `eject` is needed. The only hardware writes are `left`, `right` or `both` to `eject`, `0` or `1` to `controller_power`, and the port's `quirks` bit.

The interface facts were checked against the [AYANEO 3 compatibility project](https://github.com/matmartinez/ayaneo-3-bazzite-compat), the [OpenGamepadUI modules backend](https://github.com/matmartinez/OpenGamepadUI-ayaneo-modules) and the kernel's `hid-ayaneo` driver. This plugin is written independently and bundles neither.

## Panel and backend

- Every backend reply is `{ok: true, api_version, …}` or `{ok: false, error, diagnostic, starting}`. `error` is a plain sentence the panel shows as it is; `diagnostic` is shown only under Help & details.
- Choices apply at once; sliders send 200 ms after the last change. Each section sends one request at a time and keeps only the newest queued change. A refused change shows what is actually active, with Retry next to the control used.
- Fan and lighting choices are saved in Decky's settings folder as small private JSON files. Files that cannot be read are kept, never overwritten.

## Building and testing

Run the gate as root in a rootless Linux container with `/sys` masked and no network:

```sh
python3 -B scripts/check.py
```

It runs the Python and frontend tests, builds `dist/Ayaneo3-Decky.zip`, checks it, and builds it a second time to confirm the build is reproducible. Nothing is downloaded. See [RELEASE.md](RELEASE.md) for releases and [VALIDATION.md](VALIDATION.md) for the hardware tests.
