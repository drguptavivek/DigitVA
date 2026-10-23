/**
 * Storage of the local error log in the open, encrypted interviewer store (table `error_log`, created by
 * migrate in src/drafts.ts). It is deleted with the store on sign-out, revoke or wipe. Capped at MAX_ERRORS
 * entries and MAX_ERROR_AGE_DAYS days, both enforced on every write.
 */
import type { Db } from "./drafts";
import { MAX_ERROR_AGE_DAYS, MAX_ERRORS, pendingErrors, setErrorWriter, type ErrorEntry } from "./errorLog";
import { firstUnlockedDb } from "./interviewerDb";

export async function writeErrors(db: Db, entries: ErrorEntry[], now = Date.now()): Promise<void> {
  for (const e of entries) {
    await db.runAsync(
      "INSERT INTO error_log (at, app_version, route, what, device, android) VALUES (?, ?, ?, ?, ?, ?)",
      [e.at, e.appVersion, e.route, e.what, e.device, e.android],
    );
  }
  await db.runAsync("DELETE FROM error_log WHERE at < ?", [new Date(now - MAX_ERROR_AGE_DAYS * 86_400_000).toISOString()]);
  await db.runAsync("DELETE FROM error_log WHERE id NOT IN (SELECT id FROM error_log ORDER BY id DESC LIMIT ?)", [MAX_ERRORS]);
}

/** Stored entries, newest first. */
export async function readErrors(db: Db): Promise<ErrorEntry[]> {
  const rows = await db.getAllAsync<{ at: string; app_version: string; route: string; what: string; device: string; android: string }>(
    "SELECT at, app_version, route, what, device, android FROM error_log ORDER BY id DESC LIMIT ?",
    [MAX_ERRORS],
  );
  return rows.map((r) => ({ at: r.at, appVersion: r.app_version, route: r.route, what: r.what, device: r.device, android: r.android }));
}

/** Every stored entry plus those still waiting for the store, newest first. */
export async function allErrors(): Promise<ErrorEntry[]> {
  const db = firstUnlockedDb();
  const stored = db ? await readErrors(db) : [];
  return [...pendingErrors().reverse(), ...stored];
}

/** Route new entries into whichever store is open; false while locked keeps them buffered. */
export function installErrorLog(): () => void {
  setErrorWriter(async (entries) => {
    const db = firstUnlockedDb();
    if (!db) return false;
    await writeErrors(db, entries);
    return true;
  });
  return () => setErrorWriter(undefined);
}
