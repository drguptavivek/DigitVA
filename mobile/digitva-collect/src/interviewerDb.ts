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
import { File } from "expo-file-system";
import { defaultDatabaseDirectory, deleteDatabaseAsync, openDatabaseAsync } from "expo-sqlite";

import { countUnsentWork, countUnsentWorkByKind, migrate, type Db, type UnsentWorkKinds } from "./drafts";
import { wipeMediaCache } from "./mediaFiles";
import { summariseWork, type WorkSummary } from "./unsentWork";
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

export type UnlockResult =
  | { ok: true }
  /** `revoked`: the PIN was right, but access was removed and nothing was left unsent, so the store was wiped. */
  | { ok: false; failures: number; wipe: boolean; revoked?: true }
  /** The Keystore secret survives but the database file is gone: nothing is opened or counted; the caller offers a reset. */
  | { ok: false; failures: 0; wipe: false; storeMissing: true };

const unlocked = new Map<string, Db>();

const fileName = async (userId: string) => `iv_${await storeHash(userId)}.db`;

export const isUnlocked = (userId: string) => unlocked.has(userId);
export const anyUnlocked = () => unlocked.size > 0;
/** An open store for device-level records that belong to no one interviewer (the error log); undefined while locked. */
export const firstUnlockedDb = (): Db | undefined => unlocked.values().next().value;

/**
 * True only when the database directory is known and the interviewer's file is not in it. Opening a missing
 * file would create an empty one that the surviving secret keys without error, unlocking an empty store
 * silently (digitva-jish). Unknown directory or any error counts as present: never block a working unlock.
 */
async function dbFileMissing(userId: string): Promise<boolean> {
  try {
    if (typeof defaultDatabaseDirectory !== "string" || !defaultDatabaseDirectory) return false;
    const dir = defaultDatabaseDirectory.startsWith("file://") ? defaultDatabaseDirectory : `file://${defaultDatabaseDirectory}`;
    return !new File(dir, await fileName(userId)).exists;
  } catch {
    return false;
  }
}

/** The interviewer's unlocked database; rejects with StoreLockedError while locked. */
export async function openInterviewerDb(userId: string): Promise<Db> {
  const db = unlocked.get(userId);
  if (!db) throw new StoreLockedError();
  return db;
}

/**
 * How many items this interviewer has not sent, or undefined while the store
 * is locked: the count is inside the encrypted store and is never kept
 * outside it (no plaintext index of what a store holds). Everything on the
 * phone, drafts included: the guard for sign-out and re-enrolment, which
 * would lose it. The badges use unsentWork below (ready to send only).
 */
export async function unsentWorkCount(userId: string): Promise<number | undefined> {
  const db = unlocked.get(userId);
  return db ? countUnsentWork(db) : undefined;
}

/** unsentWorkCount split by kind (for the sign-out warning), or undefined while the store is locked. */
export async function unsentWorkKinds(userId: string): Promise<UnsentWorkKinds | undefined> {
  const db = unlocked.get(userId);
  return db ? countUnsentWorkByKind(db) : undefined;
}

/**
 * What this interviewer has not sent (src/unsentWork.ts), or undefined while the store is locked: the
 * counts are inside the encrypted store and are never kept outside it (no plaintext index of what a store holds).
 */
export async function unsentWork(userId: string): Promise<WorkSummary | undefined> {
  const db = unlocked.get(userId);
  return db ? summariseWork(db) : undefined;
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
    // Concurrent writers (poll, Refresh, focus effects) wait instead of failing with "database is locked".
    await handle.execAsync("PRAGMA busy_timeout = 5000;");
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
  if (await dbFileMissing(userId)) return { ok: false, failures: 0, wipe: false, storeMissing: true };
  const failures = await recordFailedAttempt(userId);
  try {
    const db = await openKeyed(await fileName(userId), buildPassphrase(secret, pin));
    await setFailedAttempts(userId, 0);
    unlocked.set(userId, db);
    wipeMediaCache(); // a playback copy left by a crash
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
  wipeMediaCache(); // plain playback copies do not outlive the unlocked store
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
  wipeMediaCache();
}

/**
 * Reset after `storeMissing`: forget the orphaned keys so PIN setup makes a new store. The file is already
 * gone, so no data is lost here; interviews that were only on this phone were lost with the file.
 */
export async function resetMissingStore(userId: string): Promise<void> {
  if (!(await dbFileMissing(userId))) throw new Error("store_present");
  await deleteInterviewerDb(userId);
}
