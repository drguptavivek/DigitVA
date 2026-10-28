import { requireOptionalNativeModule } from "expo";
import { isIcd11DorisEnabled } from "../icd11DorisPreference";
import type { SmartVaRequest } from "./contracts";

export interface NativeSmartvaModule {
  isAvailable(): Promise<boolean>;
  init(): Promise<{ ok: boolean; error?: string; version?: string; ms?: number }>;
  score(requestJson: string): Promise<{ ok: boolean; error?: string; text?: string; ms?: number; nativeMs?: number; version?: string }>;
}

export interface OfflineSmartvaEngine {
  available(): Promise<boolean>;
  init(): Promise<{ ok: boolean; error?: string; version?: string; ms: number }>;
  score(request: SmartVaRequest): Promise<{ ok: boolean; error?: string; text?: string; ms: number; nativeMs?: number; version?: string }>;
}

type Clock = () => number;
type SmartvaInitResult = { ok: boolean; error?: string; version?: string; ms: number };
const clock: Clock = () => globalThis.performance?.now?.() ?? Date.now();
const disabled = "icd11_doris_disabled";

function processStopped(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error
    && (error as { code?: unknown }).code === "ERR_SMARTVA_PROCESS";
}

/** Build over an optional native bridge. Init only reads the library version; scoring lazily loads its matching model. */
export function createOfflineSmartvaEngine(
  native: NativeSmartvaModule | null | undefined,
  enabled: () => Promise<boolean> = isIcd11DorisEnabled,
  now: Clock = clock,
): OfflineSmartvaEngine {
  let readyVersion: string | undefined;
  let initFlight: Promise<SmartvaInitResult> | undefined;

  async function allowed(): Promise<boolean> {
    try { return await enabled(); } catch { return false; }
  }

  async function runInit(retryProcess = true): Promise<SmartvaInitResult> {
    const start = now();
    if (!native) return { ok: false, error: "unavailable", ms: 0 };
    try {
      const result = await native.init();
      if (!result.ok) return { ok: false, error: result.error ?? "init_failed", ms: now() - start };
      readyVersion = result.version;
      return { ok: true, version: result.version, ms: now() - start };
    } catch (error) {
      if (retryProcess && processStopped(error)) return runInit(false);
      return { ok: false, error: "native_error", ms: now() - start };
    }
  }

  function initialize(): Promise<SmartvaInitResult> {
    if (readyVersion) return Promise.resolve({ ok: true, version: readyVersion, ms: 0 });
    initFlight ??= runInit().finally(() => { initFlight = undefined; });
    return initFlight;
  }

  async function score(request: SmartVaRequest) {
    const start = now();
    if (!await allowed()) return { ok: false, error: disabled, ms: 0 };
    if (!native) return { ok: false, error: "unavailable", ms: 0 };
    if (!request || request.schema_version !== 1 || !request.input || !request.options) {
      return { ok: false, error: "bad_request", ms: 0 };
    }
    let initialized = await initialize();
    if (!initialized.ok) return { ok: false, error: initialized.error, ms: now() - start };
    const requestJson = JSON.stringify(request);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const result = await native.score(requestJson);
        return {
          ok: result.ok,
          ...(result.ok && result.text !== undefined ? { text: result.text } : {}),
          ...(!result.ok ? { error: result.error ?? "engine_error" } : {}),
          ms: now() - start,
          ...(result.nativeMs !== undefined ? { nativeMs: result.nativeMs } : {}),
          version: result.version ?? readyVersion,
        };
      } catch (error) {
        if (attempt !== 0 || !processStopped(error)) {
          return { ok: false, error: "native_error", ms: now() - start };
        }
        readyVersion = undefined;
        initialized = await initialize();
        if (!initialized.ok) return { ok: false, error: initialized.error, ms: now() - start };
      }
    }
    return { ok: false, error: "native_error", ms: now() - start };
  }

  return {
    async available() {
      if (!native) return false;
      try { return await native.isAvailable(); } catch { return false; }
    },
    async init() {
      if (!await allowed()) return { ok: false, error: disabled, ms: 0 };
      return initialize();
    },
    score,
  };
}

/** The plain build and web have no module; merely importing this adapter does not bind or initialize the engine. */
let shared: OfflineSmartvaEngine | undefined;
export function offlineSmartvaEngine(): OfflineSmartvaEngine {
  if (!shared) shared = createOfflineSmartvaEngine(requireOptionalNativeModule<NativeSmartvaModule>("DigitvaSmartva"));
  return shared;
}
