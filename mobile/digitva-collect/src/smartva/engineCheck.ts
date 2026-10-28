import golden from "./engine-check-golden.json";
import { createSmartVaRequest } from "./input";
import { projectSmartVaResult } from "./projection";
import type { SmartVaOptions, SmartVaReference } from "./contracts";
import type { OfflineSmartvaEngine } from "./nativeEngine";

type CheckCase = {
  id: string;
  input: Record<string, string>;
  expected: SmartVaReference;
  all_symptoms: string | null;
};
type CheckListener = (result: SmartVaEngineCheckResult) => void;

export interface SmartVaEngineCheckCaseResult {
  id: string;
  ok: boolean;
  matched: boolean;
  ms: number;
  nativeMs?: number;
  module?: string | null;
  cause34?: string | null;
  icd10?: string | null;
  topIcd10?: Array<string | null>;
  error?: string;
}

export interface SmartVaEngineCheckResult {
  ok: boolean;
  available: boolean;
  initMs: number;
  version?: string;
  error?: string;
  cases: SmartVaEngineCheckCaseResult[];
  warmRepeat?: SmartVaEngineCheckCaseResult;
}

type Golden = {
  source: { engine_version: string };
  options: SmartVaOptions;
  cases: CheckCase[];
};

const goldenData = golden as unknown as Golden;
const now = () => globalThis.performance?.now?.() ?? Date.now();
const safeErrors = new Set([
  "bad_request", "disabled", "engine_error", "icd11_doris_disabled", "init_failed",
  "native_error", "too_large", "unavailable",
]);

export function engineCheckAutoRun(run?: string, smartva?: string): "icd11" | "smartva" | null {
  if (smartva === "1") return "smartva";
  return run === "1" ? "icd11" : null;
}

function safeError(value: string | undefined): string {
  return value && safeErrors.has(value) ? value : "engine_error";
}

function matches(actual: SmartVaReference, expected: SmartVaReference): boolean {
  return JSON.stringify(actual) === JSON.stringify(expected);
}

function displayResult(
  id: string,
  result: Awaited<ReturnType<OfflineSmartvaEngine["score"]>>,
  expected: SmartVaReference,
  expectedAllSymptoms: string | null,
): SmartVaEngineCheckCaseResult {
  if (!result.ok || !result.text) {
    return {
      id,
      ok: false,
      matched: false,
      ms: result.ms,
      ...(result.nativeMs !== undefined ? { nativeMs: result.nativeMs } : {}),
      error: safeError(result.error),
    };
  }
  try {
    const decoded = JSON.parse(result.text) as { predictions?: Array<{ all_symptoms?: unknown }> };
    const actual = projectSmartVaResult(decoded);
    const rawAllSymptoms = decoded.predictions?.[0]?.all_symptoms;
    return {
      id,
      ok: true,
      matched: matches(actual, expected) && rawAllSymptoms === expectedAllSymptoms,
      ms: result.ms,
      ...(result.nativeMs !== undefined ? { nativeMs: result.nativeMs } : {}),
      module: actual.module,
      cause34: actual.cause34,
      icd10: actual.icd10,
      topIcd10: actual.causes.map((cause) => cause.icd10),
    };
  } catch {
    return {
      id,
      ok: false,
      matched: false,
      ms: result.ms,
      ...(result.nativeMs !== undefined ? { nativeMs: result.nativeMs } : {}),
      error: "malformed_response",
    };
  }
}

/** Runs three synthetic WHO cases and repeats adult once; never touches a case store or the ICD-11 engine. */
export async function runSmartVaEngineCheck(
  engine: OfflineSmartvaEngine,
  onUpdate?: CheckListener,
): Promise<SmartVaEngineCheckResult> {
  let available = false;
  try {
    available = await engine.available();
  } catch {
    const result = { ok: false, available: false, initMs: 0, error: "unavailable", cases: [] };
    onUpdate?.(result);
    return result;
  }
  if (!available) {
    const result = { ok: false, available: false, initMs: 0, error: "unavailable", cases: [] };
    onUpdate?.(result);
    return result;
  }

  const initStarted = now();
  let initialized: Awaited<ReturnType<OfflineSmartvaEngine["init"]>>;
  try {
    initialized = await engine.init();
  } catch {
    const result: SmartVaEngineCheckResult = {
      ok: false, available: true, initMs: now() - initStarted, error: "init_failed", cases: [],
    };
    onUpdate?.(result);
    return result;
  }
  const initMs = initialized.ms || now() - initStarted;
  if (!initialized.ok) {
    const result: SmartVaEngineCheckResult = {
      ok: false, available: true, initMs, error: safeError(initialized.error), cases: [],
    };
    onUpdate?.(result);
    return result;
  }

  const cases: SmartVaEngineCheckCaseResult[] = [];
  for (const fixture of goldenData.cases) {
    const request = createSmartVaRequest(fixture.input, goldenData.options);
    const scoreStarted = now();
    let scored: Awaited<ReturnType<OfflineSmartvaEngine["score"]>>;
    try {
      scored = await engine.score(request);
    } catch {
      scored = { ok: false, error: "engine_error", ms: now() - scoreStarted };
    }
    cases.push(displayResult(fixture.id, scored, fixture.expected, fixture.all_symptoms));
    onUpdate?.({
      ok: cases.every((item) => item.ok && item.matched),
      available: true,
      initMs,
      version: initialized.version,
      cases: [...cases],
    });
  }

  const adult = goldenData.cases.find((fixture) => fixture.id === "adult");
  let warmRepeat: SmartVaEngineCheckCaseResult | undefined;
  if (adult) {
    const scoreStarted = now();
    let scored: Awaited<ReturnType<OfflineSmartvaEngine["score"]>>;
    try {
      scored = await engine.score(createSmartVaRequest(adult.input, goldenData.options));
    } catch {
      scored = { ok: false, error: "engine_error", ms: now() - scoreStarted };
    }
    warmRepeat = displayResult(
      "adult-warm",
      scored,
      adult.expected,
      adult.all_symptoms,
    );
  }
  const versionMatches = initialized.version === goldenData.source.engine_version;
  const result: SmartVaEngineCheckResult = {
    ok: versionMatches && cases.length === goldenData.cases.length
      && cases.every((item) => item.ok && item.matched)
      && !!warmRepeat?.ok && !!warmRepeat.matched,
    available: true,
    initMs,
    version: initialized.version,
    cases,
    ...(warmRepeat ? { warmRepeat } : {}),
  };
  onUpdate?.(result);
  return result;
}

export const SMARTVA_ENGINE_CHECK_CASES = goldenData.cases.map(({ id }) => id);
