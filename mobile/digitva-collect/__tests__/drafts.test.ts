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
  getMeta,
  listDrafts,
  markCompleted,
  migrate,
  setMeta,
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

  it("saves, loads and updates a draft without moving its site", async () => {
    const store = createDraftStore(db, { siteId: "SITE1", orgUnitId: "unit-1" });
    await store.save(draft("a", "2026-09-30T01:00:00Z", { Id10007: "x" }));
    expect((await store.load!("a"))?.data).toEqual({ Id10007: "x" });

    const otherHost = createDraftStore(db, { siteId: "SITE2" });
    await otherHost.save(draft("a", "2026-09-30T02:00:00Z", { Id10007: "y" }));
    const rows = await listDrafts(db);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: "a", site_id: "SITE1", org_unit_id: "unit-1", completed: 0 });
    expect((await store.load!("a"))?.data).toEqual({ Id10007: "y" });
  });

  it("returns undefined for an unknown draft and removes one", async () => {
    const store = createDraftStore(db, { siteId: "SITE1" });
    expect(await store.load!("missing")).toBeUndefined();
    await store.save(draft("a", "2026-09-30T01:00:00Z"));
    expect(await countDrafts(db)).toBe(1);
    await store.remove!("a");
    expect(await countDrafts(db)).toBe(0);
  });

  it("lists only completed drafts for upload, with their envelopes", async () => {
    const store = createDraftStore(db, { siteId: "SITE1" });
    await store.save(draft("a", "2026-09-30T01:00:00Z"));
    await store.save(draft("b", "2026-09-30T02:00:00Z", { Id10007: "z" }));
    expect(await completedDrafts(db)).toEqual([]);
    await markCompleted(db, "b");
    const ready = await completedDrafts(db);
    expect(ready).toHaveLength(1);
    expect(ready[0]).toMatchObject({ id: "b", site_id: "SITE1", org_unit_id: null });
    expect(ready[0].draft.data).toEqual({ Id10007: "z" });
  });

  it("keeps meta values such as the cached bootstrap", async () => {
    expect(await getMeta(db, "bootstrap")).toBeUndefined();
    await setMeta(db, "bootstrap", { context: [] });
    await setMeta(db, "bootstrap", { context: [{ site_id: "S" }] });
    expect(await getMeta(db, "bootstrap")).toEqual({ context: [{ site_id: "S" }] });
  });
});
