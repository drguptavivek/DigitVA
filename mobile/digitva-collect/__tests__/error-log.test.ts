/**
 * The local error log: Ref-only content, no personal fields, a 500 / 30-day cap, the encrypted store as its
 * only home, and the export text. Storage runs on a real SQLite engine (node:sqlite), as drafts.test.ts does.
 */
import { DatabaseSync } from "node:sqlite";
import { Share } from "react-native";

import { ApiError } from "../src/api";
import en from "../src/strings/en.json";
import { countUnsentWork, migrate, type Db } from "../src/drafts";
import {
  buildErrorExport,
  flushErrors,
  pendingErrors,
  recordError,
  recordToastError,
  resetErrorLog,
  setErrorRoute,
  setErrorWriter,
  type ErrorEntry,
} from "../src/errorLog";
import { exportErrors } from "../src/errorExport";
import { allErrors, readErrors, writeErrors } from "../src/errorLogDb";
import { errorText } from "../src/ui";

const mockShare = jest.spyOn(Share, "share");
let mockOpenDb: Db | undefined;
jest.mock("../src/interviewerDb", () => ({ firstUnlockedDb: () => mockOpenDb }));

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const entry = (n: number, at = new Date(Date.UTC(2026, 9, 1, 0, n)).toISOString()): ErrorEntry => ({
  at, appVersion: "0.3.2", route: "/worklist", what: `HTTP 500 e${n}`, device: "Acme X", android: "14",
});

beforeEach(() => {
  resetErrorLog();
  setErrorWriter(undefined);
  mockOpenDb = undefined;
  mockShare.mockReset().mockResolvedValue({ action: "sharedAction" });
});

describe("what is recorded", () => {
  it("files the Ref content of an error, with the route, version and device", () => {
    setErrorRoute("/worklist");
    const error = new ApiError(502, "bad_gateway", undefined, undefined, undefined, "/api/v1/cases/:id", "GET");
    errorText(error);
    const [only] = pendingErrors();
    expect(only).toMatchObject({ route: "/worklist", what: "HTTP 502 bad_gateway GET /api/v1/cases/:id" });
    expect(Object.keys(only).sort()).toEqual(["android", "appVersion", "at", "device", "route", "what"]);
    expect(only.at).toMatch(/Z$/);
  });

  it("keeps no names, long numbers, paths or server text from a device error", () => {
    errorText(new Error('no such row "Asha Devi" phone 9876543210 at file:///data/user/0/x/iv.db'));
    const [only] = pendingErrors();
    expect(only.what).not.toMatch(/Asha|9876543210|iv\.db/);
    expect(only.what).toContain("no such row");
  });

  it("records messages that carry no Ref line too (offline, rate limited)", () => {
    errorText(new TypeError("Network request failed"));
    errorText(new ApiError(429, "rate_limited"));
    expect(pendingErrors().map((e) => e.what)).toEqual(["network", "HTTP 429 rate_limited"]);
  });

  it("files a repeat of the same error on the same screen once", () => {
    for (let i = 0; i < 5; i += 1) errorText(new ApiError(500, "boom"));
    expect(pendingErrors()).toHaveLength(1);
  });

  it("files an error toast only when its text is a fixed app string and errorText did not just record it", () => {
    recordToastError("Sent 3. Not accepted 0. Still on this phone 1."); // carries numbers: not a dictionary string
    expect(pendingErrors()).toHaveLength(0);
    errorText(new ApiError(500, "boom"));
    recordToastError(en.errGeneric); // the same failure, echoed by the toast
    expect(pendingErrors()).toHaveLength(1);
    resetErrorLog();
    recordToastError(en.noCollectionAccess);
    expect(pendingErrors().map((e) => e.what)).toEqual([`toast: ${en.noCollectionAccess}`]);
  });
});

describe("storage", () => {
  it("waits in memory while locked, then moves into the open store", async () => {
    const db = memoryDb();
    await migrate(db);
    setErrorWriter(async (entries) => {
      if (!mockOpenDb) return false;
      await writeErrors(mockOpenDb, entries);
      return true;
    });
    recordError("HTTP 500 first");
    await flushErrors();
    expect(pendingErrors()).toHaveLength(1);
    mockOpenDb = db;
    await flushErrors();
    expect(pendingErrors()).toHaveLength(0);
    expect((await readErrors(db)).map((e) => e.what)).toEqual(["HTTP 500 first"]);
  });

  it("keeps the newest 500 entries", async () => {
    const db = memoryDb();
    await migrate(db);
    const now = Date.UTC(2026, 9, 2);
    await writeErrors(db, Array.from({ length: 510 }, (_, i) => entry(i, new Date(now - 1000 * (510 - i)).toISOString())), now);
    const rows = await readErrors(db);
    expect(rows).toHaveLength(500);
    expect(rows[0].what).toBe("HTTP 500 e509");
    expect(rows.at(-1)?.what).toBe("HTTP 500 e10");
  });

  it("drops entries older than 30 days", async () => {
    const db = memoryDb();
    await migrate(db);
    const now = Date.UTC(2026, 9, 31);
    await writeErrors(db, [entry(1, "2026-09-20T00:00:00.000Z"), entry(2, "2026-10-20T00:00:00.000Z")], now);
    expect((await readErrors(db)).map((e) => e.what)).toEqual(["HTTP 500 e2"]);
  });

  it("is a table of the interviewer's own store, so sign-out and wipe (which delete that file) remove it", async () => {
    const db = memoryDb();
    await migrate(db);
    const tables = await db.getAllAsync<{ name: string }>("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'error_log'", []);
    expect(tables).toHaveLength(1);
    const columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(error_log)", []);
    expect(columns.map((c) => c.name)).toEqual(["id", "at", "app_version", "route", "what", "device", "android"]);
  });

  it("does not count as unsent work", async () => {
    const db = memoryDb();
    await migrate(db);
    await writeErrors(db, [entry(1)]);
    expect(await countUnsentWork(db)).toBe(0);
  });
});

describe("export", () => {
  it("writes a header with build, device and time, then entries newest first", () => {
    const { name, text, shown } = buildErrorExport([entry(2), entry(1)], new Date("2026-10-23T10:00:00Z"));
    expect(name).toBe("digitva-errors-2026-10-23.txt");
    expect(text).toContain("File: digitva-errors-2026-10-23.txt");
    expect(text).toContain("Exported: 2026-10-23T10:00:00.000Z");
    expect(text).toContain("App: DigitVA v");
    expect(text.indexOf("e2")).toBeLessThan(text.indexOf("e1"));
    expect(shown).toBe(2);
  });

  it("cuts the oldest entries to fit and says so", () => {
    const many = Array.from({ length: 400 }, (_, i) => entry(399 - i));
    const { text, shown } = buildErrorExport(many, new Date("2026-10-23T10:00:00Z"), 5_000);
    expect(shown).toBeLessThan(400);
    expect(text).toMatch(/older entries left out/);
    expect(text.length).toBeLessThan(5_200);
  });

  it("shares the file text through the Android share sheet", async () => {
    const db = memoryDb();
    await migrate(db);
    // A recent entry: writes prune by the real clock (MAX_ERROR_AGE_DAYS).
    await writeErrors(db, [entry(1, new Date().toISOString())]);
    mockOpenDb = db;
    expect(await exportErrors(new Date("2026-10-23T10:00:00Z"))).toBe(1);
    expect(mockShare).toHaveBeenCalledTimes(1);
    const arg = mockShare.mock.calls[0][0] as { title: string; message: string };
    expect(arg.title).toBe("digitva-errors-2026-10-23.txt");
    expect(arg.message).toContain("HTTP 500 e1");
    expect((await allErrors()).length).toBe(1);
  });

  it("shares nothing when the log is empty", async () => {
    expect(await exportErrors()).toBe(0);
    expect(mockShare).not.toHaveBeenCalled();
  });
});
