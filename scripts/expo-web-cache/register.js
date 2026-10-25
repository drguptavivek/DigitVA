/* Injected only into a production export, never into Metro/HMR. */
(() => {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  const release = __DIGITVA_RELEASE__;
  async function register() {
    try {
      await navigator.serviceWorker.register("/app/asset-worker.js", {
        scope: "/app/", updateViaCache: "none",
      });
      const registration = await navigator.serviceWorker.ready;
      const connection = navigator.connection;
      if (connection?.saveData || connection?.effectiveType !== "4g") return;
      const warm = () => {
        if (document.visibilityState === "visible" && navigator.onLine !== false) {
          registration.active?.postMessage({ type: "warm-public-assets", release });
        }
      };
      if ("requestIdleCallback" in window) window.requestIdleCallback(warm, { timeout: 10000 });
      else window.setTimeout(warm, 3000);
    } catch {
      // Storage restrictions or offline registration must not prevent normal app loading.
    }
  }
  if (document.readyState === "complete") void register();
  else window.addEventListener("load", register, { once: true });
})();
