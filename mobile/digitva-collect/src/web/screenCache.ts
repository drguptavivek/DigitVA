/**
 * In-memory last-good responses of the web screens, so a revisit (every sidebar click mounts a fresh screen) paints
 * the previous answer at once while the same request refreshes it. Memory only, never sessionStorage/localStorage:
 * these lists carry personal data. Keys start with the signed-in user id (screenKey), so one user's rows never reach
 * another's screen; sign-out and a user switch call clearScreenCache. Stored values are replaced, never merged.
 */
import { clearStatsCache } from "./stats/cache";

const MAX_ENTRIES = 200;
const entries = new Map<string, unknown>();

/** The key of one response: the user, then every part that changes it (screen, project, filters, tab, page). Undefined without a user: nothing is cached. */
export function screenKey(userId: string | undefined, ...parts: unknown[]): string | undefined {
  return userId ? JSON.stringify([userId, ...parts]) : undefined;
}

export function readCached<T>(key: string | undefined): T | undefined {
  return key === undefined ? undefined : (entries.get(key) as T | undefined);
}

export function writeCached(key: string | undefined, value: unknown): void {
  if (key === undefined) return;
  entries.delete(key);
  entries.set(key, value);
  if (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value!);
}

/** A refused or failed refetch: the old answer must not come back on the next visit. */
export function dropCached(key: string | undefined): void {
  if (key !== undefined) entries.delete(key);
}

/** Sign-out or a different user: drop every screen's cached response (and Statistics' own cache). */
export function clearScreenCache(): void {
  entries.clear();
  clearStatsCache();
}
