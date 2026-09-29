/**
 * Draft rows in one interviewer's database, and the WhoVaDraftStore the form
 * writes through.
 *
 * The WHO draft envelope is stored whole; host metadata the server needs to
 * route it (site, unit, completed flag, the case it belongs to and the
 * prefill it started from) lives in its own columns, outside the WHO
 * answers. A draft keeps its own case binding, so pruning a downloaded case
 * (src/cases.ts) never strands it. The device keeps in-flight interviews
 * only: a row is deleted once the server acknowledges it (push and purge).
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
  /** The server case, once known (a downloaded case, or a registration the server acknowledged). */
  death_id: string | null;
  unique_id: string | null;
  /** An offline registration not yet acknowledged; the draft waits for it. */
  client_death_id: string | null;
}

/** The case a new draft belongs to, written on its first save. */
export interface DraftBinding {
  deathId?: string | null;
  uniqueId?: string | null;
  clientDeathId?: string | null;
  /** The prefill it starts from (src/cases.ts Prefill), kept for later opens. */
  prefill?: unknown;
}

const ROW_COLUMNS = "id, site_id, org_unit_id, completed, updated_at, death_id, unique_id, client_death_id";

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
  // v2 (phase 3): the case binding and the offline case tables.
  if (!columns.some((c) => c.name === "death_id")) {
    await db.execAsync(`
      ALTER TABLE drafts ADD COLUMN death_id TEXT;
      ALTER TABLE drafts ADD COLUMN unique_id TEXT;
      ALTER TABLE drafts ADD COLUMN client_death_id TEXT;
      ALTER TABLE drafts ADD COLUMN prefill TEXT;
    `);
  }
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS cases (
      death_id TEXT PRIMARY KEY NOT NULL,
      position INTEGER NOT NULL,
      row TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS registrations (
      client_death_id TEXT PRIMARY KEY NOT NULL,
      site_id TEXT NOT NULL,
      org_unit_id TEXT,
      fields TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS case_actions (
      client_id TEXT PRIMARY KEY NOT NULL,
      kind TEXT NOT NULL,
      death_id TEXT,
      client_death_id TEXT,
      body TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL
    );
  `);
}

/**
 * The form's draft store for one interview. `host` supplies the site, unit
 * and case binding on the first save; later saves update only the envelope,
 * so a draft never moves site or case.
 */
export function createDraftStore(
  db: Db,
  host: { siteId: string; orgUnitId?: string | null; binding?: DraftBinding }
): WhoVaDraftStore {
  const binding = host.binding ?? {};
  return {
    async save(draft) {
      await db.runAsync(
        `INSERT INTO drafts (id, site_id, org_unit_id, updated_at, envelope, death_id, unique_id, client_death_id, prefill)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET envelope = excluded.envelope, updated_at = excluded.updated_at`,
        [
          draft.id,
          host.siteId,
          host.orgUnitId ?? null,
          draft.updatedAt,
          JSON.stringify(draft),
          binding.deathId ?? null,
          binding.uniqueId ?? null,
          binding.clientDeathId ?? null,
          binding.prefill === undefined ? null : JSON.stringify(binding.prefill)
        ]
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
  return db.getAllAsync<DraftRow>(`SELECT ${ROW_COLUMNS} FROM drafts ORDER BY updated_at DESC`, []);
}

export async function getDraftRow(db: Db, id: string): Promise<DraftRow | null> {
  return db.getFirstAsync<DraftRow>(`SELECT ${ROW_COLUMNS} FROM drafts WHERE id = ?`, [id]);
}

/** The prefill a draft started from, or undefined. */
export async function getDraftPrefill<T>(db: Db, id: string): Promise<T | undefined> {
  const row = await db.getFirstAsync<{ prefill: string | null }>("SELECT prefill FROM drafts WHERE id = ?", [id]);
  return row?.prefill ? (JSON.parse(row.prefill) as T) : undefined;
}

/** The newest local draft on a case (by server id or offline registration id), to resume instead of starting another. */
export async function draftForCase(db: Db, key: { deathId?: string; clientDeathId?: string }): Promise<DraftRow | null> {
  if (key.deathId) {
    return db.getFirstAsync<DraftRow>(
      `SELECT ${ROW_COLUMNS} FROM drafts WHERE death_id = ? ORDER BY updated_at DESC`,
      [key.deathId]
    );
  }
  if (!key.clientDeathId) return null;
  return db.getFirstAsync<DraftRow>(
    `SELECT ${ROW_COLUMNS} FROM drafts WHERE client_death_id = ? ORDER BY updated_at DESC`,
    [key.clientDeathId]
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
  death_id: string | null;
  client_death_id: string | null;
  draft: WhoVaDraft;
  completion: Completion | null;
}

/** Completed drafts with their envelopes and verdicts, oldest first, for upload. */
export async function completedDrafts(db: Db): Promise<CompletedDraft[]> {
  const rows = await db.getAllAsync<{
    id: string;
    site_id: string;
    org_unit_id: string | null;
    death_id: string | null;
    client_death_id: string | null;
    envelope: string;
    completion: string | null;
  }>(
    `SELECT id, site_id, org_unit_id, death_id, client_death_id, envelope, completion
     FROM drafts WHERE completed = 1 ORDER BY updated_at`,
    []
  );
  return rows.map((row) => ({
    id: row.id,
    site_id: row.site_id,
    org_unit_id: row.org_unit_id,
    death_id: row.death_id,
    client_death_id: row.client_death_id,
    draft: JSON.parse(row.envelope) as WhoVaDraft,
    completion: row.completion ? (JSON.parse(row.completion) as Completion) : null
  }));
}

/** Every draft id on the phone (the outstanding-work report). */
export async function draftIds(db: Db): Promise<string[]> {
  const rows = await db.getAllAsync<{ id: string }>("SELECT id FROM drafts ORDER BY id", []);
  return rows.map((row) => row.id);
}

/** Case ids of the drafts bound to a server case (the outstanding-work report). */
export async function draftUniqueIds(db: Db): Promise<string[]> {
  const rows = await db.getAllAsync<{ unique_id: string }>(
    "SELECT DISTINCT unique_id FROM drafts WHERE unique_id IS NOT NULL ORDER BY unique_id",
    []
  );
  return rows.map((row) => row.unique_id);
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
