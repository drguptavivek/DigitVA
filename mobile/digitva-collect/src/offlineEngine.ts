/**
 * Offline WHO ICD-11 / DORIS engine of the Collect Plus build (modules/digitva-icd11, the same ICD-API 2.6.0 code
 * the server runs). Every result carries timings in milliseconds. The plain build and the web have no native module:
 * available() is false and every call answers { ok: false, error: "unavailable" }.
 *
 * Init runs once per engine process on the module's worker thread; a failure is sticky until that process restarts.
 * Concurrent init() calls share one in-flight request, so the start-up warm-up and a screen that opens coding mid-way
 * wait for the same init. Calls are serialized by the worker thread; if Android killed the engine process, a call
 * re-inits once and retries. Failed calls carry a status or a short code, never the engine's payload, which can hold
 * stack traces or certificate text. Do not log certificates passed to doris()/codedit() either.
 *
 * WHO files are fetched only by the first setup, a missing or wrong-size WHO file, or updateWhoFiles() (the user's
 * explicit request). updateWhoFiles() ends the engine process and runs one fetching init in a new one; calls made while
 * it runs wait for it, like an init.
 */
import { requireOptionalNativeModule } from "expo";
import { InteractionManager } from "react-native";
import { isIcd11DorisEnabled } from "./icd11DorisPreference";

/** The ops the engine bridge answers (Bridge.cs `Dispatch` is the only allow-list; the native module passes the name through). */
export type EngineOp = "search" | "codeinfo" | "entity" | "foundation_entity" | "doris" | "codedit";

/** Optional arguments of `search`; absent ones take WHO's defaults (LinearizationController.SearchLinearization). */
export interface SearchOptions {
  subtreesFilter?: string;
  subtreeFilterUsesFoundationDescendants?: boolean;
  includeKeywordResult?: boolean;
  chapterFilter?: string;
  includePostcoordination?: boolean;
  useFlexisearch?: boolean;
  flatResults?: boolean;
  highlightingEnabled?: boolean;
  medicalCodingMode?: boolean;
  propertiesToBeSearched?: string;
  /** DigitVA addition, not WHO's: keep at most this many `destinationEntities` (integer 1 to 200; others are a 400) and set `resultChopped` when it cut any. */
  limit?: number;
}

/** Optional arguments of `codeinfo` (GetCodeInfo). */
export interface CodeinfoOptions {
  flexiblemode?: boolean;
  convertToTerminalCodes?: boolean;
}

/** Optional arguments of `entity`: `residual` ("unspecified" or "other") reads the residual child; `include` is WHO's (ancestor, diagnosticCriteria); `descendant` is refused (400) because the reply is a whole subtree. */
export interface EntityOptions {
  residual?: string;
  include?: string;
}

/** What the native module returns (modules/digitva-icd11/android/.../DigitvaIcd11Module.kt). */
export interface NativeInit {
  ok: boolean;
  error?: string;
  copyMs: number;
  initMs: number;
  ms: number;
  cached: boolean;
  phases?: string;
  setup?: string;
}

export interface NativeEngine {
  isAvailable(): Promise<boolean>;
  init(): Promise<NativeInit>;
  /** Ends the engine process and fetches WHO files in a new one, when online; "no_connection" otherwise. */
  updateWhoFiles(): Promise<NativeInit>;
  /** `input` is the JSON object of named arguments of `op` (see the bridge's Dispatch); the reply `text` is WHO's REST JSON. */
  call(op: EngineOp, input: string): Promise<{ ok: boolean; error?: string; status: number; text?: string; nativeMs: number }>;
  addListener?(event: "icd11Progress", listener: (progress: { phase: string; percent: number }) => void): { remove(): void };
}

/**
 * How the engine's first setup ran: "downloaded" (the setup init fetched WHO files; `files` are what it changed or
 * added, names and sizes only) or "shipped" (only the copies in the APK). "attempt" is never returned once init is ok.
 */
export interface EngineSetup {
  mode: "downloaded" | "shipped" | "attempt";
  files: { path: string; size: number }[];
}

export type EngineInit =
  | { ok: true; ms: number; copyMs: number; initMs: number; cached: boolean; phases?: string; setup?: EngineSetup }
  | { ok: false; error: string; ms: number };

/** An init in progress: `phase` is copy, setup, engine or ready; `percent` is 0-100 when known. */
export interface EngineProgress {
  phase: string;
  percent?: number;
}

/** Parses the native setup record. Anything unexpected reads as no setup record. */
export function parseSetup(text: string | undefined): EngineSetup | undefined {
  if (!text) return undefined;
  try {
    const value = JSON.parse(text) as { mode?: unknown; files?: unknown };
    if (typeof value.mode !== "string" || !Array.isArray(value.files)) return undefined;
    const files = value.files
      .filter((file) => typeof file?.path === "string" && typeof file?.size === "number")
      .map((file: { path: string; size: number }) => ({ path: file.path, size: file.size }));
    return { mode: value.mode as EngineSetup["mode"], files };
  } catch {
    return undefined;
  }
}

export type EngineResult =
  | { ok: true; data: unknown; status: number; ms: number; nativeMs: number }
  | { ok: false; error: string; status?: number; ms: number };

export interface OfflineEngine {
  available(): Promise<boolean>;
  init(): Promise<EngineInit>;
  /**
   * The background warm-up: asks the native side even when this wrapper thinks the engine is ready, because Android
   * may have ended the engine process alone. A live, initialised engine answers at once as cached (EngineHost.init), so
   * a warm engine is never warmed twice; only a new process runs the full init.
   */
  warm(): Promise<EngineInit>;
  /** Explicit update of the WHO files (one fetching init in a new engine process). Never throws. */
  updateWhoFiles(): Promise<EngineInit>;
  /** One engine call: `args` is the object of named arguments of `op`; `data` of the result is WHO's REST JSON for that action. */
  call(op: EngineOp, args: Record<string, unknown>): Promise<EngineResult>;
  /** Pass the server's `q` ("<text>%") and flags in `options` for the same hits as the server. */
  search(query: string, options?: SearchOptions): Promise<EngineResult>;
  codeinfo(code: string, options?: CodeinfoOptions): Promise<EngineResult>;
  /** A linearization (mms 2026-01) entity by its numeric id. */
  entity(id: string, options?: EntityOptions): Promise<EngineResult>;
  /** A foundation entity by its numeric id; only `include` applies. */
  foundationEntity(id: string, options?: Pick<EntityOptions, "include">): Promise<EngineResult>;
  /** `certificate` is the DORIS certificate JSON object the server's process endpoint takes. */
  doris(certificate: unknown): Promise<EngineResult>;
  codedit(certificate: unknown): Promise<EngineResult>;
  /** Progress of the init while it runs (copy, setup, engine, ready). Returns the unsubscribe. */
  onProgress(listener: (progress: EngineProgress) => void): () => void;
}

const clock = (): number => globalThis.performance?.now?.() ?? Date.now();

/** Build the API over a native module (or none) and a clock; tests pass fakes. */
export function createOfflineEngine(native: NativeEngine | null | undefined, now: () => number = clock): OfflineEngine {
  let inflight: Promise<EngineInit> | undefined;
  let ready: Extract<EngineInit, { ok: true }> | undefined;
  const progressListeners = new Set<(progress: EngineProgress) => void>();
  native?.addListener?.("icd11Progress", (event) => {
    const progress: EngineProgress = { phase: event.phase, percent: event.percent < 0 ? undefined : event.percent };
    for (const listener of progressListeners) listener(progress);
  });

  /** One native init (plain or the explicit update), timed; never rejects. */
  async function runInit(start: () => Promise<NativeInit>): Promise<EngineInit> {
    const began = now();
    if (!native) return { ok: false, error: "unavailable", ms: 0 };
    try {
      const raw = await start();
      const ms = now() - began;
      if (!raw.ok) return { ok: false, error: raw.error ?? "init_failed", ms };
      return (ready = { ok: true, ms, copyMs: raw.copyMs, initMs: raw.initMs, cached: raw.cached, phases: raw.phases, setup: parseSetup(raw.setup) });
    } catch {
      return { ok: false, error: "native_error", ms: now() - began };
    }
  }

  /** One init per engine process: concurrent callers share the in-flight request, later ones get it as cached. */
  function init(): Promise<EngineInit> {
    if (ready) return Promise.resolve({ ...ready, ms: 0, cached: true });
    inflight ??= runInit(() => native!.init()).finally(() => {
      inflight = undefined;
    });
    return inflight;
  }

  function warm(): Promise<EngineInit> {
    if (!inflight) ready = undefined;
    return init();
  }

  /**
   * Waits for any init or update in progress, then runs one update. Calls made meanwhile wait on the same in-flight
   * slot (callNative() awaits it), so they run on the updated engine.
   */
  function updateWhoFiles(): Promise<EngineInit> {
    const previous = inflight;
    ready = undefined;
    const update = (async (): Promise<EngineInit> => {
      if (previous) await previous;
      return runInit(() => native!.updateWhoFiles());
    })();
    const settled: Promise<EngineInit> = update.finally(() => {
      if (inflight === settled) inflight = undefined;
    });
    inflight = settled;
    return settled;
  }

  /** Android can kill the engine process (low memory) while the app lives; its next incarnation needs a new init. */
  async function callNative(op: EngineOp, input: string): Promise<Awaited<ReturnType<NativeEngine["call"]>>> {
    // A re-init after a lost process may be under way; calling before it lands would hit an uninitialised engine.
    if (inflight) await inflight;
    const wasReady = ready !== undefined;
    try {
      const raw = await native!.call(op, input);
      if (raw.ok || raw.error !== "not_initialized" || !wasReady) return raw;
    } catch (error) {
      if (!wasReady || (error as { code?: string }).code !== "ERR_ICD11_PROCESS") throw error;
    }
    ready = undefined;
    const again = await init();
    if (!again.ok) return { ok: false, error: again.error, status: 0, nativeMs: 0 };
    return native!.call(op, input);
  }

  async function run(op: EngineOp, args: Record<string, unknown>): Promise<EngineResult> {
    const start = now();
    if (!native) return { ok: false, error: "unavailable", ms: 0 };
    try {
      const raw = await callNative(op, JSON.stringify(args));
      const ms = now() - start;
      if (!raw.ok || raw.text === undefined) return { ok: false, error: raw.error ?? "engine_error", status: raw.status, ms };
      try {
        return { ok: true, data: JSON.parse(raw.text), status: raw.status, ms, nativeMs: raw.nativeMs };
      } catch {
        return { ok: false, error: "bad_json", status: raw.status, ms };
      }
    } catch {
      return { ok: false, error: "native_error", ms: now() - start };
    }
  }

  return {
    async available() {
      if (!native) return false;
      try {
        return await native.isAvailable();
      } catch {
        return false;
      }
    },
    init,
    warm,
    updateWhoFiles,
    call: run,
    search: (q, options) => run("search", { q, ...options }),
    codeinfo: (code, options) => run("codeinfo", { code, ...options }),
    entity: (id, options) => run("entity", { id, ...options }),
    foundationEntity: (id, options) => run("foundation_entity", { id, ...options }),
    doris: (certificate) => run("doris", { certificate }),
    codedit: (certificate) => run("codedit", { certificate }),
    onProgress(listener) {
      progressListeners.add(listener);
      return () => {
        progressListeners.delete(listener);
      };
    },
  };
}

/** The process-wide engine; resolves the native module on first use (null on web and in the plain build). */
let shared: OfflineEngine | undefined;
export function offlineEngine(): OfflineEngine {
  if (!shared) {
    const engine = createOfflineEngine(requireOptionalNativeModule<NativeEngine>("DigitvaIcd11"));
    const disabledInit: EngineInit = { ok: false, error: "icd11_doris_disabled", ms: 0 };
    const disabledResult: EngineResult = { ok: false, error: "icd11_doris_disabled", ms: 0 };
    const enabled = () => isIcd11DorisEnabled();
    /** The same call, answered as disabled while the preference is off. */
    const gated = <A extends unknown[]>(f: (...args: A) => Promise<EngineResult>) => async (...args: A) => (await enabled() ? f(...args) : disabledResult);
    shared = {
      ...engine,
      async init() { return await enabled() ? engine.init() : disabledInit; },
      async warm() { return await enabled() ? engine.warm() : disabledInit; },
      async updateWhoFiles() { return await enabled() ? engine.updateWhoFiles() : disabledInit; },
      call: gated(engine.call),
      search: gated(engine.search),
      codeinfo: gated(engine.codeinfo),
      entity: gated(engine.entity),
      foundationEntity: gated(engine.foundationEntity),
      doris: gated(engine.doris),
      codedit: gated(engine.codedit),
    };
  }
  return shared;
}

/**
 * Start the engine in the background so it is ready before the coder opens a case: init takes ~18 s on a phone and the
 * work is CPU bound, so it waits until the first screen has rendered and animations are done. Never throws; logs one
 * timing line (no payload).
 */
export function warmUpOfflineEngine(engine: OfflineEngine, log: (line: string) => void = console.log): Promise<void> {
  return engine.available().then(async (available) => {
    if (!available) return;
    const init = await engine.warm();
    log(`ICD11WARM ready=${init.ok} ms=${init.ms.toFixed(0)}${init.ok ? ` cached=${init.cached}` : ` error=${init.error}`} at=${Date.now()}`);
  });
}

/**
 * runAfterInteractions never fires while a looping animation (a spinner on the sign-in or unlock screen) holds an
 * interaction handle, so the warm-up also starts after `fallbackMs` at the latest. The task runs once.
 */
export function afterInteractionsOrTimeout(task: () => void, fallbackMs = 5000): { cancel: () => void } {
  let done = false;
  const once = () => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    task();
  };
  const timer = setTimeout(once, fallbackMs);
  const handle = InteractionManager.runAfterInteractions(once);
  return {
    cancel: () => {
      done = true;
      clearTimeout(timer);
      handle.cancel();
    },
  };
}

/** Schedule the warm-up after interactions plus `delayMs`; the returned function cancels one that has not started. */
export function scheduleEngineWarmUp(
  engine: OfflineEngine = offlineEngine(),
  delayMs = 1000,
  afterInteractions: (task: () => void) => { cancel: () => void } = afterInteractionsOrTimeout,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const handle = afterInteractions(() => {
    timer = setTimeout(() => void warmUpOfflineEngine(engine).catch(() => undefined), delayMs);
  });
  return () => {
    handle.cancel();
    if (timer) clearTimeout(timer);
  };
}
