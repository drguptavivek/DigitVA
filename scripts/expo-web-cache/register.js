/* Injected only into a production export, never into Metro/HMR. */
(() => {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  const release = __DIGITVA_RELEASE__;
  window.__DIGITVA_WEB_RELEASE__ = release;
  async function register() {
    try {
      await navigator.serviceWorker.register("/app/asset-worker.js", {
        scope: "/app/", updateViaCache: "none",
      });
      // Registration is intentionally anonymous. AppState.web starts the
      // interview-only warm after authenticated access is known; this keeps
      // login, coding and coder-only sessions cache-light.
    } catch {
      // Storage restrictions or offline registration must not prevent normal app loading.
    }
  }
  if (document.readyState === "complete") void register();
  else window.addEventListener("load", register, { once: true });
})();
