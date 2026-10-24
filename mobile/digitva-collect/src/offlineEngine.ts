/**
 * Offline WHO ICD-11 / DORIS engine of the Collect Plus build (modules/digitva-icd11, the same ICD-API 2.6.0 code
 * the server runs). Every result carries timings in milliseconds. The plain build and the web have no native module:
 * available() is false and every call answers { ok: false, error: "unavailable" }.
 *
 * Init runs once per process on the module's worker thread; a failure is sticky until the app restarts. Calls are
 * serialized by that thread. Failed calls carry a status or a short code, never the engine's payload, which can hold
 * stack traces or certificate text. Do not log certificates passed to doris()/codedit() either.
 */
import { requireOptionalNativeModule } from "expo";

export type EngineOp = "search" | "codeinfo" | "doris" | "codedit";

/** What the native module returns (modules/digitva-icd11/android/.../DigitvaIcd11Module.kt). */
export interface NativeEngine {
  isAvailable(): Promise<boolean>;
  init(): Promise<{ ok: boolean; error?: string; copyMs: number; initMs: number; ms: number; cached: boolean }>;
  call(op: EngineOp, input: string): Promise<{ ok: boolean; error?: string; status: number; text?: string; nativeMs: number }>;
}

export type EngineInit =
  | { ok: true; ms: number; copyMs: number; initMs: number; cached: boolean }
  | { ok: false; error: string; ms: number };

export type EngineResult =
  | { ok: true; data: unknown; status: number; ms: number; nativeMs: number }
  | { ok: false; error: string; status?: number; ms: number };

export interface OfflineEngine {
  available(): Promise<boolean>;
  init(): Promise<EngineInit>;
  search(query: string): Promise<EngineResult>;
  codeinfo(code: string): Promise<EngineResult>;
  /** `certificate` is the DORIS certificate JSON object the server's process endpoint takes. */
  doris(certificate: unknown): Promise<EngineResult>;
  codedit(certificate: unknown): Promise<EngineResult>;
}

const clock = (): number => globalThis.performance?.now?.() ?? Date.now();

/** Build the API over a native module (or none) and a clock; tests pass fakes. */
export function createOfflineEngine(native: NativeEngine | null | undefined, now: () => number = clock): OfflineEngine {
  async function run(op: EngineOp, input: string): Promise<EngineResult> {
    const start = now();
    if (!native) return { ok: false, error: "unavailable", ms: 0 };
    try {
      const raw = await native.call(op, input);
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
    async init() {
      const start = now();
      if (!native) return { ok: false, error: "unavailable", ms: 0 };
      try {
        const raw = await native.init();
        const ms = now() - start;
        return raw.ok
          ? { ok: true, ms, copyMs: raw.copyMs, initMs: raw.initMs, cached: raw.cached }
          : { ok: false, error: raw.error ?? "init_failed", ms };
      } catch {
        return { ok: false, error: "native_error", ms: now() - start };
      }
    },
    search: (query) => run("search", query),
    codeinfo: (code) => run("codeinfo", code),
    doris: (certificate) => run("doris", JSON.stringify(certificate)),
    codedit: (certificate) => run("codedit", JSON.stringify(certificate)),
  };
}

/** The process-wide engine; resolves the native module on first use (null on web and in the plain build). */
let shared: OfflineEngine | undefined;
export function offlineEngine(): OfflineEngine {
  shared ??= createOfflineEngine(requireOptionalNativeModule<NativeEngine>("DigitvaIcd11"));
  return shared;
}
