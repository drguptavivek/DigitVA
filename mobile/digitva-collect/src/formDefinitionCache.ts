/**
 * Verified form definitions in an already-open interviewer's SQLCipher store.
 *
 * The cache keeps exact version and hash slices so an offline draft can recover
 * the definition it started with. Pruning belongs to the caller, which can
 * check draft and revision references before removing anything.
 */
import type { SQLiteDatabase } from "expo-sqlite";

import {
  FormDefinitionError,
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "./formDefinitions";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

interface StoredDefinitionRow {
  raw_json: unknown;
  etag: unknown;
}

interface CacheEntry {
  identity: DefinitionIdentity;
  value: VerifiedFormDefinition;
}

interface NativeDefinitionCache {
  initialize(): Promise<void>;
  get(identity: DefinitionIdentity): Promise<VerifiedFormDefinition | undefined>;
  put(value: VerifiedFormDefinition): Promise<void>;
  removeProject(projectId: string): Promise<void>;
  restoreProject(projectId: string): void;
}

const cacheInstances = new WeakMap<SQLiteDatabase, Map<string, NativeDefinitionCache>>();

/** Use a JSON tuple so identity parts cannot collide through delimiters. */
function identityKey(identity: DefinitionIdentity): string {
  return JSON.stringify([
    identity.accountId,
    identity.projectId,
    identity.instrumentCode,
    identity.composedVersion,
    identity.sha256,
  ]);
}

function assertIdentity(identity: DefinitionIdentity, accountId: string): void {
  if (
    !identity ||
    typeof identity.accountId !== "string" ||
    identity.accountId !== accountId ||
    typeof identity.projectId !== "string" ||
    !identity.projectId.trim() ||
    identity.instrumentCode !== "WHO_2022_VA" ||
    typeof identity.composedVersion !== "string" ||
    !identity.composedVersion.trim() ||
    typeof identity.sha256 !== "string" ||
    !SHA256_PATTERN.test(identity.sha256)
  ) {
    throw new FormDefinitionError("invalid_identity");
  }
}

function isCorruptDefinition(error: unknown): boolean {
  return error instanceof FormDefinitionError && [
    "definition_hash_mismatch",
    "definition_version_mismatch",
    "invalid_definition",
  ].includes(error.code);
}

/**
 * Bind verified definitions to one account's unlocked encrypted database.
 * The database must already be open; this helper never manages its key or life cycle.
 */
export function createNativeDefinitionCache(
  db: SQLiteDatabase,
  accountId: string,
): NativeDefinitionCache {
  if (typeof accountId !== "string" || !accountId.trim()) {
    throw new FormDefinitionError("invalid_identity");
  }
  const accounts = cacheInstances.get(db) ?? new Map<string, NativeDefinitionCache>();
  const existing = accounts.get(accountId);
  if (existing) return existing;

  const entries = new Map<string, CacheEntry>();
  const pending = new Map<
    string,
    { projectId: string; promise: Promise<VerifiedFormDefinition | undefined> }
  >();
  const projectReadGeneration = new Map<string, number>();
  const projectRevocationGeneration = new Map<string, number>();
  const revokedProjects = new Set<string>();

  function clearProjectCache(projectId: string): void {
    projectReadGeneration.set(projectId, (projectReadGeneration.get(projectId) ?? 0) + 1);
    for (const [key, entry] of entries) {
      if (entry.identity.projectId === projectId) entries.delete(key);
    }
    for (const [key, request] of pending) {
      if (request.projectId === projectId) pending.delete(key);
    }
  }

  async function read(identity: DefinitionIdentity): Promise<VerifiedFormDefinition | undefined> {
    const key = identityKey(identity);
    const generation = projectReadGeneration.get(identity.projectId) ?? 0;
    const row = await db.getFirstAsync<StoredDefinitionRow>(
      `SELECT raw_json, etag FROM form_definitions
       WHERE account_id = ? AND project_id = ? AND instrument_code = ?
         AND composed_version = ? AND sha256 = ?`,
      [
        identity.accountId,
        identity.projectId,
        identity.instrumentCode,
        identity.composedVersion,
        identity.sha256,
      ],
    );
    if (!row || typeof row.raw_json !== "string" || (row.etag !== null && typeof row.etag !== "string")) {
      return undefined;
    }

    let verified: VerifiedFormDefinition;
    try {
      verified = await verifyAndCompileDefinition({
        rawJson: row.raw_json,
        identity,
        responseSha256: identity.sha256,
        etag: row.etag,
      });
    } catch (error) {
      if (isCorruptDefinition(error)) return undefined;
      throw error;
    }
    if (
      revokedProjects.has(identity.projectId) ||
      (projectReadGeneration.get(identity.projectId) ?? 0) !== generation
    ) return undefined;
    entries.set(key, { identity, value: verified });
    return verified;
  }

  const cache: NativeDefinitionCache = {
    /** Create the additive table; repeated calls leave existing rows untouched. */
    async initialize(): Promise<void> {
      await db.execAsync(`
        CREATE TABLE IF NOT EXISTS form_definitions (
          account_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          instrument_code TEXT NOT NULL,
          composed_version TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          etag TEXT,
          PRIMARY KEY (account_id, project_id, instrument_code, composed_version, sha256)
        );
      `);
    },

    /** Return only an exact identity whose stored bytes still verify and compile. */
    async get(identity: DefinitionIdentity): Promise<VerifiedFormDefinition | undefined> {
      assertIdentity(identity, accountId);
      if (revokedProjects.has(identity.projectId)) return undefined;
      const copy = { ...identity };
      const key = identityKey(copy);
      const cached = entries.get(key);
      if (cached) return cached.value;
      const activeRead = pending.get(key);
      if (activeRead) return activeRead.promise;

      const readPromise = read(copy).finally(() => {
        if (pending.get(key)?.promise === readPromise) pending.delete(key);
      });
      pending.set(key, { projectId: copy.projectId, promise: readPromise });
      return readPromise;
    },

    /** Verify the exact source text again before an atomic upsert. */
    async put(value: VerifiedFormDefinition): Promise<void> {
      const identity = { ...value.identity };
      assertIdentity(identity, accountId);
      if (revokedProjects.has(identity.projectId)) return;
      const generation = projectRevocationGeneration.get(identity.projectId) ?? 0;
      const verified = await verifyAndCompileDefinition({
        rawJson: value.rawJson,
        identity,
        responseSha256: identity.sha256,
        etag: value.etag,
      });
      if (
        revokedProjects.has(identity.projectId) ||
        (projectRevocationGeneration.get(identity.projectId) ?? 0) !== generation
      ) return;
      const upsert = async (transaction: SQLiteDatabase): Promise<void> => {
        if (
          revokedProjects.has(identity.projectId) ||
          (projectRevocationGeneration.get(identity.projectId) ?? 0) !== generation
        ) return;
        await transaction.runAsync(
          `INSERT INTO form_definitions
             (account_id, project_id, instrument_code, composed_version, sha256, raw_json, etag)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(account_id, project_id, instrument_code, composed_version, sha256)
           DO UPDATE SET raw_json = excluded.raw_json, etag = excluded.etag`,
          [
            identity.accountId,
            identity.projectId,
            identity.instrumentCode,
            identity.composedVersion,
            identity.sha256,
            verified.rawJson,
            verified.etag,
          ],
        );
      };

      await db.withExclusiveTransactionAsync(upsert);
      if (
        revokedProjects.has(identity.projectId) ||
        (projectRevocationGeneration.get(identity.projectId) ?? 0) !== generation
      ) return;
      clearProjectCache(identity.projectId);
      entries.set(identityKey(identity), { identity, value: verified });
    },

    /** Delete only this account's selected project after the caller revokes access. */
    async removeProject(projectId: string): Promise<void> {
      if (typeof projectId !== "string" || !projectId.trim()) {
        throw new FormDefinitionError("invalid_identity");
      }
      revokedProjects.add(projectId);
      projectRevocationGeneration.set(projectId, (projectRevocationGeneration.get(projectId) ?? 0) + 1);
      clearProjectCache(projectId);
      await db.runAsync(
        "DELETE FROM form_definitions WHERE account_id = ? AND project_id = ?",
        [accountId, projectId],
      );
    },

    /** Re-enable future reads and writes after authoritative access is restored. */
    restoreProject(projectId: string): void {
      if (typeof projectId !== "string" || !projectId.trim()) {
        throw new FormDefinitionError("invalid_identity");
      }
      revokedProjects.delete(projectId);
      projectRevocationGeneration.set(projectId, (projectRevocationGeneration.get(projectId) ?? 0) + 1);
      clearProjectCache(projectId);
    },
  };
  accounts.set(accountId, cache);
  cacheInstances.set(db, accounts);
  return cache;
}
