/** runInTransaction: commit, rollback, per-handle serialisation, and no new native connection. */
import { runInTransaction } from "../src/dbTransaction";

function fakeDb(log: string[]) {
  return { execAsync: jest.fn(async (sql: string) => void log.push(sql)) };
}

describe("runInTransaction", () => {
  it("commits on success, on the same handle", async () => {
    const log: string[] = [];
    const db = fakeDb(log);
    await runInTransaction(db, async (tx) => {
      expect(tx).toBe(db);
      log.push("work");
    });
    expect(log).toEqual(["BEGIN IMMEDIATE", "work", "COMMIT"]);
  });

  it("rolls back and rethrows the original error", async () => {
    const log: string[] = [];
    const db = fakeDb(log);
    await expect(runInTransaction(db, async () => { throw new Error("boom"); })).rejects.toThrow("boom");
    expect(log).toEqual(["BEGIN IMMEDIATE", "ROLLBACK"]);
  });

  it("keeps the write error when ROLLBACK also fails, and still runs the next call", async () => {
    const log: string[] = [];
    const db = {
      execAsync: async (sql: string) => {
        log.push(sql);
        if (sql === "ROLLBACK") throw new Error("rollback failed");
      },
    };
    await expect(runInTransaction(db, async () => { throw new Error("boom"); })).rejects.toThrow("boom");
    await runInTransaction(db, async () => undefined);
    expect(log.slice(-2)).toEqual(["BEGIN IMMEDIATE", "COMMIT"]);
  });

  it("starts the second BEGIN only after the first COMMIT", async () => {
    const log: string[] = [];
    const db = fakeDb(log);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const first = runInTransaction(db, async () => { log.push("a"); await gate; });
    const second = runInTransaction(db, async () => { log.push("b"); });
    await new Promise((resolve) => setImmediate(resolve));
    expect(log).toEqual(["BEGIN IMMEDIATE", "a"]);
    release();
    await Promise.all([first, second]);
    expect(log).toEqual(["BEGIN IMMEDIATE", "a", "COMMIT", "BEGIN IMMEDIATE", "b", "COMMIT"]);
  });
});
