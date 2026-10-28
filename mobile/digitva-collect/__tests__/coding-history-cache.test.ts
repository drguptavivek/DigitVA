import { DatabaseSync } from "node:sqlite";
import { invalidateCodingHistory, migrate, type Db } from "../src/drafts";
import { createNativeCodingHistoryCache } from "../src/codingHistoryCache.native";
import type { CodingHistoryIdentity } from "../src/codingHistoryCache";
import type { CoderHistory } from "../src/workspace/contracts";

function memoryDb(): Db {
  const sqlite = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void sqlite.exec(sql),
    runAsync: async (sql, params) => sqlite.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => sqlite.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (sqlite.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => sqlite.close(),
  };
}

const identity: CodingHistoryIdentity = { mode: "enrolled", serverOrigin: "https://va.example.org", userId: "u1" };
const item = (index: number, projectId = "P1") => ({
  va_sid: `sid-${index}`, va_uniqueid_masked: `MASK-${index}`, project_id: projectId, site_id: "S1",
  va_submission_date: "2026-10-01", va_coding_date: "2026-10-02", va_code_status: "completed",
  recodeable: true, recode_until: "2026-10-03T00:00:00Z",
  deceased_name: "must not persist", va_data_collector: "must not persist", va_deceased_age: 44,
  va_deceased_gender: "female", va_form_id: "must not persist", answer: "must not persist",
});
const page = (offset: number, count = 1, projectId = "P1"): CoderHistory => ({
  history: Array.from({ length: count }, (_, index) => item(offset + index, projectId)),
  count: count * 11, limit: 50, offset, has_more: true,
});
const fingerprint = "a".repeat(64);

describe("native coded-history cache", () => {
  it("stores only allowed metadata, then reconstructs a read-only page", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = await createNativeCodingHistoryCache(db, identity, fingerprint);
    await cache.writePage(identity, "P1", page(0), fingerprint);
    const cached = await cache.readPage(identity, "P1", 0);
    expect(cached?.page.history[0]).toMatchObject({
      va_sid: "sid-0", va_uniqueid_masked: "MASK-0", project_id: "P1", site_id: "S1",
      va_submission_date: "2026-10-01", va_coding_date: "2026-10-02", va_code_status: "completed",
      recode_until: "2026-10-03T00:00:00Z", recodeable: false, va_form_id: "",
      va_deceased_age: null, va_deceased_gender: null,
    });
    expect(cached?.fetchedAt).toEqual(expect.any(String));
    const stored = await db.getFirstAsync<{ cases_json: string }>("SELECT cases_json FROM coding_history_cache", []);
    expect(stored?.cases_json).not.toContain("must not persist");
    expect(stored?.cases_json).not.toContain("answer");
    await db.closeAsync();
  });

  it("isolates mode, server, account and project, and invalidates when access narrows", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = await createNativeCodingHistoryCache(db, identity, fingerprint);
    await cache.writePage(identity, "P1", page(0), fingerprint);
    expect(await cache.readPage({ ...identity, mode: "demo" }, "P1", 0)).toBeNull();
    expect(await cache.readPage({ ...identity, serverOrigin: "https://demo.example.org" }, "P1", 0)).toBeNull();
    expect(await cache.readPage({ ...identity, userId: "u2" }, "P1", 0)).toBeNull();
    expect(await cache.readPage(identity, "P2", 0)).toBeNull();

    const narrowed = await createNativeCodingHistoryCache(db, identity, "b".repeat(64));
    expect(await narrowed.readPage(identity, "P1", 0)).toBeNull();
    expect(await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM coding_history_cache", [])).toMatchObject({ n: 0 });
    await db.closeAsync();
  });

  it("keeps at most ten pages and five hundred cases per encrypted account database", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = await createNativeCodingHistoryCache(db, identity, fingerprint);
    for (let offset = 0; offset < 550; offset += 50) {
      await cache.writePage(identity, "P1", page(offset, 50), fingerprint);
    }
    expect(await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM coding_history_cache", [])).toMatchObject({ n: 10 });
    expect(await cache.readPage(identity, "P1", 0)).toBeNull();
    expect((await cache.readPage(identity, "P1", 50))?.page.history).toHaveLength(50);
    await db.closeAsync();
  });

  it("refuses caching without the validated access fingerprint", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = await createNativeCodingHistoryCache(db, identity, "missing");
    await cache.writePage(identity, "P1", page(0), fingerprint);
    expect(cache.fingerprintForProject("P1")).toBeUndefined();
    expect(await cache.readPage(identity, "P1", 0)).toBeNull();
    await db.closeAsync();
  });

  it("invalidates only cached history after a completed upload", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = await createNativeCodingHistoryCache(db, identity, fingerprint);
    await cache.writePage(identity, "P1", page(0), fingerprint);
    await db.runAsync("INSERT INTO drafts (id, site_id, updated_at, envelope) VALUES (?, ?, ?, ?)", ["draft-1", "S1", "2026-10-01", "{}"]);
    await invalidateCodingHistory(db);
    expect(await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM coding_history_cache", [])).toMatchObject({ n: 0 });
    expect(await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM drafts", [])).toMatchObject({ n: 1 });
    await db.closeAsync();
  });
});
