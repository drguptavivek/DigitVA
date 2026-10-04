/**
 * On-demand submitted-interview metadata and encrypted native revision drafts.
 * Server answers are fetched only when an interviewer opens a revision; the
 * local row is kept only while that revision is being edited or sent.
 */
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { createWhoVa2022Instrument, type SubmissionData, type WhoVaDraft, type WhoVaDraftStore } from "@drguptavivek/who-2022-va";
import { ApiError, INTAKE_API } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import { localDateTimeWithOffset, type Completion, type Db, type DeviceTimedDraft } from "./drafts";

export type RevisionReason = "interviewer_correction" | "respondent_correction" | "more_information" | "finish_partial";
export type RevisionState = "editing" | "ready" | "attention";

export interface SubmittedRevisionSummary {
  draft_id: string;
  project_id: string;
  site_id: string;
  death_id: string | null;
  va_sid: string;
  unique_id?: string;
  status?: string;
  current_section?: string | null;
  updated_at?: string;
  instrument_code?: string;
  instrument_version?: string;
}

export interface RevisionConfig {
  projectId?: string;
  locale?: string;
  enabledExtensions?: string[];
  instrumentCode?: string;
  translationVersion?: number;
}

export interface RevisionRow extends SubmittedRevisionSummary {
  envelope: DeviceTimedDraft;
  prefill: Record<string, unknown>;
  config?: RevisionConfig;
  original_answers_sha256: string | null;
  original_outcome: string | null;
  reason_code: RevisionReason | null;
  completion: Completion | null;
  frozen_json: string | null;
  answers_sha256: string | null;
  state: RevisionState;
  refusal_code: string | null;
  updated_at: string;
}

interface RevisionListBody {
  drafts: unknown[];
}

interface RevisionDetailBody {
  draft: unknown;
  envelope: unknown;
  prefill: unknown;
  answers_sha256: unknown;
}

interface RevisionDbRow {
  row_json: string;
}

const REASONS: readonly RevisionReason[] = [
  "interviewer_correction", "respondent_correction", "more_information", "finish_partial"
];
const HASH = /^[0-9a-f]{64}$/i;
const PAGE_SIZE = 100;
const LIST_LIMIT = 200;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRevisionReason(value: unknown): value is RevisionReason {
  return typeof value === "string" && REASONS.includes(value as RevisionReason);
}

/** Match the backend's persisted interview outcome for a revision attempt. */
export function effectiveRevisionOutcome(data: Record<string, unknown>, completion: Completion): string | null {
  const consent = typeof data.Id10013 === "string" ? data.Id10013.trim().toLowerCase() : "";
  if (consent === "no") return "refused";
  if (completion.valid === true && !consent) return null;
  if (completion.valid === true) return "completed";
  return typeof data.interview_outcome === "string" ? data.interview_outcome : null;
}

function validConfig(value: unknown): value is RevisionConfig {
  if (!isRecord(value)) return false;
  return (value.projectId === undefined || typeof value.projectId === "string") &&
    (value.locale === undefined || typeof value.locale === "string") &&
    (value.instrumentCode === undefined || typeof value.instrumentCode === "string") &&
    (value.translationVersion === undefined || (typeof value.translationVersion === "number" && Number.isInteger(value.translationVersion) && value.translationVersion >= 0)) &&
    (value.enabledExtensions === undefined || (Array.isArray(value.enabledExtensions) && value.enabledExtensions.every((item) => typeof item === "string")));
}

function parseSummary(value: unknown): SubmittedRevisionSummary {
  if (!isRecord(value) || value.status !== "submitted" ||
      typeof value.draft_id !== "string" || !value.draft_id ||
      typeof value.project_id !== "string" || !value.project_id ||
      typeof value.site_id !== "string" || !value.site_id ||
      !(value.death_id === null || (typeof value.death_id === "string" && value.death_id.length > 0)) ||
      typeof value.va_sid !== "string" || !value.va_sid ||
      (value.unique_id !== undefined && value.unique_id !== null && typeof value.unique_id !== "string") ||
      (value.updated_at !== undefined && typeof value.updated_at !== "string") ||
      (value.current_section !== undefined && value.current_section !== null && typeof value.current_section !== "string")) {
    throw new ApiError(200, "malformed_response");
  }
  return {
    draft_id: value.draft_id,
    project_id: value.project_id,
    site_id: value.site_id,
      death_id: value.death_id,
    va_sid: value.va_sid,
    ...(typeof value.unique_id === "string" ? { unique_id: value.unique_id } : {}),
    status: "submitted",
    ...(typeof value.current_section === "string" || value.current_section === null ? { current_section: value.current_section } : {}),
    ...(typeof value.updated_at === "string" ? { updated_at: value.updated_at } : {}),
    ...(typeof value.instrument_code === "string" ? { instrument_code: value.instrument_code } : {}),
    ...(typeof value.instrument_version === "string" ? { instrument_version: value.instrument_version } : {})
  };
}

/** Read only the current server list; answers are never part of this response. */
export async function fetchSubmittedRevisions(userId: string): Promise<SubmittedRevisionSummary[]> {
  const path = `${INTAKE_API}/drafts?status=submitted`;
  const { body } = await authedRequest<unknown>(userId, path);
  if (!isRecord(body) || !Array.isArray(body.drafts)) throw new ApiError(200, "malformed_response");
  return body.drafts.slice(0, LIST_LIMIT).map(parseSummary);
}

async function readStoredConfig(db: Db, draftId: string, projectId: string): Promise<RevisionConfig | undefined> {
  const result = await db.getFirstAsync<{ value: string }>("SELECT value FROM meta WHERE key = ?", [`draft-config:${draftId}`]);
  if (!result) return undefined;
  try {
    const config: unknown = JSON.parse(result.value);
    if (!validConfig(config) || (config.projectId !== undefined && config.projectId !== projectId)) return undefined;
    return config;
  } catch {
    return undefined;
  }
}

function validateDetail(summary: SubmittedRevisionSummary, body: unknown, config?: RevisionConfig): RevisionRow {
  if (!isRecord(body)) throw new ApiError(200, "malformed_response");
  const detail = body as unknown as RevisionDetailBody;
  const draft = detail.draft;
  const envelope = detail.envelope;
  if (!isRecord(draft) || draft.status !== "submitted" || draft.draft_id !== summary.draft_id ||
      draft.project_id !== summary.project_id || draft.site_id !== summary.site_id ||
      draft.death_id !== summary.death_id || draft.va_sid !== summary.va_sid ||
      !isRecord(envelope) || envelope.id !== summary.draft_id || envelope.schemaVersion !== 1 ||
      typeof envelope.formVersion !== "string" || !envelope.formVersion || typeof envelope.instrumentId !== "string" || !envelope.instrumentId ||
      typeof envelope.instrumentVersion !== "string" || typeof envelope.currentSection !== "string" ||
      typeof envelope.createdAt !== "string" || !Number.isFinite(Date.parse(envelope.createdAt)) ||
      typeof envelope.updatedAt !== "string" || !Number.isFinite(Date.parse(envelope.updatedAt)) || !isRecord(envelope.data) ||
      !isRecord(detail.prefill) ||
      (detail.answers_sha256 !== null && (typeof detail.answers_sha256 !== "string" || !HASH.test(detail.answers_sha256)))) {
    throw new ApiError(200, "malformed_response");
  }
  if (config?.enabledExtensions) {
    const configured = createWhoVa2022Instrument(config.enabledExtensions);
    if ((envelope.instrumentId && configured.id !== envelope.instrumentId) ||
        (envelope.instrumentVersion && configured.version !== envelope.instrumentVersion)) {
      throw new ApiError(200, "instrument_incompatible");
    }
  }
  for (const key of ["startedAt", "completedAt"] as const) {
    if (envelope[key] !== undefined && (typeof envelope[key] !== "string" || !Number.isFinite(Date.parse(envelope[key] as string)))) {
      throw new ApiError(200, "malformed_response");
    }
  }
  if (envelope.locale !== undefined && (typeof envelope.locale !== "string" || !/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(envelope.locale))) {
    throw new ApiError(200, "malformed_response");
  }
  if (envelope.translation_version !== undefined &&
      (typeof envelope.translation_version !== "number" || !Number.isInteger(envelope.translation_version) || envelope.translation_version < 0)) {
    throw new ApiError(200, "malformed_response");
  }
  return {
    ...summary,
    envelope: envelope as unknown as DeviceTimedDraft,
    prefill: detail.prefill,
    ...(config ? { config } : {}),
    original_answers_sha256: detail.answers_sha256 as string | null,
    original_outcome: typeof envelope.data.interview_outcome === "string" ? envelope.data.interview_outcome : null,
    reason_code: null,
    completion: null,
    frozen_json: null,
    answers_sha256: null,
    state: "editing",
    refusal_code: null,
    updated_at: summary.updated_at ?? envelope.updatedAt
  };
}

function rowFromJson(rowJson: string): RevisionRow {
  let value: unknown;
  try {
    value = JSON.parse(rowJson);
  } catch {
    throw new Error("invalid_revision_row");
  }
  if (!isRecord(value) || typeof value.draft_id !== "string" || !value.draft_id ||
      typeof value.project_id !== "string" || !value.project_id ||
      typeof value.site_id !== "string" || !value.site_id ||
      !(value.death_id === null || (typeof value.death_id === "string" && value.death_id.length > 0)) ||
      typeof value.va_sid !== "string" || !value.va_sid ||
      !["editing", "ready", "attention"].includes(String(value.state)) ||
      !isRecord(value.envelope) || value.envelope.id !== value.draft_id || !isRecord(value.envelope.data) || !isRecord(value.prefill) ||
      ![null, "interviewer_correction", "respondent_correction", "more_information", "finish_partial"].includes(value.reason_code as never) ||
      !(value.original_answers_sha256 === null || (typeof value.original_answers_sha256 === "string" && HASH.test(value.original_answers_sha256))) ||
      !(value.answers_sha256 === null || (typeof value.answers_sha256 === "string" && HASH.test(value.answers_sha256))) ||
      !(value.frozen_json === null || typeof value.frozen_json === "string") ||
      !(value.refusal_code === null || typeof value.refusal_code === "string") ||
      !(value.completion === null || (isRecord(value.completion) && typeof value.completion.valid === "boolean" && Array.isArray(value.completion.issues))) ||
      !(value.original_outcome === undefined || value.original_outcome === null || typeof value.original_outcome === "string")) throw new Error("invalid_revision_row");
  if (value.original_outcome === undefined) value.original_outcome = null;
  return value as unknown as RevisionRow;
}

async function readRow(db: Db, draftId: string): Promise<{ row: RevisionRow; rowJson: string } | null> {
  const stored = await db.getFirstAsync<RevisionDbRow>("SELECT row_json FROM revision_drafts WHERE draft_id = ?", [draftId]);
  return stored ? { row: rowFromJson(stored.row_json), rowJson: stored.row_json } : null;
}

async function insertRow(db: Db, row: RevisionRow): Promise<void> {
  const rowJson = JSON.stringify(row);
  const result = await db.runAsync(
    "INSERT INTO revision_drafts (draft_id, project_id, state, updated_at, row_json) VALUES (?, ?, ?, ?, ?) ON CONFLICT(draft_id) DO NOTHING",
    [row.draft_id, row.project_id, row.state, row.updated_at, rowJson]
  );
  if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) throw new Error("revision_conflict");
}

/** Resume an encrypted local revision before making any network request. */
export async function beginRevision(userId: string, db: Db, draftId: string): Promise<RevisionRow> {
  const local = await getRevisionRow(db, draftId);
  if (local) return local;
  const summaries = await fetchSubmittedRevisions(userId);
  const summary = summaries.find((item) => item.draft_id === draftId);
  if (!summary) throw new ApiError(404, "not_found");
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/drafts/${encodeURIComponent(draftId)}`);
  const config = await readStoredConfig(db, draftId, summary.project_id);
  const row = validateDetail(summary, body, config);
  await insertRow(db, row);
  return (await getRevisionRow(db, draftId)) ?? row;
}

/** Read one active local revision without downloading or retaining history. */
export async function getRevisionRow(db: Db, draftId: string): Promise<RevisionRow | null> {
  return (await readRow(db, draftId))?.row ?? null;
}

/** Return the newest local in-flight revisions, never more than one page. */
export async function listLocalRevisions(db: Db): Promise<RevisionRow[]> {
  const rows = await db.getAllAsync<RevisionDbRow>(
    "SELECT row_json FROM revision_drafts ORDER BY updated_at DESC, draft_id LIMIT ?", [LIST_LIMIT]
  );
  return rows.map(({ row_json }) => rowFromJson(row_json));
}

function envelopeForSave(draft: WhoVaDraft, existing: DeviceTimedDraft): DeviceTimedDraft {
  const locale = typeof (draft as DeviceTimedDraft).locale === "string" ? (draft as DeviceTimedDraft).locale : existing.locale;
  const translationVersion = typeof (draft as DeviceTimedDraft).translation_version === "number"
    ? (draft as DeviceTimedDraft).translation_version
    : existing.translation_version;
  return {
    ...draft,
    ...(existing.startedAt ? { startedAt: existing.startedAt } : {}),
    ...(existing.completedAt ? { completedAt: existing.completedAt } : {}),
    ...(locale ? { locale } : {}),
    ...(translationVersion !== undefined ? { translation_version: translationVersion } : {})
  };
}

/** Store WHO autosaves in the revision table, serializing writes per form mount. */
export function createRevisionDraftStore(db: Db, draftId: string): WhoVaDraftStore {
  let pending = Promise.resolve();
  return {
    async save(draft) {
      const operation = pending.then(async () => {
        if (draft.id !== draftId) throw new Error("revision_id_mismatch");
        const current = await readRow(db, draftId);
        if (!current) throw new Error("revision_not_found");
        if (current.row.state === "attention") throw new Error("revision_attention_required");
        if (draft.instrumentId !== current.row.envelope.instrumentId ||
            draft.instrumentVersion !== current.row.envelope.instrumentVersion ||
            draft.formVersion !== current.row.envelope.formVersion) throw new Error("instrument_incompatible");
        const envelope = envelopeForSave(draft, current.row.envelope);
        const next: RevisionRow = {
          ...current.row,
          envelope,
          completion: null,
          frozen_json: null,
          answers_sha256: null,
          state: "editing",
          refusal_code: null,
          updated_at: draft.updatedAt
        };
        const nextJson = JSON.stringify(next);
        const result = await db.runAsync(
          `UPDATE revision_drafts SET state = ?, updated_at = ?, row_json = ?
           WHERE draft_id = ? AND row_json = ?`,
          [next.state, next.updated_at, nextJson, draftId, current.rowJson]
        );
        if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) throw new Error("revision_conflict");
      });
      pending = operation.catch(() => undefined);
      return operation;
    },
    async load(id) {
      if (id !== draftId) return undefined;
      return (await getRevisionRow(db, draftId))?.envelope;
    },
    async remove(id) {
      if (id === draftId) await discardRevision(db, draftId);
    }
  };
}

/** Freeze one answer string and its completion time before hashing it. */
export async function queueRevision(db: Db, draftId: string, reason: RevisionReason, completion: Completion): Promise<RevisionRow> {
  if (!isRevisionReason(reason) || !isRecord(completion) || typeof completion.valid !== "boolean" || !Array.isArray(completion.issues)) {
    throw new Error("invalid_revision_input");
  }
  const current = await readRow(db, draftId);
  if (!current) throw new Error("revision_not_found");
  if (current.row.state === "attention") throw new Error("revision_attention_required");
  const currentOutcome = effectiveRevisionOutcome(current.row.envelope.data, completion);
  if (completion.valid && currentOutcome === null) throw new Error("consent_required");
  if (currentOutcome === "completed" &&
      (current.row.original_outcome === null || ["partially_completed", "respondent_unavailable"].includes(current.row.original_outcome)) &&
      reason !== "finish_partial") {
    throw new Error("finish_partial_required");
  }
  const completedAt = localDateTimeWithOffset();
  const envelope: DeviceTimedDraft = {
    ...current.row.envelope,
    updatedAt: completedAt,
    completedAt
  };
  const frozenJson = JSON.stringify(envelope.data as SubmissionData);
  const next: RevisionRow = {
    ...current.row,
    envelope,
    reason_code: reason,
    completion: { valid: completion.valid, issues: completion.issues },
    frozen_json: frozenJson,
    answers_sha256: null,
    state: "editing",
    refusal_code: null,
    updated_at: completedAt
  };
  const nextJson = JSON.stringify(next);
  const saved = await db.runAsync(
    `UPDATE revision_drafts SET state = ?, updated_at = ?, row_json = ?
     WHERE draft_id = ? AND row_json = ?`,
    [next.state, next.updated_at, nextJson, draftId, current.rowJson]
  );
  if (!saved || typeof saved !== "object" || !("changes" in saved) || Number(saved.changes) === 0) throw new Error("revision_conflict");

  // Hash the frozen text after saving it so process death can resume it exactly.
  const hash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, frozenJson)).toLowerCase();
  const latest = await readRow(db, draftId);
  if (!latest || latest.rowJson !== nextJson) {
    throw new Error("revision_conflict");
  }
  const ready: RevisionRow = { ...latest.row, answers_sha256: hash, state: "ready" };
  const readyJson = JSON.stringify(ready);
  const result = await db.runAsync(
    `UPDATE revision_drafts SET state = ?, row_json = ?
     WHERE draft_id = ? AND row_json = ?`,
    [ready.state, readyJson, draftId, latest.rowJson]
  );
  if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) throw new Error("revision_conflict");
  return ready;
}

/** Explicitly make a refused revision editable while keeping its raw answers. */
export async function reopenRevision(db: Db, draftId: string): Promise<void> {
  const current = await readRow(db, draftId);
  if (!current) return;
  const next: RevisionRow = { ...current.row, state: "editing", frozen_json: null, answers_sha256: null, refusal_code: null, updated_at: localDateTimeWithOffset() };
  const result = await db.runAsync(
    "UPDATE revision_drafts SET state = ?, updated_at = ?, row_json = ? WHERE draft_id = ? AND row_json = ?",
    [next.state, next.updated_at, JSON.stringify(next), draftId, current.rowJson]
  );
  if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) === 0) throw new Error("revision_conflict");
}

/** Remove one in-flight revision after an explicit interviewer discard. */
export async function discardRevision(db: Db, draftId: string): Promise<void> {
  await db.runAsync("DELETE FROM revision_drafts WHERE draft_id = ?", [draftId]);
}

function revisionMeta(row: RevisionRow): Record<string, string> {
  return {
    ...(row.envelope.startedAt ? { startedAt: row.envelope.startedAt } : {}),
    ...(row.envelope.completedAt ? { completedAt: row.envelope.completedAt } : {})
  };
}

function validAck(value: unknown, row: RevisionRow): value is {
  changed: boolean; va_sid: string; payload_version_id: string; answers_sha256: string;
  outcome: string; workflow_state: string;
} {
  return isRecord(value) && typeof value.changed === "boolean" && value.va_sid === row.va_sid &&
    typeof value.payload_version_id === "string" && value.payload_version_id.length > 0 &&
    typeof value.answers_sha256 === "string" &&
    HASH.test(value.answers_sha256) && value.answers_sha256.toLowerCase() === row.answers_sha256 &&
    typeof value.outcome === "string" && value.outcome.length > 0 &&
    typeof value.workflow_state === "string" && value.workflow_state.length > 0;
}

async function markAttention(db: Db, rowJson: string, row: RevisionRow, code: string): Promise<boolean> {
  const next: RevisionRow = { ...row, state: "attention", refusal_code: code, updated_at: localDateTimeWithOffset() };
  const result = await db.runAsync(
    "UPDATE revision_drafts SET state = ?, updated_at = ?, row_json = ? WHERE draft_id = ? AND row_json = ?",
    [next.state, next.updated_at, JSON.stringify(next), row.draft_id, rowJson]
  );
  return !!result && typeof result === "object" && "changes" in result && Number(result.changes) > 0;
}

const TERMINAL_CODES = new Set([
  "revision_locked", "case_already_submitted", "case_closed", "case_state_conflict",
  "invalid_reason", "outcome_regression", "answers_hash_required", "invalid_interview"
]);

/** Send queued revisions independently; transient failures retain the exact ready snapshot. */
export async function syncQueuedRevisions(userId: string, db: Db, authorizedProjects: Set<string>): Promise<{ sent: number; failed: number; attentionIds: string[] }> {
  let sent = 0;
  let failed = 0;
  const attentionIds: string[] = [];
  let afterId: string | undefined;
  while (true) {
    const rows = await db.getAllAsync<RevisionDbRow>(
      `SELECT row_json FROM revision_drafts WHERE state = 'ready'${afterId ? " AND draft_id > ?" : ""}
       ORDER BY draft_id LIMIT ?`,
      afterId ? [afterId, PAGE_SIZE] : [PAGE_SIZE]
    );
    if (rows.length === 0) break;
    for (const stored of rows) {
      const rowJson = stored.row_json;
      const row = rowFromJson(rowJson);
      afterId = row.draft_id;
      if (row.state !== "ready" || !authorizedProjects.has(row.project_id)) continue;
      if (!row.reason_code || !row.frozen_json || !row.answers_sha256 || !row.completion) {
        await markAttention(db, rowJson, row, "invalid_revision_snapshot");
        attentionIds.push(row.draft_id);
        failed += 1;
        continue;
      }
      const path = `${INTAKE_API}/submissions/${encodeURIComponent(row.va_sid)}/revisions`;
      const send = () => authedRequest<unknown>(userId, path, {
        method: "POST",
        timeoutMs: 120_000,
        bodyFactory: () => ({
          reason_code: row.reason_code,
          answers_json: row.frozen_json,
          answers_sha256: row.answers_sha256,
          completion: row.completion,
          draft: { ...revisionMeta(row), deviceClockAt: localDateTimeWithOffset() }
        })
      });
      let acknowledgement;
      try {
        try {
          acknowledgement = await send();
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 422 || error.code !== "answers_hash_invalid") throw error;
          const retryHash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, row.frozen_json)).toLowerCase();
          if (retryHash !== row.answers_sha256) {
            await markAttention(db, rowJson, row, "local_hash_mismatch");
            attentionIds.push(row.draft_id);
            failed += 1;
            continue;
          }
          try {
            acknowledgement = await send();
          } catch (retryError) {
            if (!(retryError instanceof ApiError) || retryError.status !== 422 || retryError.code !== "answers_hash_invalid") throw retryError;
            await markAttention(db, rowJson, row, "answers_hash_invalid");
            attentionIds.push(row.draft_id);
            failed += 1;
            continue;
          }
        }
        if (!validAck(acknowledgement.body, row)) {
          await markAttention(db, rowJson, row, "invalid_revision_ack");
          attentionIds.push(row.draft_id);
          failed += 1;
          continue;
        }
        const deleted = await db.runAsync("DELETE FROM revision_drafts WHERE draft_id = ? AND row_json = ?", [row.draft_id, rowJson]);
        if (deleted && typeof deleted === "object" && "changes" in deleted && Number(deleted.changes) > 0) sent += 1;
      } catch (error) {
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
        if (error instanceof ApiError && error.status === 403) throw error;
        if (error instanceof ApiError && TERMINAL_CODES.has(error.code ?? "")) {
          if (await markAttention(db, rowJson, row, error.code!)) attentionIds.push(row.draft_id);
        } else if (error instanceof ApiError && error.status === 404) {
          if (await markAttention(db, rowJson, row, error.code ?? "not_found")) attentionIds.push(row.draft_id);
        } else if (error instanceof ApiError && (error.status === 409 || error.status === 422)) {
          if (await markAttention(db, rowJson, row, "revision_rejected")) attentionIds.push(row.draft_id);
        }
        console.warn(`revision sync refused draft=${row.draft_id} status=${error instanceof ApiError ? error.status : 0} code=${error instanceof ApiError ? error.code ?? "-" : "network"}`);
        failed += 1;
      }
    }
    if (rows.length < PAGE_SIZE) break;
  }
  return { sent, failed, attentionIds };
}
