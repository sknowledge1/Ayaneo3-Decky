// SPDX-License-Identifier: GPL-3.0-or-later
// PLUGIN_NAME is defined by the build script.
const deckyConnection = (() => {
  const loader = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
  if (typeof loader?.connect !== "function") throw new Error("Ayaneo 3 Decky: Decky Loader's plugin interface is unavailable.");
  const connection = loader.connect(2, PLUGIN_NAME);
  if (typeof connection?.callable !== "function") throw new Error("Ayaneo 3 Decky needs a Decky Loader with backend calls (API 2).");
  return connection;
})();
const CALL_TIMEOUT_MS = 8000;
// Decky does not restart a backend that stopped; without a time limit the panel would freeze on old values.
const callable = name => {
  const call = deckyConnection.callable(name);
  return (...args) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("The plugin is not responding. Restart Decky.")), CALL_TIMEOUT_MS);
    call(...args).then(resolve, reject).finally(() => clearTimeout(timer));
  });
};
const definePlugin = factory => factory;
