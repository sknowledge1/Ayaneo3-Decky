// SPDX-License-Identifier: GPL-3.0-or-later
const copyConfig = value => JSON.parse(JSON.stringify(value));
const SLIDER_DELAY_MS = 200;
const sameConfig = (config, draft) => Object.keys(draft).every(key => JSON.stringify(config?.[key]) === JSON.stringify(draft[key]));
const listenable = view => Object.assign(view, { listeners: new Set(), publish: () => view.listeners.forEach(listener => listener()) });
function managedControl({ read, write, check, initial, shown = status => status.config, confirmed }) {
  const view = listenable({
    status: null, draft: copyConfig(initial), dirty: false, sending: false, polling: false,
    queued: null, timer: null, generation: 0, error: "", statusError: "", starting: false, diagnostic: "", blocked: false
  });
  view.stopQueue = () => {
    if (view.timer !== null) clearTimeout(view.timer);
    view.timer = null;
    view.queued = null;
  };
  view.refresh = async () => {
    if (view.polling || view.sending) return;
    view.polling = true;
    const generation = view.generation;
    try {
      const status = check(await read());
      if (generation !== view.generation) return;
      view.status = status;
      view.statusError = "";
      view.starting = false;
      if (view.blocked && view.dirty && view.queued === null && view.timer === null && sameConfig(status.config, view.draft) && confirmed(status)) {
        view.blocked = false; view.dirty = false; view.error = "";
      }
      if (!view.dirty) view.draft = copyConfig(shown(status, initial));
    } catch (cause) {
      if (generation === view.generation) {
        view.status = null;
        view.statusError = cause.message || String(cause);
        view.starting = !!cause.starting;
        if ("diagnostic" in cause) view.diagnostic = cause.diagnostic;
        view.stopQueue();
        view.blocked = view.dirty;
      }
    } finally { view.polling = false; view.publish(); }
  };
  view.drain = async () => {
    if (view.sending || !view.queued || view.timer !== null || view.blocked) return;
    const request = view.queued;
    view.queued = null;
    view.sending = true;
    view.publish();
    try {
      const response = await write(copyConfig(request.config));
      if (!response?.ok) {
        if (response?.state?.ok) view.status = check(response.state);
        throw new Error(response?.error || "The setting could not be applied.");
      }
      view.status = check(response);
      view.statusError = "";
      if (request.generation === view.generation && !view.queued && view.timer === null) {
        view.draft = copyConfig(view.status.config);
        view.dirty = false;
      }
    } catch (cause) {
      view.error = cause.message || String(cause);
      view.blocked = true;
      view.stopQueue();
    } finally {
      view.sending = false;
      view.publish();
      if (view.blocked) await view.refresh();
      else if (view.queued && view.timer === null) return view.drain();
    }
  };
  view.edit = (changes, immediate = false) => {
    if (!view.status) return;
    view.draft = { ...copyConfig(view.draft), ...copyConfig(changes) };
    view.generation++;
    view.dirty = true;
    view.blocked = false;
    view.error = "";
    view.stopQueue();
    view.queued = { config: copyConfig(view.draft), generation: view.generation };
    if (!immediate) view.timer = setTimeout(() => { view.timer = null; view.drain(); }, SLIDER_DELAY_MS);
    view.publish();
    if (immediate) return view.drain();
  };
  view.retry = () => view.edit({}, true);
  return view;
}
