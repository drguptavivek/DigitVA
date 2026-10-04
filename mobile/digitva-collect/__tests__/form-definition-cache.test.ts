/** The cache uses a real in-memory SQLite engine, as the native draft tests do. */
import { DatabaseSync } from "node:sqlite";
import * as Crypto from "expo-crypto";
import { createWhoVa2022Instrument, ENGINE_VERSION } from "@drguptavivek/who-2022-va";
import type { SQLiteDatabase } from "expo-sqlite";

import {
  createNativeDefinitionCache,
} from "../src/formDefinitionCache";
import {
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "../src/formDefinitions";

function deferred<T>(): { promise: Promise<T>; resolve(value: T): void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    CryptoEncoding: { HEX: "hex" },
    digestStringAsync: async (_algorithm: string, value: string) =>
      createHash("sha256").update(value, "utf8").digest("hex"),
  };
});

function memoryDb(): { db: SQLiteDatabase; newHandle(): SQLiteDatabase; close(): void } {
  const sqlite = new DatabaseSync(":memory:");
  const newHandle = (): SQLiteDatabase => {
    const db = {
      execAsync: async (sql: string) => void sqlite.exec(sql),
      runAsync: async (sql: string, params: (string | number | null)[]) =>
        sqlite.prepare(sql).run(...params),
      getFirstAsync: async <T,>(sql: string, params: (string | number | null)[]) =>
        (sqlite.prepare(sql).get(...params) as T | undefined) ?? null,
      getAllAsync: async <T,>(sql: string, params: (string | number | null)[]) =>
        sqlite.prepare(sql).all(...params) as T[],
      withExclusiveTransactionAsync: async (task: (transaction: SQLiteDatabase) => Promise<void>) => {
        sqlite.exec("BEGIN IMMEDIATE");
        try {
          await task(db as unknown as SQLiteDatabase);
          sqlite.exec("COMMIT");
        } catch (error) {
          sqlite.exec("ROLLBACK");
          throw error;
        }
      },
    } as unknown as SQLiteDatabase;
    return db;
  };
  const db = newHandle();
  return { db, newHandle, close: () => sqlite.close() };
}

async function makeDefinition(
  options: { accountId?: string; projectId?: string; version?: string; title?: string; engineVersion?: number } = {},
): Promise<VerifiedFormDefinition> {
  const rawJson = JSON.stringify({
    ...createWhoVa2022Instrument(["narration_language"]),
    title: options.title ?? "WHO VA survey",
    version: options.version ?? "20261005-test-version",
    engineVersion: options.engineVersion ?? ENGINE_VERSION,
    extensions: [],
  });
  const sha256 = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    rawJson,
    { encoding: Crypto.CryptoEncoding.HEX },
  );
  const identity: DefinitionIdentity = {
    accountId: options.accountId ?? "account-1",
    projectId: options.projectId ?? "project-1",
    instrumentCode: "WHO_2022_VA",
    composedVersion: options.version ?? "20261005-test-version",
    sha256,
  };
  return verifyAndCompileDefinition({
    rawJson,
    identity,
    responseSha256: sha256,
    etag: '"definition-etag"',
  });
}

describe("native form definition cache", () => {
  let sqlite: ReturnType<typeof memoryDb>;

  beforeEach(() => {
    sqlite = memoryDb();
  });

  afterEach(() => sqlite.close());

  it("initializes idempotently and keeps the exact account, project, version, and hash identity", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    await cache.initialize();
    const first = await makeDefinition();
    const sameVersionDifferentHash = await makeDefinition({ title: "Updated survey" });
    const otherProject = await makeDefinition({ projectId: "project-2" });
    await cache.put(first);
    await cache.put(sameVersionDifferentHash);
    await cache.put(otherProject);

    expect(await cache.get(first.identity)).toMatchObject({ rawJson: first.rawJson });
    expect(await cache.get(sameVersionDifferentHash.identity)).toMatchObject({ rawJson: sameVersionDifferentHash.rawJson });
    expect(await cache.get(otherProject.identity)).toMatchObject({ rawJson: otherProject.rawJson });
    await expect(cache.get({ ...first.identity, accountId: "account-2" })).rejects.toMatchObject({ code: "invalid_identity" });
    await expect(cache.get({ ...first.identity, sha256: "A".repeat(64) })).rejects.toMatchObject({ code: "invalid_identity" });
  });

  it("retains old versions and invalidates verified values after replacement", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const old = await makeDefinition({ version: "20261001-old" });
    const current = await makeDefinition({ version: "20261005-current" });
    await cache.put(old);
    await cache.put(current);
    expect(await cache.get(old.identity)).toMatchObject({ rawJson: old.rawJson });
    expect(await cache.get(current.identity)).toMatchObject({ rawJson: current.rawJson });

    const replacement = await makeDefinition({ version: "20261005-current", title: "Replaced same slice" });
    await cache.put(replacement);
    expect(await cache.get(current.identity)).toMatchObject({ rawJson: current.rawJson });
    expect(await cache.get(replacement.identity)).toMatchObject({ rawJson: replacement.rawJson });
    expect(await sqlite.db.getFirstAsync<{ count: number }>(
      "SELECT count(*) AS count FROM form_definitions WHERE account_id = ? AND project_id = ?",
      ["account-1", "project-1"],
    )).toEqual({ count: 3 });
  });

  it("treats corrupt stored bytes as a miss and accepts a verified recovery", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    await cache.put(value);
    await sqlite.db.runAsync(
      "UPDATE form_definitions SET raw_json = ? WHERE account_id = ? AND project_id = ? AND sha256 = ?",
      ["{corrupt", "account-1", "project-1", value.identity.sha256],
    );

    const reopened = createNativeDefinitionCache(sqlite.newHandle(), "account-1");
    expect(await reopened.get(value.identity)).toBeUndefined();
    await reopened.put(value);
    expect(await reopened.get(value.identity)).toMatchObject({ rawJson: value.rawJson });
  });

  it("deduplicates concurrent reads and does not mutate input values", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    await cache.put(value);
    const readDb = sqlite.newHandle();
    const getFirstAsync = jest.spyOn(readDb, "getFirstAsync");
    const reopened = createNativeDefinitionCache(readDb, "account-1");
    const [first, second] = await Promise.all([
      reopened.get(value.identity),
      reopened.get(value.identity),
    ]);
    expect(first).toEqual(second);
    expect(getFirstAsync).toHaveBeenCalledTimes(1);

    const identity = { ...value.identity };
    const input: VerifiedFormDefinition = { ...value, identity };
    const before = structuredClone(input);
    const newCache = createNativeDefinitionCache(sqlite.db, "account-1");
    await newCache.put(input);
    expect(input).toEqual(before);
  });

  it("does not recreate a project row when removal starts during put verification", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    const verificationStarted = deferred<void>();
    const continueVerification = deferred<void>();
    const originalDigest = Crypto.digestStringAsync.bind(Crypto);
    const digest = jest.spyOn(Crypto, "digestStringAsync").mockImplementation(async (algorithm, data, options) => {
      verificationStarted.resolve();
      await continueVerification.promise;
      return originalDigest(algorithm, data, options);
    });

    const put = cache.put(value);
    await verificationStarted.promise;
    await cache.removeProject(value.identity.projectId);
    continueVerification.resolve();
    await put;
    digest.mockRestore();

    expect(await sqlite.db.getFirstAsync(
      "SELECT raw_json FROM form_definitions WHERE account_id = ? AND project_id = ?",
      ["account-1", value.identity.projectId],
    )).toBeNull();
  });

  it("shares revocation across factories for one account and cancels another reference's pending put", async () => {
    const writer = createNativeDefinitionCache(sqlite.db, "account-1");
    const revoker = createNativeDefinitionCache(sqlite.db, "account-1");
    const otherAccount = createNativeDefinitionCache(sqlite.db, "account-2");
    expect(revoker).toBe(writer);
    expect(otherAccount).not.toBe(writer);
    await writer.initialize();
    const value = await makeDefinition();
    const verificationStarted = deferred<void>();
    const continueVerification = deferred<void>();
    const originalDigest = Crypto.digestStringAsync.bind(Crypto);
    const digest = jest.spyOn(Crypto, "digestStringAsync").mockImplementation(async (algorithm, data, options) => {
      verificationStarted.resolve();
      await continueVerification.promise;
      return originalDigest(algorithm, data, options);
    });

    const put = writer.put(value);
    await verificationStarted.promise;
    await revoker.removeProject(value.identity.projectId);
    continueVerification.resolve();
    await put;
    digest.mockRestore();

    expect(await sqlite.db.getFirstAsync(
      "SELECT raw_json FROM form_definitions WHERE account_id = ? AND project_id = ?",
      ["account-1", value.identity.projectId],
    )).toBeNull();
    const otherValue = await makeDefinition({ accountId: "account-2" });
    await otherAccount.put(otherValue);
    expect(await otherAccount.get(otherValue.identity)).toMatchObject({ rawJson: otherValue.rawJson });
  });

  it("restores access without restoring rows or reviving a pre-revocation put", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    const verificationStarted = deferred<void>();
    const continueVerification = deferred<void>();
    const originalDigest = Crypto.digestStringAsync.bind(Crypto);
    const digest = jest.spyOn(Crypto, "digestStringAsync").mockImplementation(async (algorithm, data, options) => {
      verificationStarted.resolve();
      await continueVerification.promise;
      return originalDigest(algorithm, data, options);
    });

    const stalePut = cache.put(value);
    await verificationStarted.promise;
    await cache.removeProject(value.identity.projectId);
    cache.restoreProject(value.identity.projectId);
    continueVerification.resolve();
    await stalePut;
    digest.mockRestore();

    expect(await sqlite.db.getFirstAsync(
      "SELECT raw_json FROM form_definitions WHERE account_id = ? AND project_id = ?",
      ["account-1", value.identity.projectId],
    )).toBeNull();
    expect(await cache.get(value.identity)).toBeUndefined();

    await cache.put(value);
    expect(await cache.get(value.identity)).toMatchObject({ rawJson: value.rawJson });
  });

  it("keeps removal ordered after an upsert already inside its transaction", async () => {
    const writer = createNativeDefinitionCache(sqlite.db, "account-1");
    const revoker = createNativeDefinitionCache(sqlite.db, "account-1");
    await writer.initialize();
    const value = await makeDefinition();
    const writeComplete = deferred<void>();
    const allowCommit = deferred<void>();
    const originalTransaction = sqlite.db.withExclusiveTransactionAsync.bind(sqlite.db);
    const transaction = jest.spyOn(sqlite.db, "withExclusiveTransactionAsync").mockImplementation(async (task) => {
      await originalTransaction(async (tx) => {
        await task(tx);
        writeComplete.resolve();
        await allowCommit.promise;
      });
    });

    const put = writer.put(value);
    await writeComplete.promise;
    const remove = revoker.removeProject(value.identity.projectId);
    await remove;
    allowCommit.resolve();
    await put;
    transaction.mockRestore();

    expect(await sqlite.db.getFirstAsync(
      "SELECT raw_json FROM form_definitions WHERE account_id = ? AND project_id = ?",
      ["account-1", value.identity.projectId],
    )).toBeNull();
    expect(await revoker.get(value.identity)).toBeUndefined();
  });

  it("does not return a pending read after project removal starts", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    await cache.put(value);
    const readDb = sqlite.newHandle();
    const reopened = createNativeDefinitionCache(readDb, "account-1");
    const readStarted = deferred<void>();
    const continueRead = deferred<void>();
    const originalGet = readDb.getFirstAsync.bind(readDb);
    const getFirst = jest.spyOn(readDb, "getFirstAsync").mockImplementation(async (sql, params) => {
      const row = await originalGet(sql, params);
      readStarted.resolve();
      await continueRead.promise;
      return row;
    });

    const read = reopened.get(value.identity);
    await readStarted.promise;
    await reopened.removeProject(value.identity.projectId);
    continueRead.resolve();
    await expect(read).resolves.toBeUndefined();
    getFirst.mockRestore();
  });

  it("removes only one account's selected project and leaves answers untouched", async () => {
    await sqlite.db.execAsync("CREATE TABLE answers (id TEXT PRIMARY KEY, body TEXT NOT NULL)");
    await sqlite.db.runAsync("INSERT INTO answers (id, body) VALUES (?, ?)", ["draft-1", "answers"]);
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const selected = await makeDefinition({ projectId: "project-1" });
    const otherProject = await makeDefinition({ projectId: "project-2" });
    const otherAccount = await makeDefinition({ accountId: "account-2", projectId: "project-1" });
    await cache.put(selected);
    await cache.put(otherProject);
    const otherAccountCache = createNativeDefinitionCache(sqlite.db, "account-2");
    await otherAccountCache.put(otherAccount);

    await cache.removeProject("project-1");
    expect(await cache.get(selected.identity)).toBeUndefined();
    expect(await cache.get(otherProject.identity)).toMatchObject({ rawJson: otherProject.rawJson });
    expect(await otherAccountCache.get(otherAccount.identity)).toMatchObject({ rawJson: otherAccount.rawJson });
    expect(await sqlite.db.getFirstAsync("SELECT body FROM answers WHERE id = ?", ["draft-1"])).toEqual({ body: "answers" });
  });

  it("propagates database failures and engine incompatibility", async () => {
    const cache = createNativeDefinitionCache(sqlite.db, "account-1");
    await cache.initialize();
    const value = await makeDefinition();
    const failingDb = {
      ...sqlite.db,
      withExclusiveTransactionAsync: async () => { throw new Error("database_write_failed"); },
    } as unknown as SQLiteDatabase;
    await expect(createNativeDefinitionCache(failingDb, "account-1").put(value))
      .rejects.toThrow("database_write_failed");

    const incompatibleJson = JSON.stringify({
      ...JSON.parse(value.rawJson),
      engineVersion: ENGINE_VERSION + 1,
    });
    const incompatibleHash = await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      incompatibleJson,
      { encoding: Crypto.CryptoEncoding.HEX },
    );
    const incompatible: VerifiedFormDefinition = {
      ...value,
      rawJson: incompatibleJson,
      engineVersion: ENGINE_VERSION + 1,
      identity: { ...value.identity, sha256: incompatibleHash },
    };
    await expect(cache.put(incompatible)).rejects.toMatchObject({ code: "incompatible_engine" });
  });
});
