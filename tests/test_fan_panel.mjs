// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import test from "node:test";
import { harness, item, choice, button, nodes, text, tick, deferred, fanStatus } from "./ui-harness.mjs";

test("fan settings lead the sections, show truthful telemetry and have no Apply button", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  assert.deepEqual(ui.run("Controls()").children.map(node => node.type.name), ["FanPanel", "LightingPanel", "ModulesPanel", "HelpPanel"]);
  assert.equal(mounted.tree.props.title, "Fan");
  assert.match(text(mounted.tree), /43\s*°C/); assert.doesNotMatch(text(mounted.tree), /adjusts the fan speed itself/);
  assert.ok(nodes(mounted.tree).some(node => node.props?.className === "ay3-big" && text(node).trim() === "—"));
  assert.doesNotMatch(text(mounted.tree), /Apply changes|\d rpm/);
  assert.equal(ui.sent("set_config").length, 0);
  mounted.unmount();
});

test("mode selections apply immediately and preserve manual/custom preferences", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  await choice(ui.render(), "Fan mode").props.onChange({ data: "quiet" });
  assert.equal(ui.sent("set_config").length, 1);
  assert.equal(ui.sent("set_config")[0][1].mode, "quiet");
  assert.equal(ui.sent("set_config")[0].length, 2);
  await choice(ui.render(), "Fan mode").props.onChange({ data: "curve" });
  assert.equal(nodes(ui.render()).filter(node => node.type === "SliderField").length, 0);
  assert.match(text(ui.render()), /Press Curve again/);
  await choice(ui.render(), "Fan mode").props.onChange({ data: "curve" });
  assert.equal(ui.sent("set_config").length, 2);
  const sliders = nodes(ui.render()).filter(node => node.type === "SliderField");
  assert.deepEqual(sliders.map(node => node.props.value), [40, 50, 70, 85]);
  assert.match(text(ui.render()), /95 °C is always 100%/);
  mounted.unmount();
});

test("rapid slider changes coalesce after 200ms and survive QAM unmount", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  await choice(ui.render(), "Fan mode").props.onChange({ data: "manual" });
  item(ui.render(), "SliderField", "Fixed level").props.onChange(41);
  await ui.advance(100);
  item(ui.render(), "SliderField", "Fixed level").props.onChange(54);
  mounted.unmount(); await ui.advance(199);
  assert.equal(ui.sent("set_config").length, 1);
  await ui.advance(1);
  assert.equal(ui.sent("set_config").length, 2);
  assert.equal(ui.sent("set_config")[1][1].percent, 54);
  const remount = await ui.mount("FanPanel");
  assert.equal(item(ui.render(), "SliderField", "Fixed level").props.value, 54);
  remount.unmount();
});

test("one request is active and Automatic discards queued custom updates", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel"), pending = deferred();
  let first = true;
  ui.override("set_config", async config => {
    if (first) { first = false; return pending.promise; }
    return { ...fanStatus(), config, automatic: true };
  });
  const task = choice(ui.render(), "Fan mode").props.onChange({ data: "manual" });
  item(ui.render(), "SliderField", "Fixed level").props.onChange(31);
  await ui.advance(200);
  await choice(ui.render(), "Fan mode").props.onChange({ data: "auto" });
  assert.equal(ui.sent("set_config").length, 1);
  pending.resolve({ ...fanStatus(), config: { ...fanStatus().config, mode: "manual" }, automatic: false });
  await task; await tick();
  assert.deepEqual(ui.sent("set_config").map(call => call[1].mode), ["manual", "auto"]);
  mounted.unmount();
});

test("a refused write clears the queue and requires an explicit retry", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel"), pending = deferred();
  ui.override("set_config", () => pending.promise);
  const task = choice(ui.render(), "Fan mode").props.onChange({ data: "manual" });
  item(ui.render(), "SliderField", "Fixed level").props.onChange(44);
  await ui.advance(200);
  pending.resolve({ ok: false, error: "Native write denied", state: fanStatus() });
  await task; await ui.advance(5000);
  assert.equal(ui.sent("set_config").length, 1);
  assert.match(text(ui.render()), /Native write denied/);
  assert.ok(button(ui.render(), "Retry: Manual"));
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, "auto");
  mounted.unmount();
});

test("a stale read cannot replace a newer confirmed selection", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel"), pending = deferred();
  ui.override("get_status", () => pending.promise);
  const stale = ui.run("fanView.refresh()");
  await choice(ui.render(), "Fan mode").props.onChange({ data: "quiet" });
  pending.resolve(fanStatus()); await stale;
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, "quiet");
  assert.equal(ui.sent("set_config").length, 1);
  mounted.unmount();
});

test("telemetry failure leaves Automatic available; missing service disables stale controls", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  ui.set("get_status", { can_configure: false, telemetry: null }); await ui.run("fanView.refresh()");
  assert.deepEqual(Array.from(choice(ui.render(), "Fan mode").props.rgOptions, option => option.data), ["auto"]);
  assert.equal(choice(ui.render(), "Fan mode").props.disabled, false);
  ui.set("get_status", { ok: false, error: "Update Bazzite" }); await ui.run("fanView.refresh()");
  assert.equal(choice(ui.render(), "Fan mode").props.disabled, true);
  assert.match(text(ui.render()), /Update Bazzite/);
  mounted.unmount();
});

test("after a safety fallback the panel shows Auto as the active mode", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: true, fault: "CPU temperature is unavailable, so the fan is on automatic.", config: { ...fanStatus().config, mode: "quiet" } });
  const mounted = await ui.mount("FanPanel");
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, "auto");
  assert.match(text(ui.render()), /on automatic/);
  mounted.unmount();
});

test("a failed hand-off to the firmware is not presented as Auto", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: true, handoff_failed: true, fault: "The fan could not be returned to automatic control: write denied", config: { ...fanStatus().config, mode: "auto" } });
  const mounted = await ui.mount("FanPanel");
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, undefined);
  assert.match(text(ui.render()), /could not be returned to automatic/);
  assert.ok(nodes(ui.render()).some(node => node.props?.className === "ay3-big" && text(node).trim() === "—"));
  mounted.unmount();
});

test("before the first status nothing is shown as the active fan mode", async () => {
  const ui = await harness(), pending = deferred();
  ui.override("get_status", () => pending.promise);
  const mounted = await ui.mount("FanPanel");
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, undefined);
  assert.match(text(ui.render()), /Reading fan status/);
  assert.doesNotMatch(text(ui.render()), /adjusts the fan speed itself/);
  mounted.unmount();
});

test("a setting the hardware has not accepted yet still shows Applying", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: false, applying: true, config: { ...fanStatus().config, mode: "manual" } });
  const mounted = await ui.mount("FanPanel");
  assert.match(text(ui.render()), /Applying…/);
  ui.set("get_status", { applying: false }); await ui.run("fanView.refresh()");
  assert.doesNotMatch(text(ui.render()), /Applying…/);
  mounted.unmount();
});

test("a setting that applied but was not saved is not reported as not applied", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: false, save_error: "Applied, but the selection could not be saved for the next start: disk full", config: { ...fanStatus().config, mode: "curve" } });
  const mounted = await ui.mount("FanPanel");
  await choice(ui.render(), "Fan mode").props.onChange({ data: "curve" });
  assert.equal((text(ui.render()).match(/not saved|could not be saved/gi) || []).length, 1);
  assert.doesNotMatch(text(ui.render()), /Not applied/);
  assert.equal(ui.sent("set_config").length, 0);
  mounted.unmount();
});

test("a rejected request that later takes effect clears its error and Retry", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  ui.override("set_config", async () => ({ ok: false, error: "The fan could not be controlled, so it is on automatic: busy", state: fanStatus() }));
  await choice(ui.render(), "Fan mode").props.onChange({ data: "quiet" });
  assert.ok(button(ui.render(), "Retry: Quiet"));
  ui.set("get_status", { automatic: false, config: { ...fanStatus().config, mode: "quiet" } });
  await ui.run("fanView.refresh()");
  assert.equal(button(ui.render(), "Retry: Quiet"), undefined);
  assert.doesNotMatch(text(ui.render()), /could not be controlled/);
  assert.equal(choice(ui.render(), "Fan mode").props.selectedOption, "quiet");
  mounted.unmount();
});

test("an applied-but-not-saved fan setting offers Retry saving, which resends the active setting", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: false, save_error: "Applied, but not saved for the next start.", config: { ...fanStatus().config, mode: "quiet" } });
  const mounted = await ui.mount("FanPanel");
  await button(ui.render(), "Retry saving").props.onClick();
  assert.equal(ui.sent("set_config").length, 1);
  assert.equal(ui.sent("set_config")[0][1].mode, "quiet");
  mounted.unmount();
});

test("a temperature fallback explains automatic control once", async () => {
  const ui = await harness();
  ui.set("get_status", { automatic: true, can_configure: false, telemetry: null, fault: "CPU temperature is unavailable, so the fan is on automatic until it can be read again.", config: { ...fanStatus().config, mode: "quiet" } });
  const mounted = await ui.mount("FanPanel");
  const all = text(ui.render());
  assert.match(all, /on automatic until it can be read again/);
  assert.doesNotMatch(all, /adjusts the fan speed itself/);
  mounted.unmount();
});

test("a starting fan service is shown as progress, not as an error", async () => {
  const ui = await harness(), mounted = await ui.mount("FanPanel");
  ui.set("get_status", { ok: false, starting: true, error: "Fan control is starting.", diagnostic: "" }); await ui.run("fanView.refresh()");
  const status = nodes(ui.render()).find(node => node.props.role === "status" && /is starting/.test(text(node)));
  assert.ok(status);
  assert.notEqual(status.props.style.color, "#ff8f8f");
  assert.equal(nodes(status).some(node => node.type?.name === "Spinner"), true);
  mounted.unmount();
});
