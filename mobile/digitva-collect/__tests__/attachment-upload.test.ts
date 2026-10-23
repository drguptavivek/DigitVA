/** Files go up before the interview: order, idempotent retry, transient vs permanent failures, consent refusal. Real SQLite. */
import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockRequest = jest.fn();
jest.mock("../src/auth", () => ({ authedRequest: (...args: unknown[]) => mockRequest(...args) }));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digest: async (_algorithm: string, data: Uint8Array) => require("node:crypto").createHash("sha256").update(data).digest().buffer,
}));

import { ApiError } from "../src/api";
import { draftAttachments, saveAttachment } from "../src/attachmentStore";
import { uploadDraftAttachments } from "../src/attachmentUpload";
import { createDraftStore, getDraftRow, markCompleted, migrate, type Db } from "../src/drafts";
import { sendRefusal } from "../src/unsentWork";
import { withoutCovered } from "../src/consentStore";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...(params as never[])),
    getAllAsync: async <T,>(sql: string, params: unknown[]) => db.prepare(sql).all(...(params as never[])) as T[],
    getFirstAsync: async <T,>(sql: string, params: unknown[]) => (db.prepare(sql).get(...(params as never[])) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const SERVER_DRAFT = "99999999-9999-4999-8999-999999999999";
const ref = (id: string) => ({ id, uri: `who-va-attachment:${id}` });
const item = { id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, death_id: "death-1" };
const draft: WhoVaDraft = {
  schemaVersion: 1, formVersion: "f1", id: "d1", instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z", updatedAt: "2026-09-30T00:00:00Z", data: {},
};
const file = (id: string, question: string, byte: number) => ({
  id, draftId: "d1", projectId: "P1", question, kind: "audio" as const, mimeType: "audio/mp4", ext: "m4a", bytes: new Uint8Array([byte, 1]),
});

let db: Db;
beforeEach(async () => {
  db = memoryDb();
  await migrate(db);
  mockRequest.mockReset();
  mockRequest.mockImplementation(async (_user: string, path: string, init: { method?: string }) =>
    init.method === "POST" && path.endsWith("/drafts") ? { status: 201, body: { draft: { draft_id: SERVER_DRAFT } } } : { status: 201, body: { created: true } });
  await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save({ ...draft, data: { Id10476_audio: ref(A), imagenarr: ref(B) } as never });
  await markCompleted(db, "d1", { valid: true, issues: [] });
  await saveAttachment(db, file(A, "Id10476_audio", 7));
  await saveAttachment(db, file(B, "imagenarr", 8));
});

const puts = () => mockRequest.mock.calls.filter(([, , init]) => init.method === "PUT");

it("gets the server draft once, PUTs each referenced file as a raw body with its hash, and marks them confirmed", async () => {
  const result = await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A), imagenarr: ref(B) });
  expect(result).toEqual({ state: "done" });
  expect(mockRequest.mock.calls[0]).toEqual(["u1", "/api/v1/intake/drafts", expect.objectContaining({ method: "POST", body: { project_id: "P1", site_id: "S1", death_id: "death-1" } })]);
  expect(puts().map(([, path]) => path)).toEqual([`/api/v1/intake/drafts/${SERVER_DRAFT}/attachments/${A}`, `/api/v1/intake/drafts/${SERVER_DRAFT}/attachments/${B}`]);
  const [, , init] = puts()[0]!;
  expect([...init.rawBody.bytes]).toEqual([7, 1]);
  expect(init.rawBody.sha256).toMatch(/^[0-9a-f]{64}$/);
  expect((await draftAttachments(db, "d1")).every((f) => f.uploaded_at)).toBe(true);
});

it("sends nothing for confirmed files, or when the answers reference no file", async () => {
  await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A), imagenarr: ref(B) });
  mockRequest.mockClear();
  expect(await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A), imagenarr: ref(B) })).toEqual({ state: "done" });
  expect(await uploadDraftAttachments("u1", db, item, { Id10013: "yes" })).toEqual({ state: "done" });
  expect(mockRequest).not.toHaveBeenCalled();
});

it("never sends the file of a question a consent refusal covers", async () => {
  const sent = withoutCovered({ Id10476_audio: ref(A), imagenarr: ref(B) }, ["Id10476_audio"]) as Record<string, unknown>;
  await uploadDraftAttachments("u1", db, item, sent);
  expect(puts().map(([, path]) => path)).toEqual([`/api/v1/intake/drafts/${SERVER_DRAFT}/attachments/${B}`]);
});

it("keeps what was sent and retries the rest next time after a network or server fault", async () => {
  let n = 0;
  mockRequest.mockImplementation(async (_u: string, path: string, init: { method?: string }) => {
    if (init.method === "POST") return { status: 201, body: { draft: { draft_id: SERVER_DRAFT } } };
    if (++n === 2) throw new ApiError(503, "unavailable");
    return { status: 201, body: {} };
  });
  const result = await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A), imagenarr: ref(B) });
  expect(result).toMatchObject({ state: "retry" });
  const files = await draftAttachments(db, "d1");
  expect(files.find((f) => f.id === A)!.uploaded_at).not.toBeNull();
  expect(files.find((f) => f.id === B)!.uploaded_at).toBeNull();
  expect((await sendRefusal(db, B))?.status).toBe(503);
  expect((await getDraftRow(db, "d1"))!.completed).toBe(1);
  // The next pass sends only the remaining file.
  mockRequest.mockClear();
  mockRequest.mockImplementation(async (_u: string, _p: string, init: { method?: string }) =>
    init.method === "POST" ? { status: 201, body: { draft: { draft_id: SERVER_DRAFT } } } : { status: 200, body: {} });
  expect(await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A), imagenarr: ref(B) })).toEqual({ state: "done" });
  expect(puts()).toHaveLength(1);
});

it("reopens the interview when the server refuses the file for good, and does not retry it until the file is replaced", async () => {
  mockRequest.mockImplementation(async (_u: string, _p: string, init: { method?: string }) => {
    if (init.method === "POST") return { status: 201, body: { draft: { draft_id: SERVER_DRAFT } } };
    throw new ApiError(415, "unsupported_media_type");
  });
  const result = await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A) });
  expect(result).toMatchObject({ state: "held" });
  expect((await getDraftRow(db, "d1"))!.completed).toBe(0);
  expect((await sendRefusal(db, A))?.status).toBe(415);

  await markCompleted(db, "d1", { valid: true, issues: [] });
  mockRequest.mockClear();
  expect(await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A) })).toMatchObject({ state: "held" });
  expect(mockRequest).not.toHaveBeenCalled(); // no resend of a refused file
});

it("holds the interview when its case is closed or gone (409, 404) as a refused submit does", async () => {
  mockRequest.mockRejectedValueOnce(new ApiError(409, "case_closed"));
  expect(await uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A) })).toMatchObject({ state: "held" });
  expect((await getDraftRow(db, "d1"))!.upload_issue).toBe("case_conflict");
});

describe("direct start (no case)", () => {
  const direct = { ...item, death_id: null };
  const starts = () => mockRequest.mock.calls.filter(([, path, init]) => init.method === "POST" && String(path).endsWith("/drafts"));

  it("starts the server draft by the interview's own id, PUTs the files to it, and is done", async () => {
    expect(await uploadDraftAttachments("u1", db, direct, { Id10476_audio: ref(A), imagenarr: ref(B) })).toEqual({ state: "done" });
    expect(mockRequest.mock.calls[0]).toEqual(["u1", "/api/v1/intake/drafts", expect.objectContaining({ method: "POST", body: { project_id: "P1", site_id: "S1", client_draft_id: "d1" } })]);
    expect(puts().map(([, path]) => path)).toEqual([
      `/api/v1/intake/drafts/${SERVER_DRAFT}/attachments/${A}`,
      `/api/v1/intake/drafts/${SERVER_DRAFT}/attachments/${B}`,
    ]);
    expect(mockRequest.mock.calls.findIndex(([, , init]) => init.method === "PUT")).toBeGreaterThan(0); // start first
  });

  it("is repeat-safe: a 200 for an id already started returns the same draft and only unconfirmed files go up", async () => {
    mockRequest.mockImplementation(async (_u: string, path: string, init: { method?: string }) =>
      init.method === "POST" && path.endsWith("/drafts") ? { status: 200, body: { draft: { draft_id: SERVER_DRAFT } } } : { status: 201, body: {} });
    mockRequest.mockRejectedValueOnce(new ApiError(503, "unavailable")); // the first start fails
    expect(await uploadDraftAttachments("u1", db, direct, { Id10476_audio: ref(A) })).toMatchObject({ state: "retry" });
    expect(await uploadDraftAttachments("u1", db, direct, { Id10476_audio: ref(A) })).toEqual({ state: "done" });
    expect(await uploadDraftAttachments("u1", db, direct, { Id10476_audio: ref(A) })).toEqual({ state: "done" }); // confirmed: no call
    expect(starts()).toHaveLength(2);
    expect(puts()).toHaveLength(1);
  });

  it("holds the interview on a 409 at the start (another user, already uploaded, mismatch) and uploads nothing", async () => {
    mockRequest.mockRejectedValueOnce(new ApiError(409, "draft_conflict"));
    expect(await uploadDraftAttachments("u1", db, direct, { Id10476_audio: ref(A) })).toMatchObject({ state: "held" });
    expect((await getDraftRow(db, "d1"))!.upload_issue).toBe("case_conflict");
    expect(puts()).toHaveLength(0);
  });
});

describe("which refusals are permanent", () => {
  const failPut = (error: ApiError) => mockRequest.mockImplementation(async (_u: string, _p: string, init: { method?: string }) => {
    if (init.method === "POST") return { status: 201, body: { draft: { draft_id: SERVER_DRAFT } } };
    throw error;
  });
  const send = () => uploadDraftAttachments("u1", db, item, { Id10476_audio: ref(A) });

  it.each([[400, "checksum_mismatch"], [400, "invalid_request"], [413, undefined], [413, "redirected_response"]])(
    "retries a truncated or proxy-refused transfer (%s %s) and keeps the interview complete", async (status, code) => {
      failPut(new ApiError(status, code));
      expect(await send()).toMatchObject({ state: "retry" });
      expect((await getDraftRow(db, "d1"))!.completed).toBe(1);
    });

  it.each([[413, "payload_too_large"], [415, "unsupported_media_type"], [422, "empty_attachment"], [400, "bad_thing"]])(
    "holds for the server's own refusal (%s %s)", async (status, code) => {
      failPut(new ApiError(status, code));
      expect(await send()).toMatchObject({ state: "held" });
      expect((await getDraftRow(db, "d1"))!.completed).toBe(0);
    });

  it("holds on attachment_limit but blames the interview, not the file, so a later send tries again", async () => {
    failPut(new ApiError(422, "attachment_limit"));
    expect(await send()).toMatchObject({ state: "held" });
    expect(await sendRefusal(db, A)).toBeUndefined();
    expect((await sendRefusal(db, "d1"))?.status).toBe(422);
    await markCompleted(db, "d1", { valid: true, issues: [] });
    mockRequest.mockClear();
    failPut(new ApiError(422, "attachment_limit"));
    await send();
    expect(puts()).toHaveLength(1);
  });
});
