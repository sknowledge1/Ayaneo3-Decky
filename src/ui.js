// SPDX-License-Identifier: GPL-3.0-or-later
const R = window.SP_REACT;
const h = R.createElement;
const { PanelSection, PanelSectionRow, SliderField, ButtonItem, Focusable, DialogButton } = window.DFL;
const row = (key, child) => h(PanelSectionRow, { key }, child);
const API_VERSION = 5;
function checkedReply(status, name) {
  if (!status?.ok) {
    throw Object.assign(new Error(status?.error || `${name} is unavailable.`), { diagnostic: status?.diagnostic || "", starting: !!status?.starting });
  }
  if (status.api_version !== API_VERSION) throw new Error(`${name}: the panel and the backend differ. Restart Decky.`);
  return status;
}
const CSS = `
.ay3-cap{white-space:nowrap!important;font-size:12px!important;font-weight:600!important;letter-spacing:.04em!important;text-transform:uppercase!important;color:#9aa4ae!important;padding:2px 0 6px!important}
.ay3-caprow{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:8px!important}
.ay3-capstat{white-space:nowrap!important;display:flex!important;align-items:center!important;gap:6px!important;font-size:12px!important;padding:0 0 4px!important}
.ay3-seg{display:grid!important;grid-template-columns:48fr 55fr 73fr 83fr!important;gap:4px!important;padding:5px 5px 6px!important;margin:0 -5px!important}
.ay3-seg>.ay3-opt{width:auto!important;min-width:0!important;padding:9px 5px!important;font-size:14px!important;line-height:16px!important;border-radius:6px!important;font-weight:600!important;background:rgba(255,255,255,.08)!important;color:#dfe5ea!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
.ay3-seg>.ay3-opt.ay3-on{background:#1a9fff!important;color:#0e141b!important}
.ay3-seg>.ay3-opt.ay3-on.ay3-unc{background:transparent!important;color:#66c0f4!important;box-shadow:inset 0 0 0 2px #1a9fff!important}
.ay3-seg>.ay3-opt.ay3-on.ay3-unc.gpfocus{background:#e6ebf0!important;color:#0e141b!important;box-shadow:inset 0 0 0 2px #1a9fff!important}
.ay3-seg>.ay3-opt.gpfocus{background:#e6ebf0!important;color:#0e141b!important}
.ay3-seg>.ay3-opt.ay3-on.gpfocus{background:#1a9fff!important;color:#0e141b!important;box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #e6ebf0!important}
.ay3-opt{position:relative!important}
.ay3-opt.gpfocus{z-index:1!important}
.ay3-chev{position:absolute!important;right:8px!important;top:50%!important;margin-top:-5px!important;display:flex!important;width:10px!important}
.ay3-chev svg{width:10px!important;height:10px!important}
.ay3-chev svg,.ay3-link svg{transition:transform .15s!important}
.ay3-opt[aria-expanded=true] svg,.ay3-link[aria-expanded=true] svg{transform:rotate(180deg)!important}
.ay3-chev.ay3-off{visibility:hidden!important}
.ay3-custom .ay3-chev{right:5px!important}
.ay3-seg>.ay3-opt:disabled,.ay3-sw>.ay3-opt:disabled,.ay3-pops>.ay3-pop:disabled{opacity:.4!important}
.ay3-sw{display:flex!important;justify-content:space-between!important;gap:4px!important;padding:7px 7px 8px 7px!important;margin:0 -7px!important}
.ay3-sw>.ay3-opt{flex:0 0 26px!important;width:26px!important;height:26px!important;min-width:0!important;padding:0!important;display:flex!important;align-items:center!important;justify-content:center!important;border-radius:50%!important;border:none!important;box-shadow:inset 0 0 0 1px rgba(255,255,255,.25)!important;transition:box-shadow .12s!important}
.ay3-sw>.ay3-opt.ay3-on:not(.ay3-custom){box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #1a9fff!important}
.ay3-sw>.ay3-opt.gpfocus{box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #e6ebf0!important}
.ay3-sw>.ay3-opt.ay3-on:not(.ay3-custom).gpfocus{box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #1a9fff,0 0 0 5.5px #e6ebf0!important}
.ay3-sw>.ay3-opt.ay3-on.ay3-unc{outline:2px dashed #ff8f8f!important;outline-offset:2px!important}
.ay3-sw>.ay3-opt.ay3-custom.ay3-on.ay3-unc{box-shadow:none!important;background:rgba(255,255,255,.08)!important;outline-offset:-2px!important}
.ay3-sw>.ay3-opt.ay3-custom{flex:0 0 108px!important;width:108px!important;height:26px!important;justify-content:center!important;border-radius:13px!important;padding:0!important;display:flex!important;align-items:center!important;gap:3px!important;font-size:14px!important;font-weight:600!important;color:#dfe5ea!important;background:rgba(255,255,255,.08)!important;box-shadow:none!important}
.ay3-sw>.ay3-opt.ay3-custom.ay3-on{color:#fff!important;background:rgba(26,159,255,.18)!important;box-shadow:inset 0 0 0 2px #1a9fff!important}
.ay3-sw>.ay3-opt.ay3-custom.gpfocus{background:#e6ebf0!important;color:#0e141b!important;box-shadow:none!important}
.ay3-sw>.ay3-opt.ay3-custom.ay3-on.gpfocus{background:rgba(26,159,255,.18)!important;color:#fff!important;box-shadow:inset 0 0 0 2px #1a9fff,0 0 0 1.5px #0e141b,0 0 0 3.5px #e6ebf0!important}
.ay3-sw>.ay3-opt.ay3-on.ay3-unc:not(.ay3-custom){box-shadow:inset 0 0 0 1px rgba(255,255,255,.25)!important}
.ay3-sw>.ay3-opt.ay3-on.ay3-unc:not(.ay3-custom).gpfocus{box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #e6ebf0!important;outline-offset:3.5px!important}
.ay3-sw>.ay3-opt.ay3-custom.ay3-on.ay3-unc.gpfocus{box-shadow:0 0 0 1.5px #0e141b,0 0 0 3.5px #e6ebf0!important}
.ay3-dot{width:16px;height:16px;border-radius:50%;flex:0 0 16px}
.ay3-link{display:flex!important;align-items:center!important;justify-content:space-between!important;width:100%!important;min-width:0!important;padding:7px 8px!important;margin:0 -8px!important;box-sizing:content-box!important;font-size:13px!important;background:transparent!important;color:#b6bfc8!important;border-radius:4px!important}
.ay3-link.gpfocus{background:#e6ebf0!important;color:#0e141b!important}
.ay3-pops{display:flex!important;gap:4px!important}
.ay3-pops>.ay3-pop{flex:1 1 0!important;min-width:0!important;height:34px!important;padding:0 6px!important;border-radius:6px!important;background:rgba(255,255,255,.08)!important;color:#dfe5ea!important;display:flex!important;align-items:center!important;justify-content:center!important}
.ay3-pops>.ay3-pop.gpfocus{background:#e6ebf0!important;color:#0e141b!important}
.ay3-rgbbox{background:rgba(255,255,255,.05)!important;border-radius:10px!important;padding:8px 10px 4px!important;margin-top:6px!important}
.ay3-rgbbox.ay3-tight{margin-top:-2px!important}
.ay3-pop b{font-size:14px!important;line-height:17px!important}
.ay3-card{display:flex!important;align-items:stretch!important;gap:10px!important;padding:10px 12px!important;margin-bottom:10px!important;border-radius:10px!important;background:linear-gradient(135deg,rgba(255,255,255,.09),rgba(255,255,255,.04))!important}
.ay3-card>div{flex:1 1 0!important;min-width:0!important}
.ay3-big{font-size:28px!important;line-height:32px!important;height:32px!important;font-weight:700!important;white-space:nowrap!important}
.ay3-big small{font-size:15px!important;font-weight:600!important;margin-left:2px!important;opacity:.8!important}
.ay3-bar{height:4px!important;border-radius:2px!important;background:rgba(255,255,255,.12)!important;margin-top:5px!important;overflow:hidden!important}
.ay3-bar>div{height:100%!important;border-radius:2px!important;transition:width .4s!important}
.ay3-note{font-size:13px!important;line-height:18px!important;color:#b6bfc8!important;padding:2px 0 6px!important}
`;
const SLIDER = window.DFL.gamepadSliderClasses || {};
const SLIDER_CSS = SLIDER.LabelText ? `
.ay3-sl .${SLIDER.LabelText}{font-size:12px!important;font-weight:600!important;letter-spacing:.04em!important;text-transform:uppercase!important;color:#9aa4ae!important}
.ay3-sl .${SLIDER.DescriptionValueText}{font-size:13px!important;font-weight:600!important;color:#dfe5ea!important}` : "";
const FIELD = window.DFL.gamepadDialogClasses || {};
// Steam's slider row overflows its column; keep it inside.
const SLIDER_FIT_CSS = FIELD.FieldChildrenWithIcon ? `
.ay3-sl .${FIELD.FieldChildrenWithIcon}{width:100%!important;min-width:0!important;max-width:100%!important}
.ay3-sl>.${FIELD.Field}{padding-top:0!important}
:last-child>.ay3-sl>.${FIELD.Field},.ay3-sl.ay3-noted>.${FIELD.Field}{padding-bottom:4px!important}` : "";
const slider = ({ key, noted = false, ...props }) => h("div", { key, className: noted ? "ay3-sl ay3-noted" : "ay3-sl" }, h(SliderField, { bottomSeparator: "none", ...props }));
const note = text => h("div", { className: "ay3-note" }, text);

const reducedMotion = () => !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
function FanIcon({ percent = null } = {}) {
  const spin = percent > 0 && !reducedMotion() ? ["2.0s", "1.4s", "0.9s", "0.5s"][Math.min(3, Math.floor(percent / 25))] : null;
  return h("svg", { viewBox: "0 0 24 24", width: "1em", height: "1em", fill: "none", stroke: "currentColor", strokeWidth: 1.6, "aria-hidden": true },
    h("g", null, h("circle", { cx: 12, cy: 12, r: 2.2 }),
      ...[0, 90, 180, 270].map(angle => h("path", { key: angle, transform: `rotate(${angle} 12 12)`, d: "M11 9 C5 9 5 2 9 2 C13 2 15 5 13 9" })),
      spin && h("animateTransform", { attributeName: "transform", type: "rotate", from: "0 12 12", to: "360 12 12", dur: spin, repeatCount: "indefinite" })));
}
function Spinner() {
  return h("svg", { viewBox: "0 0 20 20", width: "14px", height: "14px", "aria-hidden": true },
    h("circle", { cx: 10, cy: 10, r: 7, fill: "none", stroke: "currentColor", strokeWidth: 2, strokeDasharray: "30 14" },
      !reducedMotion() && h("animateTransform", { attributeName: "transform", type: "rotate", from: "0 10 10", to: "360 10 10", dur: "0.9s", repeatCount: "indefinite" })));
}
const Eject = () => h("svg", { viewBox: "0 0 12 12", width: "12px", height: "12px", "aria-hidden": true, style: { marginRight: "5px", flex: "0 0 12px" } },
  h("path", { d: "M6 1.5 L11 7 H1 Z", fill: "currentColor" }), h("rect", { x: 1, y: 8.6, width: 10, height: 1.9, rx: 0.6, fill: "currentColor" }));
const Check = ({ light }) => {
  const d = "M2.5 6.3 L5 8.6 L9.6 3.6";
  return h("svg", { viewBox: "0 0 12 12", width: "14px", height: "14px", "aria-hidden": true },
    !light && h("path", { d, fill: "none", stroke: "rgba(0,0,0,.45)", strokeWidth: 3.6, strokeLinecap: "round", strokeLinejoin: "round" }),
    h("path", { d, fill: "none", stroke: light ? "#0e141b" : "#fff", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" }));
};
const Chevron = () => h("svg", { viewBox: "0 0 12 12", width: "12px", height: "12px", "aria-hidden": true },
  h("path", { d: "M2 4 L6 8 L10 4", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" }));
const TONES = { error: ["#ff8f8f", "#ff6b6b"], success: ["#a4d866", "#a4d866"], attention: ["#ffc66d", "#ffc66d"] };
const statusChip = (text, tone = "progress") => h("div", { className: "ay3-capstat", role: "status", "aria-live": "polite",
  style: { color: tone === "progress" ? "#66c0f4" : toneColour(tone), fontWeight: tone === "progress" ? 600 : undefined } }, toneMark(tone), text);
const toneColour = tone => (TONES[tone] || ["inherit"])[0];
const toneMark = tone => tone === "progress" ? h(Spinner)
  : h("span", { "aria-hidden": true, style: { width: "8px", height: "8px", flex: "0 0 8px", borderRadius: "50%", background: (TONES[tone] || [0, "#8b929a"])[1] } });
function statusRow(key, text, tone = "normal") {
  return row(key, h("div", { role: "status", "aria-live": "polite", style: {
    display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", lineHeight: "1.45", padding: "4px 0 6px", color: toneColour(tone)
  } }, toneMark(tone), text));
}
const hintSeen = name => { try { return localStorage.getItem(`ay3-hint-${name}`) === "1"; } catch { return false; } };
const markHintSeen = name => { try { localStorage.setItem(`ay3-hint-${name}`, "1"); } catch { /* not persisted */ } };
const rowRefs = new Map();
const rowRef = key => rowRefs.get(key) || rowRefs.set(key, { current: null }).get(key);
const PREFERRED_CHILD = window.DFL.NavEntryPositionPreferences?.PREFERRED_CHILD ?? 4;
function wrapRow(key, buttons, props) {
  const ref = rowRef(key), last = buttons.length - 1;
  return h(Focusable, { "flow-children": "horizontal", navRef: ref, navEntryPreferPosition: PREFERRED_CHILD, ...props },
    ...buttons.map((button, index) => button({
      onMoveLeft: index === 0 ? () => !!(ref.current?.Node?.() ?? ref.current?.m_node)?.BFocusLastChild?.() : undefined,
      onMoveRight: index === last ? () => !!(ref.current?.Node?.() ?? ref.current?.m_node)?.BFocusFirstChild?.() : undefined })));
}
const caption = (text, status) => h("div", { className: "ay3-caprow" }, h("div", { className: "ay3-cap" }, text), status || null);
function choice(key, label, value, options, onSelect, { disabled = false, kind = "ay3-seg", caption: text = label, busy = "", unconfirmed = false } = {}) {
  const selected = options.some(option => option.data === value && !option.disabled) ? value : options.find(option => !option.disabled)?.data;
  return row(key, h("div", null, text && caption(text, busy && statusChip(busy)),
    wrapRow(key, options.map(option => edge => {
      const on = option.data === value;
      return h(DialogButton, { key: option.data, ...edge,
        className: ["ay3-opt", on && "ay3-on", on && unconfirmed && "ay3-unc", option.className].filter(Boolean).join(" "),
        role: "radio", "aria-checked": on, "aria-label": option.label, "data-choice": option.data, title: option.label,
        preferredFocus: option.data === selected, disabled: disabled || !!option.disabled, style: option.style, ...option.props,
        onClick: () => onSelect(option) }, ...[].concat(option.content ?? option.label));
    }), { className: kind, role: "radiogroup", "aria-label": label })));
}
const disclosure = (key, label, open, toggle) => row(key, h(DialogButton, { className: "ay3-link", "aria-expanded": open, onClick: toggle },
  h("span", null, label), h(Chevron)));
function useControl(view, interval = 2000, ...watched) {
  const [, render] = R.useState(0);
  R.useEffect(() => {
    const listener = () => render(value => value + 1), views = view ? [view, ...watched] : watched;
    views.forEach(each => each.listeners.add(listener));
    const timer = view && (view.refresh(), setInterval(view.refresh, interval));
    return () => { clearInterval(timer); views.forEach(each => each.listeners.delete(listener)); };
  }, []);
}
