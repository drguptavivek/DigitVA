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
  project_id: string | null;
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
  projectId: string;
  deathId?: string | null;
  uniqueId?: string | null;
  clientDeathId?: string | null;
  /** The prefill it starts from (src/cases.ts Prefill), kept for later opens. */
  prefill?: unknown;
}

const ROW_COLUMNS = "id, project_id, site_id, org_unit_id, completed, updated_at, death_id, unique_id, client_death_id";

export function projectMetaKey(projectId: string, key: string): string {
  return `project:${projectId}:${key}`;
}

export async function migrate(db: Db): Promise<void> {
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS drafts (
      id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT,
      site_id TEXT NOT NULL,
      org_unit_id TEXT,
      completed INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      envelope TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
  `);
  // v1: the completion verdict. SQLite has no ADD COLUMN IF NOT EXISTS.
  let columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((c) => c.name === "completion")) {
    await db.execAsync(`
      ALTER TABLE drafts ADD COLUMN completion TEXT;
      UPDATE drafts SET completion = '{"valid":true,"issues":[]}' WHERE completed = 1;
    `);
    // Before v1 only a form-valid interview could be marked completed.
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
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
      project_id TEXT,
      position INTEGER NOT NULL,
      row TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS registrations (
      client_death_id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT,
      site_id TEXT NOT NULL,
      org_unit_id TEXT,
      fields TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS case_actions (
      client_id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT,
      kind TEXT NOT NULL,
      death_id TEXT,
      client_death_id TEXT,
      body TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL
    );
  `);
  for (const table of ["drafts", "cases", "registrations", "case_actions"] as const) {
    const tableColumns = await db.getAllAsync<{ name: string }>(`PRAGMA table_info(${table})`, []);
    if (!tableColumns.some((column) => column.name === "project_id")) {
      await db.execAsync(`ALTER TABLE ${table} ADD COLUMN project_id TEXT`);
    }
  }
  // Legacy downloaded cases have no safe project assignment. They can be
  // fetched again from the authoritative project list; retaining them could
  // expose a contact under the wrong project after a multi-project upgrade.
  await db.runAsync("DELETE FROM cases WHERE project_id IS NULL", []);
}

/**
 * The form's draft store for one interview. `host` supplies the site, unit
 * and case binding on the first save; later saves update only the envelope,
 * so a draft never moves site or case.
 */
export function createDraftStore(
  db: Db,
  host: { projectId: string; siteId: string; orgUnitId?: string | null; binding?: DraftBinding }
): WhoVaDraftStore {
  const binding = host.binding ?? { projectId: host.projectId };
  if (binding.projectId !== host.projectId) throw new Error("project_mismatch");
  return {
    async save(draft) {
      const existing = await db.getFirstAsync<{ project_id: string | null }>(
        "SELECT project_id FROM drafts WHERE id = ?",
        [draft.id]
      );
      if (existing && existing.project_id !== host.projectId) throw new Error("project_mismatch");
      await db.runAsync(
        `INSERT INTO drafts (id, project_id, site_id, org_unit_id, updated_at, envelope, death_id, unique_id, client_death_id, prefill)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET envelope = excluded.envelope, updated_at = excluded.updated_at`,
        [
          draft.id,
          host.projectId,
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
  project_id: string | null;
  site_id: string;
  org_unit_id: string | null;
  death_id: string | null;
  client_death_id: string | null;
  draft: WhoVaDraft;
  completion: Completion | null;
}

/** Completed drafts with their envelopes and verdicts, oldest first, for upload. */
export async function completedDrafts(db: Db, projectId?: string): Promise<CompletedDraft[]> {
  const rows = await db.getAllAsync<{
    id: string;
    project_id: string | null;
    site_id: string;
    org_unit_id: string | null;
    death_id: string | null;
    client_death_id: string | null;
    envelope: string;
    completion: string | null;
  }>(
    `SELECT id, project_id, site_id, org_unit_id, death_id, client_death_id, envelope, completion
     FROM drafts WHERE completed = 1${projectId ? " AND project_id = ?" : ""} ORDER BY updated_at`,
    projectId ? [projectId] : []
  );
  return rows.map((row) => ({
    id: row.id,
    project_id: row.project_id,
    site_id: row.site_id,
    org_unit_id: row.org_unit_id,
    death_id: row.death_id,
    client_death_id: row.client_death_id,
    draft: JSON.parse(row.envelope) as WhoVaDraft,
    completion: row.completion ? (JSON.parse(row.completion) as Completion) : null
  }));
}

/** Every draft id on the phone (the outstanding-work report). */
export async function draftIds(db: Db, projectId?: string): Promise<string[]> {
  const rows = await db.getAllAsync<{ id: string }>(
    projectId ? "SELECT id FROM drafts WHERE project_id = ? ORDER BY id" : "SELECT id FROM drafts ORDER BY id",
    projectId ? [projectId] : []
  );
  return rows.map((row) => row.id);
}

/** Case ids of the drafts bound to a server case (the outstanding-work report). */
export async function draftUniqueIds(db: Db, projectId?: string): Promise<string[]> {
  const rows = await db.getAllAsync<{ unique_id: string }>(
    projectId
      ? "SELECT DISTINCT unique_id FROM drafts WHERE project_id = ? AND unique_id IS NOT NULL ORDER BY unique_id"
      : "SELECT DISTINCT unique_id FROM drafts WHERE unique_id IS NOT NULL ORDER BY unique_id",
    projectId ? [projectId] : []
  );
  return rows.map((row) => row.unique_id);
}

export async function deleteDraft(db: Db, id: string): Promise<void> {
  await db.runAsync("DELETE FROM drafts WHERE id = ?", [id]);
}

export async function countDrafts(db: Db, projectId?: string): Promise<number> {
  const row = await db.getFirstAsync<{ n: number }>(
    projectId ? "SELECT COUNT(*) AS n FROM drafts WHERE project_id = ?" : "SELECT COUNT(*) AS n FROM drafts",
    projectId ? [projectId] : []
  );
  return row?.n ?? 0;
}

export async function getMeta<T>(db: Db, key: string, projectId?: string): Promise<T | undefined> {
  const storedKey = projectId ? projectMetaKey(projectId, key) : key;
  const row = await db.getFirstAsync<{ value: string }>("SELECT value FROM meta WHERE key = ?", [storedKey]);
  return row ? (JSON.parse(row.value) as T) : undefined;
}

export async function setMeta(db: Db, key: string, value: unknown, projectId?: string): Promise<void> {
  const storedKey = projectId ? projectMetaKey(projectId, key) : key;
  await db.runAsync(
    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    [storedKey, JSON.stringify(value)]
  );
}

export async function projectIds(db: Db): Promise<string[]> {
  const rows = await db.getAllAsync<{ project_id: string }>(
    `SELECT project_id FROM drafts WHERE project_id IS NOT NULL
     UNION SELECT project_id FROM cases WHERE project_id IS NOT NULL
     UNION SELECT project_id FROM registrations WHERE project_id IS NOT NULL
     UNION SELECT project_id FROM case_actions WHERE project_id IS NOT NULL
     ORDER BY project_id`,
    []
  );
  const metadata = await db.getAllAsync<{ key: string; value?: string }>(
    "SELECT key, value FROM meta WHERE key LIKE 'project:%' OR key LIKE 'draft-config:%'",
    []
  );
  const ids = new Set(rows.map((row) => row.project_id));
  for (const { key } of metadata) {
    const match = /^project:([^:]+):/.exec(key);
    if (match) ids.add(match[1]);
  }
  for (const { value } of metadata) {
    if (!value) continue;
    try {
      const parsed = JSON.parse(value) as { projectId?: unknown; project_id?: unknown };
      const projectId = parsed.projectId ?? parsed.project_id;
      if (typeof projectId === "string" && projectId) ids.add(projectId);
    } catch {
      // A malformed draft config is not an authorization source.
    }
  }
  return [...ids].sort();
}

/** Remove one project's local data and project-scoped metadata only. */
export async function purgeProjectData(db: Db, projectId: string): Promise<void> {
  const configs = await db.getAllAsync<{ key: string; value: string }>(
    "SELECT key, value FROM meta WHERE key LIKE 'draft-config:%'",
    []
  );
  for (const config of configs) {
    let parsed: { projectId?: unknown; project_id?: unknown } | null;
    try {
      parsed = JSON.parse(config.value) as { projectId?: unknown; project_id?: unknown };
    } catch {
      // Leave malformed unrelated metadata untouched; it is not project data.
      continue;
    }
    if (parsed && typeof parsed === "object" && (parsed.projectId === projectId || parsed.project_id === projectId)) {
      // Storage errors must surface; a failed delete cannot be treated as an
      // invalid JSON value or the revoked config would survive the purge.
      await db.runAsync("DELETE FROM meta WHERE key = ?", [config.key]);
    }
  }
  await db.runAsync(
    `DELETE FROM meta
     WHERE key LIKE ?
        OR key IN (SELECT 'draft-config:' || id FROM drafts WHERE project_id = ?)`,
    [`project:${projectId}:%`, projectId]
  );
  await db.runAsync("DELETE FROM drafts WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM cases WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM registrations WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM case_actions WHERE project_id = ?", [projectId]);
}
