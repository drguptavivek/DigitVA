/**
 * Coordinates the anonymous service-worker cache with browser auth state.
 *
 * The worker only receives a release, group and generation. It never receives
 * an account id, access response, form definition or clinical answer.
 */
type NetworkInformationLike = {
  effectiveType?: string;
  saveData?: boolean;
  addEventListener?: (type: "change", listener: () => void) => void;
};

type IdleWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  cancelIdleCallback?: (handle: number) => void;
  __DIGITVA_WEB_RELEASE__?: string;
};

let eligible = false;
let generation = 0;
let activeContextGeneration: number | undefined;
let pendingTimer: number | undefined;
let listenersInstalled = false;
let manualWarmActive = false;

function browserAvailable(): boolean {
  return typeof window !== "undefined" && typeof document !== "undefined"
    && typeof navigator !== "undefined" && "serviceWorker" in navigator;
}

function visibleAndOnline(): boolean {
  return document.visibilityState === "visible" && navigator.onLine !== false;
}

function goodAutomaticConnection(): boolean {
  const connection = (navigator as Navigator & { connection?: NetworkInformationLike }).connection;
  return connection?.saveData !== true && connection?.effectiveType === "4g";
}

function cancelPendingTimer(): void {
  if (pendingTimer === undefined || typeof window === "undefined") return;
  const idleWindow = window as IdleWindow;
  if (idleWindow.cancelIdleCallback) idleWindow.cancelIdleCallback(pendingTimer);
  else window.clearTimeout(pendingTimer);
  pendingTimer = undefined;
}

function post(type: "cancel-interview-assets" | "warm-interview-assets", currentGeneration: number, manual = false): void {
  if (!browserAvailable()) return;
  const expectedGeneration = currentGeneration;
  const release = (window as IdleWindow).__DIGITVA_WEB_RELEASE__;
  if (!release) return;
  void navigator.serviceWorker.ready.then((registration) => {
    if (!eligible || expectedGeneration !== generation || !visibleAndOnline()) return;
    registration.active?.postMessage({
      type,
      release,
      group: type === "warm-interview-assets" ? "interviewRuntime" : undefined,
      generation: expectedGeneration,
      ...(manual ? { manual: true } : {}),
    });
  }).catch(() => undefined);
}

function cancelWarm(): void {
  cancelPendingTimer();
  generation += 1;
  if (browserAvailable()) {
    // Cancellation is allowed after eligibility is revoked as well. The
    // worker validates release/generation and ignores stale starts.
    const currentGeneration = generation;
    const release = (window as IdleWindow).__DIGITVA_WEB_RELEASE__;
    if (!release) return;
    void navigator.serviceWorker.ready.then((registration) => {
      registration.active?.postMessage({
        type: "cancel-interview-assets", release, generation: currentGeneration,
      });
    }).catch(() => undefined);
  }
}

function scheduleAutomaticWarm(): void {
  if (!eligible || !browserAvailable() || !visibleAndOnline() || !goodAutomaticConnection()) return;
  cancelPendingTimer();
  const currentGeneration = generation;
  const start = () => {
    pendingTimer = undefined;
    if (!eligible || currentGeneration !== generation || !visibleAndOnline() || !goodAutomaticConnection()) return;
    post("warm-interview-assets", currentGeneration);
  };
  const idleWindow = window as IdleWindow;
  pendingTimer = idleWindow.requestIdleCallback
    ? idleWindow.requestIdleCallback(start, { timeout: 15_000 })
    : window.setTimeout(start, 3_000);
}

function installListeners(): void {
  if (listenersInstalled || !browserAvailable()) return;
  listenersInstalled = true;
  const environmentChanged = () => {
    if (!eligible) return;
    if (!visibleAndOnline()) {
      manualWarmActive = false;
      cancelWarm();
    } else if (!goodAutomaticConnection()) {
      // A manual download is an explicit user choice and may continue on a
      // metered/slow link; automatic warming must stop immediately.
      if (!manualWarmActive) cancelWarm();
    } else if (!manualWarmActive) scheduleAutomaticWarm();
  };
  document.addEventListener("visibilitychange", environmentChanged);
  window.addEventListener("online", environmentChanged);
  window.addEventListener("offline", environmentChanged);
  window.addEventListener("pageshow", environmentChanged);
  const connection = (navigator as Navigator & { connection?: NetworkInformationLike }).connection;
  connection?.addEventListener?.("change", environmentChanged);
}

/** Start or stop the post-login WHO interview asset warm for the current account. */
export function setInterviewAssetWarmEligibility(value: boolean, context?: number): void {
  installListeners();
  if (context !== undefined && context !== activeContextGeneration) {
    activeContextGeneration = context;
    if (eligible) cancelWarm();
    eligible = false;
    manualWarmActive = false;
  }
  if (!value && !eligible) {
    cancelPendingTimer();
    manualWarmActive = false;
    return;
  }
  if (eligible === value && value) {
    scheduleAutomaticWarm();
    return;
  }
  eligible = value;
  if (!eligible) manualWarmActive = false;
  cancelWarm();
  if (eligible) scheduleAutomaticWarm();
}

/** Explicit UI hook for a later “download interview resources” action. */
export function warmInterviewAssetsNow(): void {
  installListeners();
  if (!eligible || !browserAvailable() || !visibleAndOnline()) return;
  cancelPendingTimer();
  generation += 1;
  manualWarmActive = true;
  post("warm-interview-assets", generation, true);
}
