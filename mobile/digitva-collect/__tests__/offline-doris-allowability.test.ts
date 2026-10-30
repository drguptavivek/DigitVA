/**
 * The offline save path applies the server's final-cause rules before a local final: it blocks a sex conflict,
 * asks for confirmation on an age conflict and records it, and stores the primary stem of a '/' cluster.
 */
import pack from "../assets/icd11-allowability-2026-01.json";
import { createAllowabilityIndex, type AllowabilityPack, type CodingContext } from "../src/coding/icd11Allowability";
import type { OfflineCodingRow } from "../src/drafts";
import type { EngineInit, EngineResult, OfflineEngine } from "../src/offlineEngine";
import type { WorkflowTimelineEvent } from "../src/workflowTimeline";
import { createOfflineDorisEditor, OfflineAllowabilityError, type OfflineCodingStore } from "../src/workspace/offlineDoris";
import type { JsonObject } from "../src/workspace/contracts";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async () => "digest",
  randomUUID: () => "uuid",
}));

const index = createAllowabilityIndex(pack as AllowabilityPack);
const ok = (data: unknown): EngineResult => ({ ok: true, data, status: 200, ms: 1, nativeMs: 1 });

/** codeinfo answers per full expression; anything else is unknown to WHO (a 404, as the engine answers it). */
function engine(codeinfo: Record<string, unknown> = {}, failure?: EngineResult | Error): OfflineEngine & { calls: string[] } {
  const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };
  const calls: string[] = [];
  return {
    calls,
    available: async () => true,
    init: async () => init,
    warm: async () => init,
    updateWhoFiles: async () => init,
    call: async () => ok({}),
    search: async () => ok({}),
    entity: async () => ok({}),
    foundationEntity: async () => ok({}),
    codeinfo: async (code) => {
      calls.push(code);
      if (failure instanceof Error) throw failure;
      return failure ?? (code in codeinfo ? ok(codeinfo[code]) : { ok: false, error: "engine_status", status: 404, ms: 1 });
    },
    doris: async () => ok({ status: "unavailable", result: null }),
    codedit: async () => ok({ status: "unavailable", result: null }),
    onProgress: () => () => undefined,
  };
}

function memoryStore(): OfflineCodingStore & { rows: Map<string, OfflineCodingRow> } {
  const rows = new Map<string, OfflineCodingRow>();
  return { rows, save: async (row) => void rows.set(row.client_draft_id, row), get: async (id) => rows.get(id) ?? null };
}

const body = (cause: string, extra: Record<string, unknown> = {}, warning?: string): JsonObject => ({
  antecedent_cod: cause,
  doris_certificate: { ICDVersion: "ICD11" },
  doris_result: { status: "completed", result: warning ? { code: cause, warning } : { code: cause } },
  codedit_result: { status: "completed", result: { report: "r", issueIds: [] } },
  doris_process_token: "local-1",
  ...extra,
}) as JsonObject;

function save(e: ReturnType<typeof createOfflineDorisEditor>, payload: JsonObject, codingTimelineV1: WorkflowTimelineEvent[] = []) {
  return e.save({ clientDraftId: "d1", body: payload, reply: null, deviceUuid: "dev", coderProfileUpdatedAt: null, codingTimelineV1 });
}
function editor(context: CodingContext, eng: OfflineEngine = engine(), store = memoryStore()) {
  return { store, editor: createOfflineDorisEditor(eng, store, { index, context, confirmedBy: "user-7" }) };
}

describe("offline save applies the allowability rules", () => {
  it("saves an allowed code and records the rules version and primary stem", async () => {
    const { editor: e, store } = editor({ ageGroup: "adult", sex: "male" });
    const codingTimeline = [
      { event: "coding_opened", at: "2026-10-28T09:00:00+05:30" },
      { event: "doris_processed", at: "2026-10-28T09:05:00+05:30", elapsed_ms: 2500 },
    ];
    const row = await save(e, body("1A00"), codingTimeline);
    expect(row.status).toBe("coded");
    const provenance = JSON.parse(row.provenance!);
    expect(provenance.allowability).toEqual({ rules: index.version, release: "2026-01" });
    expect(provenance.antecedent).toEqual({ code: "1A00", primary_stem: "1A00", release: "2026-01" });
    expect(provenance.packVersions).toEqual({ icd11_engine: "2026.10.29.1", doris_engine: "1.1.176", doris_rules: "1.2.0", icd_release: "2026-01" });
    expect(provenance.codingTimelineV1).toEqual([
      ...codingTimeline,
      { event: "initial_saved", at: row.updated_at },
    ]);
    expect(provenance.workflowTimelineV1).toEqual(provenance.codingTimelineV1);
    expect(store.rows.get("d1")).toEqual(row);
  });

  it("blocks chapter 22 and a sex conflict without storing anything", async () => {
    const { editor: e, store } = editor({ ageGroup: "adult", sex: "female" });
    await expect(save(e, body("NA07.7"))).rejects.toMatchObject({ kind: "blocked", message: "NA07.7 is not selectable for this submission." });
    await expect(save(e, body("GB00"))).rejects.toBeInstanceOf(OfflineAllowabilityError);
    expect(store.rows.size).toBe(0);
  });

  it("allows KD3B.Z for a neonate", async () => {
    const { editor: e } = editor({ ageGroup: "neonate", sex: null });
    const row = await save(e, body("KD3B.Z"));
    expect(JSON.parse(row.provenance!).antecedent.primary_stem).toBe("KD3B.Z");
  });

  it("asks for confirmation on an age conflict, then records who, when, the restriction and DORIS's warning", async () => {
    const { editor: e, store } = editor({ ageGroup: "adult", sex: null });
    await expect(save(e, body("KB2C"))).rejects.toMatchObject({
      kind: "age_confirm",
      restriction: { code: "KB2C", age_group_selectable: "neonate_infant", restriction_note: "chapter 19 (KA-KD), neonates and infants" },
    });
    expect(store.rows.size).toBe(0);

    const row = await save(e, body("KB2C", { age_restriction_confirmed: true }, "KB2C is unlikely at this age."));
    const confirmation = JSON.parse(row.provenance!).antecedent.age_restriction_confirmation;
    expect(confirmation).toMatchObject({
      confirmed_by: "user-7",
      code: "KB2C",
      age_group_selectable: "neonate_infant",
      restriction_note: "chapter 19 (KA-KD), neonates and infants",
      doris_warning: "KB2C is unlikely at this age.",
    });
    expect(typeof confirmation.confirmed_at).toBe("string");
  });

  it("keeps a DORIS warning only when it names the code", async () => {
    const { editor: e } = editor({ ageGroup: "adult", sex: null });
    const row = await save(e, body("KB2C", { age_restriction_confirmed: true }, "Something about another code."));
    expect(JSON.parse(row.provenance!).antecedent.age_restriction_confirmation.doris_warning).toBeNull();
  });

  it("judges a '/' cluster by WHO's causing condition and stores that stem", async () => {
    const info = { "1A00/GB00": { code: "1A00/GB00", stemCode: "1A00", stemId: "u", hasCausingCondition: ["GB00"] } };
    const eng = engine(info);
    // Female: the first stem 1A00 would pass, the causing condition GB00 (male only) blocks.
    await expect(save(editor({ ageGroup: "adult", sex: "female" }, eng).editor, body("1A00/GB00"))).rejects.toMatchObject({ kind: "blocked", message: "GB00 is not selectable for this submission." });
    const male = editor({ ageGroup: "adult", sex: "male" }, eng);
    const row = await save(male.editor, body("1A00/GB00"));
    expect(JSON.parse(row.provenance!).antecedent).toMatchObject({ code: "1A00/GB00", primary_stem: "GB00" });
    expect(eng.calls).toContain("1A00/GB00");
  });

  it("falls back to the first stem when codeinfo names no causing condition, and refuses an unknown expression", async () => {
    const eng = engine({ "1A00/5A11": { code: "1A00/5A11", stemCode: "1A00", stemId: "u" } });
    const row = await save(editor({ ageGroup: null, sex: null }, eng).editor, body("1A00/5A11"));
    expect(JSON.parse(row.provenance!).antecedent.primary_stem).toBe("1A00");
    await expect(save(editor({ ageGroup: null, sex: null }, eng).editor, body("1A00/5A12"))).rejects.toMatchObject({ kind: "blocked", message: "The ICD-11 code expression is not valid." });
  });

  it("reads an engine that cannot answer as icd11_unavailable, without its text, and passes other errors through", async () => {
    const down = engine({}, { ok: false, error: "SECRET stack", status: 500, ms: 1 });
    const failure = save(editor({ ageGroup: null, sex: null }, down).editor, body("1A00/GB00"));
    await expect(failure).rejects.toThrow("icd11_unavailable");
    await expect(failure).rejects.not.toThrow(/SECRET/);
    await expect(save(editor({ ageGroup: null, sex: null }, engine({}, new TypeError("bug"))).editor, body("1A00/GB00"))).rejects.toThrow(TypeError);
  });

  it("accepts causing_condition_unknown on a single stem only, and records it", async () => {
    const { editor: e } = editor({ ageGroup: null, sex: null }, engine({ "1A00/5A11": { code: "1A00/5A11", stemCode: "1A00", stemId: "u" } }));
    const row = await save(e, body("1A00", { causing_condition_unknown: true }));
    expect(JSON.parse(row.provenance!).antecedent.causing_condition_unknown).toBe(true);
    await expect(save(e, body("1A00/5A11", { causing_condition_unknown: true }))).rejects.toMatchObject({ kind: "blocked", message: expect.stringMatching(/single ICD-11 stem/) });
  });

  it("refuses a malformed code, and without allowability stores the engine versions only", async () => {
    await expect(save(editor({ ageGroup: null, sex: null }).editor, body("not-a-code"))).rejects.toMatchObject({ kind: "blocked", message: "Select a valid ICD-11 code." });
    const plain = createOfflineDorisEditor(engine(), memoryStore());
    expect(Object.keys(JSON.parse((await save(plain, body("NA07.7"))).provenance!))).toEqual(["packVersions"]);
  });
});
