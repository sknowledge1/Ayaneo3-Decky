// SPDX-License-Identifier: GPL-3.0-or-later
const lastDetail = view => view.status?.diagnostic || view.diagnostic;
let scrollHelp = false;
function HelpPanel() {
  useControl(null, 0, modulesView, fanView, lightingView);
  const [open, show] = R.useState(false);
  const details = [["module", modulesView], ["fan", fanView], ["lighting", lightingView]]
    .map(([name, view]) => [name, lastDetail(view)]).filter(([, text]) => text);
  return h(PanelSection, null,
    row("help-rule", h("div", { style: { borderTop: "1px solid rgba(255,255,255,.1)", margin: "8px 0 2px" } })),
    disclosure("help-toggle", "Help & details", open, () => { scrollHelp = !open; show(!open); }),
    open && row("help", h("div", { ref: element => { if (element && scrollHelp) { scrollHelp = false; element.scrollIntoView?.({ block: "nearest", behavior: "smooth" }); } } },
      note(h(R.Fragment, null, h("b", null, "Fan: "), "Quiet, Manual and Curve keep working with this menu closed.",
        fanView.status?.can_configure === false ? "" : " If the temperature can't be read, the device controls the fan until a reading returns.",
        " When Decky stops normally, the device takes the fan back; if Decky crashes, the fan keeps its last speed until Decky starts again.")),
      note(h(R.Fragment, null, h("b", null, "Modules: "), "After refitting, input and lighting come back only while Decky is running.")),
      modulesView.status?.notice && note(modulesView.status.notice),
      ...details.map(([name, text]) => note(`Last ${name} error: ${text}`)))));
}
