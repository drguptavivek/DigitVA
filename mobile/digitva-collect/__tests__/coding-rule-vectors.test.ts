/**
 * The phone's copies of the server's coding rules, run over the golden vectors the SERVER computes
 * (scripts/export_coding_rule_vectors.py -> fixtures/coding_rule_vectors.json; tests/services/test_coding_rule_vectors.py
 * keeps the file equal to a regeneration). A case listed under `divergences` is a known server/phone disagreement:
 * skipped here with its reason, reported to the owner, not fixed (digitva-r8nh.25).
 */
import vectors from "./fixtures/coding_rule_vectors.json";
import {
  ageGroupForDays,
  ageRestrictionConfirmation,
  causingConditionUnknownError,
  checkAllowability,
  CAUSING_CONDITION_MESSAGE,
  createAllowabilityIndex,
  extractIcd11CodeExpression,
  normalizedAgeDays,
  type AgeGroup,
  type AllowabilityPack,
} from "../src/coding/icd11Allowability";
import type { OfflineEngine, EngineInit, EngineResult } from "../src/offlineEngine";
import type { JsonObject } from "../src/workspace/contracts";
import { reportedAge } from "../src/workspace/doris/rules";
import { createOfflineDorisEditor, OfflineAllowabilityError, type OfflineCodingStore } from "../src/workspace/offlineDoris";
import type { OfflineCodingRow } from "../src/drafts";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async () => "digest",
  randomUUID: () => "uuid",
}));

type Case = { name: string };
const divergences = (vectors as { divergences: Record<string, string> }).divergences;

/** `it` for a case, `it.skip` (named with the reason) when the vectors list it as a known divergence. */
function each<T extends Case>(section: string, cases: T[], run: (c: T) => void | Promise<void>) {
  for (const c of cases) {
    const reason = divergences[`${section}:${c.name}`];
    if (reason) it.skip(`${section}: ${c.name} [DIVERGENCE: ${reason}]`, () => undefined);
    else it(`${section}: ${c.name}`, async () => run(c));
  }
}

const packOf = (restriction: { age: string; sex: string; note: string | null } | null): AllowabilityPack => ({
  schema: 1,
  release: "2026-01",
  db_revision: null,
  count: restriction ? 1 : 0,
  sha256: "0".repeat(64),
  groups: restriction ? [{ sex: restriction.sex, age: restriction.age, note: restriction.note, codes: ["1A00"] }] : [],
});

describe("coding rule vectors: the limits", () => {
  it("name the same refusal text and the 256 cap", () => {
    expect(CAUSING_CONDITION_MESSAGE).toBe(vectors.limits.causing_condition_message);
    expect(extractIcd11CodeExpression("1A00&" + "X".repeat(251))).not.toBeNull();
    expect(extractIcd11CodeExpression("1A00&" + "X".repeat(252))).toBeNull();
    expect(vectors.limits.expression_max_length).toBe(256);
  });
});

describe("coding rule vectors", () => {
  each("age_days", vectors.age_days as (Case & { data: Record<string, unknown>; days: number | null })[], (c) => {
    const got = normalizedAgeDays(c.data);
    if (c.days === null) expect(got).toBeNull();
    else expect(got).toBeCloseTo(c.days, 9);
  });

  each("age_group", vectors.age_group as (Case & { days: number | null; group: AgeGroup | null })[], (c) => {
    expect(ageGroupForDays(c.days)).toBe(c.group);
  });

  each("allowability", vectors.allowability as (Case & { restriction: { age: string; sex: string; note: string | null } | null; age_group: AgeGroup | null; sex: "male" | "female" | null; status: string })[], (c) => {
    const index = createAllowabilityIndex(packOf(c.restriction));
    expect(checkAllowability(index, "1A00", { ageGroup: c.age_group, sex: c.sex }).status).toBe(c.status);
  });

  each("age_confirmation", vectors.age_confirmation as (Case & { restriction: { code: string; age_group_selectable: string; restriction_note: string }; confirmed_by: string; doris_result: { result?: { warning?: unknown } } | null; record: Record<string, unknown> })[], (c) => {
    const { confirmed_at: at, ...record } = ageRestrictionConfirmation(c.restriction, c.confirmed_by, "2026-01-01T00:00:00Z", c.doris_result?.result?.warning);
    expect(at).toBe("2026-01-01T00:00:00Z");
    expect(record).toEqual(c.record);
  });

  each("expression", vectors.expression as (Case & { value: string; expression: string | null })[], (c) => {
    expect(extractIcd11CodeExpression(c.value)).toBe(c.expression);
  });

  each("causing_condition_unknown", vectors.causing_condition_unknown as (Case & { value: string; error: string | null })[], (c) => {
    expect(causingConditionUnknownError(extractIcd11CodeExpression(c.value))).toBe(c.error);
  });

  each("reported_age", vectors.reported_age as (Case & { estimated_age: string | null; days: number | null })[], (c) => {
    const age = reportedAge({ AdministrativeData: { EstimatedAge: c.estimated_age } } as unknown as JsonObject);
    if (c.days === null) expect(age).toBeNull();
    else expect(age?.days).toBeCloseTo(c.days, 9);
  });
});

// --- the final underlying-cause judgement, through the offline save the phone runs (judgeUnderlyingCause) ---

const ok = (data: unknown): EngineResult => ({ ok: true, data, status: 200, ms: 1, nativeMs: 1 });
const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };
const engine: OfflineEngine = {
  available: async () => true,
  init: async () => init,
  warm: async () => init,
  updateWhoFiles: async () => init,
  call: async () => ok({}),
  search: async () => ok({}),
  entity: async () => ok({}),
  foundationEntity: async () => ok({}),
  codeinfo: async () => ({ ok: false, error: "engine_status", status: 404, ms: 1 }),
  doris: async () => ok({ status: "unavailable", result: null }),
  codedit: async () => ok({ status: "unavailable", result: null }),
  onProgress: () => () => undefined,
};
const store: OfflineCodingStore = {
  save: async () => undefined,
  get: async (): Promise<OfflineCodingRow | null> => null,
};

type Underlying = Case & {
  restriction: { age: string; sex: string; note: string | null } | null;
  value: string;
  age_group: AgeGroup | null;
  sex: "male" | "female" | null;
  causing_condition_unknown: boolean;
  age_restriction_confirmed: boolean;
  expected: { outcome: string; message?: string; restriction?: Record<string, unknown> | null };
};

describe("coding rule vectors: the underlying-cause judgement", () => {
  each("underlying_cause", vectors.underlying_cause as Underlying[], async (c) => {
    const editor = createOfflineDorisEditor(engine, store, {
      index: createAllowabilityIndex(packOf(c.restriction)),
      context: { ageGroup: c.age_group, sex: c.sex },
      confirmedBy: "user-7",
    });
    const body = {
      antecedent_cod: c.value,
      doris_certificate: { ICDVersion: "ICD11" },
      doris_result: { status: "completed", result: { code: c.value } },
      codedit_result: { status: "completed", result: { report: "r", issueIds: [] } },
      doris_process_token: "local-1",
      ...(c.causing_condition_unknown ? { causing_condition_unknown: true } : {}),
      ...(c.age_restriction_confirmed ? { age_restriction_confirmed: true } : {}),
    } as JsonObject;
    let got: Underlying["expected"];
    try {
      const row = await editor.save({ clientDraftId: "d1", body, reply: null, deviceUuid: "dev", coderProfileUpdatedAt: null, codingTimelineV1: [] });
      const confirmation = JSON.parse(row.provenance!).antecedent.age_restriction_confirmation;
      got = {
        outcome: "ok",
        restriction: confirmation
          ? { code: confirmation.code, age_group_selectable: confirmation.age_group_selectable, restriction_note: confirmation.restriction_note }
          : null,
      };
    } catch (error) {
      if (!(error instanceof OfflineAllowabilityError)) throw error;
      got = { outcome: error.kind, message: error.message, ...(error.restriction ? { restriction: { ...error.restriction } } : {}) };
    }
    expect(got).toEqual(c.expected);
  });
});
