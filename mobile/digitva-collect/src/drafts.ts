/**
 * Draft rows in one interviewer's database, and the WhoVaDraftStore the form
 * writes through.
 *
 * The WHO draft envelope is stored whole; host metadata the server needs to
 * route it (site, unit, completed flag) lives in its own columns, outside the
 * WHO answers. The device keeps in-flight interviews only: a row is deleted
 * once the server acknowledges it (push and purge).
 */
import type { WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

type Bind = string | number | null;

/** The subset of expo-sqlite's SQLiteDatabase this app uses. */
export interface Db {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, params: Bind[]): Promise<unknown>;
  getAllAsync<T>(source: string, params: Bind[]): Promise<T[]>;
  getFirstAsync<T>(source: string, params: Bind[]): Promise<T | null>;
  closeAsync(): Promise<void>;
}

export interface DraftRow {
  id: string;
  site_id: string;
  org_unit_id: string | null;
  completed: number;
  updated_at: string;
}

export async function migrate(db: Db): Promise<void> {
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS drafts (
      id TEXT PRIMARY KEY NOT NULL,
      site_id TEXT NOT NULL,
      org_unit_id TEXT,
      completed INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      envelope TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
  `);
}

/**
 * The form's draft store for one interview. `host` supplies the site and
 * unit on the first save; later saves update only the envelope, so a draft
 * never moves site.
 */
export function createDraftStore(db: Db, host: { siteId: string; orgUnitId?: string | null }): WhoVaDraftStore {
  return {
    async save(draft) {
      await db.runAsync(
        `INSERT INTO drafts (id, site_id, org_unit_id, updated_at, envelope) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET envelope = excluded.envelope, updated_at = excluded.updated_at`,
        [draft.id, host.siteId, host.orgUnitId ?? null, draft.updatedAt, JSON.stringify(draft)]
      );
    },
    async load(id) {
      const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [id]);
      return row ? (JSON.parse(row.envelope) as WhoVaDraft) : undefined;
    },
    async remove(id) {
      await deleteDraft(db, id);
    }
  };
}

/** Newest first; metadata only, never answers. */
export function listDrafts(db: Db): Promise<DraftRow[]> {
  return db.getAllAsync<DraftRow>(
    "SELECT id, site_id, org_unit_id, completed, updated_at FROM drafts ORDER BY updated_at DESC",
    []
  );
}

export async function getDraftRow(db: Db, id: string): Promise<DraftRow | null> {
  return db.getFirstAsync<DraftRow>(
    "SELECT id, site_id, org_unit_id, completed, updated_at FROM drafts WHERE id = ?",
    [id]
  );
}

export async function markCompleted(db: Db, id: string): Promise<void> {
  await db.runAsync("UPDATE drafts SET completed = 1 WHERE id = ?", [id]);
}

/** Completed drafts with their envelopes, oldest first, for upload. */
export async function completedDrafts(
  db: Db
): Promise<Array<{ id: string; site_id: string; org_unit_id: string | null; draft: WhoVaDraft }>> {
  const rows = await db.getAllAsync<{ id: string; site_id: string; org_unit_id: string | null; envelope: string }>(
    "SELECT id, site_id, org_unit_id, envelope FROM drafts WHERE completed = 1 ORDER BY updated_at",
    []
  );
  return rows.map((row) => ({
    id: row.id,
    site_id: row.site_id,
    org_unit_id: row.org_unit_id,
    draft: JSON.parse(row.envelope) as WhoVaDraft
  }));
}

export async function deleteDraft(db: Db, id: string): Promise<void> {
  await db.runAsync("DELETE FROM drafts WHERE id = ?", [id]);
}

export async function countDrafts(db: Db): Promise<number> {
  const row = await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM drafts", []);
  return row?.n ?? 0;
}

export async function getMeta<T>(db: Db, key: string): Promise<T | undefined> {
  const row = await db.getFirstAsync<{ value: string }>("SELECT value FROM meta WHERE key = ?", [key]);
  return row ? (JSON.parse(row.value) as T) : undefined;
}

export async function setMeta(db: Db, key: string, value: unknown): Promise<void> {
  await db.runAsync(
    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    [key, JSON.stringify(value)]
  );
}
