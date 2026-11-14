// SPDX-License-Identifier: GPL-3.0-or-later
const ANCHORS = [40, 55, 65, 75, 95];
const fanView = managedControl({ read: callable("get_status"), write: callable("set_config"),
  check: status => checkedReply(status, "Fan control"),
  initial: { mode: "auto", percent: 60, curve: [40, 50, 70, 85, 100] },
  confirmed: status => !status.fault && !status.applying && !status.handoff_failed && (status.config.mode === "auto" || !status.automatic) });
const FAN_MODES = [{ label: "Auto", data: "auto" }, { label: "Quiet", data: "quiet" }, { label: "Manual", data: "manual" }, { label: "Curve", data: "curve" }];
const temperatureColour = (celsius, bar = false) => celsius >= 85 ? "#ff7b6b" : celsius >= 70 ? "#ffc66d" : bar ? "#a4d866" : "#f2f5f8";
const MAX_RPM = 5500; // Measured on the 8840U.
const meter = (percent, colour) => h("div", { className: "ay3-bar", style: percent == null ? { visibility: "hidden" } : undefined },
  h("div", { style: { width: `${Math.min(Math.max(percent ?? 0, 0), 100)}%`, background: colour } }));
function CurveGraph({ curve, temperature }) {
  const anchors = ANCHORS;
  const x = celsius => 44 + (celsius - 40) / 55 * 252, y = percent => 104 - percent * 0.84;
  const points = anchors.map((celsius, index) => [x(celsius), y(curve[index])]);
  const line = points.map(point => point.join(",")).join(" ");
  let marker = null;
  if (Number.isFinite(temperature)) {
    const at = Math.min(Math.max(temperature, 40), 95);
    const index = Math.max(1, anchors.findIndex(celsius => celsius >= at));
    const t = (at - anchors[index - 1]) / (anchors[index] - anchors[index - 1]);
    const percent = curve[index - 1] + t * (curve[index] - curve[index - 1]);
    marker = h("g", null, h("line", { x1: x(at), x2: x(at), y1: 16, y2: 104, stroke: "#e6ebf0", strokeOpacity: 0.7, strokeWidth: 1, strokeDasharray: "3 3" }),
      h("circle", { cx: x(at), cy: y(percent), r: 3.5, fill: "#ffffff", stroke: "#0e141b", strokeWidth: 1.5 }),
      h("text", { x: Math.min(Math.max(x(at), 62), 252), y: 11, fontSize: 14, fontWeight: 700, fill: "#f2f5f8", textAnchor: "middle" }, "Now"));
  }
  const label = (props, text) => h("text", { fontSize: 14, fill: "#aab3bc", ...props }, text);
  return h("svg", { viewBox: "0 0 300 126", role: "img",
    "aria-label": `Custom fan curve: ${anchors.map((celsius, index) => `${celsius} °C ${curve[index]}%`).join(", ")}`,
    style: { width: "100%", height: "auto", display: "block", overflow: "visible" } },
    h("defs", null, h("linearGradient", { id: "ay3-fill", x1: 0, y1: 0, x2: 0, y2: 1 },
      h("stop", { offset: "0", stopColor: "#1a9fff", stopOpacity: 0.35 }), h("stop", { offset: "1", stopColor: "#1a9fff", stopOpacity: 0 }))),
    ...[0, 50, 100].map(percent => h("line", { key: percent, x1: 44, x2: 296, y1: y(percent), y2: y(percent), stroke: "#fff", strokeOpacity: 0.08 })),
    ...[100, 50, 0].map(percent => label({ key: `y${percent}`, x: 38, y: y(percent) + 4, textAnchor: "end" }, `${percent}%`)),
    ...anchors.slice(0, 4).map(celsius => label({ key: celsius, x: x(celsius), y: 122, textAnchor: "middle" }, String(celsius))),
    label({ x: 298, y: 122, textAnchor: "end" }, "95 °C"),
    h("polygon", { points: `${x(40)},${y(0)} ${line} ${x(95)},${y(0)}`, fill: "url(#ay3-fill)" }),
    h("polyline", { points: line, fill: "none", stroke: "#1a9fff", strokeWidth: 2.5, strokeLinejoin: "round" }),
    ...points.map(([cx, cy], index) => h("circle", { key: index, cx, cy, r: 3.5, fill: "#0e141b", stroke: "#66c0f4", strokeWidth: 2 })),
    marker);
}
const fellBack = status => !!status?.fault && status.automatic && !status.handoff_failed;
const fanShown = () => {
  const { status, draft, blocked, dirty } = fanView;
  const config = blocked && status ? status.config : draft;
  return (blocked || !dirty) && fellBack(status) && config.mode !== "auto" ? { ...config, mode: "auto" } : config;
};
function FanPanel() {
  useControl(fanView);
  const [editCurve, showCurveEditor] = R.useState(false);
  const { status, draft, sending, queued, timer, blocked } = fanView;
  const locked = !status?.can_configure;
  const notApplied = fanView.error || fanView.statusError || status?.fault;
  const error = notApplied || status?.save_error || status?.settings_error;
  const cpu = Number.isFinite(status?.telemetry?.cpu_c) ? status.telemetry.cpu_c : null;
  const rpm = Number.isFinite(status?.telemetry?.fan_rpm) ? status.telemetry.fan_rpm : null;
  const shown = fanShown();
  const fanBusy = sending || queued || timer !== null || status?.applying ? "Applying…" : "";
  const editorOpen = shown.mode === "curve" && editCurve;
  const curveActive = status && shown.mode === "curve";
  const select = option => {
    fanView.lastEdited = -1;
    if (option.data === "curve" && curveActive) { markHintSeen("curve"); return showCurveEditor(!editCurve); }
    if (option.data !== "curve") showCurveEditor(false);
    if (option.data === "auto" || status?.can_configure) return fanView.edit({ ...fanShown(), mode: option.data }, true);
  };
  const modes = FAN_MODES.map(option => ({ ...option, disabled: !status || option.data !== "auto" && locked,
    ...(option.data === "curve" && {
      ...(curveActive && { label: editCurve ? "Curve, close editor" : "Curve, edit points", props: { "aria-expanded": editCurve } }),
      content: [h("span", { key: "label" }, "Curve"), h("span", { key: "chevron", className: `ay3-chev${curveActive ? "" : " ay3-off"}` }, h(Chevron))] }) }));
  const percentSlider = props => slider({ min: 0, max: 100, step: 1, showValue: true, valueSuffix: "%", disabled: locked, ...props });
  const controls = [
    h("style", { key: "css" }, CSS + SLIDER_CSS + SLIDER_FIT_CSS),
    row("summary", h("div", { className: "ay3-card" },
      h("div", null, h("div", { className: "ay3-cap" }, "CPU"),
        h("div", { className: "ay3-big", style: { color: cpu != null ? temperatureColour(cpu) : "#f2f5f8" } }, cpu != null ? Math.round(cpu) : "—", cpu != null && h("small", null, "°C")),
        meter(cpu != null ? (cpu - 40) / 55 * 100 : null, cpu != null ? temperatureColour(cpu, true) : null)),
      h("div", null, h("div", { className: "ay3-cap", style: { display: "flex", alignItems: "center", gap: "5px" } }, h(FanIcon, { percent: rpm != null ? rpm / MAX_RPM * 100 : null }), "Speed"),
        h("div", { className: "ay3-big", style: { color: "#f2f5f8" } }, rpm != null ? rpm.toLocaleString("en-US") : "—", rpm != null && h("small", null, "rpm")),
        meter(rpm != null ? rpm / MAX_RPM * 100 : null, "#1a9fff")))),
    choice("mode", "Fan mode", !status || status.handoff_failed && !fanView.dirty ? undefined : shown.mode, modes, select,
      { disabled: !status, caption: "Mode", busy: fanBusy })
  ];
  const feedback = [];
  if (error) feedback.push(statusRow("fan-error", error, fanView.starting ? "progress" : notApplied ? "error" : "attention"));
  if (!blocked && !notApplied && status?.save_error) {
    feedback.push(row("fan-save-retry", h(ButtonItem, { layout: "below", onClick: () => fanView.edit({ ...status.config }, true) }, "Retry saving")));
  }
  if (blocked && status) {
    const mode = draft.mode !== status.config.mode && FAN_MODES.find(option => option.data === draft.mode)?.label;
    feedback.push(row("fan-retry", h(ButtonItem, { layout: "below", onClick: fanView.retry }, mode ? `Retry: ${mode}` : "Retry")));
  }
  const near = editorOpen && feedback.length && fanView.lastEdited >= 0 && fanView.lastEdited < 4 ? fanView.lastEdited : -1;
  if (near < 0) controls.push(...feedback);
  if (status && locked && !error) controls.push(row("fan-locked", note("No CPU temperature reading, so only Auto is available.")));
  if (!status && !error) controls.push(statusRow("fan-reading", "Reading fan status…", "progress"));
  if (shown.mode === "quiet") controls.push(row("quiet", note("The CPU may run warmer.")));
  if (shown.mode === "manual") {
    controls.push(row("manual", percentSlider({ noted: true, label: "Fixed level", value: shown.percent,
      onChange: value => { fanView.lastEdited = -1; return fanView.edit({ ...fanShown(), percent: Math.round(value) }); } })));
    controls.push(row("manual-note", note("0% stops the fan. At 95 °C and above it always runs at 100%.")));
  }
  if (shown.mode === "curve") {
    controls.push(row("curve-graph", h("div", { style: { paddingTop: "6px" } }, h(CurveGraph, { curve: shown.curve, temperature: cpu }))));
    if (!editCurve && !hintSeen("curve")) controls.push(row("curve-hint", note("Press Curve again to edit the points.")));
    if (editCurve) {
      const setPoint = (index, value) => {
        fanView.lastEdited = index;
        const curve = [...fanShown().curve]; curve[index] = Math.round(value);
        for (let i = index - 1; i >= 0; i--) curve[i] = Math.min(curve[i], curve[index]);
        for (let i = index + 1; i < curve.length; i++) curve[i] = Math.max(curve[i], curve[index]);
        curve[4] = 100; return fanView.edit({ ...fanShown(), curve });
      };
      controls.push(row("curve-editor", h("div", { className: "ay3-rgbbox" },
        h("div", { className: "ay3-note" }, "Other points move to keep the curve rising. 95 °C is always 100%."),
        ...ANCHORS.slice(0, 4).flatMap((temperature, index) => [
          percentSlider({ key: temperature, label: `${temperature} °C`, value: shown.curve[index], onChange: value => setPoint(index, value) }),
          ...(index === near ? feedback : [])]))));
    }
  }
  return h(PanelSection, { title: "Fan" }, ...controls);
}
