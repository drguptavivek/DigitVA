/**
 * Draft rows in one interviewer's database, and the WhoVaDraftStore the form
 * writes through.
 *
 * The WHO draft envelope is stored whole; host metadata the server needs to
 * route it (site, unit, completed flag) lives in its own columns, outside the
 * WHO answers. The device keeps in-flight interviews only: a row is deleted
 * once the server acknowledges it (push and purge).
 */
import type { ValidationIssue, WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

type Bind = string | number | null;

/** The subset of expo-sqlite's SQLiteDatabase this app uses. */
export interface Db {
  execAsync(source: string): Promise<void>;
  runAsync(source: string, params: Bind[]): Promise<unknown>;
  getAllAsync<T>(source: string, params: Bind[]): Promise<T[]>;
  getFirstAsync<T>(source: string, params: Bind[]): Promise<T | null>;
  closeAsync(): Promise<void>;
}

/** The form engine's verdict when the interviewer finished, sent with the upload. */
export interface Completion {
  valid: boolean;
  issues: ValidationIssue[];
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
  // v1: the completion verdict. SQLite has no ADD COLUMN IF NOT EXISTS.
  const columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((c) => c.name === "completion")) {
    await db.execAsync(`
      ALTER TABLE drafts ADD COLUMN completion TEXT;
      UPDATE drafts SET completion = '{"valid":true,"issues":[]}' WHERE completed = 1;
    `);
    // Before v1 only a form-valid interview could be marked completed.
  }
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

export async function markCompleted(db: Db, id: string, completion: Completion): Promise<void> {
  await db.runAsync("UPDATE drafts SET completed = 1, completion = ? WHERE id = ?", [
    JSON.stringify({ valid: completion.valid, issues: completion.issues }),
    id
  ]);
}

/**
 * Back to in progress, answers kept: the server refused the interview as it
 * stands (422), so the interviewer must be able to open and correct it
 * rather than have it resent and refused on every sync.
 */
export async function reopenDraft(db: Db, id: string): Promise<void> {
  await db.runAsync("UPDATE drafts SET completed = 0, completion = NULL WHERE id = ?", [id]);
}

export interface CompletedDraft {
  id: string;
  site_id: string;
  org_unit_id: string | null;
  draft: WhoVaDraft;
  completion: Completion | null;
}

/** Completed drafts with their envelopes and verdicts, oldest first, for upload. */
export async function completedDrafts(db: Db): Promise<CompletedDraft[]> {
  const rows = await db.getAllAsync<{
    id: string;
    site_id: string;
    org_unit_id: string | null;
    envelope: string;
    completion: string | null;
  }>(
    "SELECT id, site_id, org_unit_id, envelope, completion FROM drafts WHERE completed = 1 ORDER BY updated_at",
    []
  );
  return rows.map((row) => ({
    id: row.id,
    site_id: row.site_id,
    org_unit_id: row.org_unit_id,
    draft: JSON.parse(row.envelope) as WhoVaDraft,
    completion: row.completion ? (JSON.parse(row.completion) as Completion) : null
  }));
}

/** Every draft id on the phone (the outstanding-work report). */
export async function draftIds(db: Db): Promise<string[]> {
  const rows = await db.getAllAsync<{ id: string }>("SELECT id FROM drafts ORDER BY id", []);
  return rows.map((row) => row.id);
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
