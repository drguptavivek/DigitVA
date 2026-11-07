/**
 * Opening, locking and wiping one interviewer's encrypted database.
 *
 * Each interviewer has their own SQLCipher file (`useSQLCipher` in app.json),
 * keyed with `PRAGMA key` from the store's data key, released by the PIN or,
 * after a password sign-in, by its reset copy (src/vault.ts). Wrong PINs lock
 * the store for a while and never delete it (digitva-kfi).
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
import { assertAccountStoreModeSafe } from "./accountStoreIdentity";
import { clearPinResetGrant, hasPinResetGrant, takePinResetGrant } from "./pinResetGrant";
import {
  buildPassphrase,
  checkedDataKey,
  createStoreSecret,
  failedAttempts,
  forgetStoreKeys,
  newDataKey,
  pinLockMs,
  pinLockRemainingMs,
  pinProblem,
  readPinWrap,
  readResetCopy,
  readStoreSecret,
  recordFailedAttempt,
  recordPinLength,
  saveResetCopy,
  savePinWrap,
  setFailedAttempts,
  storeHash,
  turnOffBiometric,
  turnOffScreenLock,
  unwrapDataKey,
  wrapDataKey
} from "./vault";

export class StoreLockedError extends Error {
  constructor() {
    super("store_locked");
    this.name = "StoreLockedError";
  }
}

export type UnlockResult =
  | { ok: true }
  /**
   * Wrong PIN, or refused untried while locked: `lockedMs` is the wait before the next PIN (0 = none).
   * `wipe` + `revoked`: the PIN was right, but access was removed and nothing was left unsent, so the store was wiped.
   */
  | { ok: false; failures: number; wipe: boolean; revoked?: true; lockedMs?: number }
  /** The Keystore secret survives but the database file is gone: nothing is opened or counted; the caller offers a reset. */
  | { ok: false; failures: 0; wipe: false; storeMissing: true };

/** How long a close waits for statements already running before closing anyway. */
const DRAIN_TIMEOUT_MS = 5000;

/**
 * Wrap a native handle so closing is safe (digitva-d9zg): expo-sqlite's native close can run concurrently
 * with a statement on another thread and crash in sqlite3_mutex_enter. Every statement counts as in flight;
 * closeAsync marks the handle closing (new statements reject StoreLockedError and never reach native), waits
 * for the in-flight ones (bounded), then closes.
 */
function guardHandle(raw: Db): Db {
  let closing: Promise<void> | undefined;
  const inFlight = new Set<Promise<unknown>>();
  const run = <T>(call: () => Promise<T>): Promise<T> => {
    if (closing) return Promise.reject(new StoreLockedError());
    const p = call();
    inFlight.add(p);
    const done = () => inFlight.delete(p);
    p.then(done, done);
    return p;
  };
  return {
    execAsync: (source) => run(() => raw.execAsync(source)),
    runAsync: (source, params) => run(() => raw.runAsync(source, params)),
    getAllAsync: <T>(source: string, params: Parameters<Db["getAllAsync"]>[1]) => run(() => raw.getAllAsync<T>(source, params)),
    getFirstAsync: <T>(source: string, params: Parameters<Db["getFirstAsync"]>[1]) => run(() => raw.getFirstAsync<T>(source, params)),
    closeAsync() {
      closing ??= (async () => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const timeout = new Promise<void>((resolve) => { timer = setTimeout(resolve, DRAIN_TIMEOUT_MS); });
        await Promise.race([Promise.allSettled([...inFlight]), timeout]);
        clearTimeout(timer);
        await raw.closeAsync();
      })();
      // A failed native close leaves the handle open: reopen it to statements so the caller can retry.
      closing.catch(() => { closing = undefined; });
      return closing;
    }
  };
}

const unlocked = new Map<string, Db>();
/** Unlocks and PIN setups in flight: lockAll waits for them, so a store opening as it locks is closed too. */
const opening = new Set<Promise<unknown>>();

function tracked<T>(work: Promise<T>): Promise<T> {
  opening.add(work);
  void work.catch(() => undefined).finally(() => opening.delete(work));
  return work;
}

const fileName = async (userId: string) => `iv_${await storeHash(userId)}.db`;

export const isUnlocked = (userId: string) => unlocked.has(userId);
/** A store is open, or opening (lockAll will wait for it). */
export const anyUnlocked = () => unlocked.size > 0 || opening.size > 0;
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
  await assertAccountStoreModeSafe(userId);
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
    return guardHandle(handle);
  } catch (error) {
    await handle.closeAsync().catch(() => undefined);
    throw error;
  }
}

/** SQLCipher answers a wrong key with SQLITE_NOTADB on the first read; a malformed PIN is just as wrong. */
const isWrongKey = (error: unknown) => /not a database|SQLITE_NOTADB|code 26|bad_pin/i.test(String(error));

/**
 * First PIN on this device: new store secret and random data key with both
 * copies saved (verified) before the file exists, any leftover file at this
 * path deleted, a new encrypted database left unlocked. Refuses when a store
 * secret already exists, so reaching PIN setup (a deep link, say) can never
 * replace a PIN or erase a store.
 */
export function createInterviewerDb(userId: string, pin: string): Promise<void> {
  return tracked(createInterviewerDbOnce(userId, pin));
}

async function createInterviewerDbOnce(userId: string, pin: string): Promise<void> {
  await assertAccountStoreModeSafe(userId);
  if (await hasInterviewerStore(userId)) throw new Error("store_exists");
  await deleteInterviewerDb(userId);
  let db: Db;
  try {
    const secret = await createStoreSecret(userId);
    const key = await newDataKey();
    await saveVerifiedPinWrap(userId, secret, pin, key);
    await saveResetCopy(userId, key);
    db = await openKeyed(await fileName(userId), key);
  } catch (error) {
    // No database yet: forget the half-made keys so PIN setup can try again.
    await deleteInterviewerDb(userId).catch(() => undefined);
    throw error;
  }
  await setFailedAttempts(userId, 0);
  unlocked.set(userId, db);
}

/** Wrap `key` under `pin`, check it unwraps to the same key, then save it (one SecureStore write replaces the old wrap). */
async function saveVerifiedPinWrap(userId: string, secret: string, pin: string, key: string): Promise<void> {
  const wrapped = await wrapDataKey(secret, pin, key);
  if ((await unwrapDataKey(secret, pin, wrapped)) !== key) throw new Error("wrap_check_failed");
  await savePinWrap(userId, wrapped);
}

/**
 * After a correct PIN: make sure both key copies exist. A pre-digitva-kfi store gets them here, its old
 * `secret:PIN` passphrase kept as the data key (no rekey, nothing in the file rewritten). The reset copy goes
 * first; the PIN wrap, once saved, replaces the old path. Any failure leaves the old path working and the
 * next unlock tries again; the database file and the store secret are never touched.
 */
async function keepKeyCopies(userId: string, secret: string, pin: string, key: string, hadPinWrap: boolean): Promise<void> {
  try {
    if ((await readResetCopy(userId)) !== key) await saveResetCopy(userId, key);
    if (!hadPinWrap) await saveVerifiedPinWrap(userId, secret, pin, key);
  } catch {
    // The store is open; the old path still opens it next time.
  }
}

/**
 * Try `pin`. While a lockout runs (src/vault.ts pinLockRemainingMs) the PIN is
 * neither tried nor counted. Otherwise the attempt is counted before the key is
 * tried (killing the app mid-try still counts) and the count cleared on
 * success. Wrong PINs never delete anything (digitva-kfi); `lockedMs` says
 * how long the next PIN must wait. Throws StoreLockedError when no PIN is set
 * up (go to PIN setup).
 */
export function unlockInterviewerDb(userId: string, pin: string): Promise<UnlockResult> {
  // One attempt at a time per user: the failure counter is read, then written, and a rollback reuses the read.
  const run = (unlockQueue.get(userId) ?? Promise.resolve()).then(() => unlockInterviewerDbOnce(userId, pin));
  const tail = run.then(() => undefined, () => undefined);
  unlockQueue.set(userId, tail);
  void tail.then(() => { if (unlockQueue.get(userId) === tail) unlockQueue.delete(userId); });
  return tracked(run);
}

const unlockQueue = new Map<string, Promise<void>>();

async function unlockInterviewerDbOnce(userId: string, pin: string): Promise<UnlockResult> {
  await assertAccountStoreModeSafe(userId);
  if (unlocked.has(userId)) {
    clearPinResetGrant(userId);
    return { ok: true };
  }
  const secret = await readStoreSecret(userId);
  if (!secret) throw new StoreLockedError();
  if (await dbFileMissing(userId)) return { ok: false, failures: 0, wipe: false, storeMissing: true };
  const waitMs = await pinLockRemainingMs(userId);
  if (waitMs > 0) return { ok: false, failures: await failedAttempts(userId), wipe: false, lockedMs: waitMs };
  const failures = await recordFailedAttempt(userId);
  const wrapped = await readPinWrap(userId);
  try {
    // Once a PIN wrap exists the old `secret:PIN` path is closed: after a reset the old PIN must not open it.
    const key = wrapped ? await unwrapDataKey(secret, pin, wrapped) : buildPassphrase(secret, pin);
    if (!key) throw new Error("bad_pin");
    const db = await openKeyed(await fileName(userId), checkedDataKey(key));
    await setFailedAttempts(userId, 0);
    unlocked.set(userId, db);
    clearPinResetGrant(userId);
    await keepKeyCopies(userId, secret, pin, key, wrapped !== null);
    wipeMediaCache(); // a playback copy left by a crash
    return { ok: true };
  } catch (error) {
    if (!isWrongKey(error)) {
      await setFailedAttempts(userId, failures - 1);
      throw error;
    }
  }
  const lockedMs = pinLockMs(failures);
  return lockedMs ? { ok: false, failures, wipe: false, lockedMs } : { ok: false, failures, wipe: false };
}

/**
 * Forgotten PIN: after a password sign-in for this account (src/pinResetGrant.ts), open the store with its reset copy
 * and wrap the data key under `pin`. Every interview stays; the counter and lockout clear; fingerprint and
 * screen-lock entries (they hold the old PIN) are dropped. Uses the permission once, after the new wrap is saved (a failure before that keeps it). Throws
 * `pin_reset_not_allowed` without one, `pin_reset_unavailable` when the store has no reset copy (it never
 * unlocked on this version), or the open error; on any throw the old PIN wrap is still in place.
 */
export function resetInterviewerPin(userId: string, pin: string): Promise<void> {
  return tracked(resetInterviewerPinOnce(userId, pin));
}

async function resetInterviewerPinOnce(userId: string, pin: string): Promise<void> {
  await assertAccountStoreModeSafe(userId);
  if (!hasPinResetGrant(userId)) throw new Error("pin_reset_not_allowed");
  if (pinProblem(pin, pin)) throw new Error("bad_pin");
  const secret = await readStoreSecret(userId);
  const key = await readResetCopy(userId);
  if (!secret || !key || (await dbFileMissing(userId))) throw new Error("pin_reset_unavailable");
  // Prove the reset copy opens the file before the PIN wrap changes.
  const db = unlocked.get(userId) ?? await openKeyed(await fileName(userId), checkedDataKey(key));
  try {
    await saveVerifiedPinWrap(userId, secret, pin, key);
  } catch (error) {
    if (!unlocked.has(userId)) await db.closeAsync().catch(() => undefined);
    throw error;
  }
  // Used only now that the new wrap is saved: a transient failure above leaves the grant for a retry.
  takePinResetGrant(userId);
  unlocked.set(userId, db);
  await setFailedAttempts(userId, 0);
  await turnOffBiometric(userId);
  await turnOffScreenLock(userId);
  await recordPinLength(userId, pin.length).catch(() => undefined);
}

/** Close every unlocked database and drop the handles, after any unlock in flight has settled. */
export async function lockAll(): Promise<void> {
  clearPinResetGrant();
  await Promise.allSettled([...opening]);
  const failures: unknown[] = [];
  await Promise.all([...unlocked.entries()].map(async ([userId, db]) => {
    // Out of the map first: nobody can be handed a handle that is closing.
    if (unlocked.get(userId) === db) unlocked.delete(userId);
    try {
      await db.closeAsync();
    } catch (error) {
      if (!unlocked.has(userId)) unlocked.set(userId, db); // still open: keep it so the next lock retries
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
