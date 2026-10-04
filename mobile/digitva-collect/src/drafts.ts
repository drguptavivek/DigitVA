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

/** Host timestamps stored beside vendor-owned WHO draft fields. */
export type DeviceTimedDraft = WhoVaDraft & {
  startedAt?: string;
  completedAt?: string;
  deviceClockAt?: string;
  locale?: string;
  translation_version?: number;
};

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
  /** A persistent upload refusal that needs interviewer attention. */
  upload_issue?: "hash_mismatch" | "answers_hash_invalid" | null;
  upload_issue_unique_id?: string | null;
  /** Server draft identity is separate from the stable local submission id. */
  server_draft_id?: string | null;
  base_updated_at?: string | null;
  draft_sync_dirty?: number;
  draft_sync_blocked?: number;
}

/** An unfinished registered-case snapshot selected for one sync attempt. */
export interface DraftSyncItem extends DraftRow {
  project_id: string;
  death_id: string;
  envelope: string;
  draft: DeviceTimedDraft;
  server_draft_id: string | null;
  base_updated_at: string | null;
  draft_sync_dirty: number;
  draft_sync_blocked: number;
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

const ROW_COLUMNS = "id, project_id, site_id, org_unit_id, completed, updated_at, death_id, unique_id, client_death_id, upload_issue, upload_issue_unique_id, server_draft_id, base_updated_at, draft_sync_dirty, draft_sync_blocked";
const LOCALE_RE = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;

/**
 * Format a date as local ISO 8601 with a numeric offset and milliseconds.
 * Defaults to the current device time; throws RangeError for an invalid date.
 */
export function localDateTimeWithOffset(date = new Date()): string {
  if (Number.isNaN(date.getTime())) throw new RangeError("invalid_device_time");
  const offsetMinutes = date.getTimezoneOffset();
  const localDate = new Date(date.getTime() - offsetMinutes * 60_000);
  const pad = (value: number, width = 2) => String(value).padStart(width, "0");
  const sign = offsetMinutes <= 0 ? "+" : "-";
  const absoluteOffset = Math.abs(offsetMinutes);
  return `${localDate.getUTCFullYear()}-${pad(localDate.getUTCMonth() + 1)}-${pad(localDate.getUTCDate())}` +
    `T${pad(localDate.getUTCHours())}:${pad(localDate.getUTCMinutes())}:${pad(localDate.getUTCSeconds())}.` +
    `${pad(localDate.getUTCMilliseconds(), 3)}${sign}${pad(Math.floor(absoluteOffset / 60))}:${pad(absoluteOffset % 60)}`;
}

function storedTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    !Number.isNaN(Date.parse(value));
}

/** Keep valid host timestamps from storage when the vendor decoder strips them. */
function envelopeWithDeviceTimes(
  draft: WhoVaDraft,
  existingEnvelope: string | null,
  startedAt: string,
  host: { locale?: string; translationVersion?: number }
): DeviceTimedDraft {
  const existing = existingEnvelope ? JSON.parse(existingEnvelope) as Record<string, unknown> : {};
  const locale = host.locale && LOCALE_RE.test(host.locale)
    ? host.locale
    : typeof existing.locale === "string" && LOCALE_RE.test(existing.locale) ? existing.locale : undefined;
  const translationVersion = typeof host.translationVersion === "number" && Number.isInteger(host.translationVersion) && host.translationVersion >= 0
    ? host.translationVersion
    : typeof existing.translation_version === "number" && Number.isInteger(existing.translation_version) && existing.translation_version >= 0
      ? existing.translation_version
      : undefined;
  return {
    ...draft,
    startedAt: storedTimestamp(existing.startedAt) ? existing.startedAt : startedAt,
    ...(storedTimestamp(existing.completedAt) ? { completedAt: existing.completedAt } : {}),
    ...(locale ? { locale } : {}),
    ...(translationVersion !== undefined ? { translation_version: translationVersion } : {})
  };
}

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
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "upload_issue")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN upload_issue TEXT");
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "upload_issue_unique_id")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN upload_issue_unique_id TEXT");
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "server_draft_id")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN server_draft_id TEXT");
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "base_updated_at")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN base_updated_at TEXT");
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "draft_sync_dirty")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN draft_sync_dirty INTEGER NOT NULL DEFAULT 1");
  }
  columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(drafts)", []);
  if (!columns.some((column) => column.name === "draft_sync_blocked")) {
    await db.execAsync("ALTER TABLE drafts ADD COLUMN draft_sync_blocked INTEGER NOT NULL DEFAULT 0");
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
    CREATE TABLE IF NOT EXISTS revision_drafts (
      draft_id TEXT PRIMARY KEY NOT NULL,
      project_id TEXT NOT NULL,
      state TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      row_json TEXT NOT NULL
    );
  `);
  for (const table of ["drafts", "cases", "registrations", "case_actions"] as const) {
    const tableColumns = await db.getAllAsync<{ name: string }>(`PRAGMA table_info(${table})`, []);
    if (!tableColumns.some((column) => column.name === "project_id")) {
      await db.execAsync(`ALTER TABLE ${table} ADD COLUMN project_id TEXT`);
    }
  }
  await db.execAsync(`
    CREATE INDEX IF NOT EXISTS ix_drafts_sync_selection
      ON drafts(project_id, id)
      WHERE completed = 0 AND death_id IS NOT NULL AND draft_sync_blocked = 0 AND upload_issue IS NULL;
    CREATE INDEX IF NOT EXISTS ix_drafts_sync_id
      ON drafts(id)
      WHERE completed = 0 AND death_id IS NOT NULL AND draft_sync_blocked = 0 AND upload_issue IS NULL;
    CREATE INDEX IF NOT EXISTS ix_drafts_case_lookup
      ON drafts(death_id, updated_at DESC, id)
      WHERE death_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS ix_revision_drafts_sync
      ON revision_drafts(state, draft_id);
  `);
  // Legacy downloaded cases have no safe project assignment. They can be
  // fetched again from the authoritative project list; retaining them could
  // expose a contact under the wrong project after a multi-project upgrade.
  await db.runAsync("DELETE FROM cases WHERE project_id IS NULL", []);
}

/**
 * The form's draft store for one interview. `host` supplies the site, unit
 * and case binding on the first save; later saves update the envelope and
 * clear an editable hash issue, so a draft never moves site or case.
 */
export function createDraftStore(
  db: Db,
  host: { projectId: string; siteId: string; orgUnitId?: string | null; binding?: DraftBinding; locale?: string; translationVersion?: number }
): WhoVaDraftStore {
  const binding = host.binding ?? { projectId: host.projectId };
  if (binding.projectId !== host.projectId) throw new Error("project_mismatch");
  const openedAt = localDateTimeWithOffset();
  return {
    async save(draft) {
      const existing = await db.getFirstAsync<{ project_id: string | null; envelope: string }>(
        "SELECT project_id, envelope FROM drafts WHERE id = ?",
        [draft.id]
      );
      if (existing && existing.project_id !== host.projectId) throw new Error("project_mismatch");
      const envelope = JSON.stringify(envelopeWithDeviceTimes(draft, existing?.envelope ?? null, openedAt, host));
      const params = [
          draft.id,
          host.projectId,
          host.siteId,
          host.orgUnitId ?? null,
          draft.updatedAt,
          envelope,
          binding.deathId ?? null,
          binding.uniqueId ?? null,
          binding.clientDeathId ?? null,
          binding.prefill === undefined ? null : JSON.stringify(binding.prefill)
        ];
      const result = existing
        ? await db.runAsync(
            `UPDATE drafts SET envelope = ?, updated_at = ?, draft_sync_dirty = 1,
               upload_issue = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue END,
               upload_issue_unique_id = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue_unique_id END
             WHERE id = ? AND envelope = ?`,
            [envelope, draft.updatedAt, draft.id, existing.envelope]
          )
        : await db.runAsync(
            `INSERT INTO drafts (id, project_id, site_id, org_unit_id, updated_at, envelope, death_id, unique_id, client_death_id, prefill)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(id) DO NOTHING`,
            params
          );
      if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) {
        throw new Error("draft_conflict");
      }
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

/** Unfinished registered-case drafts that are eligible for device sync. */
export async function unfinishedDraftsForSync(
  db: Db,
  projectId?: string,
  afterId?: string,
  limit = 100,
): Promise<DraftSyncItem[]> {
  const pageSize = Math.max(1, Math.min(200, Math.trunc(limit) || 100));
  const filters = [
    "completed = 0",
    "project_id IS NOT NULL",
    "death_id IS NOT NULL",
    "draft_sync_blocked = 0",
    "upload_issue IS NULL",
    ...(projectId ? ["project_id = ?"] : []),
    ...(afterId ? ["id > ?"] : [])
  ];
  const params: Bind[] = [
    ...(projectId ? [projectId] : []),
    ...(afterId ? [afterId] : []),
    pageSize
  ];
  const rows = await db.getAllAsync<Omit<DraftSyncItem, "draft">>(
    `SELECT ${ROW_COLUMNS}, envelope FROM drafts
     WHERE ${filters.join(" AND ")} ORDER BY id LIMIT ?`,
    params
  );
  return rows.map((row) => ({ ...row, draft: JSON.parse(row.envelope) as DeviceTimedDraft }));
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
      `SELECT ${ROW_COLUMNS} FROM drafts WHERE death_id = ? ORDER BY updated_at DESC, id LIMIT 1`,
      [key.deathId]
    );
  }
  if (!key.clientDeathId) return null;
  return db.getFirstAsync<DraftRow>(
    `SELECT ${ROW_COLUMNS} FROM drafts WHERE client_death_id = ? ORDER BY updated_at DESC`,
    [key.clientDeathId]
  );
}

/** Save the verdict and completion time, clearing editable hash issues but preserving hash mismatches. */
export async function markCompleted(db: Db, id: string, completion: Completion): Promise<void> {
  const current = await db.getFirstAsync<{ envelope: string; upload_issue: string | null }>(
    "SELECT envelope, upload_issue FROM drafts WHERE id = ?",
    [id]
  );
  if (!current || current.upload_issue === "hash_mismatch") return;
  const draft = JSON.parse(current.envelope) as Record<string, unknown>;
  const envelope = JSON.stringify({ ...draft, completedAt: localDateTimeWithOffset() });
  const result = await db.runAsync(`UPDATE drafts SET
    envelope = ?, completed = 1, completion = ?,
    upload_issue = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue END,
    upload_issue_unique_id = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue_unique_id END
    WHERE id = ? AND envelope = ? AND upload_issue IS NOT 'hash_mismatch'`, [
    envelope,
    JSON.stringify({ valid: completion.valid, issues: completion.issues }),
    id,
    current.envelope
  ]);
  if (result && typeof result === "object" && "changes" in result && Number(result.changes) > 0) return;
  const latest = await db.getFirstAsync<{ upload_issue: string | null }>("SELECT upload_issue FROM drafts WHERE id = ?", [id]);
  if (latest?.upload_issue !== "hash_mismatch") throw new Error("draft_conflict");
}

/** Persist an upload refusal while retaining the interview and its answers. */
export async function setDraftUploadIssue(
  db: Db,
  id: string,
  issue: "hash_mismatch" | "answers_hash_invalid",
  uniqueId?: string,
): Promise<void> {
  await db.runAsync(`UPDATE drafts SET upload_issue = ?, upload_issue_unique_id = ?,
    completed = CASE WHEN ? = 'answers_hash_invalid' THEN 0 ELSE completed END
    WHERE id = ?`, [issue, issue === "hash_mismatch" ? uniqueId ?? null : null, issue, id]);
}

/**
 * Back to in progress, answers kept: the server refused the interview as it
 * stands (422), so the interviewer must be able to open and correct it
 * rather than have it resent and refused on every sync.
 */
export async function reopenDraft(db: Db, id: string): Promise<void> {
  await db.runAsync("UPDATE drafts SET completed = 0, completion = NULL, draft_sync_dirty = 1 WHERE id = ?", [id]);
}

export interface CompletedDraft {
  id: string;
  project_id: string | null;
  site_id: string;
  org_unit_id: string | null;
  death_id: string | null;
  client_death_id: string | null;
  draft: DeviceTimedDraft;
  completion: Completion | null;
  envelope: string;
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
     FROM drafts WHERE completed = 1 AND upload_issue IS NULL${projectId ? " AND project_id = ?" : ""} ORDER BY updated_at`,
    projectId ? [projectId] : []
  );
  return rows.map((row) => ({
    id: row.id,
    project_id: row.project_id,
    site_id: row.site_id,
    org_unit_id: row.org_unit_id,
    death_id: row.death_id,
    client_death_id: row.client_death_id,
    draft: JSON.parse(row.envelope) as DeviceTimedDraft,
    completion: row.completion ? (JSON.parse(row.completion) as Completion) : null,
    envelope: row.envelope
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

/** Delete only the exact envelope sent, preserving edits made during upload. */
export async function deleteDraftSnapshot(db: Db, id: string, envelope: string): Promise<boolean> {
  const result = await db.runAsync("DELETE FROM drafts WHERE id = ? AND envelope = ?", [id, envelope]);
  return !!result && typeof result === "object" && "changes" in result && Number(result.changes) > 0;
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
     UNION SELECT project_id FROM revision_drafts
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
  await db.runAsync("DELETE FROM revision_drafts WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM cases WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM registrations WHERE project_id = ?", [projectId]);
  await db.runAsync("DELETE FROM case_actions WHERE project_id = ?", [projectId]);
}
