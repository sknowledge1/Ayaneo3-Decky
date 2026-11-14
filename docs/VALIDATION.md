# Validation for 1.0.0

On an AYANEO 3 (Ryzen 7 8840U) with Bazzite 45.20261112 (kernel `7.3.3-ogc1.1.fc45`) and Decky Loader 3.3.1, with the plugin installed from its ZIP. Each setting was sent through the plugin's backend calls and checked against the values read back from the kernel.

| Area | Result |
| --- | --- |
| Loading | After a Decky restart and after a reboot, Decky loads the panel as a module and shows it. |
| Fan modes | Manual 100%: `pwm1` 255, 5,458 rpm. Manual 20%: `pwm1` 51. Quiet and Curve followed their curves. Auto: `pwm1_enable` 2. The reported speed tracked `fan1_input`. |
| Lighting | Solid Teal, Breathe Deep purple, Rainbow, Off and a custom colour all reached the ring LED (`effect`, `multi_intensity`, `brightness`). |
| Pop and refit | Pop Both from the panel: controller power was cut and the controller left USB. After the refit, power came back on and the controller returned 12.5 s later; the modules were ready and the saved ring colour was back. |
| Sleep and wake | 40.7 s asleep. Afterwards the fan was still on Quiet, the rings kept their colour and the modules stayed powered, with no faults. |
| Reboot | The fan came back on Quiet, the rings on the saved colour, and the controller's USB setting was applied again. |
| Decky stop | The plugin stopped in 0.1 s and the fan went back to Auto. |
| Backend stopped | Decky does not restart a plugin backend that died; after 8 s the panel says the plugin is not responding (checked by the tests). |
| Panel | With Help & details open, it shows as its own section below Magic Modules. |

Not tested: the HX 370 model.

## Automated checks

`scripts/check.py` ran in a clean clone, in a rootless container with `/sys` masked and no network: all Python and frontend tests passed with none skipped, the ZIP was checked, and two builds were identical. `scripts/check-release.py` passed for the release files.
