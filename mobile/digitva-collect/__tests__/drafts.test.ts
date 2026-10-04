/**
 * The draft store against a real SQLite engine (Node's built-in node:sqlite),
 * wrapped in the same async surface expo-sqlite exposes.
 */
import { DatabaseSync } from "node:sqlite";

import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import {
  completedDrafts,
  countDrafts,
  createDraftStore,
  deleteDraftSnapshot,
  draftIds,
  getDraftRow,
  getMeta,
  listDrafts,
  localDateTimeWithOffset,
  markCompleted,
  migrate,
  purgeProjectData,
  setMeta,
  setDraftUploadIssue,
  type Db
} from "../src/drafts";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) =>
      db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) =>
      (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close()
  };
}

const draft = (id: string, updatedAt: string, data: Record<string, unknown> = {}): WhoVaDraft => ({
  schemaVersion: 1,
  formVersion: "f1",
  id,
  instrumentId: "who-va-2022",
  instrumentVersion: "1",
  currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z",
  updatedAt,
  data: data as WhoVaDraft["data"]
});

describe("draft store", () => {
  let db: Db;
  beforeEach(async () => {
    db = memoryDb();
    await migrate(db);
    await migrate(db); // idempotent
  });

  it("formats local wall time with its explicit offset across midnight", () => {
    const date = new Date("2026-10-01T18:31:00.123Z");
    jest.spyOn(date, "getTimezoneOffset").mockReturnValue(-330);
    expect(localDateTimeWithOffset(date)).toBe("2026-10-02T00:01:00.123+05:30");
  });

  it("keeps start and completion times when autosave and resume drafts omit host fields", async () => {
    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T18:31:00Z"));
    try {
      const openedAt = localDateTimeWithOffset();
      const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
      jest.setSystemTime(new Date("2026-10-01T18:31:02Z"));
      await store.save(draft("timed", "2026-09-30T01:00:00Z", { Id10007: "first" }));
      const startedAt = (await store.load!("timed") as WhoVaDraft & { startedAt?: string }).startedAt;
      expect(startedAt).toBe(openedAt);

      await markCompleted(db, "timed", { valid: true, issues: [] });
      const completedAt = (await store.load!("timed") as WhoVaDraft & { completedAt?: string }).completedAt;
      expect(completedAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);

      const resumedStore = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
      await resumedStore.save(draft("timed", "2026-09-30T02:00:00Z", { Id10007: "updated" }));
      const resumed = await resumedStore.load!("timed") as WhoVaDraft & { startedAt?: string; completedAt?: string };
      expect(resumed).toMatchObject({ startedAt, completedAt, data: { Id10007: "updated" } });
    } finally {
      jest.useRealTimers();
    }
  });

  it("updates completion time on each explicit completion", async () => {
    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T18:31:00Z"));
    try {
      const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
      await store.save(draft("repeat", "2026-09-30T01:00:00Z"));
      await markCompleted(db, "repeat", { valid: true, issues: [] });
      const first = (await store.load!("repeat") as WhoVaDraft & { completedAt?: string }).completedAt;

      jest.setSystemTime(new Date("2026-10-01T18:31:01Z"));
      await markCompleted(db, "repeat", { valid: false, issues: [] });
      const second = (await store.load!("repeat") as WhoVaDraft & { completedAt?: string }).completedAt;

      expect(second).not.toBe(first);
      expect(await getDraftRow(db, "repeat")).toMatchObject({ completed: 1 });
    } finally {
      jest.useRealTimers();
    }
  });

  it("adds a start on the next save of a legacy completed draft without inventing its completion time", async () => {
    await db.runAsync("INSERT INTO drafts (id, project_id, site_id, completed, updated_at, envelope) VALUES (?, ?, ?, ?, ?, ?)", [
      "legacy", "PROJECT1", "SITE1", 1, "2026-09-30T01:00:00Z", JSON.stringify(draft("legacy", "2026-09-30T01:00:00Z"))
    ]);
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
    await store.save(draft("legacy", "2026-09-30T02:00:00Z"));
    const saved = await store.load!("legacy") as WhoVaDraft & { startedAt?: string; completedAt?: string };
    expect(saved.startedAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(saved.completedAt).toBeUndefined();
  });

  it("saves, loads and updates a draft without moving its site", async () => {
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1", orgUnitId: "unit-1" });
    await store.save(draft("a", "2026-09-30T01:00:00Z", { Id10007: "x" }));
    expect((await store.load!("a"))?.data).toEqual({ Id10007: "x" });

    const otherHost = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE2" });
    await otherHost.save(draft("a", "2026-09-30T02:00:00Z", { Id10007: "y" }));
    const rows = await listDrafts(db);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "a", site_id: "SITE1", org_unit_id: "unit-1", completed: 0 });
    expect((await store.load!("a"))?.data).toEqual({ Id10007: "y" });
  });

  it("returns undefined for an unknown draft and removes one", async () => {
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
    expect(await store.load!("missing")).toBeUndefined();
    await store.save(draft("a", "2026-09-30T01:00:00Z"));
    expect(await countDrafts(db)).toBe(1);
    await store.remove!("a");
    expect(await countDrafts(db)).toBe(0);
  });

  it("lists only completed drafts for upload, with their envelopes", async () => {
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
    await store.save(draft("a", "2026-09-30T01:00:00Z"));
    await store.save(draft("b", "2026-09-30T02:00:00Z", { Id10007: "z" }));
    expect(await completedDrafts(db)).toEqual([]);
    const issues = [{ question: "Id10010", code: "required" as const, message: "Required" }];
    await markCompleted(db, "b", { valid: false, issues });
    const ready = await completedDrafts(db);
    expect(ready).toHaveLength(1);
    expect(ready[0]).toMatchObject({ id: "b", site_id: "SITE1", org_unit_id: null });
    expect(ready[0].draft.data).toEqual({ Id10007: "z" });
    expect(ready[0].completion).toEqual({ valid: false, issues });
    expect(await draftIds(db)).toEqual(["a", "b"]);
  });

  it("persists upload issues without making hash mismatches resendable", async () => {
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
    await store.save(draft("mismatch", "2026-09-30T01:00:00Z", { Id10007: "old" }));
    await store.save(draft("invalid", "2026-09-30T02:00:00Z", { Id10007: "bad" }));
    await markCompleted(db, "mismatch", { valid: true, issues: [] });
    await markCompleted(db, "invalid", { valid: true, issues: [] });
    await setDraftUploadIssue(db, "mismatch", "hash_mismatch", "U-77");
    await setDraftUploadIssue(db, "invalid", "answers_hash_invalid");

    expect(await getDraftRow(db, "mismatch")).toMatchObject({ completed: 1, upload_issue: "hash_mismatch", upload_issue_unique_id: "U-77" });
    expect(await getDraftRow(db, "invalid")).toMatchObject({ completed: 0, upload_issue: "answers_hash_invalid" });
    expect(await completedDrafts(db)).toEqual([]);

    const blockedEnvelope = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", ["mismatch"]);
    await markCompleted(db, "mismatch", { valid: false, issues: [] });
    expect(await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", ["mismatch"])).toEqual(blockedEnvelope);

    await store.save(draft("mismatch", "2026-09-30T03:00:00Z", { Id10007: "edited" }));
    await markCompleted(db, "mismatch", { valid: true, issues: [] });
    expect(await getDraftRow(db, "mismatch")).toMatchObject({ completed: 1, upload_issue: "hash_mismatch" });
    expect(await completedDrafts(db)).toEqual([]);

    await store.save(draft("invalid", "2026-09-30T04:00:00Z", { Id10007: "fixed" }));
    expect(await getDraftRow(db, "invalid")).toMatchObject({ completed: 0, upload_issue: null });
    await setDraftUploadIssue(db, "invalid", "answers_hash_invalid");
    await markCompleted(db, "invalid", { valid: true, issues: [] });
    expect(await getDraftRow(db, "invalid")).toMatchObject({ completed: 1, upload_issue: null });
  });

  it("deletes only the envelope that was acknowledged", async () => {
    const store = createDraftStore(db, { projectId: "PROJECT1", siteId: "SITE1" });
    await store.save(draft("a", "2026-09-30T01:00:00Z", { Id10007: "sent" }));
    await markCompleted(db, "a", { valid: true, issues: [] });
    const snapshot = (await completedDrafts(db))[0].envelope;
    await store.save(draft("a", "2026-09-30T02:00:00Z", { Id10007: "edited while uploading" }));
    await expect(deleteDraftSnapshot(db, "a", snapshot)).resolves.toBe(false);
    expect((await store.load!("a"))?.data).toEqual({ Id10007: "edited while uploading" });
    const latest = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", ["a"]);
    await expect(deleteDraftSnapshot(db, "a", latest!.envelope)).resolves.toBe(true);
    expect(await getDraftRow(db, "a")).toBeNull();
  });

  it("adds the completion column to an older database, treating its completed drafts as valid", async () => {
    const old = memoryDb();
    await old.execAsync(`
      CREATE TABLE drafts (id TEXT PRIMARY KEY NOT NULL, site_id TEXT NOT NULL, org_unit_id TEXT,
        completed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, envelope TEXT NOT NULL);
    `);
    await old.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, ?, ?, ?)", [
      "done", "S", 1, "2026-09-30T01:00:00Z", JSON.stringify(draft("done", "2026-09-30T01:00:00Z"))
    ]);
    await old.runAsync("INSERT INTO drafts (id, site_id, completed, updated_at, envelope) VALUES (?, ?, ?, ?, ?)", [
      "open", "S", 0, "2026-09-30T02:00:00Z", JSON.stringify(draft("open", "2026-09-30T02:00:00Z"))
    ]);
    await migrate(old);
    await migrate(old);
    const ready = await completedDrafts(old);
    expect(ready.map((d) => [d.id, d.completion])).toEqual([["done", { valid: true, issues: [] }]]);
  });

  it("keeps meta values such as the cached bootstrap", async () => {
    expect(await getMeta(db, "bootstrap")).toBeUndefined();
    await setMeta(db, "bootstrap", { context: [] });
    await setMeta(db, "bootstrap", { context: [{ site_id: "S" }] });
    expect(await getMeta(db, "bootstrap")).toEqual({ context: [{ site_id: "S" }] });
  });

  it("surfaces a draft-config delete failure during project purge", async () => {
    await setMeta(db, "draft-config:one", { projectId: "PROJECT1" });
    const failing: Db = {
      ...db,
      runAsync: async (sql, params) => {
        if (sql === "DELETE FROM meta WHERE key = ?") throw new Error("storage failure");
        return db.runAsync(sql, params);
      }
    };
    await expect(purgeProjectData(failing, "PROJECT1")).rejects.toThrow("storage failure");
    expect(await getMeta(db, "draft-config:one")).toEqual({ projectId: "PROJECT1" });
  });
});
