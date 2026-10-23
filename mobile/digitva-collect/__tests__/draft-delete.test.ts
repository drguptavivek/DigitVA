/** Deleting a never-sent draft: who may, and everything the phone keeps for it goes (real SQLite). */
import { DatabaseSync } from "node:sqlite";

import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import { draftAttachments, markUploaded, saveAttachment } from "../src/attachmentStore";
import { saveDraftConsent, loadConsents, storedConsent } from "../src/consentStore";
import type { ConsentRecordEnvelope, ProjectConsentConfig } from "../src/consent";
import {
  createDraftStore, deleteUnsentDraft, getDraftRow, getMeta, isNeverSentDraft, listDrafts, markCompleted, migrate, setDraftUploadIssue, setMeta, type Db,
} from "../src/drafts";
import { noteSendError, sendRefusal } from "../src/unsentWork";

jest.mock("expo-crypto", () => ({ CryptoDigestAlgorithm: { SHA256: "SHA-256" }, digestStringAsync: jest.fn() }));
jest.mock("expo-secure-store", () => ({}));

const memoryDb = (): Db => {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
};
const config = { project_id: "P", notice_versions: [{ notice_version_id: "n1", covered_fields: ["Id10007"] }] } as unknown as ProjectConsentConfig;
const envelope = { client_id: "c1", notice_version_id: "n1", decision: "granted" } as unknown as ConsentRecordEnvelope;

const draft = (id: string): WhoVaDraft => ({
  schemaVersion: 1, formVersion: "f1", id, instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1",
  createdAt: "2026-10-24T00:00:00Z", updatedAt: "2026-10-24T00:00:00Z", data: { Id10007: "Asha" } as WhoVaDraft["data"],
});

let db: Db;
async function addDraft(id: string) {
  await createDraftStore(db, { projectId: "P", siteId: "S" }).save(draft(id));
  await setMeta(db, `draft-config:${id}`, { projectId: "P" });
  await saveDraftConsent(db, id, storedConsent(envelope, config, "u1"));
  await saveAttachment(db, { id: `${id}-file`, draftId: id, projectId: "P", question: "Id10007", kind: "audio", mimeType: "audio/mp4", ext: "m4a", bytes: new Uint8Array([1, 2]) });
}
beforeEach(async () => {
  db = memoryDb();
  await migrate(db);
});

describe("deleteUnsentDraft", () => {
  it("removes the draft, its consent, files, form choices and send note, and leaves other drafts alone", async () => {
    await addDraft("a");
    await addDraft("b");
    // Subject present first.
    expect(await getDraftRow(db, "a")).not.toBeNull();
    expect((await loadConsents(db)).has("consent:draft:a")).toBe(true);
    expect(await draftAttachments(db, "a")).toHaveLength(1);

    expect(await deleteUnsentDraft(db, "a")).toBe(true);

    expect(await getDraftRow(db, "a")).toBeNull();
    expect((await loadConsents(db)).has("consent:draft:a")).toBe(false);
    expect(await draftAttachments(db, "a")).toHaveLength(0);
    expect(await getMeta(db, "draft-config:a")).toBeUndefined();
    expect(await sendRefusal(db, "a")).toBeUndefined();
    // The other draft is untouched.
    expect((await listDrafts(db)).map((row) => row.id)).toEqual(["b"]);
    expect((await loadConsents(db)).has("consent:draft:b")).toBe(true);
    expect(await draftAttachments(db, "b")).toHaveLength(1);
    expect(await getMeta(db, "draft-config:b")).toBeDefined();
  });

  it("returns false for a draft that is not there", async () => {
    expect(await deleteUnsentDraft(db, "nope")).toBe(false);
  });

  it("is not offered, and deletes nothing, for a draft that was queued, sent once, held or has a server copy", async () => {
    for (const id of ["queued", "refused", "held", "server", "files"]) await addDraft(id);
    await markCompleted(db, "queued", { valid: true, issues: [] });
    await noteSendError(db, "refused", "HTTP 422 invalid_interview");
    await setDraftUploadIssue(db, "held", "case_conflict");
    await db.runAsync("UPDATE drafts SET server_draft_id = ? WHERE id = ?", ["srv-1", "server"]);
    await markUploaded(db, "files-file");

    await addDraft("fresh");
    expect(await isNeverSentDraft(db, "fresh")).toBe(true);
    for (const id of ["queued", "refused", "held", "server", "files"]) {
      expect(await isNeverSentDraft(db, id)).toBe(false);
      expect(await deleteUnsentDraft(db, id)).toBe(false);
      expect(await getDraftRow(db, id)).not.toBeNull();
      // (Completing prunes files no answer names, so the queued draft's file is already gone.)
      if (id !== "queued") expect(await draftAttachments(db, id)).toHaveLength(1);
    }
  });
});
