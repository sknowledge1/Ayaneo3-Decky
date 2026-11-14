// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import test from "node:test";
import { harness, button, popButtons, nodes, text, moduleStatus, deferred, tick, openHelp } from "./ui-harness.mjs";

const GENERIC = "Magic Modules can't be controlled right now. Details are under Help & details.";

test("modules follow fan and lighting, retain identification and have compact status", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  assert.deepEqual(ui.run("Controls()").children.map(node => node.type.name), ["FanPanel", "LightingPanel", "ModulesPanel", "HelpPanel"]);
  assert.equal(popButtons(ui.render()).length, 3);
  assert.deepEqual(popButtons(ui.render()).map(node => node.props["aria-label"]), ["Pop left module", "Pop right module", "Pop both modules"]);
  assert.doesNotMatch(text(ui.render()), /Joystick|ABXY|Cross|D-pad/);
  assert.equal(nodes(ui.render()).find(node => node.props.role === "status"), undefined);
  assert.equal(button(ui.render(), "Help & details"), undefined);
  assert.ok(ui.calls.every(call => call[0] === "get_modules_status"));
  mounted.unmount();
});

test("each Pop is immediate, pins its side and cannot repeat while busy", async () => {
  for (const [index, side] of ["left", "right", "both"].entries()) {
    const ui = await harness(), mounted = await ui.mount("ModulesPanel");
    await popButtons(ui.render())[index].props.onClick();
    for (const control of popButtons(ui.render())) await control.props.onClick();
    assert.deepEqual(ui.sent("pop_module"), [["pop_module", side]]);
    assert.ok(popButtons(ui.render()).every(control => control.props.disabled));
    mounted.unmount();
  }
});

test("normal reattachment uses neutral Connecting then a brief green confirmation", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "activating", can_pop: false, status_error: GENERIC, diagnostic: "HID identification in progress" });
  await ui.run("refreshModules()");
  let status = nodes(ui.render()).find(node => node.props.role === "status");
  assert.match(text(status), /Connecting/); assert.equal(status.props.style.color, "#66c0f4");
  assert.doesNotMatch(text(status), /HID identification|right now/);
  ui.set("get_modules_status", moduleStatus()); await ui.run("refreshModules()");
  status = nodes(ui.render()).find(node => node.props.role === "status");
  assert.match(text(status), /Connected/); assert.equal(status.props.style.color, "#a4d866");
  await ui.advance(3000);
  assert.equal(nodes(ui.render()).find(node => node.props.role === "status"), undefined);
  assert.doesNotMatch(await openHelp(ui, "ModulesPanel"), /HID identification/);
  mounted.unmount();
});

test("real faults remain actionable and diagnostics are expandable", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "error", can_pop: false, error: "Refit the module and check its contacts." });
  await ui.run("refreshModules()");
  assert.match(text(ui.render()), /check its contacts/);
  assert.ok(popButtons(ui.render()).every(control => control.props.disabled));
  assert.match(await openHelp(ui, "ModulesPanel"), /input and lighting come back only while Decky is running/);
  mounted.unmount();
});

test("stale polls cannot re-enable Pop after an operation starts", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel"), pending = deferred();
  ui.override("get_modules_status", () => pending.promise);
  const oldPoll = ui.run("refreshModules()");
  await popButtons(ui.render())[2].props.onClick();
  pending.resolve(moduleStatus()); await oldPoll;
  assert.ok(popButtons(ui.render()).every(control => control.props.disabled));
  mounted.unmount();
});

test("lost responses survive remount without another eject request", async () => {
  const ui = await harness(); let mounted = await ui.mount("ModulesPanel");
  ui.override("pop_module", async () => { ui.set("get_modules_status", { phase: "waiting", can_pop: false }); throw new Error("Response lost; inspect the modules."); });
  await popButtons(ui.render())[0].props.onClick(); await ui.run("refreshModules()");
  mounted.unmount(); mounted = await ui.mount("ModulesPanel");
  assert.equal(ui.sent("pop_module").length, 1); assert.match(text(ui.render()), /Response lost/);
  mounted.unmount();
});

test("a failed Pop stays visible after routine Ready polls", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.override("pop_module", async () => ({ ok: false, error: "Module release could not start." }));
  await popButtons(ui.render())[1].props.onClick();
  await ui.run("refreshModules()"); await ui.run("refreshModules()");
  const statuses = nodes(ui.render()).filter(node => node.props.role === "status").map(text);
  assert.ok(statuses.some(line => /Last pop failed: .*could not start/.test(line)), statuses.join(" | "));
  mounted.unmount();
});

test("a release that fails after it was accepted is kept as history, not shown as Connected", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  await popButtons(ui.render())[0].props.onClick(); await tick(); await tick();
  ui.set("get_modules_status", { phase: "error", can_pop: false, error: "The release did not finish. Check both modules, then try again." });
  await ui.run("refreshModules()");
  ui.set("get_modules_status", moduleStatus()); await ui.run("refreshModules()");
  const statuses = nodes(ui.render()).filter(node => node.props.role === "status").map(text);
  assert.ok(statuses.some(line => /Last pop failed: The release did not finish/.test(line)), statuses.join(" | "));
  assert.ok(!statuses.some(line => /Connected/.test(line)));
  mounted.unmount();
});

test("driver-level module errors are shown in plain words, with details kept for Help", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "unavailable", can_pop: false, status_error: GENERIC, diagnostic: "A single compatible hid-ayaneo module device is required." });
  await ui.run("refreshModules()");
  assert.match(text(ui.render()), /can't be controlled right now/);
  assert.match(await openHelp(ui, "ModulesPanel"), /hid-ayaneo/);
  mounted.unmount();
});

test("Help adds only what the panel does not already say", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "error", can_pop: false, error: "The release did not finish. Check both modules, then try again." });
  await ui.run("refreshModules()");
  const help = await openHelp(ui, "ModulesPanel");
  assert.equal(((text(ui.render()) + help).match(/did not finish/g) || []).length, 1);
  assert.doesNotMatch(help, /Last module error/);
  mounted.unmount();
});

test("a readiness error that clears without a Pop is not reported as a failed pop", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "error", can_pop: false, error: "Handheld Daemon is controlling the modules." });
  await ui.run("refreshModules()");
  ui.set("get_modules_status", moduleStatus()); await ui.run("refreshModules()");
  assert.doesNotMatch(text(ui.render()), /Last pop failed/);
  mounted.unmount();
});

test("raw filesystem errors are shown in plain words", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "unavailable", can_pop: false, status_error: GENERIC, diagnostic: "[Errno 2] No such file or directory: '/sys/bus/hid/devices/x/controller_power'" });
  await ui.run("refreshModules()");
  const panel = text(ui.render());
  assert.match(panel, /can't be controlled right now/);
  assert.doesNotMatch(panel, /Errno|\/sys\//);
  mounted.unmount();
});

test("a technical pop failure kept as history does not claim the modules are unavailable now", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  await popButtons(ui.render())[0].props.onClick(); await tick(); await tick();
  ui.set("get_modules_status", { phase: "error", can_pop: false, error: GENERIC, diagnostic: "The kernel did not accept the complete module command." });
  await ui.run("refreshModules()");
  ui.set("get_modules_status", { ...moduleStatus(), error: GENERIC, diagnostic: "The kernel did not accept the complete module command." });
  await ui.run("refreshModules()");
  const all = text(ui.render());
  assert.match(all, /Last pop failed\. Details are under Help & details\./);
  assert.doesNotMatch(all, /right now/);
  assert.match(await openHelp(ui, "ModulesPanel"), /Last module error: The kernel did not accept/);
  mounted.unmount();
});

test("a release that is still running after a timeout is shown as waiting, not as finished", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "error", can_pop: false, busy: true, error: "The release is taking longer than expected. Still waiting…" });
  await ui.run("refreshModules()");
  const status = nodes(ui.render()).find(node => node.props.role === "status");
  assert.match(text(status), /Still waiting/);
  assert.doesNotMatch(text(ui.render()), /did not finish|try again/);
  assert.notEqual(status.props.style.color, "#ff8f8f");
  mounted.unmount();
});

test("startup is shown as progress, never as an error", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  for (const reply of [{ phase: "unavailable", can_pop: false }, { ok: false, starting: true, error: "Magic Modules is starting." }]) {
    ui.set("get_modules_status", reply);
    await ui.run("refreshModules()");
    const status = nodes(ui.render()).find(node => node.props.role === "status");
    assert.ok(status, JSON.stringify(reply));
    assert.notEqual(status.props.style.color, "#ff8f8f", JSON.stringify(reply));
    assert.doesNotMatch(text(ui.render()), /Check the modules/);
  }
  mounted.unmount();
});

test("while waiting for a refit the hold warning is not repeated", async () => {
  const ui = await harness(), mounted = await ui.mount("ModulesPanel");
  ui.set("get_modules_status", { phase: "waiting", can_pop: false });
  await ui.run("refreshModules()");
  assert.doesNotMatch(text(ui.render()), /Hold the device firmly/);
  assert.equal(text(ui.render()).match(/Refit both modules/g).length, 1);
  mounted.unmount();
});
