// SPDX-License-Identifier: GPL-3.0-or-later
function Controls() { return h(R.Fragment, null, h(FanPanel), h(LightingPanel), h(ModulesPanel), h(HelpPanel)); }

export default definePlugin(() => ({
  title: h("div", { className: window.DFL.staticClasses.Title }, "Ayaneo 3 Decky"),
  content: h(Controls), icon: h(FanIcon)
}));
