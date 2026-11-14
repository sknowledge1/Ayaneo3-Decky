// SPDX-License-Identifier: GPL-3.0-or-later
// The rings stay dark below native 36/255 per channel, and the kernel scales colour by brightness.
function minimumBrightness(config = { effect: "solid", color: [255, 255, 255] }) {
  const peak = config.effect === "cycle" ? 255 : Math.max(...config.color);
  for (let percent = 14; percent <= 100; percent++) {
    if (Math.floor(peak * Math.round(percent * 255 / 100) / 255) >= 36) return percent;
  }
  return 100;
}
function nativeBrightness(value, config) {
  if (value === 0) return 0;
  const minimum = minimumBrightness(config);
  return minimum + Math.round((value - 1) * (100 - minimum) / 99);
}
function visibleBrightness(value, config) {
  const minimum = minimumBrightness(config);
  if (value < minimum) return 0;
  return minimum === 100 ? 100 : 1 + Math.round((value - minimum) * 99 / (100 - minimum));
}

const lightingView = managedControl({ read: callable("get_led_status"), write: callable("set_led_config"),
  check: status => checkedReply(status, "Joystick lighting"),
  initial: { effect: null, color: [255, 255, 255], brightness: 30 },
  shown: (status, initial) => status.status === "unconfigured" ? initial : status.config,
  confirmed: status => status.status === "applied" });
// Two slider percentages can map to one native level; keep the one the user chose.
function lightingBrightness(config = lightingView.draft) {
  const input = lightingView.brightnessInput;
  return input && input.native === config.brightness && input.minimum === minimumBrightness(config)
    ? input.percent : visibleBrightness(config.brightness, config);
}
const validRgb = value => Array.isArray(value) && value.length === 3 && value.every(part => Number.isInteger(part) && part >= 0 && part <= 255);
try {
  const saved = JSON.parse(localStorage.getItem("ay3-last-custom"));
  if (validRgb(saved)) lightingView.lastCustom = saved;
} catch { /* no saved custom colour */ }
function lightingShown() {
  const { status, draft, blocked } = lightingView;
  return !blocked || !status || status.status === "failed" ? draft : status.status === "unconfigured" ? { ...draft, effect: null } : status.config;
}
function editLighting(changes, immediate = false, brightness = lightingBrightness(lightingShown())) {
  const config = { ...lightingShown(), ...changes };
  config.brightness = nativeBrightness(brightness, config);
  lightingView.brightnessInput = { percent: brightness, native: config.brightness, minimum: minimumBrightness(config) };
  return lightingView.edit(config, immediate);
}
const COLOURS = [{ label: "Teal", data: "0,200,170", light: true }, { label: "Bright orange", data: "255,110,0", light: true },
  { label: "Pink", data: "255,60,170" }, { label: "Deep green", data: "0,140,50" }, { label: "Deep purple", data: "100,0,220" }];
const EFFECTS = [{ label: "Off", data: "off" }, { label: "Solid", data: "solid" }, { label: "Breathe", data: "breathing" }, { label: "Rainbow", data: "cycle" }];
const RAINBOW = "conic-gradient(#ff3b3b, #ffd23b, #3bff6b, #3bd8ff, #5b3bff, #ff3bd8, #ff3b3b)";
function LightingPanel() {
  useControl(lightingView);
  const [customColour, showCustomColour] = R.useState(false);
  const { status, draft, sending, queued, timer, blocked } = lightingView;
  const disabled = !status?.can_configure;
  const chosen = draft.effect != null;
  const shown = lightingShown();
  const coloured = shown.effect === "solid" || shown.effect === "breathing";
  const rgbOpen = coloured && customColour;
  const notApplied = lightingView.error || lightingView.statusError || status?.fault;
  const notSaved = !status?.fault && !!status?.save_error;
  const settingsWarning = !status?.fault && !status?.save_error && !!status?.settings_error;
  const error = notApplied || status?.save_error || status?.settings_error;
  const busy = sending || queued || timer !== null ? "Applying…" : "";
  const unconfirmed = status?.status === "failed" && !busy;
  const selectEffect = option => {
    lightingView.lastEdited = -1;
    if (option.data !== "solid" && option.data !== "breathing") showCustomColour(false);
    return editLighting({ effect: option.data }, true);
  };
  const controls = [choice("effect", "Effect", shown.effect ?? undefined, EFFECTS, selectEffect, { disabled, busy: rgbOpen ? "" : busy, unconfirmed })];
  const feedback = [];
  if (error) feedback.push(statusRow("lighting-error", error, lightingView.starting ? "progress" : notApplied ? "error" : "attention"));
  if (status && disabled && (status.status === "unavailable" || !error)) feedback.push(row("lighting-locked", note(status.status === "unavailable"
    ? "The joystick rings are not connected right now. Your setting is applied when they are back." : "The joystick rings are not available right now.")));
  if ((blocked || status?.status === "failed") && chosen && !disabled) {
    const named = status?.status === "failed" || draft.effect !== status?.config.effect;
    feedback.push(row("lighting-retry", h(ButtonItem, { layout: "below", onClick: lightingView.retry },
      named ? `Retry: ${EFFECTS.find(option => option.data === draft.effect)?.label}` : "Retry")));
  }
  if (!blocked && notSaved && !disabled) {
    feedback.push(row("lighting-save-retry", h(ButtonItem, { layout: "below", onClick: () => lightingView.edit({ ...status.config }, true) }, "Retry saving")));
  }
  if (!status && !error) controls.push(statusRow("lighting-reading", "Reading lighting status…", "progress"));
  const near = rgbOpen && feedback.length && lightingView.lastEdited >= 0 && lightingView.lastEdited < 3 ? lightingView.lastEdited : -1;
  if (near < 0) controls.push(...feedback);
  const brightness = () => row("brightness", slider({ label: "Brightness", value: lightingBrightness(shown), min: 1, max: 100, step: 1, showValue: true, valueSuffix: "%",
    disabled: disabled || !chosen, onChange: value => { lightingView.lastEdited = -1; return editLighting({}, false, Math.round(value)); } }));
  if (shown.effect === "cycle") controls.push(brightness());
  if (coloured) {
    const colour = shown.color.join(",");
    const preset = COLOURS.some(option => option.data === colour);
    if (!preset && Math.max(...shown.color) > 0 && colour !== lightingView.lastCustom?.join(",")) {
      lightingView.lastCustom = [...shown.color];
      try { localStorage.setItem("ay3-last-custom", JSON.stringify(lightingView.lastCustom)); } catch { /* not persisted */ }
    }
    const swatchColour = preset ? lightingView.lastCustom?.join(",") : colour;
    const recalls = !customColour && preset && lightingView.lastCustom;
    const pickCustom = () => customColour ? showCustomColour(false)
      : recalls ? editLighting({ color: lightingView.lastCustom }, true) : (markHintSeen("custom"), showCustomColour(true));
    const swatches = [
      ...COLOURS.map(option => ({ ...option, style: { background: `rgb(${option.data})` },
        content: option.data === colour && !unconfirmed ? h(Check, { key: "check", light: option.light }) : "" })),
      { label: preset ? "Custom colour" : `Custom colour, RGB ${shown.color.join(", ")}`, data: "custom", className: "ay3-custom", props: { "aria-expanded": customColour },
        content: [
          h("span", { key: "dot", className: "ay3-dot", style: { background: swatchColour ? `radial-gradient(closest-side, rgb(${swatchColour}) 60%, transparent 64%), ${RAINBOW}` : RAINBOW } }),
          h("span", { key: "label" }, "Custom"),
          h("span", { key: "chevron", className: `ay3-chev${recalls ? " ay3-off" : ""}` }, h(Chevron))] }];
    const selectColour = option => {
      lightingView.lastEdited = -1;
      if (option.data === "custom") return pickCustom();
      showCustomColour(false);
      return editLighting({ color: option.data.split(",").map(Number) }, true);
    };
    controls.push(choice("colour", "Colour", preset ? colour : "custom", swatches, selectColour,
      { disabled, kind: "ay3-sw", unconfirmed, caption: "Colour", busy: rgbOpen ? busy : "" }));
    if (!preset && !customColour && !hintSeen("custom")) controls.push(row("custom-hint", note("Press Custom again to mix a colour.")));
    controls.push(brightness());
    if (customColour) {
      const setChannel = (index, value) => {
        lightingView.lastEdited = index;
        const color = [...lightingShown().color]; color[index] = Math.round(value);
        return editLighting({ color });
      };
      controls.push(row("rgb", h("div", { className: "ay3-rgbbox ay3-tight" },
        ...["Red", "Green", "Blue"].flatMap((label, index) => [
          slider({ key: label, label, value: shown.color[index], min: 0, max: 255, step: 1, showValue: true, disabled, onChange: value => setChannel(index, value) }),
          ...(index === near ? feedback : [])]))));
    }
    const peak = Math.max(...shown.color);
    if (peak < 36) controls.push(row("dark-colour", note(peak === 0
      ? "Black keeps both rings off." : "This colour is too dark for the rings. Increase an RGB value or choose a preset.")));
  }
  if (!busy && status?.status === "unconfigured" && !settingsWarning) controls.push(statusRow("lighting-unconfigured", "Lighting is unchanged until you choose an effect."));
  return h(PanelSection, { title: "Joystick Lighting" }, ...controls);
}
