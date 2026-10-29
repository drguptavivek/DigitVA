/** Captured files in the encrypted store: save/read, deletion with the draft, consent refusal, unsent accounting. Real SQLite. */
import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import {
  deleteAttachment,
  deleteCoveredAttachments,
  pruneUnreferencedAttachments,
  draftAttachments,
  getAttachmentBytes,
  markDraftUnconfirmed,
  markUploaded,
  referenceId,
  referencedIds,
  saveAttachment,
  sendableAttachments,
} from "../src/attachmentStore";
import { createDraftStore, deleteDraft, deleteDraftSnapshot, markCompleted, migrate, stripDraftCovered, type Db } from "../src/drafts";
import { pendingErrors, resetErrorLog } from "../src/errorLog";
import { noteSendError, sendRefusal, summariseWork } from "../src/unsentWork";

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
const draft = (id: string, data: Record<string, unknown> = {}): WhoVaDraft => ({
  schemaVersion: 1, formVersion: "f1", id, instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z", updatedAt: "2026-09-30T00:00:00Z", data: data as WhoVaDraft["data"],
});
const ref = (id: string) => ({ id, uri: `who-va-attachment:${id}`, mimeType: "audio/mp4" });
const file = (id: string, draftId: string, question = "Id10476_audio", byte = 7) => ({
  id, draftId, projectId: "P1", question, kind: "audio" as const, mimeType: "audio/mp4", ext: "m4a", durationMs: 1000, bytes: new Uint8Array([byte, 2, 3]),
});

let db: Db;
beforeEach(async () => { db = memoryDb(); await migrate(db); resetErrorLog(); });

it("round-trips the bytes and keeps the listing free of them", async () => {
  await saveAttachment(db, file(A, "d1"));
  expect([...(await getAttachmentBytes(db, A))!]).toEqual([7, 2, 3]);
  const [meta] = await draftAttachments(db, "d1");
  expect(meta).toMatchObject({ id: A, question: "Id10476_audio", kind: "audio", size_bytes: 3, uploaded_at: null });
  expect(meta).not.toHaveProperty("data");
  expect(await getAttachmentBytes(db, B)).toBeNull();
});

it("reads a reference from the engine's object, the prefixed string, or nothing", () => {
  expect(referenceId(ref(A))).toBe(A);
  expect(referenceId(`who-va-attachment:${A.toUpperCase()}`)).toBe(A);
  expect(referenceId({ id: "not-a-uuid" })).toBeUndefined();
  expect(referenceId("free text")).toBeUndefined();
  expect([...referencedIds({ q1: ref(A), q2: "hello", q3: { startedAt: "x" }, q4: ["a"], q5: `who-va-attachment:${B}` })].sort()).toEqual([A, B]);
});

it("lists only the files the sent answers reference, and reports a reference the phone does not hold", async () => {
  await saveAttachment(db, file(A, "d1"));
  await saveAttachment(db, file(B, "d1", "md_im1"));
  const sent = await sendableAttachments(db, "d1", { Id10476_audio: ref(A), md_im2: ref("33333333-3333-4333-8333-333333333333") });
  expect(sent.files.map((f) => f.id)).toEqual([A]);
  expect(sent.missing).toEqual(["33333333-3333-4333-8333-333333333333"]);
});

it("deletes the files with their draft, whether deleted outright or after an acknowledged upload", async () => {
  await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft("d1"));
  await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft("d2"));
  await saveAttachment(db, file(A, "d1"));
  await saveAttachment(db, file(B, "d2"));
  await deleteDraft(db, "d1");
  expect((await draftAttachments(db, "d1"))).toEqual([]);
  expect((await draftAttachments(db, "d2")).length).toBe(1);
  const envelope = (await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", ["d2"]))!.envelope;
  expect(await deleteDraftSnapshot(db, "d2", "stale")).toBe(false);
  expect((await draftAttachments(db, "d2")).length).toBe(1); // edited while sending: the files stay
  expect(await deleteDraftSnapshot(db, "d2", envelope)).toBe(true);
  expect(await draftAttachments(db, "d2")).toEqual([]);
});

it("drops files captured for a draft that was never saved when the store is opened", async () => {
  await saveAttachment(db, file(A, "never-saved"));
  await migrate(db);
  expect(await draftAttachments(db, "never-saved")).toEqual([]);
});

it("a consent refusal deletes the files of the covered questions and keeps the others", async () => {
  await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft("d1", { Id10476_audio: ref(A), md_im1: ref(B) }));
  await saveAttachment(db, file(A, "d1", "Id10476_audio"));
  await saveAttachment(db, file(B, "d1", "md_im1"));
  await stripDraftCovered(db, "d1", ["Id10476_audio"]);
  expect((await draftAttachments(db, "d1")).map((f) => f.question)).toEqual(["md_im1"]);
});

it("deleting a file forgets its refusal; marking a draft unconfirmed re-queues every file", async () => {
  await saveAttachment(db, file(A, "d1"));
  await markUploaded(db, A);
  expect((await draftAttachments(db, "d1"))[0]!.uploaded_at).not.toBeNull();
  await markDraftUnconfirmed(db, "d1");
  expect((await draftAttachments(db, "d1"))[0]!.uploaded_at).toBeNull();
  await noteSendError(db, A, "senderr");
  expect(await sendRefusal(db, A)).toBeDefined();
  await deleteAttachment(db, A);
  expect(await sendRefusal(db, A)).toBeUndefined();
  expect(pendingErrors().length).toBeGreaterThan(0);
});

describe("unsent work", () => {
  const complete = async (id: string, valid = true) => {
    await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft(id));
    await markCompleted(db, id, { valid, issues: [] });
  };

  it("lists each file of a completed interview the server has not confirmed, counted apart from the interview", async () => {
    await complete("d1");
    await saveAttachment(db, file(A, "d1"));
    await saveAttachment(db, file(B, "d1", "md_im1"));
    expect(await summariseWork(db)).toMatchObject({ unsent: 1, unsentFiles: 2, attention: 0 });
    await markUploaded(db, B);
    const work = await summariseWork(db);
    expect(work).toMatchObject({ unsent: 1, unsentFiles: 1 });
    expect(work.items.filter((item) => item.kind === "attachment")).toHaveLength(1);
  });

  it("does not count the files of an interview still being filled in", async () => {
    await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft("d1"));
    await saveAttachment(db, file(A, "d1"));
    expect(await summariseWork(db)).toMatchObject({ unsent: 0, attention: 0, inProgress: 1 });
  });

  it("moves the files to attention with the interview, each with its own Ref after a failed send", async () => {
    await complete("d1", false); // not valid and no incomplete outcome: held
    await saveAttachment(db, file(A, "d1"));
    await noteSendError(db, A, "network");
    const work = await summariseWork(db);
    expect(work).toMatchObject({ unsent: 0, attention: 2 });
    expect(work.items.find((item) => item.kind === "attachment")).toMatchObject({ state: "attention", error: expect.any(String) });
  });
});

describe("covered and unreferenced files", () => {
  it("deletes only the covered questions' files, with their refusal notes", async () => {
    await saveAttachment(db, file(A, "d1", "md_im1"));
    await saveAttachment(db, file(B, "d1", "Id10476_audio"));
    expect(await draftAttachments(db, "d1")).toHaveLength(2);
    await deleteCoveredAttachments(db, "d1", ["md_im1"]);
    expect((await draftAttachments(db, "d1")).map((f) => f.id)).toEqual([B]);
    await deleteCoveredAttachments(db, "d1", []);
    expect(await draftAttachments(db, "d1")).toHaveLength(1);
  });

  it("completing a draft drops files its answers no longer reference", async () => {
    await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft("d1", { Id10476_audio: ref(A) }));
    await saveAttachment(db, file(A, "d1"));
    await saveAttachment(db, file(B, "d1", "md_im1")); // replaced take
    await markCompleted(db, "d1", { valid: true, issues: [] });
    expect((await draftAttachments(db, "d1")).map((f) => f.id)).toEqual([A]);
  });

  it("prunes nothing when there are no answers to compare with", async () => {
    await saveAttachment(db, file(A, "d1"));
    await pruneUnreferencedAttachments(db, "d1", undefined);
    expect(await draftAttachments(db, "d1")).toHaveLength(1);
  });
});
