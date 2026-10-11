/**
 * Opening, locking and wiping one interviewer's encrypted database.
 *
 * Each interviewer has their own SQLCipher file (`useSQLCipher` in app.json),
 * keyed with `PRAGMA key` from the store secret and the PIN (src/vault.ts).
 * An unlocked handle lives only in this module's memory; locking closes it
 * and drops the reference, so the key is gone until the next unlock.
 * Callers take the returned Db handle and never see the key.
 *
 * One file per interviewer, named by a hash of the user id, so the file list
 * reveals that accounts exist but not who they are or what they hold.
 *
 * Phase-2a plaintext files: PIN setup deletes any file already at the
 * interviewer's path before creating the encrypted one. Pre-release builds
 * held no real interviews, and opening a plaintext file with a key fails
 * exactly like a wrong PIN, so it would otherwise burn the attempts.
 */
import { deleteDatabaseAsync, openDatabaseAsync } from "expo-sqlite";

import { migrate, type Db } from "./drafts";
import {
  buildPassphrase,
  createStoreSecret,
  forgetStoreKeys,
  readStoreSecret,
  recordFailedAttempt,
  setFailedAttempts,
  storeHash,
  WIPE_AFTER_FAILURES
} from "./vault";

export class StoreLockedError extends Error {
  constructor() {
    super("store_locked");
    this.name = "StoreLockedError";
  }
}

export type UnlockResult = { ok: true } | { ok: false; failures: number; wipe: boolean };

const unlocked = new Map<string, Db>();

const fileName = async (userId: string) => `iv_${await storeHash(userId)}.db`;

export const isUnlocked = (userId: string) => unlocked.has(userId);
export const anyUnlocked = () => unlocked.size > 0;

/** The interviewer's unlocked database; rejects with StoreLockedError while locked. */
export async function openInterviewerDb(userId: string): Promise<Db> {
  const db = unlocked.get(userId);
  if (!db) throw new StoreLockedError();
  return db;
}

/** Whether a PIN has been set up for this interviewer on this device. */
export async function hasInterviewerStore(userId: string): Promise<boolean> {
  return (await readStoreSecret(userId)) !== null;
}

/** Open a fresh connection, key it, prove the key with a read, migrate. Closes it on any failure. */
async function openKeyed(name: string, passphrase: string): Promise<Db> {
  const handle = await openDatabaseAsync(name, { useNewConnection: true });
  try {
    await handle.execAsync(`PRAGMA key = '${passphrase}';`);
    await handle.getFirstAsync("SELECT count(*) AS n FROM sqlite_master", []);
    await migrate(handle);
    return handle;
  } catch (error) {
    await handle.closeAsync().catch(() => undefined);
    throw error;
  }
}

/** SQLCipher answers a wrong key with SQLITE_NOTADB on the first read; a malformed PIN is just as wrong. */
const isWrongKey = (error: unknown) => /not a database|SQLITE_NOTADB|code 26|bad_pin/i.test(String(error));

/**
 * First PIN on this device: new store secret, any leftover file at this
 * path deleted, a new encrypted database left unlocked. Refuses when a store
 * secret already exists, so reaching PIN setup (a deep link, say) can never
 * replace a PIN or erase a store.
 */
export async function createInterviewerDb(userId: string, pin: string): Promise<void> {
  if (await hasInterviewerStore(userId)) throw new Error("store_exists");
  await deleteInterviewerDb(userId);
  const secret = await createStoreSecret(userId);
  const db = await openKeyed(await fileName(userId), buildPassphrase(secret, pin));
  await setFailedAttempts(userId, 0);
  unlocked.set(userId, db);
}

/**
 * Try `pin`. The attempt is counted before the key is tried (killing the app
 * mid-try still counts) and the count cleared on success. `wipe` is true on
 * the WIPE_AFTER_FAILURES-th wrong PIN in a row, after this store and its
 * keys are already deleted; the caller then signs the interviewer out.
 * Throws StoreLockedError when no PIN is set up (go to PIN setup).
 */
export async function unlockInterviewerDb(userId: string, pin: string): Promise<UnlockResult> {
  if (unlocked.has(userId)) return { ok: true };
  const secret = await readStoreSecret(userId);
  if (!secret) throw new StoreLockedError();
  const failures = await recordFailedAttempt(userId);
  try {
    const db = await openKeyed(await fileName(userId), buildPassphrase(secret, pin));
    await setFailedAttempts(userId, 0);
    unlocked.set(userId, db);
    return { ok: true };
  } catch (error) {
    if (!isWrongKey(error)) {
      await setFailedAttempts(userId, failures - 1);
      throw error;
    }
  }
  if (failures < WIPE_AFTER_FAILURES) return { ok: false, failures, wipe: false };
  await deleteInterviewerDb(userId);
  return { ok: false, failures, wipe: true };
}

/** Close every unlocked database and drop the handles. */
export async function lockAll(): Promise<void> {
  const failures: unknown[] = [];
  await Promise.all([...unlocked.entries()].map(async ([userId, db]) => {
    try {
      await db.closeAsync();
      if (unlocked.get(userId) === db) unlocked.delete(userId);
    } catch (error) {
      failures.push(error);
    }
  }));
  if (failures.length) throw failures[0];
}

/** Close and delete the interviewer's database file and forget its keys. Other interviewers are untouched. */
export async function deleteInterviewerDb(userId: string): Promise<void> {
  const db = unlocked.get(userId);
  unlocked.delete(userId);
  if (db) await db.closeAsync().catch(() => undefined);
  try {
    await deleteDatabaseAsync(await fileName(userId));
  } catch {
    // No file yet: nothing to wipe.
  }
  await forgetStoreKeys(userId);
}
