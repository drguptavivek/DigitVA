/**
 * Opening and wiping one interviewer's database.
 *
 * Phase 2a: plain expo-sqlite, NOT encrypted. Debug builds only, no real
 * interviews. Phase 2b replaces the body of openInterviewerDb with SQLCipher
 * (`useSQLCipher`) keyed from the per-store secret joined with the PIN; no
 * caller changes, because everything else takes the returned Db handle.
 *
 * One file per interviewer, named by a hash of the user id, so the file list
 * reveals that accounts exist but not who they are or what they hold.
 */
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { deleteDatabaseAsync, openDatabaseAsync } from "expo-sqlite";

import { migrate, type Db } from "./drafts";

const open = new Map<string, Promise<Db>>();

async function fileName(userId: string): Promise<string> {
  const hash = await digestStringAsync(CryptoDigestAlgorithm.SHA256, `digitva-collect:${userId}`);
  return `iv_${hash}.db`;
}

/** The interviewer's database, opened once per app run and migrated. */
export function openInterviewerDb(userId: string): Promise<Db> {
  let db = open.get(userId);
  if (!db) {
    db = fileName(userId)
      .then((name) => openDatabaseAsync(name))
      .then(async (handle) => {
        await migrate(handle);
        return handle;
      });
    db.catch(() => open.delete(userId));
    open.set(userId, db);
  }
  return db;
}

/** Close and delete the interviewer's database file. Other interviewers are untouched. */
export async function deleteInterviewerDb(userId: string): Promise<void> {
  const pending = open.get(userId);
  open.delete(userId);
  if (pending) {
    try {
      await (await pending).closeAsync();
    } catch {
      // Already closed or never opened; the delete below still runs.
    }
  }
  try {
    await deleteDatabaseAsync(await fileName(userId));
  } catch {
    // No file yet: nothing to wipe.
  }
}
