// SPDX-License-Identifier: GPL-3.0-or-later
import assert from "node:assert/strict";
import test from "node:test";
import { harness, item, choice, button, nodes, text, deferred, tick, ledStatus } from "./ui-harness.mjs";

test("first use remains untouched and offers one effect selector for both rings", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  assert.equal(ui.sent("set_led_config").length, 0);
  assert.equal(choice(ui.render(), "Effect").props.selectedOption, undefined);
  assert.deepEqual(Array.from(choice(ui.render(), "Effect").props.rgOptions, option => option.data), ["off", "solid", "breathing", "cycle"]);
  assert.match(text(ui.render()), /unchanged until you choose/);
  assert.doesNotMatch(text(ui.render()), /Apply lighting/);
  assert.equal(item(ui.render(), "SliderField", "Brightness"), undefined);
  await ui.advance(5000); assert.equal(ui.sent("set_led_config").length, 0);
  mounted.unmount();
});

test("effect and colour selections apply immediately and RGB controls expand", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  await choice(ui.render(), "Effect").props.onChange({ data: "breathing" });
  await choice(ui.render(), "Colour").props.onChange({ data: "0,200,170" });
  assert.equal(ui.sent("set_led_config").length, 2);
  assert.deepEqual(ui.sent("set_led_config")[1].slice(1), [{ effect: "breathing", color: [0, 200, 170], brightness: 33 }]);
  assert.equal(item(ui.render(), "SliderField", "Red"), undefined);
  assert.equal(choice(ui.render(), "Colour").props.selectedOption, "0,200,170");
  await choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  assert.equal(ui.sent("set_led_config").length, 3);
  assert.deepEqual(ui.sent("set_led_config")[2][1].color, [255, 255, 255]);
  assert.equal(choice(ui.render(), "Colour").props.selectedOption, "custom");
  assert.equal(item(ui.render(), "SliderField", "Green"), undefined);
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  assert.equal(item(ui.render(), "SliderField", "Green").props.value, 255);
  mounted.unmount();
});

test("Rainbow and Off retain colour, brightness zero survives remount and no default replays", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied" });
  let mounted = await ui.mount("LightingPanel");
  await choice(ui.render(), "Effect").props.onChange({ data: "cycle" });
  assert.equal(choice(ui.render(), "Colour"), undefined);
  item(ui.render(), "SliderField", "Brightness").props.onChange(0);
  mounted.unmount(); await ui.advance(200);
  mounted = await ui.mount("LightingPanel");
  assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, 0);
  await choice(ui.render(), "Effect").props.onChange({ data: "off" });
  mounted.unmount(); mounted = await ui.mount("LightingPanel");
  assert.equal(ui.sent("set_led_config").length, 3);
  assert.equal(choice(ui.render(), "Effect").props.selectedOption, "off");
  await choice(ui.render(), "Effect").props.onChange({ data: "solid" });
  assert.deepEqual(ui.sent("set_led_config").at(-1)[1].color, [17, 34, 51]);
  mounted.unmount();
});

test("sliders coalesce complete configurations while a request is active", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied" });
  const mounted = await ui.mount("LightingPanel"), pending = deferred(); let first = true;
  ui.override("set_led_config", async config => first ? (first = false, pending.promise) : ({ ...ledStatus(), config, status: "applied" }));
  const task = choice(ui.render(), "Effect").props.onChange({ data: "breathing" });
  item(ui.render(), "SliderField", "Brightness").props.onChange(35);
  item(ui.render(), "SliderField", "Brightness").props.onChange(60);
  await ui.advance(200); assert.equal(ui.sent("set_led_config").length, 1);
  pending.resolve({ ...ledStatus(), config: { ...ledStatus().config, effect: "breathing" }, status: "applied" });
  await task; await tick();
  assert.equal(ui.sent("set_led_config").length, 2);
  assert.equal(ui.sent("set_led_config")[1][1].brightness, 88);
  assert.deepEqual(ui.sent("set_led_config")[1][1].color, [17, 34, 51]);
  assert.equal(ui.sent("set_led_config")[1][1].effect, "breathing");
  mounted.unmount();
});

test("a failed hardware state is never labelled applied", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  ui.set("get_led_status", { status: "failed", fault: "Cannot write effect" }); await ui.run("lightingView.refresh()");
  assert.match(text(ui.render()), /Cannot write effect/); assert.ok(button(ui.render(), "Retry: Solid"));
  assert.doesNotMatch(text(ui.render()), /Not applied/);
  assert.match(nodes(ui.render()).find(node => node.props["aria-checked"] === true && node.props["data-choice"] === "solid").props.className, /ay3-unc/);
  assert.equal(ui.sent("set_led_config").length, 0);
  mounted.unmount();
});

test("different RGB sliders changed in one render retain both edits", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied" });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  const tree = ui.render();
  item(tree, "SliderField", "Red").props.onChange(99);
  item(tree, "SliderField", "Green").props.onChange(88);
  await ui.advance(200);
  assert.equal(ui.sent("set_led_config").length, 1);
  assert.deepEqual(ui.sent("set_led_config")[0][1].color, [99, 88, 51]);
  mounted.unmount();
});

test("lost replies stop queued changes and remain visible after refresh/remount", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel"), pending = deferred();
  ui.override("set_led_config", () => pending.promise);
  const task = choice(ui.render(), "Effect").props.onChange({ data: "breathing" });
  item(ui.render(), "SliderField", "Brightness").props.onChange(40); await ui.advance(200);
  pending.reject(new Error("The plugin is not responding. Restart Decky."));
  await task; mounted.unmount(); const again = await ui.mount("LightingPanel"); await ui.advance(4000);
  assert.equal(ui.sent("set_led_config").length, 1);
  assert.match(text(ui.render()), /not responding/);
  assert.doesNotMatch(text(ui.render()), /Lighting applied/);
  again.unmount();
});

test("incompatible or unavailable services disable stale lighting controls", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  ui.set("get_led_status", { api_version: 99 }); await ui.run("lightingView.refresh()");
  assert.equal(choice(ui.render(), "Effect").props.disabled, true);
  assert.match(text(ui.render()), /the panel and the backend differ/);
  assert.equal(ui.sent("set_led_config").length, 0);
  mounted.unmount();
});

test("brightness uses the illuminated native range, preserves stored levels and keeps zero truly off", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [255, 255, 255] } });
  let mounted = await ui.mount("LightingPanel");
  assert.equal(ui.sent("set_led_config").length, 0);
  for (let native = 14; native <= 100; native++) {
    assert.equal(ui.run(`nativeBrightness(visibleBrightness(${native}))`), native);
  }
  const levels = Array.from({ length: 101 }, (_, value) => ui.run(`nativeBrightness(${value})`));
  assert.equal(levels[0], 0); assert.equal(levels[1], 14); assert.equal(levels[100], 100);
  assert.ok(levels.slice(1).every(value => value >= 14 && value <= 100));
  assert.deepEqual(levels, [...levels].sort((a, b) => a - b));
  for (let native = 0; native <= 13; native++) assert.equal(ui.run(`visibleBrightness(${native})`), 0);
  item(ui.render(), "SliderField", "Brightness").props.onChange(1);
  await ui.advance(199); assert.equal(ui.sent("set_led_config").length, 0);
  await ui.advance(1); assert.equal(ui.sent("set_led_config")[0][1].brightness, 14);
  mounted.unmount(); mounted = await ui.mount("LightingPanel");
  assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, 1);
  assert.equal(ui.sent("set_led_config").length, 1);
  await choice(ui.render(), "Effect").props.onChange({ data: "cycle" });
  assert.equal(ui.sent("set_led_config").at(-1)[1].brightness, 14);
  item(ui.render(), "SliderField", "Brightness").props.onChange(0);
  await ui.advance(200); assert.equal(ui.sent("set_led_config").at(-1)[1].brightness, 0);
  mounted.unmount();
});

test("all 101 slider percentages remain selectable through acknowledgements, polls and QAM remounts", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [255, 255, 255] } });
  let mounted = await ui.mount("LightingPanel");
  for (let percentage = 0; percentage <= 100; percentage++) {
    item(ui.render(), "SliderField", "Brightness").props.onChange(percentage);
    assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, percentage);
    await ui.advance(200); await ui.run("lightingView.refresh()");
    assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, percentage);
    if ([4, 19, 50].includes(percentage)) {
      mounted.unmount(); mounted = await ui.mount("LightingPanel");
      assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, percentage);
    }
  }
  mounted.unmount();
});

test("custom colours retain RGB and a useful first-lit level when changing effects", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [99, 150, 142], brightness: 100 } });
  const mounted = await ui.mount("LightingPanel");
  item(ui.render(), "SliderField", "Brightness").props.onChange(1); await ui.advance(200);
  assert.equal(ui.sent("set_led_config").at(-1)[1].brightness, 25);
  assert.deepEqual(ui.sent("set_led_config").at(-1)[1].color, [99, 150, 142]);
  assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, 1);
  await choice(ui.render(), "Effect").props.onChange({ data: "cycle" });
  assert.equal(ui.sent("set_led_config").at(-1)[1].brightness, 14);
  assert.equal(item(ui.render(), "SliderField", "Brightness").props.value, 1);
  await choice(ui.render(), "Effect").props.onChange({ data: "off" });
  await choice(ui.render(), "Effect").props.onChange({ data: "solid" });
  assert.equal(ui.sent("set_led_config").at(-1)[1].brightness, 25);
  assert.deepEqual(ui.sent("set_led_config").at(-1)[1].color, [99, 150, 142]);
  await ui.run("editLighting({color: [20, 15, 10]}, true)");
  assert.match(text(ui.render()), /colour is too dark/);
  await ui.run("editLighting({color: [0, 0, 0]}, true)");
  assert.match(text(ui.render()), /Black keeps both rings off/);
  mounted.unmount();
});

test("a backend that reports no saved choice shows no effect and replays nothing", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied" });
  const mounted = await ui.mount("LightingPanel");
  ui.set("get_led_status", { status: "unconfigured" });
  await ui.run("lightingView.refresh()");
  assert.equal(choice(ui.render(), "Effect").props.selectedOption, undefined);
  assert.equal(ui.sent("set_led_config").length, 0);
  mounted.unmount();
});

test("a rejected change shows the active effect and offers to retry the request", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  ui.override("set_led_config", async () => ({ ok: false, error: "Write denied", state: ledStatus() }));
  await choice(ui.render(), "Effect").props.onChange({ data: "off" });
  assert.equal(choice(ui.render(), "Effect").props.selectedOption, undefined);
  ui.set("get_led_status", { status: "applied" });
  ui.override("set_led_config", async () => ({ ok: false, error: "Write denied", state: { ...ledStatus(), status: "applied" } }));
  await ui.run("lightingView.refresh()");
  item(ui.render(), "SliderField", "Brightness").props.onChange(80); await ui.advance(200);
  await choice(ui.render(), "Effect").props.onChange({ data: "off" });
  assert.equal(choice(ui.render(), "Effect").props.selectedOption, ledStatus().config.effect);
  assert.match(text(ui.render()), /Write denied/);
  assert.notEqual(item(ui.render(), "SliderField", "Brightness").props.value, 80);
  assert.ok(button(ui.render(), "Retry: Off"));
  mounted.unmount();
});

test("with the RGB editor open, errors and Retry appear under the edited slider", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [17, 34, 51] } });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  ui.override("set_led_config", async () => ({ ok: false, error: "Write denied", state: { ...ledStatus(), status: "applied", config: { ...ledStatus().config, color: [17, 34, 51] } } }));
  item(ui.render(), "SliderField", "Red").props.onChange(99); await ui.advance(200); await tick();
  const all = text(ui.render());
  const order = nodes(ui.render()), at = test => order.findIndex(test);
  const red = at(node => node.type === "SliderField" && node.props.label === "Red"), green = at(node => node.type === "SliderField" && node.props.label === "Green");
  const failure = at(node => node.props?.role === "status" && /Write denied/.test(text(node)));
  assert.ok(red < failure && failure < green, "error sits under the edited slider");
  assert.doesNotMatch(all, /Not applied/);
  assert.ok(button(ui.render(), "Retry"));
  mounted.unmount();
});

test("an Effect change that fails after editing RGB reports beside the Effect row", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [17, 34, 51] } });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  item(ui.render(), "SliderField", "Blue").props.onChange(60); await ui.advance(200); await tick();
  ui.override("set_led_config", async () => ({ ok: false, error: "Write denied", state: { ...ledStatus(), status: "applied", config: { ...ledStatus().config, color: [17, 34, 60] } } }));
  await choice(ui.render(), "Effect").props.onChange({ data: "breathing" });
  const order = nodes(ui.render()), at = test => order.findIndex(test);
  const failure = at(node => node.props?.role === "status" && /Write denied/.test(text(node)));
  const red = at(node => node.type === "SliderField" && node.props.label === "Red");
  assert.ok(failure >= 0 && failure < red, "error sits under the Effect row, above the editor");
  mounted.unmount();
});

test("a lighting change that applied but was not saved is a warning, not a failure", async () => {
  const ui = await harness();
  const saveError = "Applied, but not saved for the next start.";
  ui.set("get_led_status", { status: "applied", save_error: saveError, config: { ...ledStatus().config, color: [17, 34, 51] } });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  const all = text(ui.render());
  assert.equal((all.match(/not saved/gi) || []).length, 1);
  assert.doesNotMatch(all, /Not applied/);
  assert.equal(nodes(ui.render()).find(node => node.props?.role === "status" && /not saved for the next start/.test(text(node))).props.style.color, "#ffc66d");
  mounted.unmount();
});

test("a settings-read warning is neither 'Not saved' nor 'Not applied'", async () => {
  const ui = await harness();
  const warning = "Saved lighting settings could not be read. Choose an effect to set the rings.";
  ui.set("get_led_status", { status: "applied", settings_error: warning, config: { ...ledStatus().config, color: [17, 34, 51] } });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  const all = text(ui.render());
  assert.match(all, /could not be read/);
  assert.doesNotMatch(all, /Not saved|Not applied/);
  assert.doesNotMatch(all, /unchanged until you choose/);
  mounted.unmount();
});

test("a colour the hardware refused is shown as requested, not as applied", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "failed", fault: "Lighting could not be applied.", config: { ...ledStatus().config, effect: "solid", color: [255, 60, 170] } });
  const mounted = await ui.mount("LightingPanel");
  assert.doesNotMatch(text(ui.render()), /Requested colour/);
  const pink = nodes(ui.render()).find(node => node.props?.["data-choice"] === "255,60,170");
  assert.match(pink.props.className, /ay3-unc/);
  assert.equal(nodes(pink).some(node => node.type?.name === "Check"), false);
  mounted.unmount();
});

test("disconnected rings are explained even when saving also failed", async () => {
  const ui = await harness();
  const saveError = "Not saved for the next start.";
  ui.set("get_led_status", { status: "unavailable", can_configure: false, save_error: saveError, config: { ...ledStatus().config, effect: "solid" } });
  const mounted = await ui.mount("LightingPanel");
  const all = text(ui.render());
  assert.match(all, /Not saved for the next start/);
  assert.match(all, /not connected right now/);
  assert.doesNotMatch(all, /Applied/);
  mounted.unmount();
});

test("with the RGB editor open, Custom closes it even when the colour matches a preset", async () => {
  const ui = await harness(); ui.set("get_led_status", { status: "applied", config: { ...ledStatus().config, color: [17, 34, 51] } });
  const mounted = await ui.mount("LightingPanel");
  choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  await ui.run("editLighting({ color: [255, 60, 170] }, true)");
  const sent = ui.sent("set_led_config").length;
  await choice(ui.render(), "Colour").props.onChange({ data: "custom" });
  assert.equal(item(ui.render(), "SliderField", "Red"), undefined, "editor closed");
  assert.equal(ui.sent("set_led_config").length, sent, "colour unchanged");
  mounted.unmount();
});

test("an unreadable settings file is explained once, not also as 'unchanged'", async () => {
  const ui = await harness();
  const warning = "Saved lighting settings could not be read. Choose an effect to set the rings.";
  ui.set("get_led_status", { status: "unconfigured", settings_error: warning });
  const mounted = await ui.mount("LightingPanel");
  const all = text(ui.render());
  assert.match(all, /could not be read/);
  assert.doesNotMatch(all, /unchanged until you choose/);
  mounted.unmount();
});

test("rings that cannot be found are explained once", async () => {
  const ui = await harness();
  ui.set("get_led_status", { status: "failed", can_configure: false, fault: "The joystick rings could not be found." });
  const mounted = await ui.mount("LightingPanel");
  const all = text(ui.render());
  assert.match(all, /could not be found/);
  assert.doesNotMatch(all, /not available right now/);
  mounted.unmount();
});

test("a starting lighting service is shown as progress, not as an error", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  ui.set("get_led_status", { ok: false, starting: true, error: "Joystick lighting is starting.", diagnostic: "" }); await ui.run("lightingView.refresh()");
  const status = nodes(ui.render()).find(node => node.props.role === "status" && /is starting/.test(text(node)));
  assert.ok(status);
  assert.notEqual(status.props.style.color, "#ff8f8f");
  mounted.unmount();
});

test("rings that recover after a failed apply and save show only the save warning", async () => {
  const ui = await harness(), mounted = await ui.mount("LightingPanel");
  let off;
  ui.override("set_led_config", async config => (off = config, { ...ledStatus(), status: "failed", config,
    fault: "Lighting could not be applied.", save_error: "Not saved for the next start." }));
  await choice(ui.render(), "Effect").props.onChange({ data: "off" });
  assert.match(text(ui.render()), /could not be applied/);
  ui.set("get_led_status", { status: "applied", config: off, save_error: "Not saved for the next start." });
  await ui.run("lightingView.refresh()");
  assert.doesNotMatch(text(ui.render()), /could not be applied/);
  assert.match(text(ui.render()), /Not saved for the next start/);
  assert.ok(button(ui.render(), "Retry saving"));
  assert.equal(button(ui.render(), "Retry"), undefined);
  mounted.unmount();
});
