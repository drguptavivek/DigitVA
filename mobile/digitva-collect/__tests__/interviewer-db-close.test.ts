import { openDatabaseAsync } from "expo-sqlite";

import { StoreLockedError, createInterviewerDb, lockAll, deleteInterviewerDb, openInterviewerDb } from "../src/interviewerDb";

jest.mock("expo-sqlite", () => ({ defaultDatabaseDirectory: "", openDatabaseAsync: jest.fn(), deleteDatabaseAsync: jest.fn() }));
jest.mock("expo-file-system", () => ({ File: class {} }));
jest.mock("../src/drafts", () => ({ migrate: jest.fn(async () => undefined), countUnsentWork: jest.fn(), countUnsentWorkByKind: jest.fn() }));
jest.mock("../src/mediaFiles", () => ({ wipeMediaCache: jest.fn() }));
jest.mock("../src/unsentWork", () => ({ summariseWork: jest.fn() }));
jest.mock("../src/accountStoreIdentity", () => ({ assertAccountStoreModeSafe: jest.fn(async () => undefined) }));
jest.mock("../src/pinResetGrant", () => ({ clearPinResetGrant: jest.fn(), clearProfileDeleteGrant: jest.fn(), hasPinResetGrant: jest.fn(), takePinResetGrant: jest.fn() }));
jest.mock("../src/vault", () => ({
  createStoreSecret: jest.fn(async () => "s"),
  newDataKey: jest.fn(async () => "k"),
  unwrapDataKey: jest.fn(async () => "k"),
  wrapDataKey: jest.fn(async () => "w"),
  savePinWrap: jest.fn(),
  saveResetCopy: jest.fn(),
  setFailedAttempts: jest.fn(),
  readStoreSecret: jest.fn(async () => null),
  forgetStoreKeys: jest.fn(),
  storeHash: jest.fn(async () => "h")
}));

const sqlite = jest.requireMock("expo-sqlite") as { deleteDatabaseAsync: jest.Mock };

const tick = () => new Promise((r) => setTimeout(r, 0));

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => { resolve = r; });
  return { promise, resolve };
}

async function setup() {
  const slow = deferred();
  const log: string[] = [];
  const native = {
    execAsync: jest.fn(async (sql: string) => { log.push(`exec:${sql}`); }),
    runAsync: jest.fn(),
    getAllAsync: jest.fn(),
    getFirstAsync: jest.fn(async (sql: string) => { if (sql === "slow") { await slow.promise; log.push("slow done"); } return null; }),
    closeAsync: jest.fn(async () => { log.push("close"); })
  };
  (openDatabaseAsync as jest.Mock).mockResolvedValue(native);
  await createInterviewerDb("u1", "1234");
  const db = await openInterviewerDb("u1");
  sqlite.deleteDatabaseAsync.mockClear();
  return { native, slow, log, db };
}

beforeEach(() => { jest.clearAllMocks(); });

test("a query started before lockAll finishes before close", async () => {
  const { slow, log, db, native } = await setup();
  const query = db.getFirstAsync("slow", []);
  const locking = lockAll();
  await tick();
  expect(native.closeAsync).not.toHaveBeenCalled();
  slow.resolve();
  await Promise.all([query, locking]);
  expect(log.slice(-2)).toEqual(["slow done", "close"]);
});

test("a query after lockAll starts rejects StoreLockedError and never reaches native", async () => {
  const { slow, db, native } = await setup();
  const first = db.getFirstAsync("slow", []);
  const locking = lockAll();
  await tick();
  await expect(db.execAsync("late")).rejects.toBeInstanceOf(StoreLockedError);
  expect(native.execAsync).not.toHaveBeenCalledWith("late");
  await expect(openInterviewerDb("u1")).rejects.toBeInstanceOf(StoreLockedError);
  slow.resolve();
  await Promise.all([first, locking]);
});

test("deleteInterviewerDb waits for in-flight work before closing and deleting the file", async () => {
  const { slow, db, native } = await setup();
  const query = db.getFirstAsync("slow", []);
  const deleting = deleteInterviewerDb("u1");
  await tick();
  expect(native.closeAsync).not.toHaveBeenCalled();
  expect(sqlite.deleteDatabaseAsync).not.toHaveBeenCalled();
  slow.resolve();
  await Promise.all([query, deleting]);
  expect(native.closeAsync).toHaveBeenCalledTimes(1);
  expect(sqlite.deleteDatabaseAsync).toHaveBeenCalledTimes(1);
});

test("a hung statement does not block close past DRAIN_TIMEOUT_MS", async () => {
  jest.useFakeTimers();
  try {
    const { db, native } = await setup();
    void db.getFirstAsync("slow", []).catch(() => undefined); // never resolves
    const locking = lockAll();
    await jest.advanceTimersByTimeAsync(4999);
    expect(native.closeAsync).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1);
    await locking;
    expect(native.closeAsync).toHaveBeenCalledTimes(1);
  } finally {
    jest.useRealTimers();
  }
});

test("a failed native close keeps the handle so the next lockAll retries and closes it", async () => {
  const { db, native } = await setup();
  native.closeAsync.mockRejectedValueOnce(new Error("close failed"));
  await expect(lockAll()).rejects.toThrow("close failed");
  await expect(openInterviewerDb("u1")).resolves.toBeDefined(); // back in the map
  await expect(lockAll()).resolves.toBeUndefined();
  expect(native.closeAsync).toHaveBeenCalledTimes(2);
  await expect(db.execAsync("after")).rejects.toBeInstanceOf(StoreLockedError);
});

test("lockAll drops every Delete profile password grant with the PIN reset grant", async () => {
  const grants = jest.requireMock("../src/pinResetGrant") as { clearPinResetGrant: jest.Mock; clearProfileDeleteGrant: jest.Mock };
  grants.clearProfileDeleteGrant.mockClear();
  await lockAll();
  expect(grants.clearPinResetGrant).toHaveBeenCalled();
  expect(grants.clearProfileDeleteGrant).toHaveBeenCalledWith();
});
