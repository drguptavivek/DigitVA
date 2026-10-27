/** A surviving Keystore secret with no database file must not unlock an empty store (digitva-jish). */
jest.mock("expo-file-system", () => {
  const exists = jest.fn();
  return { __exists: exists, File: function File(this: any, dir: string, name: string) { Object.defineProperty(this, "exists", { get: () => exists(dir, name) }); } };
});
jest.mock("expo-sqlite", () => ({
  defaultDatabaseDirectory: "/data/SQLite",
  openDatabaseAsync: jest.fn(),
  deleteDatabaseAsync: async () => undefined,
}));
jest.mock("../src/vault", () => ({
  buildPassphrase: () => "k",
  createStoreSecret: async () => "s",
  forgetStoreKeys: jest.fn(async () => undefined),
  readStoreSecret: async () => "secret",
  recordFailedAttempt: jest.fn(async () => 1),
  setFailedAttempts: async () => undefined,
  storeHash: async () => "abc",
  WIPE_AFTER_FAILURES: 5,
}));
jest.mock("../src/mediaFiles", () => ({ wipeMediaCache: () => undefined }));

const mockExists = (jest.requireMock("expo-file-system") as { __exists: jest.Mock }).__exists;
const mockOpen = (jest.requireMock("expo-sqlite") as { openDatabaseAsync: jest.Mock }).openDatabaseAsync;
const vault = jest.requireMock("../src/vault") as { forgetStoreKeys: jest.Mock; recordFailedAttempt: jest.Mock };
const mockRecord = vault.recordFailedAttempt;
const mockForget = vault.forgetStoreKeys;

import { isUnlocked, resetMissingStore, unlockInterviewerDb } from "../src/interviewerDb";
import { isStorageFull } from "../src/storageErrors";

describe("missing database file", () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it("reports storeMissing without opening, counting an attempt or unlocking", async () => {
    mockExists.mockReturnValue(false);
    const result = await unlockInterviewerDb("u1", "123456");
    expect(result).toEqual({ ok: false, failures: 0, wipe: false, storeMissing: true });
    expect(mockOpen).not.toHaveBeenCalled();
    expect(mockRecord).not.toHaveBeenCalled();
    expect(isUnlocked("u1")).toBe(false);
    expect(mockExists).toHaveBeenCalledWith("file:///data/SQLite", "iv_abc.db");
  });

  it("resets only when the file really is missing", async () => {
    mockExists.mockReturnValue(true);
    await expect(resetMissingStore("u1")).rejects.toThrow("store_present");
    expect(mockForget).not.toHaveBeenCalled();
    mockExists.mockReturnValue(false);
    await resetMissingStore("u1");
    expect(mockForget).toHaveBeenCalledWith("u1");
  });
});

describe("storage full", () => {
  it("recognises SQLite and OS disk-full errors", () => {
    expect(isStorageFull(new Error("Error code 13: database or disk is full"))).toBe(true);
    expect(isStorageFull(new Error("SQLITE_FULL"))).toBe(true);
    expect(isStorageFull(new Error("ENOSPC: No space left on device"))).toBe(true);
    expect(isStorageFull(new Error("something else"))).toBe(false);
    expect(isStorageFull(null)).toBe(false);
  });
});
