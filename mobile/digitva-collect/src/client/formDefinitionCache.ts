import {
  FormDefinitionError,
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "../formDefinitions";

interface PendingPut {
  cancelled: boolean;
}

/** Create an in-memory definition cache scoped to one signed-in account. */
export function createBrowserDefinitionCache(accountId: string): {
  get(identity: DefinitionIdentity): Promise<VerifiedFormDefinition | undefined>;
  put(value: VerifiedFormDefinition): Promise<void>;
  removeProject(projectId: string): void;
  clear(): void;
} {
  const entries = new Map<string, VerifiedFormDefinition>();
  const pending = new Map<string, Set<PendingPut>>();

  function key(identity: DefinitionIdentity): string {
    return JSON.stringify([
      identity.accountId,
      identity.projectId,
      identity.instrumentCode,
      identity.composedVersion,
      identity.sha256,
    ]);
  }

  function cancelProjectPuts(projectId?: string): void {
    for (const [pendingProjectId, puts] of pending) {
      if (projectId === undefined || pendingProjectId === projectId) {
        for (const put of puts) put.cancelled = true;
      }
    }
  }

  return {
    /** Return a newly verified definition so caller mutations cannot poison the cache. */
    async get(identity) {
      if (identity.accountId !== accountId) {
        throw new FormDefinitionError("invalid_identity");
      }
      const cached = entries.get(key(identity));
      if (!cached) return undefined;
      try {
        const verified = await verifyAndCompileDefinition({
          rawJson: cached.rawJson,
          identity: cached.identity,
          responseSha256: cached.identity.sha256,
          etag: cached.etag,
        });
        return entries.get(key(identity)) === cached ? verified : undefined;
      } catch (error) {
        if (entries.get(key(identity)) === cached) entries.delete(key(identity));
        throw error;
      }
    },

    /** Verify before retaining; a revocation during verification cancels this write. */
    async put(value) {
      const identity = { ...value.identity };
      if (identity.accountId !== accountId) {
        throw new FormDefinitionError("invalid_identity");
      }

      const token: PendingPut = { cancelled: false };
      const puts = pending.get(identity.projectId) ?? new Set<PendingPut>();
      puts.add(token);
      pending.set(identity.projectId, puts);
      try {
        const verified = await verifyAndCompileDefinition({
          rawJson: value.rawJson,
          identity,
          responseSha256: identity.sha256,
          etag: value.etag,
        });
        if (!token.cancelled) entries.set(key(identity), verified);
      } finally {
        puts.delete(token);
        if (puts.size === 0) pending.delete(identity.projectId);
      }
    },

    /** Remove all versions for a revoked project and cancel its pending writes. */
    removeProject(projectId) {
      cancelProjectPuts(projectId);
      for (const [entryKey, value] of entries) {
        if (value.identity.projectId === projectId) entries.delete(entryKey);
      }
    },

    /** Clear definitions on logout or account change, including writes still hashing. */
    clear() {
      cancelProjectPuts();
      entries.clear();
    },
  };
}
