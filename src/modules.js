// SPDX-License-Identifier: GPL-3.0-or-later
const getModulesStatus = callable("get_modules_status"), popModule = callable("pop_module");
const modulesView = listenable({ status: null, error: "", errorTechnical: false, statusError: "", starting: false, diagnostic: "", release: null,
  popAttempt: false, sending: false, polling: false, generation: 0, connectedUntil: 0, successTimer: null, refresh: refreshModules });
const canPop = status => !!status?.can_pop && !status.busy && !status.stale;
function acceptModules(status) {
  const failure = status.error || status.status_error;
  if (modulesView.popAttempt && status.phase === "error" && failure) modulesView.release = { text: failure, technical: !!status.diagnostic };
  if (status.phase === "ready" && canPop(status) && modulesView.status && modulesView.status.phase !== "ready") {
    if (modulesView.release) {
      modulesView.error = modulesView.release.text;
      modulesView.errorTechnical = modulesView.release.technical;
    } else {
      modulesView.connectedUntil = Date.now() + 3000;
      if (modulesView.successTimer !== null) clearTimeout(modulesView.successTimer);
      modulesView.successTimer = setTimeout(() => { modulesView.successTimer = null; modulesView.publish(); }, 3000);
      if (!failure) modulesView.error = "";
    }
    modulesView.release = null;
    modulesView.popAttempt = false;
  }
  modulesView.status = status;
  modulesView.statusError = modulesView.diagnostic = "";
  modulesView.starting = false;
}
async function refreshModules() {
  if (modulesView.polling || modulesView.sending) return;
  modulesView.polling = true;
  const generation = modulesView.generation;
  try {
    const status = checkedReply(await getModulesStatus(), "Magic Modules");
    if (generation === modulesView.generation) acceptModules(status);
  } catch (cause) {
    if (generation === modulesView.generation) {
      modulesView.status = null;
      modulesView.statusError = cause.message || String(cause);
      modulesView.diagnostic = cause.diagnostic || "";
      modulesView.starting = !!cause.starting;
    }
  } finally { modulesView.polling = false; modulesView.publish(); }
}
async function requestModulePop(side) {
  if (modulesView.sending || !canPop(modulesView.status)) return;
  modulesView.sending = modulesView.popAttempt = true;
  modulesView.error = ""; modulesView.errorTechnical = false; modulesView.release = null;
  modulesView.generation++; modulesView.publish();
  try {
    const response = await popModule(side);
    if (!response.ok) throw new Error(response.error || "Module release could not start.");
    acceptModules(checkedReply(response.status, "Magic Modules"));
  } catch (cause) {
    modulesView.error = cause.message || String(cause);
    modulesView.status = null;
  } finally { modulesView.sending = false; modulesView.publish(); refreshModules(); }
}
function moduleState() {
  const { status, sending, error, statusError } = modulesView;
  const phase = status?.phase;
  const progress = sending || status?.busy || status?.stale || phase === "activating" || phase === "ejecting";
  const history = error && phase === "ready" && !progress ? error : "";
  const reported = status?.error || status?.status_error || "";
  const fault = (history ? "" : error) || statusError
    || (phase === "error" ? reported || "Check the modules and try again." : phase === "unavailable" ? reported : "");
  const connected = phase === "ready" && !progress && Date.now() < modulesView.connectedUntil;
  const text = fault || (sending || phase === "ejecting" ? "Releasing modules…" : phase === "activating" ? "Connecting…"
    : phase === "waiting" ? "Refit both modules on their original sides to restore input." : progress ? "Checking modules…"
    : connected ? "Connected" : phase === "ready" ? "" : "Reading module status…");
  const tone = fault && !status?.busy && !modulesView.starting ? "error" : progress || !status || phase === "unavailable" ? "progress"
    : connected ? "success" : phase === "waiting" ? "attention" : "normal";
  return { phase, history, text, tone, long: !!fault || phase === "waiting" };
}
function ModulesPanel() {
  useControl(modulesView, 500);
  const { phase, history, text, tone, long } = moduleState();
  const disabled = modulesView.sending || !canPop(modulesView.status);
  const pop = (side, label) => edge => h(DialogButton, { key: side, ...edge, className: "ay3-pop", disabled, onClick: () => requestModulePop(side),
    "aria-label": side === "both" ? "Pop both modules" : `Pop ${side} module` },
    h("b", { style: { display: "flex", alignItems: "center" } }, h(Eject), label));
  return h(PanelSection, { title: "Magic Modules" },
    phase !== "waiting" && row("modules-hint", note(h(R.Fragment, null, h("span", { style: { color: "#e6ebf0", fontWeight: 600 } }, "Hold the device firmly."),
      " Buttons and sticks stop working until both modules are back."))),
    row("pops-caption", caption("Pop", !long && text && statusChip(text, tone))),
    long && statusRow("modules-status", text, tone),
    row("pops", wrapRow("pops", [pop("left", "Left"), pop("right", "Right"), pop("both", "Both")], { className: "ay3-pops" })),
    history && statusRow("modules-history", modulesView.errorTechnical ? "Last pop failed. Details are under Help & details." : `Last pop failed: ${history}`, "attention"));
}
