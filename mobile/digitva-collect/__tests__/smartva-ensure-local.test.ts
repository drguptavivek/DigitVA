import { ensureLocalSmartVa } from "../src/smartva/ensureLocal";
import { acquireDraftUpload } from "../src/localCodingLeases";
import { assertSmartVaEligible, runLocalSmartVa } from "../src/smartva/localApi";
import { getLocalSmartVa } from "../src/smartva/localStore";
import { loadAccounts } from "../src/auth";
import { isIcd11DorisEnabled } from "../src/icd11DorisPreference";
import type { Db } from "../src/drafts";

jest.mock("../src/accountStoreIdentity", () => ({ accountStoreIdentityIsInSelectedMode: jest.fn(async () => true) }));
jest.mock("../src/auth", () => ({ loadAccounts: jest.fn(async () => [{ user_id: "u", standalone: true }]), loadActiveSlot: jest.fn(async () => "active") }));
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => true }));
jest.mock("../src/icd11DorisPreference", () => ({ isIcd11DorisEnabled: jest.fn(async () => true) }));
jest.mock("../src/sync", () => ({ draftAnswersSha256: jest.fn(async () => "a".repeat(64)) }));
const mockInit = jest.fn(async () => ({ ok: true, version: "v1" }));
jest.mock("../src/smartva/nativeEngine", () => ({ offlineSmartvaEngine: () => ({ init: mockInit }) }));
jest.mock("../src/smartva/localApi", () => ({ assertSmartVaEligible: jest.fn(async () => "{}"), runLocalSmartVa: jest.fn() }));
jest.mock("../src/smartva/localStore", () => ({
  getLocalSmartVa: jest.fn(),
  isLocalSmartVaCurrent: (row: { answers_sha256: string; options_digest: string; engine_version: string }, hash: string, digest: string, version: string) => row.answers_sha256 === hash && row.options_digest === digest && row.engine_version === version,
}));

const options = { schemaVersion: 1, formId: "f", formUpdatedAt: "v", options: { country: "India", hiv: false, malaria: false, hce: true, freetext: true }, optionsDigest: `sha256:${"b".repeat(64)}` };
const readDb = jest.fn(async (sql: string) => sql.includes("FROM meta") ? { value: JSON.stringify({ smartva: options }) } : { project_id: "p" });
const db = { getFirstAsync: readDb } as unknown as Db;
const ready = { draft_id: "d", status: "ready", answers_sha256: "a".repeat(64), options_digest: options.optionsDigest, engine_version: "v1" };

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(isIcd11DorisEnabled).mockResolvedValue(true);
  jest.mocked(loadAccounts).mockResolvedValue([{ user_id: "u", standalone: true } as never]);
  jest.mocked(assertSmartVaEligible).mockResolvedValue("{}");
  jest.mocked(getLocalSmartVa).mockResolvedValue(null);
  mockInit.mockResolvedValue({ ok: true, version: "v1" });
  readDb.mockImplementation(async (sql: string) => sql.includes("FROM meta") ? { value: JSON.stringify({ smartva: options }) } : { project_id: "p" });
});

test("reserves synchronously and coalesces concurrent attempts", async () => {
  let finish!: (value: typeof ready) => void;
  jest.mocked(getLocalSmartVa).mockResolvedValue(null);
  jest.mocked(runLocalSmartVa).mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish; }));
  const first = ensureLocalSmartVa({ db, userId: "u", draftId: "d" });
  expect(acquireDraftUpload("u", "d")).toBeNull();
  expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).toBe(first);
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  finish(ready);
  await expect(first).resolves.toMatchObject({ status: "ran" });
  expect(runLocalSmartVa).toHaveBeenCalledTimes(1);
  const release = acquireDraftUpload("u", "d");
  expect(release).not.toBeNull();
  release?.();
});

test("reuses current results, skips busy uploads and rejects ineligible interviews", async () => {
  jest.mocked(getLocalSmartVa).mockResolvedValue(ready as never);
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toMatchObject({ status: "current" });
  expect(runLocalSmartVa).not.toHaveBeenCalled();
  const release = acquireDraftUpload("u", "d");
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "skipped", reason: "busy" });
  release?.();
  jest.mocked(assertSmartVaEligible).mockRejectedValueOnce(new Error("ineligible"));
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "skipped" });
  expect(runLocalSmartVa).not.toHaveBeenCalled();
});

test("preference and same-project permission prevent engine initialization", async () => {
  jest.mocked(isIcd11DorisEnabled).mockResolvedValue(false);
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "skipped" });
  jest.mocked(isIcd11DorisEnabled).mockResolvedValue(true);
  jest.mocked(loadAccounts).mockResolvedValue([{ user_id: "u", offline_coding_access: ["other"] } as never]);
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "skipped" });
  expect(mockInit).not.toHaveBeenCalled();
  expect(runLocalSmartVa).not.toHaveBeenCalled();
});

test("missing frozen settings require repair without initializing the engine", async () => {
  readDb.mockImplementation(async (sql: string) => sql.includes("FROM meta") ? { value: "{}" } : { project_id: "p" });
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "config_needed" });
  expect(mockInit).not.toHaveBeenCalled();
  expect(runLocalSmartVa).not.toHaveBeenCalled();
});

test("revocation after initialization prevents scoring", async () => {
  mockInit.mockImplementationOnce(async () => {
    jest.mocked(isIcd11DorisEnabled).mockResolvedValue(false);
    return { ok: true, version: "v1" };
  });
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "failed" });
  expect(mockInit).toHaveBeenCalledTimes(1);
  expect(runLocalSmartVa).not.toHaveBeenCalled();
});

test.each([null, { ...ready, engine_version: "old" }])("missing or stale result runs once", async (cached) => {
  jest.mocked(getLocalSmartVa).mockResolvedValue(cached as never);
  jest.mocked(runLocalSmartVa).mockResolvedValue(ready as never);
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toMatchObject({ status: "ran" });
  expect(runLocalSmartVa).toHaveBeenCalledTimes(1);
});

test("failed attempt releases the lease and does not retry on its own", async () => {
  jest.mocked(runLocalSmartVa).mockRejectedValueOnce(new Error("engine_error"));
  await expect(ensureLocalSmartVa({ db, userId: "u", draftId: "d" })).resolves.toEqual({ status: "failed" });
  expect(runLocalSmartVa).toHaveBeenCalledTimes(1);
  const release = acquireDraftUpload("u", "d");
  expect(release).not.toBeNull();
  release?.();
});
