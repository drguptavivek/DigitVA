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
import { reduceNationalIdData, type SubmissionData, type ValidationIssue, type WhoVaDraft, type WhoVaDraftStore } from "@drguptavivek/who-2022-va";
import { deleteCoveredAttachments, pruneUnreferencedAttachments } from "./attachmentStore";
import { readDefinitionPin, withDefinitionPin, type DefinitionPin } from "./formDefinitionRuntime";
import { createNativeDefinitionCache } from "./formDefinitionCache";
import { runInTransaction } from "./dbTransaction";
import { clearSendError, sendRefusal } from "./unsentWork";
import { localDateTimeWithOffset } from "./client/localDateTime";

export { localDateTimeWithOffset } from "./client/localDateTime";

type Bind = string | number | null | Uint8Array;

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
  definitionSha256?: unknown;
  definitionExtensions?: unknown;
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
  upload_issue?: "answers_hash_invalid" | "invalid_definition_pin" | "demo_limit" | "case_conflict" | null;
  upload_issue_unique_id?: string | null;
  /** Server draft identity is separate from the stable local submission id. */
  server_draft_id?: string | null;
  base_updated_at?: string | null;
  draft_sync_dirty?: number;
  draft_sync_blocked?: number;
  /** The envelope's startedAt / completedAt, read by listDrafts for the Interviews list. */
  started_at?: string | null;
  completed_at?: string | null;
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
const projectStoreGenerations = new WeakMap<Db, Map<string, number>>();
const projectStoreWrites = new WeakMap<Db, Map<string, Set<Promise<unknown>>>>();

/** A mounted form's lease on project-local storage; revocation makes it stale synchronously. */
export interface ProjectStoreGuard {
  assertCurrent(): void;
  runWrite<T>(operation: () => Promise<T>): Promise<T>;
}

export function createProjectStoreGuard(db: Db, projectId: string): ProjectStoreGuard {
  const generation = projectStoreGenerations.get(db)?.get(projectId) ?? 0;
  const assertCurrent = () => {
    if ((projectStoreGenerations.get(db)?.get(projectId) ?? 0) !== generation) {
      throw new Error("project_access_revoked");
    }
  };
  return {
    assertCurrent,
    runWrite<T>(operation: () => Promise<T>): Promise<T> {
      assertCurrent();
      let byProject = projectStoreWrites.get(db);
      if (!byProject) {
        byProject = new Map();
        projectStoreWrites.set(db, byProject);
      }
      let active = byProject.get(projectId);
      if (!active) {
        active = new Set();
        byProject.set(projectId, active);
      }
      const pending = operation();
      active.add(pending);
      void pending.finally(() => {
        active?.delete(pending);
        if (active?.size === 0) byProject?.delete(projectId);
      }).catch(() => undefined);
      return pending;
    },
  };
}

/** Invalidate every store mounted before project access was revoked. */
export function invalidateProjectStoreGeneration(db: Db, projectId: string): void {
  let byProject = projectStoreGenerations.get(db);
  if (!byProject) {
    byProject = new Map();
    projectStoreGenerations.set(db, byProject);
  }
  byProject.set(projectId, (byProject.get(projectId) ?? 0) + 1);
}

async function waitForProjectStoreWrites(db: Db, projectId: string): Promise<void> {
  while (true) {
    const active = projectStoreWrites.get(db)?.get(projectId);
    if (!active?.size) return;
    await Promise.allSettled([...active]);
  }
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
  host: { locale?: string; translationVersion?: number; definitionPin?: DefinitionPin | null }
): DeviceTimedDraft {
  const existing = existingEnvelope ? JSON.parse(existingEnvelope) as Record<string, unknown> : {};
  if (typeof existing.instrumentVersion === "string" && existing.instrumentVersion !== draft.instrumentVersion) {
    throw new Error("instrument_incompatible");
  }
  const existingPin = readDefinitionPin(existing);
  const suppliedPin = host.definitionPin
    ? readDefinitionPin({
        instrumentVersion: host.definitionPin.instrumentVersion,
        definitionSha256: host.definitionPin.definitionSha256,
        definitionExtensions: host.definitionPin.definitionExtensions,
      })
    : null;
  if (suppliedPin && suppliedPin.instrumentVersion !== draft.instrumentVersion) {
    throw new Error("instrument_incompatible");
  }
  if (existingPin && suppliedPin && (
    existingPin.instrumentVersion !== suppliedPin.instrumentVersion ||
    existingPin.definitionSha256 !== suppliedPin.definitionSha256 ||
    existingPin.definitionExtensions.some((name, index) => name !== suppliedPin.definitionExtensions[index])
  )) throw new Error("instrument_incompatible");
  const pin = existingPin ?? suppliedPin;
  const locale = host.locale && LOCALE_RE.test(host.locale)
    ? host.locale
    : typeof existing.locale === "string" && LOCALE_RE.test(existing.locale) ? existing.locale : undefined;
  const translationVersion = typeof host.translationVersion === "number" && Number.isInteger(host.translationVersion) && host.translationVersion >= 0
    ? host.translationVersion
    : typeof existing.translation_version === "number" && Number.isInteger(existing.translation_version) && existing.translation_version >= 0
      ? existing.translation_version
      : undefined;
  const saved: DeviceTimedDraft = {
    ...draft,
    startedAt: storedTimestamp(existing.startedAt) ? existing.startedAt : startedAt,
    ...(storedTimestamp(existing.completedAt) ? { completedAt: existing.completedAt } : {}),
    ...(locale ? { locale } : {}),
    ...(translationVersion !== undefined ? { translation_version: translationVersion } : {}),
  };
  if (pin) return withDefinitionPin(saved, pin) as DeviceTimedDraft;
  return {
    ...saved,
    ...(Object.prototype.hasOwnProperty.call(existing, "definitionSha256")
      ? { definitionSha256: existing.definitionSha256 }
      : {}),
    ...(Object.prototype.hasOwnProperty.call(existing, "definitionExtensions")
      ? { definitionExtensions: existing.definitionExtensions }
      : {}),
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
  // Older clients blocked a resend after a 409 that the server no longer sends.
  await db.runAsync(
    "UPDATE drafts SET upload_issue = NULL, upload_issue_unique_id = NULL WHERE upload_issue = ?",
    ["hash_mismatch"],
  );
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
  // Local error log (src/errorLog.ts): support reference lines only, capped by src/errorLogDb.ts.
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS error_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      at TEXT NOT NULL,
      app_version TEXT NOT NULL,
      route TEXT NOT NULL,
      what TEXT NOT NULL,
      device TEXT NOT NULL,
      android TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_error_log_at ON error_log(at);
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
  // Captured files (src/attachmentStore.ts): BLOBs inside the encrypted store, so they are encrypted and wiped with it.
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS attachments (
      id TEXT PRIMARY KEY NOT NULL,
      draft_id TEXT NOT NULL,
      project_id TEXT,
      question TEXT NOT NULL,
      kind TEXT NOT NULL,
      mime_type TEXT NOT NULL,
      ext TEXT NOT NULL,
      size_bytes INTEGER NOT NULL,
      duration_ms INTEGER,
      created_at TEXT NOT NULL,
      uploaded_at TEXT,
      data BLOB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_attachments_draft ON attachments(draft_id);
  `);
  // A file captured for a draft that was never saved has no owner to send or delete it.
  await db.runAsync("DELETE FROM attachments WHERE draft_id NOT IN (SELECT id FROM drafts)", []);
  // Legacy downloaded cases have no safe project assignment. They can be
  // fetched again from the authoritative project list; retaining them could
  // expose a contact under the wrong project after a multi-project upgrade.
  await db.runAsync("DELETE FROM cases WHERE project_id IS NULL", []);
  // Offline coding (Collect Plus phase 1): the certificate and the on-device
  // DORIS results for one interview, kept until a future sync phase. The
  // device and coder-profile references let that sync attribute records
  // without ever holding the profile itself. client_draft_id's UNIQUE
  // constraint indexes the case lookup the coding screen list does.
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS offline_coding (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      client_draft_id TEXT NOT NULL UNIQUE,
      certificate TEXT NOT NULL,
      result TEXT,
      codedit_result TEXT,
      process_token TEXT NOT NULL,
      certificate_digest TEXT,
      result_digest TEXT,
      ucod_code TEXT,
      ucod_uri TEXT,
      status TEXT NOT NULL CHECK (status IN ('draft','coded','rejected')),
      coder_profile_updated_at TEXT,
      device_uuid TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_offline_coding_draft ON offline_coding(client_draft_id);
  `);
}

/**
 * The form's draft store for one interview. `host` supplies the site, unit
 * and case binding on the first save; later saves update the envelope and
 * clear an editable hash issue, so a draft never moves site or case.
 */
export function createDraftStore(
  db: Db,
  host: { projectId: string; siteId: string; orgUnitId?: string | null; binding?: DraftBinding; locale?: string; translationVersion?: number; definitionPin?: DefinitionPin | null }
): WhoVaDraftStore {
  const binding = host.binding ?? { projectId: host.projectId };
  if (binding.projectId !== host.projectId) throw new Error("project_mismatch");
  const guard = createProjectStoreGuard(db, host.projectId);
  const openedAt = localDateTimeWithOffset();
  return {
    async save(rawDraft) {
      // The full national ID never persists on the device (the form already
      // reduces it; this covers a host that hands over an unreduced draft).
      const draft = { ...rawDraft, data: reduceNationalIdData(rawDraft.data) };
      return guard.runWrite(async () => {
        guard.assertCurrent();
        const existing = await db.getFirstAsync<{ project_id: string | null; envelope: string }>(
          "SELECT project_id, envelope FROM drafts WHERE id = ?",
          [draft.id]
        );
        guard.assertCurrent();
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
        guard.assertCurrent();
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
        guard.assertCurrent();
        if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) {
          throw new Error("draft_conflict");
        }
      });
    },
    async load(id) {
      guard.assertCurrent();
      const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [id]);
      guard.assertCurrent();
      return row ? (JSON.parse(row.envelope) as WhoVaDraft) : undefined;
    },
    async remove(id) {
      await guard.runWrite(async () => {
        guard.assertCurrent();
        await deleteDraft(db, id);
        guard.assertCurrent();
      });
    }
  };
}

/** Newest first; metadata only, never answers. */
export function listDrafts(db: Db): Promise<DraftRow[]> {
  return db.getAllAsync<DraftRow>(`SELECT ${ROW_COLUMNS}, json_extract(envelope, '$.startedAt') AS started_at, json_extract(envelope, '$.completedAt') AS completed_at FROM drafts ORDER BY updated_at DESC`, []);
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

/**
 * Remove covered answers from the stored draft and its stored prefill (a refusal was just recorded), so no
 * copy on the phone, and nothing synced from it, holds them. Marks the draft for the next sync.
 */
export async function stripDraftCovered(db: Db, id: string, covered: readonly string[]): Promise<void> {
  const row = await db.getFirstAsync<{ envelope: string; prefill: string | null }>("SELECT envelope, prefill FROM drafts WHERE id = ?", [id]);
  if (!row || !covered.length) return;
  // The files of covered questions go with their answers: a refusal leaves no copy on the phone.
  await deleteCoveredAttachments(db, id, covered);
  const strip = (value: unknown): unknown => (value && typeof value === "object" && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).filter(([name]) => !covered.includes(name))) : value);
  const envelope = JSON.parse(row.envelope) as { data?: unknown };
  const prefill = row.prefill ? (JSON.parse(row.prefill) as { answers?: unknown }) : undefined;
  if (envelope.data) envelope.data = strip(envelope.data);
  if (prefill?.answers) prefill.answers = strip(prefill.answers);
  await db.runAsync("UPDATE drafts SET envelope = ?, prefill = ?, draft_sync_dirty = 1 WHERE id = ?", [
    JSON.stringify(envelope),
    prefill ? JSON.stringify(prefill) : null,
    id,
  ]);
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

/** Save the verdict and completion time, clearing a previous editable hash issue. */
export async function markCompleted(db: Db, id: string, completion: Completion): Promise<void> {
  const current = await db.getFirstAsync<{ envelope: string }>(
    "SELECT envelope FROM drafts WHERE id = ?",
    [id]
  );
  if (!current) return;
  const draft = JSON.parse(current.envelope) as Record<string, unknown>;
  // A draft saved before the reduction existed still holds the full number.
  if (draft.data && typeof draft.data === "object") draft.data = reduceNationalIdData(draft.data as SubmissionData);
  const envelope = JSON.stringify({ ...draft, completedAt: localDateTimeWithOffset() });
  const result = await db.runAsync(`UPDATE drafts SET
    envelope = ?, completed = 1, completion = ?,
    upload_issue = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue END,
    upload_issue_unique_id = CASE WHEN upload_issue = 'answers_hash_invalid' THEN NULL ELSE upload_issue_unique_id END
    WHERE id = ? AND envelope = ?`, [
    envelope,
    JSON.stringify({ valid: completion.valid, issues: completion.issues }),
    id,
    current.envelope
  ]);
  if (result && typeof result === "object" && "changes" in result && Number(result.changes) > 0) {
    await pruneUnreferencedAttachments(db, id, draft.data as Record<string, unknown> | undefined);
    return;
  }
  throw new Error("draft_conflict");
}

/** Drop the draft's files its current answers no longer reference (after a send that left the draft in place). */
export async function pruneDraftAttachments(db: Db, id: string): Promise<void> {
  const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [id]);
  if (row) await pruneUnreferencedAttachments(db, id, (JSON.parse(row.envelope) as { data?: Record<string, unknown> }).data);
}

/** Persist an upload refusal while retaining the interview and its answers. */
export async function setDraftUploadIssue(
  db: Db,
  id: string,
  issue: "answers_hash_invalid" | "invalid_definition_pin" | "demo_limit" | "case_conflict",
): Promise<void> {
  await db.runAsync(`UPDATE drafts SET upload_issue = ?, upload_issue_unique_id = ?,
    completed = CASE WHEN ? = 'answers_hash_invalid' THEN 0 ELSE completed END
    WHERE id = ?`, [issue, null, issue, id]);
}

/**
 * The interviewer asks for a held draft (refused at the public demo's limit,
 * or by a 409 on its case) to be sent again. The only way out of
 * `demo_limit` and `case_conflict`: sync never clears them, so such a
 * refusal is never retried on its own.
 */
export async function retryHeldDraft(db: Db, id: string): Promise<void> {
  await db.runAsync(
    "UPDATE drafts SET upload_issue = NULL, upload_issue_unique_id = NULL WHERE id = ? AND upload_issue IN ('demo_limit', 'case_conflict')",
    [id],
  );
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

function reduceLegacyNationalId(draft: DeviceTimedDraft): DeviceTimedDraft {
  if (!draft.data || typeof draft.data !== "object") return draft;
  const data = reduceNationalIdData(draft.data);
  return data === draft.data ? draft : { ...draft, data };
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
    // Reduced here so a pre-update completed draft never uploads (or hashes)
    // the full number; `envelope` stays the stored text for the exact-match delete.
    draft: reduceLegacyNationalId(JSON.parse(row.envelope) as DeviceTimedDraft),
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
  await db.runAsync("DELETE FROM attachments WHERE draft_id = ?", [id]);
  await db.runAsync("DELETE FROM meta WHERE key IN (?, ?)", [`consent:draft:${id}`, `consentRefused:${id}`]);
}

/** Delete only the exact envelope sent, preserving edits made during upload. */
export async function deleteDraftSnapshot(db: Db, id: string, envelope: string): Promise<boolean> {
  const result = await db.runAsync("DELETE FROM drafts WHERE id = ? AND envelope = ?", [id, envelope]);
  const deleted = !!result && typeof result === "object" && "changes" in result && Number(result.changes) > 0;
  if (deleted) {
    await db.runAsync("DELETE FROM meta WHERE key IN (?, ?)", [`consent:draft:${id}`, `consentRefused:${id}`]);
    await db.runAsync("DELETE FROM attachments WHERE draft_id = ?", [id]);
  }
  return deleted;
}

/**
 * Whether the draft was never sent and has no server copy, so deleting it on the phone loses nothing the server
 * holds: still in progress (not queued, ready or sending), no server draft id, no upload issue, no stored send
 * refusal (a draft reopened after a 422 was sent once) and no attachment the server confirmed.
 */
export async function isNeverSentDraft(db: Db, id: string): Promise<boolean> {
  const row = await db.getFirstAsync<Pick<DraftRow, "completed" | "server_draft_id" | "base_updated_at" | "upload_issue">>(
    "SELECT completed, server_draft_id, base_updated_at, upload_issue FROM drafts WHERE id = ?", [id]);
  if (!row || row.completed !== 0 || row.server_draft_id || row.base_updated_at || row.upload_issue) return false;
  if (await sendRefusal(db, id)) return false;
  const sent = await db.getFirstAsync<{ id: string }>("SELECT id FROM attachments WHERE draft_id = ? AND uploaded_at IS NOT NULL LIMIT 1", [id]);
  return !sent;
}

/**
 * Delete a never-sent draft and everything the phone keeps for it (consent record, files, form choices, send note)
 * in one transaction, behind the project's store guard like the form's own writes. Returns false, deleting nothing,
 * when the draft is gone or was sent once. Never touches the server.
 */
export async function deleteUnsentDraft(db: Db, id: string): Promise<boolean> {
  const row = await db.getFirstAsync<{ project_id: string | null }>("SELECT project_id FROM drafts WHERE id = ?", [id]);
  if (!row?.project_id) return false;
  const guard = createProjectStoreGuard(db, row.project_id);
  let deleted = false;
  await guard.runWrite(async () => {
    guard.assertCurrent();
    await runInTransaction(db, async (tx) => {
      // Checked again inside the transaction: a sync may have given the draft a server copy meanwhile.
      if (!(await isNeverSentDraft(tx, id))) return;
      await deleteDraft(tx, id);
      await tx.runAsync("DELETE FROM meta WHERE key = ?", [`draft-config:${id}`]);
      await clearSendError(tx, id);
      deleted = true;
    });
  });
  return deleted;
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

/**
 * Work on this phone the server has not acknowledged yet: drafts, offline
 * registrations, queued contact attempts and visits, queued revisions and, for the whole phone, the
 * registration still being typed.
 * Each row is deleted on acknowledgement, so every remaining row is unsent.
 */
export async function countUnsentWork(db: Db, projectId?: string): Promise<number> {
  const where = projectId ? " WHERE project_id = ?" : "";
  // The new registration being typed lives in meta (nativeRoutes/register.tsx); the per-project purge checks skip it.
  const typing = projectId ? "0" : "(SELECT COUNT(*) FROM meta WHERE key = 'registration-in-progress')";
  const row = await db.getFirstAsync<{ n: number }>(
    `SELECT (SELECT COUNT(*) FROM drafts${where}) + (SELECT COUNT(*) FROM registrations${where})
       + (SELECT COUNT(*) FROM case_actions${where}) + (SELECT COUNT(*) FROM revision_drafts${where}) + ${typing} AS n`,
    projectId ? [projectId, projectId, projectId, projectId] : []
  );
  return Number(row?.n ?? 0);
}

/**
 * A project left this worker's access: drop what the server can send again
 * (downloaded cases, cached definitions, project settings) and stop mounted
 * forms from writing to it. Unsent work (drafts, registrations, queued
 * actions, revisions and the draft configs they reopen with) is never purged
 * automatically: it stays until it is sent or the worker or a supervisor
 * resolves it (docs/policy/field-data-collection.md, owner decision 2026-10-22).
 */
export async function purgeProjectData(db: Db, projectId: string, accountId?: string): Promise<void> {
  invalidateProjectStoreGeneration(db, projectId);
  await waitForProjectStoreWrites(db, projectId);
  if (accountId) {
    const definitions = createNativeDefinitionCache(
      db as Parameters<typeof createNativeDefinitionCache>[0],
      accountId,
    );
    await definitions.initialize();
    await definitions.removeProject(projectId);
  }
  await db.runAsync("DELETE FROM meta WHERE key LIKE ?", [`project:${projectId}:%`]);
  await db.runAsync("DELETE FROM cases WHERE project_id = ?", [projectId]);
}

/**
 * Offline coding (Collect Plus phase 1): the certificate and the on-device
 * DORIS results for one interview, stored per interviewer beside its draft.
 * Rows never sync in this phase; the draft keeps syncing as the interview.
 */
export type OfflineCodingStatus = "draft" | "coded" | "rejected";

/** One row of the offline_coding table; the JSON columns hold the saved DORIS bundle verbatim. */
export interface OfflineCodingRow {
  client_draft_id: string;
  certificate: string;
  result: string | null;
  codedit_result: string | null;
  process_token: string;
  certificate_digest: string | null;
  result_digest: string | null;
  ucod_code: string | null;
  ucod_uri: string | null;
  status: OfflineCodingStatus;
  coder_profile_updated_at: string | null;
  device_uuid: string | null;
  created_at: string;
  updated_at: string;
}

/** A completed-but-unsent interview as the offline coding list shows it: metadata only, never answers. */
export interface OfflineCodingCaseRow {
  client_draft_id: string;
  org_unit_id: string | null;
  completed_at: string | null;
  updated_at: string;
  offline_status: OfflineCodingStatus | null;
}

/** Insert or replace the coding for one interview, keeping the original created_at. */
export async function saveOfflineCoding(db: Db, row: OfflineCodingRow): Promise<void> {
  await db.runAsync(
    `INSERT INTO offline_coding
       (client_draft_id, certificate, result, codedit_result, process_token, certificate_digest,
        result_digest, ucod_code, ucod_uri, status, coder_profile_updated_at, device_uuid, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(client_draft_id) DO UPDATE SET
       certificate = excluded.certificate, result = excluded.result,
       codedit_result = excluded.codedit_result, process_token = excluded.process_token,
       certificate_digest = excluded.certificate_digest, result_digest = excluded.result_digest,
       ucod_code = excluded.ucod_code, ucod_uri = excluded.ucod_uri, status = excluded.status,
       coder_profile_updated_at = excluded.coder_profile_updated_at, device_uuid = excluded.device_uuid,
       updated_at = excluded.updated_at`,
    [
      row.client_draft_id, row.certificate, row.result, row.codedit_result, row.process_token,
      row.certificate_digest, row.result_digest, row.ucod_code, row.ucod_uri, row.status,
      row.coder_profile_updated_at, row.device_uuid, row.created_at, row.updated_at,
    ],
  );
}

/** Completed interviews the server has not taken (no upload refusal, no server copy), with any coding status. */
export async function listOfflineCodingCases(db: Db): Promise<OfflineCodingCaseRow[]> {
  return db.getAllAsync<OfflineCodingCaseRow>(
    `SELECT d.id AS client_draft_id, d.org_unit_id,
            json_extract(d.envelope, '$.completedAt') AS completed_at, d.updated_at,
            oc.status AS offline_status
     FROM drafts d LEFT JOIN offline_coding oc ON oc.client_draft_id = d.id
     WHERE d.completed = 1 AND d.upload_issue IS NULL AND d.server_draft_id IS NULL
     ORDER BY d.updated_at DESC`,
    [],
  );
}

/** The stored coding for one interview, or null when it was never coded on this device. */
export async function getOfflineCoding(db: Db, clientDraftId: string): Promise<OfflineCodingRow | null> {
  return db.getFirstAsync<OfflineCodingRow>(
    `SELECT client_draft_id, certificate, result, codedit_result, process_token, certificate_digest,
            result_digest, ucod_code, ucod_uri, status, coder_profile_updated_at, device_uuid, created_at, updated_at
     FROM offline_coding WHERE client_draft_id = ?`,
    [clientDraftId],
  );
}

/** Delete the coding for one interview. The draft itself is untouched. */
export async function deleteOfflineCoding(db: Db, clientDraftId: string): Promise<void> {
  await db.runAsync("DELETE FROM offline_coding WHERE client_draft_id = ?", [clientDraftId]);
}

/** The completed-but-unsent interview a coder opens, with its envelope for the certificate seed. */
export interface OfflineCodingCase {
  client_draft_id: string;
  org_unit_id: string | null;
  envelope: string;
  started_at: string | null;
  completed_at: string | null;
}

/** Metadata plus the answers the interviewer collected; nothing else leaves the store. */
export async function getOfflineCodingCase(db: Db, clientDraftId: string): Promise<OfflineCodingCase | null> {
  return db.getFirstAsync<OfflineCodingCase>(
    `SELECT d.id AS client_draft_id, d.org_unit_id, d.envelope,
            json_extract(d.envelope, '$.startedAt') AS started_at,
            json_extract(d.envelope, '$.completedAt') AS completed_at
     FROM drafts d
     WHERE d.id = ? AND d.completed = 1 AND d.upload_issue IS NULL AND d.server_draft_id IS NULL`,
    [clientDraftId],
  );
}
