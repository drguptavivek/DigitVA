const mockSecure = new Map<string, string>();
const mockOpenDatabase = jest.fn();
const mockReadStoreSecret = jest.fn(async () => "secret");
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-file-system", () => ({ File: class { exists = false; } }));
jest.mock("expo-sqlite", () => ({
  defaultDatabaseDirectory: "file:///db",
  deleteDatabaseAsync: jest.fn(),
  openDatabaseAsync: (...args: unknown[]) => mockOpenDatabase(...args),
}));
jest.mock("../src/drafts", () => ({
  countUnsentWork: jest.fn(), countUnsentWorkByKind: jest.fn(), migrate: jest.fn(),
}));
jest.mock("../src/mediaFiles", () => ({ wipeMediaCache: jest.fn() }));
jest.mock("../src/unsentWork", () => ({ summariseWork: jest.fn() }));
jest.mock("../src/vault", () => ({
  buildPassphrase: jest.fn(), createStoreSecret: jest.fn(), forgetStoreKeys: jest.fn(),
  readStoreSecret: mockReadStoreSecret,
  recordFailedAttempt: jest.fn(), setFailedAttempts: jest.fn(), storeHash: jest.fn(),
  WIPE_AFTER_FAILURES: 5,
}));

import { AccountStoreCollisionError } from "../src/authErrors";
import { createInterviewerDb, openInterviewerDb, unlockInterviewerDb } from "../src/interviewerDb";

const USER = "11111111-1111-4111-8111-111111111111";

beforeEach(() => {
  mockSecure.clear();
  mockOpenDatabase.mockClear();
  mockReadStoreSecret.mockClear();
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER, name: "Asha", server: "https://live.example" }]));
  mockSecure.set("demo.accounts", JSON.stringify([{ user_id: USER, name: "Asha", server: "https://live.example" }]));
});

it("refuses legacy same-server Active/Demo collisions before opening, creating, or unlocking the shared store", async () => {
  await expect(openInterviewerDb(USER)).rejects.toBeInstanceOf(AccountStoreCollisionError);
  await expect(createInterviewerDb(USER, "123456")).rejects.toBeInstanceOf(AccountStoreCollisionError);
  await expect(unlockInterviewerDb(USER, "123456")).rejects.toBeInstanceOf(AccountStoreCollisionError);

  expect(mockOpenDatabase).not.toHaveBeenCalled();
  expect(mockReadStoreSecret).not.toHaveBeenCalled();
});

it("refuses a unique retained account when its other mode is selected", async () => {
  mockSecure.set("accounts", "[]");
  mockSecure.set("demo.accounts", JSON.stringify([{ user_id: USER, name: "Asha", server: "https://demo.example" }]));

  await expect(unlockInterviewerDb(USER, "123456")).rejects.toBeInstanceOf(AccountStoreCollisionError);
  expect(mockReadStoreSecret).not.toHaveBeenCalled();
});
