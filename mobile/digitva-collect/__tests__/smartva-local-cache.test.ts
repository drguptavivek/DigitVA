import { DatabaseSync } from "node:sqlite";

import { deleteDraft, migrate, setMeta, type Db } from "../src/drafts";
import { runLocalSmartVa } from "../src/smartva/localApi";
import { getLocalSmartVa, isLocalSmartVaCurrent, saveLocalSmartVaResult } from "../src/smartva/localStore";
import { projectSmartVaSnapshot, standaloneSmartVaSnapshot, type SmartVaOptionsSnapshot } from "../src/smartva/options";
import type { OfflineSmartvaEngine } from "../src/smartva/nativeEngine";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const at = "2026-10-28T10:00:00.000Z";
const sha = "a".repeat(64);
const options: SmartVaOptionsSnapshot = {
  schemaVersion: 1,
  formId: "WHO_2022_VA",
  formUpdatedAt: "2026-10-01",
  options: { country: "India", hiv: false, malaria: true, hce: true, freetext: true },
  optionsDigest: `sha256:${"b".repeat(64)}`,
};
const envelope = JSON.stringify({ instrumentId: "WHO_2022_VA", data: { id1: "1", Id10013: "yes", Id10007: "private name", ageInDays: "100" } });
async function makeEligible(db: Db) {
  await db.runAsync("UPDATE drafts SET project_id = ?, completion = ? WHERE id = ?", ["project-1", JSON.stringify({ valid: true, issues: [] }), "draft-1"]);
  await setMeta(db, "draft-config:draft-1", { smartva: options });
  await setMeta(db, "consentConfig", { consent_required: false }, "project-1");
}
const engineResult = JSON.stringify({
  total_vas: 1,
  predictions: [{ module: "adult", age: "4", sex: "1", cause1: "Stroke", likelihood1: "high", key_symptom1: "Previous diagnosis of Asthma", key_symptom2: "private narrative", all_symptoms: "Previous diagnosis of Asthma; Open Response Word: private narrative" }],
});

function engine(score = jest.fn(async () => ({ ok: true as const, text: engineResult, ms: 2, version: "smartva-test" }))): OfflineSmartvaEngine {
  return { available: jest.fn(async () => true), init: jest.fn(async () => ({ ok: true, ms: 0 })), score };
}

describe("local SmartVA cache and options", () => {
  it("persists a compact result without narratives and deletes it with its draft", async () => {
    const db = memoryDb();
    await migrate(db);
    await db.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, 1, ?, ?)", ["draft-1", "site-1", at, envelope]);
    await makeEligible(db);
    const saved = await runLocalSmartVa({
      db, draftId: "draft-1", envelope, options, answersHash: async () => sha, engine: engine(), assertAllowed: async () => undefined, now: () => at,
    });
    expect(saved.status).toBe("ready");
    const restored = await getLocalSmartVa(db, "draft-1");
    expect(restored).toMatchObject({ status: "ready", answers_sha256: sha, options_digest: options.optionsDigest, engine_version: "smartva-test" });
    expect(isLocalSmartVaCurrent(restored, sha, options.optionsDigest, "smartva-test")).toBe(true);
    expect(isLocalSmartVaCurrent(restored, sha, options.optionsDigest, "old-version")).toBe(false);
    expect(isLocalSmartVaCurrent(restored, "c".repeat(64), options.optionsDigest, "smartva-test")).toBe(false);
    expect(isLocalSmartVaCurrent(restored, sha, `sha256:${"d".repeat(64)}`, "smartva-test")).toBe(false);
    expect(JSON.parse(restored!.result_json!)).toMatchObject({ causes: expect.arrayContaining([expect.objectContaining({ cause: "Stroke" })]), key_symptoms: ["Previous diagnosis of Asthma", null, null], symptoms: ["Previous diagnosis of Asthma"] });
    expect(JSON.stringify(restored)).not.toContain("private");

    await deleteDraft(db, "draft-1");
    expect(await getLocalSmartVa(db, "draft-1")).toBeNull();
    await db.closeAsync();
  });

  it("requires explicit authorization, detects changed answers, and stores only a safe failure code", async () => {
    const db = memoryDb();
    await migrate(db);
    const score = jest.fn(async () => ({ ok: true as const, text: engineResult, ms: 2, version: "smartva-test" }));
    await expect(runLocalSmartVa({
      db, draftId: "draft-1", envelope, options, answersHash: async () => sha, engine: engine(score),
      assertAllowed: async () => { throw new Error("icd11_doris_disabled"); }, now: () => at,
    })).rejects.toThrow("icd11_doris_disabled");
    expect(score).not.toHaveBeenCalled();
    expect(await getLocalSmartVa(db, "draft-1")).toBeNull();

    await db.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, 1, ?, ?)", ["draft-1", "site-1", at, envelope]);
    await makeEligible(db);
    let reads = 0;
    await expect(runLocalSmartVa({
      db, draftId: "draft-1", envelope, options, answersHash: async () => (++reads === 1 ? sha : "c".repeat(64)), engine: engine(score),
      assertAllowed: async () => undefined, now: () => at,
    })).rejects.toThrow("answers_changed");
    expect(await getLocalSmartVa(db, "draft-1")).toBeNull();
    expect(JSON.stringify(await getLocalSmartVa(db, "draft-1"))).not.toContain("private");
    await db.closeAsync();
  });

  it("never scores refused or invalid completions, and rechecks consent before saving", async () => {
    const db = memoryDb();
    await migrate(db);
    await db.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, 1, ?, ?)", ["draft-1", "site-1", at, envelope]);
    await makeEligible(db);
    const score = jest.fn(async () => ({ ok: true as const, text: engineResult, ms: 2, version: "smartva-test" }));
    await db.runAsync("UPDATE drafts SET completion = ? WHERE id = ?", [JSON.stringify({ valid: false }), "draft-1"]);
    await expect(runLocalSmartVa({ db, draftId: "draft-1", envelope, options, answersHash: async () => sha, engine: engine(score), assertAllowed: async () => undefined })).rejects.toThrow("offline_case_missing");
    expect(score).not.toHaveBeenCalled();
    await makeEligible(db);
    const partial = JSON.stringify({ instrumentId: "WHO_2022_VA", data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [partial, "draft-1"]);
    await expect(runLocalSmartVa({ db, draftId: "draft-1", envelope: partial, options, answersHash: async () => sha, engine: engine(score), assertAllowed: async () => undefined })).resolves.toMatchObject({ status: "ready" });
    expect(score).toHaveBeenCalledTimes(1);
    await db.runAsync("DELETE FROM local_smartva WHERE draft_id = ?", ["draft-1"]);
    await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [envelope, "draft-1"]);
    const refusingScore = jest.fn(async () => {
      await setMeta(db, "consent:server-refused:draft-1", true);
      return { ok: true as const, text: engineResult, ms: 2, version: "smartva-test" };
    });
    await expect(runLocalSmartVa({ db, draftId: "draft-1", envelope, options, answersHash: async () => sha, engine: engine(refusingScore), assertAllowed: async () => undefined })).rejects.toThrow("offline_case_missing");
    expect(refusingScore).toHaveBeenCalled();
    expect(await getLocalSmartVa(db, "draft-1")).toBeNull();
    await db.closeAsync();
  });

  it("does not score a draft that is incomplete, sent, or different from the supplied answer envelope", async () => {
    const db = memoryDb();
    await migrate(db);
    const score = jest.fn(async () => ({ ok: true as const, text: engineResult, ms: 2, version: "smartva-test" }));
    await db.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, 0, ?, ?)", ["draft-1", "site-1", at, envelope]);
    await expect(runLocalSmartVa({
      db, draftId: "draft-1", envelope, options, answersHash: async () => sha, engine: engine(score), assertAllowed: async () => undefined,
    })).rejects.toThrow("offline_case_missing");
    expect(score).not.toHaveBeenCalled();
    await db.closeAsync();
  });

  it("matches enrolled targets by exact site and unit and requires profile inputs in standalone mode", async () => {
    const target = {
      schema_version: 1 as const, site_id: "site-1", org_unit_id: null, form_id: "form-1", form_updated_at: "v1",
      options: options.options, options_digest: options.optionsDigest,
    };
    expect(projectSmartVaSnapshot([target], { siteId: "site-1", orgUnitId: null })).toMatchObject({ formId: "form-1" });
    expect(projectSmartVaSnapshot([target], { siteId: "site-1", orgUnitId: "OU-7" })).toBeNull();
    expect(projectSmartVaSnapshot([target], { siteId: "other", orgUnitId: null })).toBeNull();

    const profile = {
      name: "Coder", age_years: null, sex: null, designation: "", facility_name: "", country: " India ", state: "",
      hiv_mortality: "high" as const, malaria_mortality: "low" as const, updated_at: at,
    };
    await expect(standaloneSmartVaSnapshot(profile, "form-1", "v1")).resolves.toMatchObject({
      options: { country: "India", hiv: true, malaria: false, hce: true, freetext: true },
    });
    await expect(standaloneSmartVaSnapshot({ ...profile, malaria_mortality: null }, "form-1", "v1")).resolves.toBeNull();
  });

  it("rejects nonempty symptom text from the persistent projection", async () => {
    const db = memoryDb();
    await migrate(db);
    await expect(saveLocalSmartVaResult(db, {
      draftId: "draft-1",
      result: { age: null, gender: null, key_symptoms: [], causes: [], symptoms: ["private narrative"], module: null, cause34: null, icd10: null } as never,
      answersSha: sha, optionsDigest: options.optionsDigest, engineVersion: "smartva-test", at,
    })).rejects.toThrow("metadata is invalid");
    await db.closeAsync();
  });
});
