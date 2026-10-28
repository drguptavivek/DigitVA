import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import { ApiError } from "../src/api";
import { authedRequest } from "../src/auth";
import { saveDraftConsent } from "../src/consentStore";
import { createDraftStore, getDraftRow, markCompleted, migrate, setMeta, stripDraftCovered, unfinishedDraftsForSync, type Db, type DraftSyncItem } from "../src/drafts";
import { recoverRefusalDraft, reconcileCaseDraft, recordCodingTimeline, recordDraftTimeline, syncDraftSnapshot, type FetchedServerDraft } from "../src/draftSync";
import type { CaseDetail } from "../src/cases";

jest.mock("../src/auth", () => ({ authedRequest: jest.fn() }));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async () => "a".repeat(64))
}));
jest.mock("@drguptavivek/who-2022-va", () => {
  // The reduction is the engine's own; decoding is a stub that applies it as the real decoder does.
  const { reduceNationalIdData } = jest.requireActual("@drguptavivek/who-2022-va");
  return {
  reduceNationalIdData,
  decodeWhoVaDraft: (value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid draft");
    const draft = value as Record<string, unknown>;
    for (const field of ["id", "instrumentId", "instrumentVersion", "currentSection", "createdAt", "updatedAt"]) {
      if (typeof draft[field] !== "string" || !draft[field]) throw new Error("invalid draft");
    }
    if (!draft.data || typeof draft.data !== "object" || Array.isArray(draft.data)) throw new Error("invalid draft");
    return { ...draft, data: reduceNationalIdData(draft.data) };
  }
  };
}, { virtual: true });

const request = authedRequest as jest.Mock;
const SERVER_ID = "22222222-2222-4222-8222-222222222222";
const LOCAL_ID = "11111111-1111-4111-8111-111111111111";
const DEATH_ID = "33333333-3333-4333-8333-333333333333";
const OLD_TIME = "2026-10-01T10:00:00Z";
const NEW_TIME = "2026-10-01T11:00:00+00:00";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close()
  };
}

function localDraft(id = LOCAL_ID, updatedAt = OLD_TIME, data: Record<string, unknown> = { Id10007: "local" }): WhoVaDraft {
  return {
    schemaVersion: 1,
    formVersion: "2022",
    id,
    instrumentId: "who-va-2022",
    instrumentVersion: "1",
    currentSection: "s1",
    createdAt: OLD_TIME,
    updatedAt,
    data: data as WhoVaDraft["data"]
  };
}

function summary(updatedAt = NEW_TIME) {
  return {
    draft_id: SERVER_ID,
    project_id: "PROJECT1",
    site_id: "SITE1",
    org_unit_id: null,
    death_id: DEATH_ID,
    unique_id: "CASE-1",
    status: "draft",
    created_at: OLD_TIME,
    updated_at: updatedAt
  };
}

function serverEnvelope(data: Record<string, unknown> = { Id10007: "server" }) {
  return {
    schemaVersion: 1,
    formVersion: "2022",
    id: SERVER_ID,
    instrumentId: "who-va-2022",
    instrumentVersion: "1",
    currentSection: "s2",
    createdAt: OLD_TIME,
    updatedAt: NEW_TIME,
    data
  };
}

function syncReply(kept: "incoming" | "server", updatedAt = NEW_TIME) {
  return {
    draft: summary(updatedAt),
    kept,
    conflict: kept === "server",
    answers_sha256: kept === "incoming" ? "a".repeat(64) : null,
    message: kept === "server" ? "This interview was also edited on another device; the newer version was kept." : null,
    ...(kept === "server" ? { envelope: serverEnvelope() } : {})
  };
}

function caseDetail(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return {
    death_id: DEATH_ID,
    unique_id: "CASE-1",
    project_id: "PROJECT1",
    site_id: "SITE1",
    org_unit_id: null,
    unit_name: null,
    state: "in_progress",
    source: "register",
    details_pending: false,
    pending_flag: false,
    registered_by_me: true,
    started_by_me: true,
    my_draft_id: SERVER_ID,
    va_sid: null,
    created_at: OLD_TIME,
    updated_at: OLD_TIME,
    next_visit_at: null,
    last_contact_at: null,
    deceased: { name: null, sex: null, age_years: null, date_of_birth: null, date_of_birth_partial: null, date_of_death: null, place_of_death: null },
    household_address: { address: null, house_street: null, village_ward: null, landmark: null },
    informant: { name: null, phone: null, phone_2: null },
    remarks: null,
    links: { self: "", attempts: "", visit: "" },
    ...overrides
  };
}

const defaults = { instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1" };

describe("native draft sync", () => {
  let db: Db;
  beforeEach(async () => {
    request.mockReset();
    db = memoryDb();
    await migrate(db);
  });

  async function saveLocal(definitionPin?: { instrumentVersion: string; definitionSha256: string; definitionExtensions: string[] }): Promise<DraftSyncItem> {
    const store = createDraftStore(db, {
      projectId: "PROJECT1", siteId: "SITE1",
      binding: { projectId: "PROJECT1", deathId: DEATH_ID, uniqueId: "CASE-1" },
      ...(definitionPin ? { definitionPin } : {}),
    });
    await store.save({ ...localDraft(), ...(definitionPin ? { instrumentVersion: definitionPin.instrumentVersion } : {}) });
    const [item] = await unfinishedDraftsForSync(db, "PROJECT1");
    expect(item).toBeDefined();
    return item;
  }

  it("acknowledges incoming without changing the local envelope", async () => {
    const item = await saveLocal({ instrumentVersion: "served-v2", definitionSha256: "c".repeat(64), definitionExtensions: ["geography"] });
    const body = syncReply("incoming");
    let payload: Record<string, unknown> | undefined;
    request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
      payload = init.bodyFactory() as Record<string, unknown>;
      return { status: 200, body };
    });

    await expect(syncDraftSnapshot("user-1", db, item)).resolves.toMatchObject({ applied: true, conflict: false, draftId: LOCAL_ID });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({
      server_draft_id: SERVER_ID,
      base_updated_at: NEW_TIME,
      draft_sync_dirty: 0
    });
    const current = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(current?.envelope).toBe(item.envelope);
    expect(payload?.draft).toMatchObject({
      instrumentVersion: "served-v2", definitionSha256: "c".repeat(64), definitionExtensions: ["geography"],
    });
  });

  it("sends an explicit DP consent resume with its server version without inventing a WHO answer", async () => {
    await saveLocal();
    await db.runAsync("UPDATE drafts SET server_draft_id = ?, base_updated_at = ? WHERE id = ?", [SERVER_ID, OLD_TIME, LOCAL_ID]);
    await setMeta(db, `consent:resume-who:${LOCAL_ID}`, true);
    const [item] = await unfinishedDraftsForSync(db, "PROJECT1");
    let payload: Record<string, unknown> | undefined;
    request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
      payload = init.bodyFactory() as Record<string, unknown>;
      return { status: 200, body: syncReply("incoming") };
    });
    await syncDraftSnapshot("user-1", db, item);
    expect(payload).toMatchObject({ resume_refused: true, base_updated_at: OLD_TIME });
    expect(JSON.parse(payload!.answers_json as string)).not.toHaveProperty("Id10013");
    expect((await getDraftRow(db, LOCAL_ID))?.base_updated_at).toBe(NEW_TIME);
  });

  it("recovers only a sanitized server refusal and preserves unrelated drafts", async () => {
    await saveLocal();
    const other = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    await createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" }).save(localDraft(other, OLD_TIME, { Id10007: "other lawful work" }));
    await db.runAsync("UPDATE drafts SET server_draft_id = ?, base_updated_at = ?, upload_issue = 'refusal_stale' WHERE id = ?", [SERVER_ID, OLD_TIME, LOCAL_ID]);
    const row = (await getDraftRow(db, LOCAL_ID))!;
    request.mockResolvedValueOnce({ body: { draft: summary(), envelope: serverEnvelope({ Id10007: "changed elsewhere" }), prefill: {} } });
    await expect(recoverRefusalDraft("user-1", db, row)).rejects.toThrow("refusal_server_draft_changed");
    expect((await getDraftRow(db, LOCAL_ID))?.upload_issue).toBe("refusal_stale");
    request.mockResolvedValueOnce({ body: { draft: summary(), envelope: serverEnvelope({ Id10013: "no", refusal_sex: "female" }), prefill: {} } });
    await recoverRefusalDraft("user-1", db, row);
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ base_updated_at: NEW_TIME, upload_issue: "consent_refused" });
    const saved = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(JSON.parse(saved!.envelope).data).toEqual({ Id10013: "no", refusal_sex: "female" });
    const unrelated = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [other]);
    expect(JSON.parse(unrelated!.envelope).data).toEqual({ Id10007: "other lawful work" });
  });

  it("persists coding milestones separately from interview metadata without changing answers", async () => {
    const item = await saveLocal();
    const originalAnswers = JSON.parse(item.envelope).data;
    const answersHashBefore = await digestStringAsync(CryptoDigestAlgorithm.SHA256, JSON.stringify(originalAnswers));
    expect(await recordDraftTimeline(db, LOCAL_ID, "identity_saved", "2026-10-01T10:05:00+05:30")).toBe(true);
    const openedAt = "2026-10-01T10:10:00+05:30";
    const processedAt = "2026-10-01T10:20:00+05:30";
    expect(await recordCodingTimeline(db, LOCAL_ID, "coding_opened", openedAt)).toBe(true);
    expect(await recordCodingTimeline(db, LOCAL_ID, "doris_processed", processedAt, 1250)).toBe(true);
    expect(await recordCodingTimeline(db, LOCAL_ID, "coding_opened", "2026-10-01T11:00:00Z")).toBe(true);
    await expect(recordCodingTimeline(db, LOCAL_ID, "final_saved")).rejects.toThrow("invalid_workflow_timeline");
    const timelineEnvelope = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    const persistedAnswers = JSON.parse(timelineEnvelope!.envelope).data;
    const answersHashAfter = await digestStringAsync(CryptoDigestAlgorithm.SHA256, JSON.stringify(persistedAnswers));
    expect(answersHashAfter).toBe(answersHashBefore);

    let payload: Record<string, unknown> | undefined;
    request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
      payload = init.bodyFactory() as Record<string, unknown>;
      return { status: 200, body: syncReply("incoming") };
    });
    await syncDraftSnapshot("user-1", db, { ...item, envelope: (await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]))!.envelope });
    expect(payload?.answers_json).toBe(JSON.stringify({ Id10007: "local" }));
    expect(payload?.answers_sha256).toBe(answersHashBefore);
    expect(payload?.draft).toMatchObject({
      workflowTimelineV1: [{ event: "identity_saved", at: "2026-10-01T10:05:00+05:30" }],
      codingTimelineV1: [
      { event: "coding_opened", at: openedAt },
      { event: "doris_processed", at: processedAt, elapsed_ms: 1250 },
      ],
    });

    await markCompleted(db, LOCAL_ID, { valid: true, issues: [] });
    expect(await recordCodingTimeline(db, LOCAL_ID, "initial_saved", "2026-10-01T10:30:00+05:30")).toBe(true);
    const retained = await db.getFirstAsync<{ envelope: string; completed: number }>("SELECT envelope, completed FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(retained?.completed).toBe(1);
    expect(JSON.parse(retained!.envelope)).toMatchObject({ data: { Id10007: "local" }, codingTimelineV1: [
      { event: "coding_opened", at: openedAt },
      { event: "doris_processed", at: processedAt, elapsed_ms: 1250 },
      { event: "initial_saved", at: "2026-10-01T10:30:00+05:30" },
    ] });
  });

  it("uploads a draft saved before the reduction with the national ID reduced", async () => {
    const item = await saveLocal();
    const legacy = { ...JSON.parse(item.envelope), data: { Id10007: "local", Id10073: "123456789012" } };
    await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [JSON.stringify(legacy), LOCAL_ID]);
    const [stored] = await unfinishedDraftsForSync(db, "PROJECT1");
    let payload: Record<string, unknown> | undefined;
    request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
      payload = init.bodyFactory() as Record<string, unknown>;
      return { status: 200, body: syncReply("incoming") };
    });
    await syncDraftSnapshot("user-1", db, stored);
    expect(JSON.parse(payload!.answers_json as string)).toEqual({ Id10007: "local", Id10073: "XXXXXXXXX012" });
    expect(payload!.answers_json).not.toContain("123456789012");
  });

  it("blocks a malformed local definition pin without uploading or discarding answers", async () => {
    const item = await saveLocal();
    const malformed = { ...JSON.parse(item.envelope), definitionSha256: "c".repeat(64) };
    const envelopeJson = JSON.stringify(malformed);
    await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [envelopeJson, LOCAL_ID]);
    const [stored] = await unfinishedDraftsForSync(db, "PROJECT1");

    await expect(syncDraftSnapshot("user-1", db, stored)).rejects.toMatchObject({ code: "partial_definition_pin" });
    expect(request).not.toHaveBeenCalled();
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ draft_sync_blocked: 1 });
    const retained = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(JSON.parse(retained!.envelope)).toMatchObject({ data: { Id10007: "local" }, definitionSha256: "c".repeat(64) });
  });

  it("keeps the answers snapshot across an auth retry while refreshing the device clock", async () => {
    const item = await saveLocal();
    const payloads: Array<Record<string, unknown>> = [];
    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T10:01:00Z"));
    request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => Record<string, unknown> }) => {
      payloads.push(init.bodyFactory());
      jest.setSystemTime(new Date("2026-10-01T10:02:00Z"));
      payloads.push(init.bodyFactory());
      return { status: 200, body: syncReply("incoming") };
    });
    try {
      await syncDraftSnapshot("user-1", db, item);
    } finally {
      jest.useRealTimers();
    }
    expect(payloads).toHaveLength(2);
    expect(payloads[0]).toMatchObject({ answers_json: payloads[1].answers_json, answers_sha256: payloads[1].answers_sha256, savedAt: OLD_TIME });
    expect(payloads[0].deviceClockAt).not.toBe(payloads[1].deviceClockAt);
  });

  it("replaces with the validated server winner while keeping the local id and start time", async () => {
    const item = await saveLocal({ instrumentVersion: "local-v2", definitionSha256: "a".repeat(64), definitionExtensions: ["geography"] });
    const original = JSON.parse(item.envelope) as Record<string, unknown>;
    const reply = syncReply("server");
    (reply as { envelope?: Record<string, unknown> }).envelope = {
      ...serverEnvelope(), instrumentVersion: "historic-v1", definitionSha256: "b".repeat(64), definitionExtensions: ["medical_records"],
      codingTimelineV1: [{ event: "coding_opened", at: "2026-10-01T10:00:00+05:30" }],
    };
    request.mockResolvedValueOnce({ status: 200, body: reply });

    await expect(syncDraftSnapshot("user-1", db, item)).resolves.toMatchObject({ applied: true, conflict: true, draftId: LOCAL_ID });
    const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    const winner = JSON.parse(row!.envelope) as Record<string, unknown>;
    expect(winner).toMatchObject({
      id: LOCAL_ID, startedAt: original.startedAt, currentSection: "s2", instrumentVersion: "historic-v1",
      definitionSha256: "b".repeat(64), definitionExtensions: ["medical_records"], data: { Id10007: "server" },
      codingTimelineV1: [{ event: "coding_opened", at: "2026-10-01T10:00:00+05:30" }],
    });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ updated_at: NEW_TIME, base_updated_at: NEW_TIME, draft_sync_dirty: 0 });
  });

  it("does not overwrite a concurrent local save after the server reply", async () => {
    const item = await saveLocal();
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1", binding: { projectId: "PROJECT1", deathId: DEATH_ID } });
    request.mockImplementationOnce(async () => {
      await store.save(localDraft(LOCAL_ID, NEW_TIME, { Id10007: "new local" }));
      return { status: 200, body: syncReply("incoming") };
    });

    await expect(syncDraftSnapshot("user-1", db, item)).resolves.toMatchObject({ applied: false, conflict: true });
    expect((await store.load!(LOCAL_ID))?.data).toEqual({ Id10007: "new local" });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ draft_sync_dirty: 1, server_draft_id: null });
  });

  it("does not overwrite a concurrent completion while a sync reply is in flight", async () => {
    const item = await saveLocal();
    request.mockImplementationOnce(async () => {
      await markCompleted(db, LOCAL_ID, { valid: true, issues: [] });
      return { status: 200, body: syncReply("incoming") };
    });

    await expect(syncDraftSnapshot("user-1", db, item)).resolves.toMatchObject({ applied: false, conflict: true });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ completed: 1, server_draft_id: null, draft_sync_dirty: 1 });
    const current = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(JSON.parse(current!.envelope)).toHaveProperty("completedAt");
  });

  it("rejects mismatched scope, server identity, hash, and envelope without changing local state", async () => {
    const item = await saveLocal();
    const original = item.envelope;
    const badScope = syncReply("incoming");
    badScope.draft.project_id = "OTHER";
    const badDeath = syncReply("incoming");
    badDeath.draft.death_id = "44444444-4444-4444-8444-444444444444";
    const badHash = syncReply("incoming");
    badHash.answers_sha256 = "b".repeat(64);
    const badEnvelope = syncReply("server");
    (badEnvelope.envelope as Record<string, unknown>).id = LOCAL_ID;
    const badPin = syncReply("server");
    (badPin.envelope as Record<string, unknown>).definitionSha256 = "partial";
    const badKnownServerId = syncReply("incoming");
    const invalidReplies = [badScope, badDeath, badHash, badEnvelope, badPin, badKnownServerId];

    for (const [index, body] of invalidReplies.entries()) {
      request.mockResolvedValueOnce({ status: 200, body });
      const snapshot = index === invalidReplies.length - 1
        ? { ...item, server_draft_id: "55555555-5555-4555-8555-555555555555" }
        : item;
      await expect(syncDraftSnapshot("user-1", db, snapshot)).rejects.toThrow();
      expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({
        server_draft_id: null,
        base_updated_at: null,
        draft_sync_dirty: 1
      });
      expect((await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]))?.envelope).toBe(original);
    }
  });

  it("blocks a closed case from later sync while retaining the draft for completion", async () => {
    const item = await saveLocal();
    request.mockRejectedValueOnce(new ApiError(409, "conflict"));

    await expect(syncDraftSnapshot("user-1", db, item)).rejects.toMatchObject({ status: 409, code: "conflict" });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ completed: 0, draft_sync_blocked: 1 });
    expect(await unfinishedDraftsForSync(db, "PROJECT1")).toEqual([]);
  });

  it("retries a hash refusal once with the same saved snapshot and records the second refusal", async () => {
    const item = await saveLocal();
    const payloads: Array<Record<string, unknown>> = [];
    request.mockImplementation(async (_userId: string, _path: string, init: { bodyFactory: () => Record<string, unknown> }) => {
      payloads.push(init.bodyFactory());
      throw new ApiError(422, "answers_hash_invalid");
    });

    await expect(syncDraftSnapshot("user-1", db, item)).rejects.toMatchObject({ status: 422, code: "answers_hash_invalid" });
    expect(payloads).toHaveLength(2);
    expect(payloads[0]).toMatchObject({ answers_json: payloads[1].answers_json, answers_sha256: payloads[1].answers_sha256, savedAt: OLD_TIME });
    expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ upload_issue: "answers_hash_invalid", draft_sync_dirty: 1 });
    expect(await unfinishedDraftsForSync(db, "PROJECT1")).toEqual([]);
  });

  it("sends dirty local history before fetching a newer server draft on case open", async () => {
    const item = await saveLocal();
    const paths: string[] = [];
    request.mockImplementation(async (_userId: string, path: string, init?: { bodyFactory?: () => unknown }) => {
      paths.push(path);
      init?.bodyFactory?.();
      return path.endsWith("/sync")
        ? { status: 200, body: syncReply("server") }
        : { status: 200, body: { draft: summary(), envelope: serverEnvelope(), prefill: {} } };
    });

    const result = await reconcileCaseDraft("user-1", db, caseDetail(), await getDraftRow(db, item.id), LOCAL_ID, defaults);
    expect(paths).toEqual(["/api/v1/intake/drafts/sync", `/api/v1/intake/drafts/${SERVER_ID}`]);
    expect(result).toMatchObject({ conflict: true, message: expect.any(String), imported: false });
    expect((await getDraftRow(db, LOCAL_ID))?.base_updated_at).toBe(NEW_TIME);
  });

  it("fails closed on a server draft with answers but no recoverable instrument version", async () => {
    const blankEnvelope = { ...serverEnvelope({ Id10007: "saved" }), instrumentVersion: "", currentSection: "" };
    request.mockResolvedValueOnce({ status: 200, body: {
      draft: summary(), envelope: blankEnvelope,
      prefill: { answers: { Id10007: "prefill", Id10008: "prefilled" } }
    } satisfies FetchedServerDraft });

    await expect(reconcileCaseDraft("user-1", db, caseDetail(), null, LOCAL_ID, defaults))
      .rejects.toThrow("server_draft_instrument_mismatch");
    expect(await getDraftRow(db, LOCAL_ID)).toBeNull();
  });

  it("keeps the local row when the server timestamp is equal to its base", async () => {
    const item = await saveLocal();
    await db.runAsync("UPDATE drafts SET server_draft_id = ?, base_updated_at = ?, draft_sync_dirty = 0 WHERE id = ?", [SERVER_ID, OLD_TIME, LOCAL_ID]);
    const current = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    request.mockResolvedValueOnce({ status: 200, body: { draft: summary(OLD_TIME), envelope: serverEnvelope(), prefill: {} } });

    await expect(syncDraftSnapshot("user-1", db,
      { ...item, server_draft_id: SERVER_ID, base_updated_at: OLD_TIME, draft_sync_dirty: 0 }
    )).resolves.toMatchObject({ applied: false, conflict: false, message: null });
    expect(request).toHaveBeenCalledTimes(1);
    expect((await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]))?.envelope).toBe(current?.envelope);
  });

  it("pulls a newer browser save for a clean imported draft without posting device time", async () => {
    const item = await saveLocal();
    await db.runAsync("UPDATE drafts SET server_draft_id = ?, base_updated_at = ?, draft_sync_dirty = 0 WHERE id = ?", [SERVER_ID, OLD_TIME, LOCAL_ID]);
    request.mockImplementationOnce(async (_userId: string, path: string) => {
      expect(path).toBe(`/api/v1/intake/drafts/${SERVER_ID}`);
      return { status: 200, body: { draft: summary(NEW_TIME), envelope: serverEnvelope({ Id10007: "browser" }), prefill: {} } };
    });

    await expect(syncDraftSnapshot("user-1", db,
      { ...item, server_draft_id: SERVER_ID, base_updated_at: OLD_TIME, draft_sync_dirty: 0 }
    )).resolves.toMatchObject({ applied: true, conflict: true });
    expect(request).toHaveBeenCalledTimes(1);
    const current = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
    expect(JSON.parse(current!.envelope)).toMatchObject({ id: LOCAL_ID, data: { Id10007: "browser" } });
  });

  describe("under a recorded refusal", () => {
    const refusal = {
      envelope: { client_id: "c1", decision: "refused", client_draft_id: LOCAL_ID } as never,
      project_id: "PROJECT1", covered_fields: ["Id10007", "Id10055"], recorded_by: "u1",
    };

    it("does not sync a refused in-progress draft", async () => {
      await saveDraftConsent(db, LOCAL_ID, refusal);
      const item = await saveLocal();
      await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [
        JSON.stringify({ ...JSON.parse(item.envelope), data: { Id10007: "Asha", Id10055: "PHC06 PHC name 2; Kandaghat", Id10013: "yes" } }), LOCAL_ID]);
      const [stored] = await unfinishedDraftsForSync(db, "PROJECT1");
      let payload: Record<string, unknown> | undefined;
      request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
        payload = init.bodyFactory() as Record<string, unknown>;
        return { status: 200, body: syncReply("incoming") };
      });
      await syncDraftSnapshot("user-1", db, stored);
      expect(payload).toBeUndefined();
    });

    it("does not restore server answers into a refused draft", async () => {
      await saveDraftConsent(db, LOCAL_ID, refusal);
      const item = await saveLocal();
      await db.runAsync("UPDATE drafts SET prefill = ? WHERE id = ?", [JSON.stringify({ answers: { Id10007: "from-prefill", Id10013: "yes" } }), LOCAL_ID]);
      const reply = syncReply("server");
      (reply as { envelope?: Record<string, unknown> }).envelope = serverEnvelope({ Id10007: "server", Id10019: "female" });
      request.mockResolvedValueOnce({ status: 200, body: reply });
      await syncDraftSnapshot("user-1", db, item);
      const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [LOCAL_ID]);
      expect(JSON.parse(row!.envelope).data).toEqual({});
    });

    it("sends everything when no refusal is on file", async () => {
      const item = await saveLocal();
      let payload: Record<string, unknown> | undefined;
      request.mockImplementationOnce(async (_userId: string, _path: string, init: { bodyFactory: () => unknown }) => {
        payload = init.bodyFactory() as Record<string, unknown>;
        return { status: 200, body: syncReply("incoming") };
      });
      await syncDraftSnapshot("user-1", db, item);
      expect(JSON.parse(payload!.answers_json as string)).toEqual({ Id10007: "local" });
    });

    it("stripDraftCovered removes the covered answers from the stored envelope and prefill", async () => {
      const item = await saveLocal();
      await db.runAsync("UPDATE drafts SET envelope = ?, prefill = ? WHERE id = ?", [
        JSON.stringify({ ...JSON.parse(item.envelope), data: { Id10007: "Asha", Id10055: "PHC06 PHC name 2; Kandaghat", Id10013: "yes" } }),
        JSON.stringify({ answers: { Id10007: "Asha", Id10055: "PHC06 PHC name 2; Kandaghat", Id10019: "female" }, lockedQuestionNames: ["Id10019"] }), LOCAL_ID]);
      await stripDraftCovered(db, LOCAL_ID, ["Id10007", "Id10055"]);
      const row = await db.getFirstAsync<{ envelope: string; prefill: string }>("SELECT envelope, prefill FROM drafts WHERE id = ?", [LOCAL_ID]);
      expect(JSON.parse(row!.envelope).data).toEqual({ Id10013: "yes" });
      expect(JSON.parse(row!.prefill)).toEqual({ answers: { Id10019: "female" }, lockedQuestionNames: ["Id10019"] });
      expect(await getDraftRow(db, LOCAL_ID)).toMatchObject({ draft_sync_dirty: 1 });
    });
  });
});
