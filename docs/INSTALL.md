# Installing and removing

You need an AYANEO 3 running Bazzite, and Decky Loader. Nothing else is installed: no packages, system services or kernel modules.

## Install

1. Install Decky. On Bazzite, switch to Desktop Mode, open a terminal and run `ujust setup-decky`, or follow [Bazzite's Decky guide](https://docs.bazzite.gg/Handheld_and_HTPC_edition/Handheld_Wiki/#decky-setup).
2. Download [Ayaneo3-Decky.zip](https://github.com/sknowledge1/Ayaneo3-Decky/releases/latest/download/Ayaneo3-Decky.zip). Don't unzip it.
3. Back in Gaming Mode, open Decky's settings (the gear in the Decky menu) and turn on **Developer mode**.
4. Under **Developer**, choose **Install Plugin from ZIP File** and pick the ZIP.
5. Open **Ayaneo 3 Decky** from the Decky menu.

## Before you start

Turn off any other fan or module tool first, for example Handheld Daemon. Two programs controlling the same fan fight each other; when the plugin notices, it hands the fan back to Auto and tells you.

## When Decky is not running

- **Fan:** goes back to Auto. Your choice comes back when Decky starts.
- **Lighting:** the rings keep their colour, but after refitting the modules or sleeping they show the default until Decky runs again.
- **Magic Modules:** refitted modules only switch back on while Decky is running.

## Remove

Remove the plugin in Decky. The fan stays on Auto. Your saved choices stay in `~/homebrew/settings/ayaneo3-decky` and can be deleted.

Tested on the AYANEO 3 with the Ryzen 7 8840U. The HX 370 model uses the same interfaces but has not been tested.
