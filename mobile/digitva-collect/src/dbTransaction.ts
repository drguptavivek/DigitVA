/**
 * One write transaction on the keyed SQLCipher handle.
 *
 * expo-sqlite's `withExclusiveTransactionAsync` opens a NEW native connection
 * to the same file, and that connection has no `PRAGMA key`, so SQLCipher
 * rejects its first statement (SQLITE_NOTADB). Transactions therefore run on
 * the caller's own handle, and are queued per handle so two callers never
 * issue BEGIN inside each other's transaction. Other statements from other
 * callers may still run between a transaction's statements (one connection).
 *
 * `fn` gets the same handle. A failure rolls back and is rethrown unchanged.
 */
const queues = new WeakMap<object, Promise<unknown>>();

export async function runInTransaction<D extends { execAsync(sql: string): Promise<void> }>(
  db: D,
  fn: (db: D) => Promise<void>
): Promise<void> {
  const run = async (): Promise<void> => {
    await db.execAsync("BEGIN IMMEDIATE");
    try {
      await fn(db);
      await db.execAsync("COMMIT");
    } catch (error) {
      try {
        await db.execAsync("ROLLBACK");
      } catch {
        // Keep the write failure that caused the rollback.
      }
      throw error;
    }
  };
  const result = (queues.get(db) ?? Promise.resolve()).then(run);
  queues.set(db, result.catch(() => undefined));
  return result;
}
