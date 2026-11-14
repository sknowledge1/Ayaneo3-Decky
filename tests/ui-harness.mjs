// SPDX-License-Identifier: GPL-3.0-or-later
import { readFile } from "node:fs/promises";
import vm from "node:vm";
export const copy = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
export const tick = () => new Promise(resolve => setImmediate(resolve));
export function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
export const fanStatus = () => ({ ok: true, api_version: 5, automatic: true, can_configure: true,
  config: { mode: "auto", percent: 60, curve: [40, 50, 70, 85, 100] },
  telemetry: { cpu_c: 43 }, fault: "", save_error: "", settings_error: "", diagnostic: "" });
export const ledStatus = () => ({ ok: true, api_version: 5, status: "unconfigured", fault: "", can_configure: true,
  config: { effect: "solid", color: [17, 34, 51], brightness: 50 }, save_error: "", settings_error: "", diagnostic: "" });
export const moduleStatus = () => ({ ok: true, api_version: 5, phase: "ready", can_pop: true, busy: false, stale: false, attached: "both", powered: true,
  error: "", status_error: "", diagnostic: "", notice: "" });

export async function harness() {
  const states = { get_status: fanStatus(), get_led_status: ledStatus(), get_modules_status: moduleStatus() };
  const overrides = {}, calls = [], timers = new Map(), hooks = new Map();
  let now = 10000, sequence = 0, component = "FanPanel", cursor = 0, mounting = false, effect;
  const addTimer = (fn, ms, interval) => { timers.set(++sequence, { fn, at: now + ms, interval }); return sequence; };
  const context = vm.createContext({
    window: { SP_REACT: { Fragment: "Fragment", createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
      useState(initial) {
        const values = hooks.get(component), index = cursor++;
        if (!(index in values)) values[index] = initial;
        return [values[index], value => { values[index] = typeof value === "function" ? value(values[index]) : value; }];
      }, useEffect(callback) { if (mounting) effect = callback; } },
      DFL: { ...Object.fromEntries(["PanelSection", "PanelSectionRow", "SliderField", "ButtonItem", "Focusable", "DialogButton"].map(name => [name, name])), staticClasses: { Title: "title" } },
      matchMedia: () => ({ matches: false }) },
    Date: class extends Date { static now() { return now; } },
    callable: name => async (...args) => {
      calls.push([name, ...copy(args)]);
      if (overrides[name]) return overrides[name](...copy(args));
      if (name === "set_config") {
        const config = copy(args[0]);
        states.get_status = { ...states.get_status, config, automatic: config.mode === "auto" };
        return copy(states.get_status);
      }
      if (name === "set_led_config") {
        states.get_led_status = { ...states.get_led_status, config: copy(args[0]), status: "applied" };
        return copy(states.get_led_status);
      }
      if (name === "pop_module") {
        states.get_modules_status = { ...states.get_modules_status, phase: "ejecting", can_pop: false, busy: true };
        return { ok: true, status: copy(states.get_modules_status) };
      }
      return copy(states[name]);
    },
    definePlugin: callback => callback,
    setTimeout: (fn, ms) => addTimer(fn, ms, null), clearTimeout: id => timers.delete(id),
    setInterval: (fn, ms) => addTimer(fn, ms, ms), clearInterval: id => timers.delete(id)
  });
  const { frontend } = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  const sources = await Promise.all(frontend.filter(name => name !== "src/decky.js").map(name => readFile(new URL(`../${name}`, import.meta.url), "utf8")));
  vm.runInContext(sources.join("\n").replace("export default definePlugin", "globalThis.plugin = definePlugin"), context);
  const run = expression => vm.runInContext(expression, context);
  const render = (name = component) => { component = name; cursor = 0; if (!hooks.has(component)) hooks.set(component, []); return run(`${name}()`); };
  return {
    calls, run, render,
    set: (name, changes) => { states[name] = { ...states[name], ...copy(changes) }; },
    state: name => copy(states[name]),
    override: (name, fn) => { overrides[name] = fn; },
    sent: name => calls.filter(call => call[0] === name),
    mount: async (name = component) => {
      hooks.set(name, []); mounting = true; render(name); mounting = false;
      const cleanup = effect(); await tick();
      return { tree: render(name), unmount: cleanup };
    },
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const entry = [...timers.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!entry) break;
        const [id, timer] = entry; now = timer.at;
        if (timer.interval === null) timers.delete(id); else timer.at += timer.interval;
        timer.fn(); await tick();
      }
      now = target; await tick();
    }
  };
}
export function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...tree.children.flatMap(nodes)];
}
export function text(tree) {
  if (typeof tree === "string" || typeof tree === "number") return String(tree);
  return tree && typeof tree === "object" ? tree.children.map(text).join(" ") : "";
}
export const item = (tree, type, label) => nodes(tree).find(node => node.type === type && (label === undefined || node.props.label === label));
export const button = (tree, label) => nodes(tree).find(node => ["ButtonItem", "DialogButton"].includes(node.type) && text(node).trim() === label);
export const popButtons = tree => nodes(tree).filter(node => node.type === "DialogButton" && /^Pop /.test(node.props["aria-label"] || ""));
export function choice(tree, label) {
  const group = nodes(tree).find(node => node.props.role === "radiogroup" && node.props["aria-label"] === label);
  if (!group) return undefined;
  const options = group.children.filter(node => node && node.type === "DialogButton");
  return { props: {
    selectedOption: options.find(node => node.props["aria-checked"])?.props["data-choice"],
    disabled: options.every(node => node.props.disabled),
    rgOptions: options.filter(node => !node.props.disabled).map(node => ({ label: node.props["aria-label"], data: node.props["data-choice"] })),
    onChange: ({ data }) => options.find(node => node.props["data-choice"] === data).props.onClick()
  } };
}
export async function openHelp(ui, back) {
  await ui.mount("HelpPanel");
  button(ui.render("HelpPanel"), "Help & details").props.onClick();
  const help = text(ui.render("HelpPanel"));
  ui.render(back);
  return help;
}
