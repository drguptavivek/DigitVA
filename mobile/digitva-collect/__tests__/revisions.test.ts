import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";
import { createWhoVa2022Instrument, createWhoVaSession, decodeWhoVaDraft, WHO_VA_FORM_VERSION, type WhoVaDraft } from "@drguptavivek/who-2022-va";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"))
}));
jest.mock("../src/auth", () => ({
  authedRequest: jest.fn(),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {}
}));

import { authedRequest } from "../src/auth";
import { ApiError } from "../src/api";
import { migrate, purgeProjectData, type Db } from "../src/drafts";
import {
  beginRevision,
  createRevisionDraftStore,
  discardRevision,
  effectiveRevisionOutcome,
  fetchSubmittedRevisions,
  getRevisionRow,
  listLocalRevisions,
  queueRevision,
  reopenRevision,
  syncQueuedRevisions,
  type RevisionRow
} from "../src/revisions";

const USER = "user-1";
const PROJECT = "project-1";
const DRAFT_ID = "11111111-1111-4111-8111-111111111111";
const VA_SID = "22222222-2222-4222-8222-222222222222";
const hash = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");

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

const summary = () => ({
  draft_id: DRAFT_ID, project_id: PROJECT, site_id: "site-1", death_id: "death-1",
  unique_id: "U-1", va_sid: VA_SID, status: "submitted", updated_at: "2026-10-01T00:00:00Z"
});

const envelope = (data: Record<string, unknown> = { interview_outcome: "completed", Id10013: "yes", Id10007: "old" }) => ({
  schemaVersion: 1, formVersion: "2022", id: DRAFT_ID, instrumentId: "WHO_2022_VA",
  instrumentVersion: "instrument-v1", currentSection: "final", createdAt: "2026-10-01T00:00:00Z",
  updatedAt: "2026-10-01T00:00:00Z", locale: "en", translation_version: 3, data
});

const detail = (overrides: Record<string, unknown> = {}) => ({
  draft: summary(), envelope: envelope(), prefill: { deceased: { givenNames: "A" } },
  answers_sha256: "a".repeat(64), ...overrides
});

interface MockRequestInit {
  method?: string;
  body?: unknown;
  bodyFactory?: () => unknown;
  timeoutMs?: number;
}

function mockRequest(implementation: (userId: string, path: string, init?: MockRequestInit) => Promise<unknown>): jest.Mock {
  const request = authedRequest as jest.Mock;
  request.mockImplementation(implementation);
  return request;
}

describe("native submitted interview revisions", () => {
  let db: Db;
  beforeEach(async () => {
    db = memoryDb();
    await migrate(db);
    (authedRequest as jest.Mock).mockReset();
  });

  it("fetches validated metadata only, then validates scoped detail on tap", async () => {
    const request = mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    const listed = await fetchSubmittedRevisions(USER);
    expect(listed).toEqual([summary()]);
    expect(request.mock.calls[0][1]).toBe("/api/v1/intake/drafts?status=submitted");
    expect(JSON.stringify(listed)).not.toContain("Id10007");

    const row = await beginRevision(USER, db, DRAFT_ID);
    expect(row).toMatchObject({ original_answers_sha256: "a".repeat(64), prefill: { deceased: { givenNames: "A" } } });
    expect(row.envelope).not.toHaveProperty("startedAt");
    expect(row.envelope).not.toHaveProperty("completedAt");
    expect(request.mock.calls[2][1]).toBe(`/api/v1/intake/drafts/${DRAFT_ID}`);
    expect(await beginRevision(USER, db, DRAFT_ID)).toEqual(row);
    expect(request).toHaveBeenCalledTimes(3);
  });

  it("rejects a detail identity mismatch before saving raw answers", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ draft: { ...summary(), va_sid: "another-submission" } }) });
    await expect(beginRevision(USER, db, DRAFT_ID)).rejects.toThrow("malformed_response");
    expect(await listLocalRevisions(db)).toEqual([]);
  });

  it("supports direct-mode submitted revisions without a death record", async () => {
    const directSummary = { ...summary(), death_id: null };
    const request = mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [directSummary] } }
      : { body: detail({ draft: directSummary }) });
    expect(await fetchSubmittedRevisions(USER)).toEqual([directSummary]);
    const row = await beginRevision(USER, db, DRAFT_ID);
    expect(row.death_id).toBeNull();
    const stored = await db.getFirstAsync<{ row_json: string }>("SELECT row_json FROM revision_drafts WHERE draft_id = ?", [DRAFT_ID]);
    const savedRow = JSON.parse(stored!.row_json) as RevisionRow;
    savedRow.config = { enabledExtensions: ["saved_legacy_extension"] };
    await db.runAsync("UPDATE revision_drafts SET row_json = ? WHERE draft_id = ?", [JSON.stringify(savedRow), DRAFT_ID]);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    request.mockImplementation(async (_userId, path, init) => {
      const body = (init as { bodyFactory: () => Record<string, unknown> }).bodyFactory();
      expect(path).toBe(`/api/v1/intake/submissions/${VA_SID}/revisions`);
      expect(body.draft).toMatchObject({
        instrumentVersion: "instrument-v1",
        definitionExtensions: ["saved_legacy_extension"],
      });
      expect(body.draft).not.toHaveProperty("death_id");
      return { body: {
        changed: true, va_sid: VA_SID, payload_version_id: "payload-direct",
        answers_sha256: body.answers_sha256, outcome: "completed", workflow_state: "smartva_pending"
      } };
    });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toEqual({ sent: 1, failed: 0, attentionIds: [] });
    expect(await getRevisionRow(db, DRAFT_ID)).toBeNull();
  });

  it("serializes autosaves and preserves the server-known envelope metadata", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const base = { ...envelope(), locale: "en", translation_version: 3 } as WhoVaDraft;
    const first = store.save({ ...base, data: { Id10007: "first" }, updatedAt: "2026-10-01T00:01:00Z" });
    const second = store.save({ ...base, data: { Id10007: "second" }, updatedAt: "2026-10-01T00:02:00Z", locale: "hi", translation_version: 4 } as WhoVaDraft);
    await Promise.all([first, second]);
    expect(await store.load!(DRAFT_ID)).toMatchObject({
      data: { Id10007: "second" }, locale: "hi", translation_version: 4,
      instrumentId: "WHO_2022_VA", updatedAt: "2026-10-01T00:02:00Z"
    });
  });

  it("invalidates a mounted revision store before an in-flight save can outlive project purge", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const originalGetFirst = db.getFirstAsync.bind(db);
    let releaseRead!: () => void;
    let startedRead!: () => void;
    const readStarted = new Promise<void>((resolve) => { startedRead = resolve; });
    const readGate = new Promise<void>((resolve) => { releaseRead = resolve; });
    db.getFirstAsync = async <T,>(sql: string, params: Array<string | number | null>) => {
      if (sql === "SELECT row_json FROM revision_drafts WHERE draft_id = ?") {
        startedRead();
        await readGate;
      }
      return originalGetFirst<T>(sql, params);
    };

    const staleSave = store.save({ ...envelope(), data: { Id10007: "stale answer" } } as WhoVaDraft);
    await readStarted;
    const purge = purgeProjectData(db, PROJECT);
    const laterStaleSave = store.save({ ...envelope(), data: { Id10007: "later stale answer" } } as WhoVaDraft);
    releaseRead();
    await expect(staleSave).rejects.toThrow("project_access_revoked");
    await purge;
    await expect(laterStaleSave).rejects.toThrow("project_access_revoked");

    expect(await getRevisionRow(db, DRAFT_ID)).toBeNull();
  });

  it("keeps the saved definition pin through revision autosave, queueing, and upload", async () => {
    const pin = { definitionSha256: "d".repeat(64), definitionExtensions: ["geography"] };
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: { ...envelope(), instrumentVersion: "historic-v1", ...pin } }) });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...envelope(), instrumentVersion: "historic-v1", data: { interview_outcome: "completed", Id10013: "yes", Id10007: "edited" } } as WhoVaDraft);
    expect(await store.load!(DRAFT_ID)).toMatchObject({ instrumentVersion: "historic-v1", ...pin });
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });

    (authedRequest as jest.Mock).mockClear();
    const request = mockRequest(async (_userId, _path, init) => {
      const payload = (init as MockRequestInit & { bodyFactory: () => Record<string, unknown> }).bodyFactory() as Record<string, unknown>;
      expect(payload.draft).toMatchObject({
        instrumentVersion: "historic-v1",
        definitionSha256: pin.definitionSha256,
        definitionExtensions: pin.definitionExtensions,
      });
      return { body: {
        changed: true, va_sid: VA_SID, payload_version_id: "payload-2",
        answers_sha256: payload.answers_sha256, outcome: "completed", workflow_state: "smartva_pending",
      } };
    });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toEqual({ sent: 1, failed: 0, attentionIds: [] });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("freezes one exact answer string, preserves unknown start time and uses one queued completion time", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(envelope() as WhoVaDraft), data: { Id10007: "edited", interview_outcome: "completed", Id10013: "yes" } });
    const ready = await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    expect(ready.frozen_json).toBe('{"Id10007":"edited","interview_outcome":"completed","Id10013":"yes"}');
    expect(ready.answers_sha256).toBe(hash(ready.frozen_json!));
    expect(ready.envelope).not.toHaveProperty("startedAt");
    const completedAt = ready.envelope.completedAt;
    expect(completedAt).toMatch(/^[0-9T:+.\-]+$/);
    expect((await getRevisionRow(db, DRAFT_ID))?.envelope.completedAt).toBe(completedAt);
    expect(ready.state).toBe("ready");
  });

  it("keeps the server's original outcome through autosave and requires finish_partial to complete it", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: envelope({ interview_outcome: "partially_completed", Id10007: "old" }) }) });
    const row = await beginRevision(USER, db, DRAFT_ID);
    expect(row.original_outcome).toBe("partially_completed");
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(row.envelope as WhoVaDraft), data: { interview_outcome: "completed", Id10007: "finished", Id10013: "yes" } });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ original_outcome: "partially_completed" });
    await expect(queueRevision(db, DRAFT_ID, "more_information", { valid: true, issues: [] }))
      .rejects.toThrow("finish_partial_required");
    expect((await queueRevision(db, DRAFT_ID, "finish_partial", { valid: true, issues: [] })).reason_code)
      .toBe("finish_partial");
  });

  it("uses backend effective outcomes for the finish_partial gate", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: envelope({ interview_outcome: "partially_completed", Id10007: "old" }) }) });
    const row = await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(row.envelope as WhoVaDraft), data: { interview_outcome: "partially_completed", Id10013: "yes", Id10007: "finished" } });
    const completion = { valid: true, issues: [] };
    expect(effectiveRevisionOutcome({ interview_outcome: "partially_completed", Id10013: "yes" }, completion)).toBe("completed");
    await expect(queueRevision(db, DRAFT_ID, "more_information", completion)).rejects.toThrow("finish_partial_required");
    expect((await queueRevision(db, DRAFT_ID, "finish_partial", completion)).reason_code).toBe("finish_partial");
  });

  it.each([undefined, "   "])("keeps a valid revision editable when consent is missing (%s)", async (consent) => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    const row = await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const data = { Id10007: "preserved answer", interview_outcome: "completed", ...(consent !== undefined ? { Id10013: consent } : {}) };
    await store.save({ ...(row.envelope as WhoVaDraft), data });
    const completion = { valid: true, issues: [] };
    expect(effectiveRevisionOutcome(data, completion)).toBeNull();
    await expect(queueRevision(db, DRAFT_ID, "interviewer_correction", completion)).rejects.toThrow("consent_required");
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({
      state: "editing", reason_code: null, completion: null, frozen_json: null,
      envelope: { data: { Id10007: "preserved answer" } }
    });
  });

  it("keeps consent refusal ahead of completion validity", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: envelope({ interview_outcome: "partially_completed", Id10007: "old" }) }) });
    const row = await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const data = { interview_outcome: "partially_completed", Id10013: "no", Id10007: "refused" };
    await store.save({ ...(row.envelope as WhoVaDraft), data });
    const completion = { valid: true, issues: [] };
    expect(effectiveRevisionOutcome(data, completion)).toBe("refused");
    expect((await queueRevision(db, DRAFT_ID, "interviewer_correction", completion)).reason_code)
      .toBe("interviewer_correction");
  });

  it("round-trips a queued revision through the bundled WHO instrument and decoder", async () => {
    const instrument = createWhoVa2022Instrument(["digitva_core"]);
    const session = createWhoVaSession(instrument, { locale: "en" });
    session.replaceData({ Id10013: "yes" });
    const rawAnswers = session.getSnapshot().data;
    const whoEnvelope = {
      schemaVersion: 1,
      formVersion: WHO_VA_FORM_VERSION,
      id: DRAFT_ID,
      instrumentId: instrument.id,
      instrumentVersion: instrument.version,
      currentSection: session.getSnapshot().currentSection.name,
      createdAt: "2026-10-01T00:00:00Z",
      updatedAt: "2026-10-01T00:00:00Z",
      locale: "en",
      translation_version: 3,
      data: { ...rawAnswers, interview_outcome: "partially_completed" }
    };
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: whoEnvelope }) });
    const row = await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const decoded = decodeWhoVaDraft(await store.load!(DRAFT_ID));
    const restoredSession = createWhoVaSession(instrument, {
      initialData: decoded.data,
      initialSection: decoded.currentSection,
      locale: "en"
    });
    const resumedAnswers = { ...restoredSession.getSnapshot().data, interview_outcome: "partially_completed" };
    const serializedAnswers = JSON.parse(JSON.stringify(resumedAnswers)) as Record<string, unknown>;
    await store.save({
      ...decoded,
      data: resumedAnswers,
      updatedAt: "2026-10-01T00:02:00Z",
      locale: "hi",
      translation_version: 4
    } as WhoVaDraft);
    const saved = await store.load!(DRAFT_ID);
    expect(saved).toMatchObject({
      instrumentId: instrument.id,
      instrumentVersion: instrument.version,
      formVersion: WHO_VA_FORM_VERSION,
      locale: "hi",
      translation_version: 4,
      updatedAt: "2026-10-01T00:02:00Z",
      data: serializedAnswers
    });
    const ready = await queueRevision(db, DRAFT_ID, "finish_partial", { valid: true, issues: [] });
    expect(ready.frozen_json).toBe(JSON.stringify(saved!.data));
    expect(ready.answers_sha256).toBe(hash(ready.frozen_json!));
    expect(ready.envelope).not.toHaveProperty("startedAt");
    expect(row.envelope.instrumentId).toBe(instrument.id);
  });

  it("does not mark a revision ready if an autosave wins while the frozen hash is computed", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(envelope() as WhoVaDraft), data: { Id10007: "before hash", Id10013: "yes" } });
    const crypto = require("expo-crypto") as { digestStringAsync: jest.Mock };
    let releaseHash!: (value: string) => void;
    let hashStarted!: () => void;
    const started = new Promise<void>((resolve) => { hashStarted = resolve; });
    crypto.digestStringAsync.mockImplementationOnce(() => {
      hashStarted();
      return new Promise<string>((resolve) => { releaseHash = resolve; });
    });
    const queued = queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    await started;
    await store.save({ ...(envelope() as WhoVaDraft), data: { Id10007: "after hash began", Id10013: "yes" } });
    releaseHash(hash('{"Id10007":"before hash"}'));
    await expect(queued).rejects.toThrow("revision_conflict");
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({
      state: "editing", answers_sha256: null, envelope: { data: { Id10007: "after hash began" } }
    });
  });

  it("sends the frozen text through one hash retry and accepts a matching no-change acknowledgement", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(envelope() as WhoVaDraft), data: { Id10007: "frozen", Id10013: "yes" } });
    const row = await queueRevision(db, DRAFT_ID, "more_information", { valid: true, issues: [] });
    let sends = 0;
    const deviceClocks: unknown[] = [];
    const request = mockRequest(async (_userId, _path, init) => {
      const body = (init as { bodyFactory: () => Record<string, unknown> }).bodyFactory();
      expect(body.answers_json).toBe(row.frozen_json);
      deviceClocks.push((body.draft as Record<string, unknown>).deviceClockAt);
      sends += 1;
      if (sends === 1) {
        jest.advanceTimersByTime(1000);
        throw new ApiError(422, "answers_hash_invalid");
      }
      return { body: {
        changed: false, va_sid: VA_SID, payload_version_id: "payload-1",
        answers_sha256: row.answers_sha256, outcome: "completed", workflow_state: "smartva_pending"
      } };
    });
    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T00:00:00Z"));
    const result = await syncQueuedRevisions(USER, db, new Set([PROJECT]));
    jest.useRealTimers();
    expect(result).toEqual({ sent: 1, failed: 0, attentionIds: [] });
    expect(sends).toBe(2);
    expect(deviceClocks[0]).not.toBe(deviceClocks[1]);
    expect(await getRevisionRow(db, DRAFT_ID)).toBeNull();
  });

  it("retains a newer autosave when the server acknowledges the frozen snapshot", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    await store.save({ ...(envelope() as WhoVaDraft), data: { Id10007: "sent", Id10013: "yes" } });
    const row = await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async () => {
      await store.save({ ...(row.envelope as WhoVaDraft), data: { Id10007: "edited during upload" } });
      return { body: {
        changed: true, va_sid: VA_SID, payload_version_id: "payload-1",
        answers_sha256: row.answers_sha256, outcome: "completed", workflow_state: "smartva_pending"
      } };
    });
    const result = await syncQueuedRevisions(USER, db, new Set([PROJECT]));
    expect(result).toEqual({ sent: 0, failed: 0, attentionIds: [] });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "editing", envelope: { data: { Id10007: "edited during upload" } } });
  });

  it("retains malformed acknowledgements for attention and retries network failures later", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async () => ({ body: { changed: true, va_sid: "wrong", answers_sha256: "b".repeat(64) } }));
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toMatchObject({ failed: 1, attentionIds: [DRAFT_ID] });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "attention", refusal_code: "invalid_revision_ack" });
    await reopenRevision(db, DRAFT_ID);
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "editing", answers_sha256: null });
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async () => { throw new Error("network"); });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toMatchObject({ failed: 1, attentionIds: [] });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "ready" });
  });

  it("keeps malformed imported revision pins visible and prevents queued upload", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail({ envelope: { ...envelope(), definitionSha256: "d".repeat(64) } }) });
    const imported = await beginRevision(USER, db, DRAFT_ID);
    expect(imported).toMatchObject({ state: "attention", refusal_code: "invalid_definition_pin", envelope: { data: { Id10007: "old" } } });
    expect(await listLocalRevisions(db)).toMatchObject([{ state: "attention", refusal_code: "invalid_definition_pin" }]);

    await discardRevision(db, DRAFT_ID);
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    const stored = await db.getFirstAsync<{ row_json: string }>("SELECT row_json FROM revision_drafts WHERE draft_id = ?", [DRAFT_ID]);
    const row = JSON.parse(stored!.row_json) as RevisionRow;
    row.envelope.definitionExtensions = ["geography"];
    await db.runAsync("UPDATE revision_drafts SET row_json = ? WHERE draft_id = ?", [JSON.stringify(row), DRAFT_ID]);

    const before = (authedRequest as jest.Mock).mock.calls.length;
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toMatchObject({ failed: 1, attentionIds: [DRAFT_ID] });
    expect((authedRequest as jest.Mock).mock.calls).toHaveLength(before);
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({
      state: "attention", refusal_code: "invalid_definition_pin", envelope: { data: { Id10007: "old" }, definitionExtensions: ["geography"] }
    });
  });

  it("retains terminal refusals and skips revoked projects", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    const request = mockRequest(async () => { throw new ApiError(409, "revision_locked"); });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toMatchObject({ failed: 1, attentionIds: [DRAFT_ID] });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "attention", refusal_code: "revision_locked" });
    expect(request).toHaveBeenCalledTimes(3); // submitted list, on-demand detail, then revision
    await reopenRevision(db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    request.mockClear();
    expect(await syncQueuedRevisions(USER, db, new Set())).toEqual({ sent: 0, failed: 0, attentionIds: [] });
    expect(request).not.toHaveBeenCalled();
    await discardRevision(db, DRAFT_ID);
    expect(await listLocalRevisions(db)).toEqual([]);
  });

  it("retains a locked correction through manual reopen and purges only its acknowledged snapshot", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    const row = await beginRevision(USER, db, DRAFT_ID);
    const store = createRevisionDraftStore(db, DRAFT_ID, PROJECT);
    const correctedAnswers = { ...row.envelope.data, Id10007: "retained correction" };
    await store.save({ ...(row.envelope as WhoVaDraft), data: correctedAnswers });
    const firstSnapshot = await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });

    mockRequest(async () => { throw new ApiError(409, "revision_locked"); });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT])))
      .toMatchObject({ failed: 1, attentionIds: [DRAFT_ID] });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({
      state: "attention",
      refusal_code: "revision_locked",
      frozen_json: firstSnapshot.frozen_json,
      answers_sha256: firstSnapshot.answers_sha256,
      envelope: { data: correctedAnswers },
    });

    await reopenRevision(db, DRAFT_ID);
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({
      state: "editing", frozen_json: null, answers_sha256: null, envelope: { data: correctedAnswers },
    });
    const ready = await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async (_userId, _path, init) => {
      const body = init?.bodyFactory?.() as Record<string, unknown>;
      expect(body.answers_json).toBe(ready.frozen_json);
      expect(body.answers_sha256).toBe(ready.answers_sha256);
      return { body: {
        changed: true, va_sid: VA_SID, payload_version_id: "payload-unlocked",
        answers_sha256: ready.answers_sha256, outcome: "completed", workflow_state: "smartva_pending",
      } };
    });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT])))
      .toEqual({ sent: 1, failed: 0, attentionIds: [] });
    expect(await getRevisionRow(db, DRAFT_ID)).toBeNull();
  });

  it.each([409, 422])("moves unrecognized HTTP %s revision rejections to attention", async (status) => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async () => { throw new ApiError(status, "new_backend_rejection"); });
    expect(await syncQueuedRevisions(USER, db, new Set([PROJECT]))).toMatchObject({
      sent: 0, failed: 1, attentionIds: [DRAFT_ID]
    });
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "attention", refusal_code: "revision_rejected" });
  });

  it("propagates project-level authorization failures without discarding a ready revision", async () => {
    mockRequest(async (_userId, path) => path.endsWith("?status=submitted")
      ? { body: { drafts: [summary()] } }
      : { body: detail() });
    await beginRevision(USER, db, DRAFT_ID);
    await queueRevision(db, DRAFT_ID, "interviewer_correction", { valid: true, issues: [] });
    mockRequest(async () => { throw new ApiError(403, "forbidden"); });
    await expect(syncQueuedRevisions(USER, db, new Set([PROJECT]))).rejects.toThrow("forbidden");
    expect(await getRevisionRow(db, DRAFT_ID)).toMatchObject({ state: "ready" });
  });
});
