/**
 * The last site/unit an interviewer started an interview at, kept in their own encrypted store (the `meta`
 * table) per project, so "Recent" in the picker survives a restart, is never shared between accounts and goes
 * with the project when access is revoked (purgeProjectData clears project meta).
 */
import { getMeta, setMeta, type Db } from "./drafts";

export interface RecentTarget { siteId: string; orgUnitId?: string }
const KEY = "recentTarget";

export async function readRecentTarget(db: Db, projectId: string): Promise<RecentTarget | undefined> {
  try {
    const value = await getMeta<RecentTarget>(db, KEY, projectId);
    return value && typeof value.siteId === "string" ? value : undefined;
  } catch {
    return undefined;
  }
}

export async function writeRecentTarget(db: Db, projectId: string, target: RecentTarget): Promise<void> {
  try {
    await setMeta(db, KEY, { siteId: target.siteId, ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {}) }, projectId);
  } catch {
    // A missing Recent row is harmless; never block starting an interview.
  }
}
