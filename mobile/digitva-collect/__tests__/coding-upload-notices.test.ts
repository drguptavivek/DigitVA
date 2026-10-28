import { DatabaseSync } from "node:sqlite";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { codingNotices, dismissCodingNotices, recordCodingOutcome } from "../src/codingUploadNotices";
import { migrate, type Db } from "../src/drafts";

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

describe("coding upload notices", () => {
  it("stores a refusal before the caller deletes its acknowledged draft and reads it back", async () => {
    const dir = mkdtempSync(join(tmpdir(), "digitva-notices-"));
    const sqlite = new DatabaseSync(join(dir, "account.sqlite"));
    const db: Db = {
      execAsync: async (sql) => void sqlite.exec(sql),
      runAsync: async (sql, params) => sqlite.prepare(sql).run(...params),
      getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => sqlite.prepare(sql).all(...params) as T[],
      getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (sqlite.prepare(sql).get(...params) as T | undefined) ?? null,
      closeAsync: async () => sqlite.close(),
    };
    try {
      await migrate(db);
      await recordCodingOutcome(db, {
        draftId: "draft-1", status: "refused", code: "coding_mode_mismatch", codingSha256: "a".repeat(64),
      });
      await db.closeAsync();

      const reopenedSqlite = new DatabaseSync(join(dir, "account.sqlite"));
      const reopened: Db = {
        execAsync: async (sql) => void reopenedSqlite.exec(sql),
        runAsync: async (sql, params) => reopenedSqlite.prepare(sql).run(...params),
        getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => reopenedSqlite.prepare(sql).all(...params) as T[],
        getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (reopenedSqlite.prepare(sql).get(...params) as T | undefined) ?? null,
        closeAsync: async () => reopenedSqlite.close(),
      };
      expect(await codingNotices(reopened)).toEqual([
        { draftId: "draft-1", code: "coding_mode_mismatch", at: expect.any(String), codingSha256: "a".repeat(64) },
      ]);
      await reopened.closeAsync();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not show pending outcomes and clears only a matching applied coding", async () => {
    const db = memoryDb();
    await migrate(db);
    await recordCodingOutcome(db, {
      draftId: "draft-1", status: "refused", code: "coding_mode_mismatch", codingSha256: "a".repeat(64),
    });
    await recordCodingOutcome(db, {
      draftId: "draft-1", status: "pending", code: "not_ready", codingSha256: "a".repeat(64),
    });
    expect(await codingNotices(db)).toHaveLength(1);
    await recordCodingOutcome(db, {
      draftId: "draft-1", status: "applied", code: null, codingSha256: "b".repeat(64),
    });
    expect(await codingNotices(db)).toHaveLength(1);
    await recordCodingOutcome(db, {
      draftId: "draft-1", status: "applied", code: null, codingSha256: "a".repeat(64),
    });
    expect(await codingNotices(db)).toEqual([]);
    await db.closeAsync();
  });

  it("keeps only the newest 50 refusal notices and supports dismissal", async () => {
    const db = memoryDb();
    await migrate(db);
    for (let i = 0; i < 55; i += 1) {
      await recordCodingOutcome(db, {
        draftId: `draft-${i}`, status: "refused", code: "coding_grant_required", codingSha256: String(i).padStart(64, "0"),
      });
    }
    const notices = await codingNotices(db);
    expect(notices).toHaveLength(50);
    expect(notices[0].draftId).toBe("draft-54");
    expect(notices[49].draftId).toBe("draft-5");
    await dismissCodingNotices(db);
    expect(await codingNotices(db)).toEqual([]);
    await db.closeAsync();
  });
});
