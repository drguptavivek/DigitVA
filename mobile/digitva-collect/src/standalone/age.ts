/** Age warning and backup reminder rules for standalone records (pure; thresholds in ./config). */
import { BACKUP_REMINDER_DAYS, STANDALONE_AGE_WARNING_DAYS } from "./config";

const DAY_MS = 86_400_000;

/** Whole days from an ISO time to `now`; null for a missing or unreadable time. */
export function daysSince(iso: string | null | undefined, now: Date): number | null {
  const at = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(at) ? null : Math.max(0, Math.floor((now.getTime() - at) / DAY_MS));
}

/** A record older than the threshold (not pushed or backed up) shows the age warning. */
export function isOverAgeLimit(startedAt: string | null | undefined, now: Date): boolean {
  const days = daysSince(startedAt, now);
  return days !== null && days > STANDALONE_AGE_WARNING_DAYS;
}

/**
 * Whether to remind about a backup: there is at least one record, and the last backup (or, with none, the oldest
 * record) is more than BACKUP_REMINDER_DAYS ago. `days` is what the message shows (null: never backed up).
 */
export function backupReminder(
  input: { lastBackupAt: string | null; oldestRecordAt: string | null; recordCount: number },
  now: Date,
): { due: boolean; days: number | null } {
  if (input.recordCount === 0) return { due: false, days: null };
  const days = daysSince(input.lastBackupAt, now);
  const basis = days ?? daysSince(input.oldestRecordAt, now);
  return { due: basis !== null && basis >= BACKUP_REMINDER_DAYS, days };
}
