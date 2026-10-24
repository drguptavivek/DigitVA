import type { EngineInit, EngineProgress, EngineResult, EngineSetup, OfflineEngine } from "./offlineEngine";

/**
 * Synthetic adult certificate (acute myocardial infarction over coronary atherosclerosis, type 2 diabetes in Part 2)
 * from the offline-engine spike. It describes no real person. DORIS must answer BA41.Z.
 */
export const CHECK_CERTIFICATE = {
  ICDVersion: "ICD11",
  AdministrativeData: { Sex: 1, EstimatedAge: "P62Y" },
  Part1: [
    {
      Conditions: [
        {
          Text: "Acute myocardial infarction",
          Code: "BA41.Z",
          LinearizationURI: "http://id.who.int/icd/release/11/2026-01/mms/1334938734/unspecified",
          Interval: "PT12H",
        },
      ],
    },
    {
      Conditions: [
        {
          Text: "Coronary atherosclerosis",
          Code: "BA52.Z",
          LinearizationURI: "http://id.who.int/icd/release/11/2026-01/mms/1280712786/unspecified",
          Interval: "P10Y",
        },
      ],
    },
  ],
  Part2: {
    Conditions: [
      {
        Text: "Type 2 diabetes mellitus",
        Code: "5A11",
        LinearizationURI: "http://id.who.int/icd/release/11/2026-01/mms/119724091",
        Interval: "P8Y",
      },
    ],
  },
};

export interface CheckStep {
  name: string;
  ok: boolean;
  /** Round trip from JS, ms. */
  ms: number;
  /** Time inside the engine call, ms (absent for init). */
  nativeMs?: number;
  /** A short non-sensitive summary or error code. */
  note: string;
}

function summarize(result: EngineResult, pick: (data: unknown) => string): Omit<CheckStep, "name"> {
  if (!result.ok) return { ok: false, ms: result.ms, note: result.status ? `${result.error} ${result.status}` : result.error };
  return { ok: true, ms: result.ms, nativeMs: result.nativeMs, note: pick(result.data) };
}

const field = (data: unknown, key: string): string => {
  const value = (data as Record<string, unknown> | null)?.[key];
  return typeof value === "string" ? value : "?";
};

/** One line for an init in progress, e.g. "copy 40%" or "setup" (percent unknown). */
export function describeProgress(progress: EngineProgress): string {
  return progress.percent === undefined ? progress.phase : `${progress.phase} ${progress.percent}%`;
}

/**
 * How the first setup ran, with the files it changed (names and sizes; no hashes). "downloaded" means the setup init
 * fetched WHO files; "shipped" means only the APK's copies were used.
 */
export function describeSetup(setup: EngineSetup): string {
  if (setup.mode !== "downloaded") return "shipped copies";
  const files = setup.files.map((file) => `${file.path} (${file.size} B)`).join("; ");
  return `downloaded ${setup.files.length} files${files ? `: ${files}` : ""}`;
}

/** Runs init, search, codeinfo, DORIS (cold and warm) and CoDEdit once, reporting each step's timings. */
export async function runEngineCheck(engine: OfflineEngine, onStep: (step: CheckStep) => void = () => undefined): Promise<CheckStep[]> {
  const steps: CheckStep[] = [];
  const push = (step: CheckStep) => {
    steps.push(step);
    onStep(step);
  };
  if (!(await engine.available())) {
    push({ name: "available", ok: false, ms: 0, note: "unavailable" });
    return steps;
  }
  const init: EngineInit = await engine.init();
  push({
    name: "init",
    ok: init.ok,
    ms: init.ms,
    note: init.ok ? `copy ${init.copyMs.toFixed(0)} ms, engine ${init.initMs.toFixed(0)} ms${init.cached ? " (already up)" : ""}${init.phases ? ` [${init.phases}]` : ""}` : init.error,
  });
  if (!init.ok) return steps;
  if (init.setup) push({ name: "setup", ok: true, ms: 0, note: describeSetup(init.setup) });
  push({ name: "search", ...summarize(await engine.search("myocardial infarction"), (data) => {
    const entities = (data as { destinationEntities?: unknown[] } | null)?.destinationEntities;
    return `${Array.isArray(entities) ? entities.length : 0} results`;
  }) });
  push({ name: "codeinfo BC42.Z", ...summarize(await engine.codeinfo("BC42.Z"), (data) => field(data, "code")) });
  push({ name: "doris", ...summarize(await engine.doris(CHECK_CERTIFICATE), (data) => `underlying ${field(data, "Code")}`) });
  push({ name: "doris (warm)", ...summarize(await engine.doris(CHECK_CERTIFICATE), (data) => `underlying ${field(data, "Code")}`) });
  push({ name: "codedit", ...summarize(await engine.codedit(CHECK_CERTIFICATE), () => "checked") });
  return steps;
}
