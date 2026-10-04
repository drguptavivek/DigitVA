/** Sync unfinished phone drafts with the interviewer's server-side web draft. */
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { decodeWhoVaDraft } from "@drguptavivek/who-2022-va";

import { ApiError, INTAKE_API } from "./api";
import { authedRequest } from "./auth";
import type { CaseDetail } from "./cases";
import { canStartDeathInterview } from "./deathWorkflow";
import { draftForCase, getDraftPrefill, getDraftRow, localDateTimeWithOffset, type Db, type DeviceTimedDraft, type DraftRow, type DraftSyncItem } from "./drafts";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const LOCALE_RE = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;
const SYNC_MESSAGE = "This interview was also edited on another device; the newer version was kept.";
const LOCAL_CHANGE_MESSAGE = "This interview changed on this device while it was syncing; the local version was kept.";

export interface DraftSyncDefaults {
  instrumentId: string;
  instrumentVersion: string;
  currentSection: string;
}

export interface ServerDraftSummary {
  draft_id: string;
  project_id: string;
  site_id: string;
  org_unit_id: string | null;
  death_id: string | null;
  unique_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Server drafts can be blank before the first form save, so two fields may be empty. */
export interface ServerDraftEnvelope {
  schemaVersion: number;
  formVersion: string;
  id: string;
  instrumentId: string;
  instrumentVersion: string;
  currentSection: string;
  createdAt: string;
  updatedAt: string;
  data: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FetchedServerDraft {
  draft: ServerDraftSummary;
  envelope: ServerDraftEnvelope;
  prefill: Record<string, unknown>;
}

export interface DraftSyncResult {
  applied: boolean;
  conflict: boolean;
  message: string | null;
  /** Stable local id, also sent as the final submission's client_draft_id. */
  draftId: string;
}

export interface CaseDraftReconcileResult {
  draft: DraftRow | null;
  conflict: boolean;
  message: string | null;
  imported: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isOffsetTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    !Number.isNaN(Date.parse(value));
}

function requiredString(value: Record<string, unknown>, key: string): string {
  const field = value[key];
  if (typeof field !== "string" || !field.trim()) throw new Error("invalid_server_draft");
  return field;
}

function serverSummary(value: unknown, expectedId?: string): ServerDraftSummary {
  if (!isRecord(value)) throw new Error("invalid_server_draft");
  for (const key of ["org_unit_id", "death_id", "unique_id"] as const) {
    if (value[key] !== null && value[key] !== undefined && typeof value[key] !== "string") {
      throw new Error("invalid_server_draft");
    }
  }
  const summary: ServerDraftSummary = {
    draft_id: requiredString(value, "draft_id"),
    project_id: requiredString(value, "project_id"),
    site_id: requiredString(value, "site_id"),
    org_unit_id: typeof value.org_unit_id === "string" ? value.org_unit_id : null,
    death_id: typeof value.death_id === "string" ? value.death_id : null,
    unique_id: typeof value.unique_id === "string" ? value.unique_id : null,
    status: requiredString(value, "status"),
    created_at: requiredString(value, "created_at"),
    updated_at: requiredString(value, "updated_at")
  };
  if (!UUID_RE.test(summary.draft_id) || (expectedId && summary.draft_id !== expectedId) ||
      !isOffsetTimestamp(summary.created_at) || !isOffsetTimestamp(summary.updated_at)) {
    throw new Error("invalid_server_draft");
  }
  return summary;
}

function serverEnvelope(value: unknown, draftId: string): ServerDraftEnvelope {
  if (!isRecord(value) || value.id !== draftId || value.schemaVersion !== 1 || !isRecord(value.data) ||
      !isOffsetTimestamp(value.createdAt) || !isOffsetTimestamp(value.updatedAt)) {
    throw new Error("invalid_server_draft");
  }
  const formVersion = requiredString(value, "formVersion");
  const instrumentId = requiredString(value, "instrumentId");
  if (typeof value.instrumentVersion !== "string" || typeof value.currentSection !== "string") {
    throw new Error("invalid_server_draft");
  }
  if ((value.locale !== undefined && (typeof value.locale !== "string" || !LOCALE_RE.test(value.locale))) ||
      (value.translation_version !== undefined && (typeof value.translation_version !== "number" ||
        !Number.isInteger(value.translation_version) || value.translation_version < 0))) {
    throw new Error("invalid_server_draft");
  }
  return {
    ...value,
    schemaVersion: 1,
    formVersion,
    id: draftId,
    instrumentId,
    instrumentVersion: value.instrumentVersion,
    currentSection: value.currentSection,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    data: value.data
  };
}

function prefillRecord(value: unknown): Record<string, unknown> {
  if (value === undefined || value === null) return {};
  if (!isRecord(value)) throw new Error("invalid_server_draft");
  return value;
}

/** Fetch one authorized server draft and validate its identity before exposing its envelope. */
export async function fetchServerDraft(userId: string, serverDraftId: string): Promise<FetchedServerDraft> {
  if (!UUID_RE.test(serverDraftId)) throw new Error("invalid_server_draft");
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/drafts/${encodeURIComponent(serverDraftId)}`);
  if (!isRecord(body)) throw new Error("invalid_server_draft");
  const draft = serverSummary(body.draft, serverDraftId);
  if (draft.status !== "draft") throw new Error("server_draft_not_editable");
  return {
    draft,
    envelope: serverEnvelope(body.envelope, serverDraftId),
    prefill: prefillRecord(body.prefill)
  };
}

async function fetchForLocalSnapshot(userId: string, db: Db, item: DraftSyncItem): Promise<FetchedServerDraft> {
  try {
    return await fetchServerDraft(userId, item.server_draft_id!);
  } catch (error) {
    if (error instanceof Error && error.message === "server_draft_not_editable") {
      await db.runAsync(`UPDATE drafts SET draft_sync_blocked = 1
        WHERE id = ? AND envelope = ? AND updated_at = ? AND completed = 0 AND draft_sync_blocked = 0`,
      [item.id, item.envelope, item.updated_at]);
    }
    throw error;
  }
}

function parseLocalEnvelope(item: DraftSyncItem): DeviceTimedDraft {
  let raw: unknown;
  try {
    raw = JSON.parse(item.envelope) as unknown;
  } catch {
    throw new Error("invalid_local_draft");
  }
  const decoded = decodeWhoVaDraft(raw);
  if (decoded.id !== item.id) throw new Error("invalid_local_draft");
  const host = isRecord(raw) ? raw : {};
  return {
    ...decoded,
    ...(isOffsetTimestamp(host.startedAt) ? { startedAt: host.startedAt } : {}),
    ...(isOffsetTimestamp(host.completedAt) ? { completedAt: host.completedAt } : {}),
    ...(isOffsetTimestamp(host.deviceClockAt) ? { deviceClockAt: host.deviceClockAt } : {}),
    ...(typeof host.locale === "string" ? { locale: host.locale } : {}),
    ...(typeof host.translation_version === "number" && Number.isInteger(host.translation_version) && host.translation_version >= 0
      ? { translation_version: host.translation_version }
      : {})
  };
}

function metadataForSync(draft: DeviceTimedDraft): Record<string, unknown> {
  return {
    schemaVersion: draft.schemaVersion,
    formVersion: draft.formVersion,
    instrumentId: draft.instrumentId,
    instrumentVersion: draft.instrumentVersion,
    createdAt: draft.createdAt,
    updatedAt: draft.updatedAt,
    currentSection: draft.currentSection,
    ...(draft.startedAt ? { startedAt: draft.startedAt } : {}),
    ...(draft.locale ? { locale: draft.locale } : {}),
    ...(draft.translation_version !== undefined ? { translation_version: draft.translation_version } : {})
  };
}

function resultChanges(result: unknown): boolean {
  return !!result && typeof result === "object" && "changes" in result && Number(result.changes) > 0;
}

function draftPrefillAnswers(prefill: Record<string, unknown> | undefined): Record<string, unknown> {
  return prefill && isRecord(prefill.answers) ? prefill.answers : {};
}

function normalizedEnvelope(
  envelope: ServerDraftEnvelope,
  server: ServerDraftSummary,
  localId: string,
  defaults: DraftSyncDefaults,
  prefill?: Record<string, unknown>,
  startedAt?: string,
  createdAt?: string,
): DeviceTimedDraft {
  if (!UUID_RE.test(localId) || envelope.instrumentId !== defaults.instrumentId ||
      (envelope.instrumentVersion && envelope.instrumentVersion !== defaults.instrumentVersion)) {
    throw new Error("server_draft_instrument_mismatch");
  }
  if (!defaults.instrumentId || !defaults.instrumentVersion || !defaults.currentSection) {
    throw new Error("draft_defaults_required");
  }
  const merged = {
    ...envelope,
    id: localId,
    instrumentVersion: envelope.instrumentVersion || defaults.instrumentVersion,
    currentSection: envelope.currentSection || defaults.currentSection,
    createdAt: createdAt ?? envelope.createdAt ?? server.created_at,
    updatedAt: server.updated_at,
    data: { ...draftPrefillAnswers(prefill), ...envelope.data }
  };
  const decoded = decodeWhoVaDraft(merged);
  return {
    ...decoded,
    ...(startedAt && isOffsetTimestamp(startedAt) ? { startedAt } : {}),
    ...(typeof envelope.locale === "string" ? { locale: envelope.locale } : {}),
    ...(typeof envelope.translation_version === "number" && Number.isInteger(envelope.translation_version) && envelope.translation_version >= 0
      ? { translation_version: envelope.translation_version }
      : {})
  };
}

function prefillFromStored(value: unknown): Record<string, unknown> {
  if (value === undefined || value === null) return {};
  return isRecord(value) ? value : {};
}

type DraftCaseIdentity = {
  project_id: string;
  site_id: string;
  org_unit_id: string | null;
  death_id: string | null;
};

function serverIdentityMatches(server: DraftCaseIdentity, item: DraftCaseIdentity): boolean {
  return server.project_id === item.project_id && server.site_id === item.site_id &&
    server.death_id === item.death_id && server.org_unit_id === item.org_unit_id;
}

/** Send one immutable local snapshot; a concurrent save or completion always wins the local compare-and-set. */
export async function syncDraftSnapshot(userId: string, db: Db, item: DraftSyncItem): Promise<DraftSyncResult> {
  const draft = parseLocalEnvelope(item);
  if (!item.project_id || !item.death_id || !isOffsetTimestamp(item.updated_at)) throw new Error("invalid_local_draft");
  if (item.draft_sync_blocked) return { applied: true, conflict: false, message: null, draftId: item.id };
  if (item.draft_sync_dirty === 0 && item.server_draft_id && item.base_updated_at && isOffsetTimestamp(item.base_updated_at)) {
    const fetched = await fetchForLocalSnapshot(userId, db, item);
    if (!serverIdentityMatches(fetched.draft, item)) throw new Error("server_draft_case_mismatch");
    if (Date.parse(fetched.draft.updated_at) <= Date.parse(item.base_updated_at)) {
      return { applied: false, conflict: false, message: null, draftId: item.id };
    }
    const prefill = prefillFromStored(await getDraftPrefill<Record<string, unknown>>(db, item.id));
    const applied = await storeServerWinner(db, item, fetched,
      { instrumentId: draft.instrumentId, instrumentVersion: draft.instrumentVersion, currentSection: draft.currentSection },
      prefill);
    return {
      applied,
      conflict: true,
      message: applied ? SYNC_MESSAGE : LOCAL_CHANGE_MESSAGE,
      draftId: item.id
    };
  }
  const answersJson = JSON.stringify(draft.data);
  let answersHash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, answersJson)).toLowerCase();
  const send = () => authedRequest<unknown>(userId, `${INTAKE_API}/drafts/sync`, {
    method: "POST",
    timeoutMs: 120_000,
    bodyFactory: () => ({
      project_id: item.project_id,
      site_id: item.site_id,
      ...(item.org_unit_id ? { org_unit_id: item.org_unit_id } : {}),
      death_id: item.death_id,
      client_draft_id: item.id,
      answers_json: answersJson,
      answers_sha256: answersHash,
      draft: metadataForSync(draft),
      savedAt: item.updated_at,
      deviceClockAt: localDateTimeWithOffset(),
      base_updated_at: item.base_updated_at
    })
  });

  let response: { status: number; body: unknown };
  try {
    response = await send();
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.code === "conflict") {
      await db.runAsync(`UPDATE drafts SET draft_sync_blocked = 1
        WHERE id = ? AND envelope = ? AND updated_at = ? AND completed = 0 AND draft_sync_blocked = 0`,
      [item.id, item.envelope, item.updated_at]);
      throw error;
    }
    if (!(error instanceof ApiError) || error.status !== 422 || error.code !== "answers_hash_invalid") throw error;
    answersHash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, answersJson)).toLowerCase();
    try {
      response = await send();
    } catch (retryError) {
      if (!(retryError instanceof ApiError) || retryError.status !== 422 || retryError.code !== "answers_hash_invalid") throw retryError;
      await db.runAsync(`UPDATE drafts SET upload_issue = 'answers_hash_invalid',
        upload_issue_unique_id = NULL, draft_sync_dirty = 1
        WHERE id = ? AND envelope = ? AND updated_at = ? AND completed = 0 AND draft_sync_blocked = 0`,
      [item.id, item.envelope, item.updated_at]);
      throw retryError;
    }
  }

  const body = response.body;
  if (response.status !== 200 || !isRecord(body) || (body.kept !== "incoming" && body.kept !== "server") ||
      typeof body.conflict !== "boolean" || (body.message !== null && typeof body.message !== "string")) {
    throw new Error("invalid_draft_sync_response");
  }
  const server = serverSummary(body.draft);
  if (server.status !== "draft" || !serverIdentityMatches(server, item) ||
      (item.server_draft_id && server.draft_id !== item.server_draft_id)) {
    throw new Error("invalid_draft_sync_response");
  }
  if (body.kept === "incoming" && (typeof body.answers_sha256 !== "string" || body.answers_sha256.toLowerCase() !== answersHash)) {
    throw new Error("invalid_draft_sync_response");
  }
  if (body.kept === "server" && body.answers_sha256 !== null &&
      (typeof body.answers_sha256 !== "string" || !/^[0-9a-f]{64}$/i.test(body.answers_sha256))) {
    throw new Error("invalid_draft_sync_response");
  }

  let envelope = item.envelope;
  let savedAt = item.updated_at;
  if (body.kept === "server") {
    const prefill = prefillFromStored(await getDraftPrefill<Record<string, unknown>>(db, item.id));
    const serverEnvelopeValue = serverEnvelope(body.envelope, server.draft_id);
    const merged = normalizedEnvelope(
      serverEnvelopeValue,
      server,
      item.id,
      { instrumentId: draft.instrumentId, instrumentVersion: draft.instrumentVersion, currentSection: draft.currentSection },
      prefill,
      draft.startedAt,
      draft.createdAt
    );
    envelope = JSON.stringify(merged);
    savedAt = server.updated_at;
  }

  const persisted = await db.runAsync(`UPDATE drafts SET envelope = ?, updated_at = ?,
      server_draft_id = ?, base_updated_at = ?, draft_sync_dirty = 0
    WHERE id = ? AND envelope = ? AND updated_at = ? AND completed = 0 AND draft_sync_blocked = 0`,
  [envelope, savedAt, server.draft_id, server.updated_at, item.id, item.envelope, item.updated_at]);
  const applied = resultChanges(persisted);
  return {
    applied,
    conflict: body.conflict || !applied,
    message: applied ? (body.conflict ? SYNC_MESSAGE : null) : LOCAL_CHANGE_MESSAGE,
    draftId: item.id
  };
}

async function readSyncItem(db: Db, id: string): Promise<DraftSyncItem | null> {
  const row = await db.getFirstAsync<Omit<DraftSyncItem, "draft">>(
    `SELECT id, project_id, site_id, org_unit_id, completed, updated_at, death_id, unique_id,
            client_death_id, upload_issue, upload_issue_unique_id, server_draft_id, base_updated_at,
            draft_sync_dirty, draft_sync_blocked, envelope
       FROM drafts WHERE id = ?`,
    [id]
  );
  if (!row || !row.project_id || !row.death_id) return null;
  return { ...row, draft: JSON.parse(row.envelope) as DeviceTimedDraft };
}

function caseDraftIdentity(caseDetail: CaseDetail): Pick<DraftSyncItem, "project_id" | "site_id" | "org_unit_id" | "death_id"> {
  return {
    project_id: caseDetail.project_id,
    site_id: caseDetail.site_id,
    org_unit_id: caseDetail.org_unit_id,
    death_id: caseDetail.death_id
  };
}

function caseIsOpen(caseDetail: CaseDetail): boolean {
  return canStartDeathInterview(caseDetail.state);
}

async function storeServerWinner(
  db: Db,
  local: DraftSyncItem,
  fetched: FetchedServerDraft,
  defaults: DraftSyncDefaults,
  prefill: Record<string, unknown>,
): Promise<boolean> {
  const localDraft = parseLocalEnvelope(local);
  const merged = normalizedEnvelope(
    fetched.envelope,
    fetched.draft,
    local.id,
    defaults,
    prefill,
    localDraft.startedAt,
    localDraft.createdAt
  );
  const result = await db.runAsync(`UPDATE drafts SET envelope = ?, updated_at = ?,
      server_draft_id = ?, base_updated_at = ?, draft_sync_dirty = 0
    WHERE id = ? AND envelope = ? AND updated_at = ? AND completed = 0 AND draft_sync_blocked = 0`,
  [JSON.stringify(merged), fetched.draft.updated_at, fetched.draft.draft_id, fetched.draft.updated_at,
    local.id, local.envelope, local.updated_at]);
  return resultChanges(result);
}

async function insertServerDraft(
  db: Db,
  caseDetail: CaseDetail,
  fetched: FetchedServerDraft,
  localId: string,
  defaults?: DraftSyncDefaults,
): Promise<{ row: DraftRow | null; imported: boolean }> {
  const existing = await draftForCase(db, { deathId: caseDetail.death_id });
  if (existing) return { row: existing, imported: false };
  if (!defaults) throw new Error("draft_defaults_required");
  const identity = caseDraftIdentity(caseDetail);
  if (!serverIdentityMatches(fetched.draft, identity)) throw new Error("server_draft_case_mismatch");
  const startedAt = fetched.draft.created_at;
  const draft = normalizedEnvelope(fetched.envelope, fetched.draft, localId, defaults, fetched.prefill,
    startedAt, fetched.draft.created_at);
  const result = await db.runAsync(`INSERT INTO drafts (
      id, project_id, site_id, org_unit_id, completed, updated_at, envelope,
      death_id, unique_id, client_death_id, prefill, server_draft_id, base_updated_at,
      draft_sync_dirty, draft_sync_blocked
    )
    SELECT ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, ?, ?, ?, 0, 0
    WHERE NOT EXISTS (SELECT 1 FROM drafts WHERE death_id = ?)
      AND NOT EXISTS (SELECT 1 FROM drafts WHERE id = ?)`, [
    localId, caseDetail.project_id, caseDetail.site_id, caseDetail.org_unit_id,
    fetched.draft.updated_at, JSON.stringify(draft), caseDetail.death_id,
    fetched.draft.unique_id ?? caseDetail.unique_id,
    JSON.stringify(fetched.prefill), fetched.draft.draft_id, fetched.draft.updated_at,
    caseDetail.death_id, localId
  ]);
  if (resultChanges(result)) return { row: await getDraftRow(db, localId), imported: true };
  return { row: await draftForCase(db, { deathId: caseDetail.death_id }), imported: false };
}

/** Preserve local history, syncing it before any newer server copy can replace it. */
export async function reconcileCaseDraft(
  userId: string,
  db: Db,
  caseDetail: CaseDetail,
  local: DraftRow | null,
  newLocalId: string,
  defaults?: DraftSyncDefaults,
): Promise<CaseDraftReconcileResult> {
  let current = local ? await readSyncItem(db, local.id) : null;
  if (local && !current) return { draft: null, conflict: false, message: null, imported: false };
  if (current && !serverIdentityMatches(current, caseDraftIdentity(caseDetail))) {
    throw new Error("local_draft_case_mismatch");
  }

  if (!current && caseDetail.my_draft_id) {
    const existing = await draftForCase(db, { deathId: caseDetail.death_id });
    if (existing) return { draft: existing, conflict: false, message: null, imported: false };
    if (!caseIsOpen(caseDetail)) return { draft: null, conflict: false, message: null, imported: false };
    const fetched = await fetchServerDraft(userId, caseDetail.my_draft_id);
    const imported = await insertServerDraft(db, caseDetail, fetched, newLocalId, defaults);
    return { draft: imported.row, conflict: false, message: null, imported: imported.imported };
  }
  if (!current) return { draft: null, conflict: false, message: null, imported: false };
  if (current.completed || current.upload_issue || current.draft_sync_blocked) {
    return { draft: await getDraftRow(db, current.id), conflict: false, message: null, imported: false };
  }

  let conflict = false;
  let message: string | null = null;
  if (current.draft_sync_dirty || !current.server_draft_id || !current.base_updated_at) {
    const synced = await syncDraftSnapshot(userId, db, current);
    current = await readSyncItem(db, current.id);
    if (!synced.applied || !current) {
      return { draft: current ? await getDraftRow(db, current.id) : null, conflict: true,
        message: synced.message ?? LOCAL_CHANGE_MESSAGE, imported: false };
    }
    conflict = synced.conflict;
    message = synced.message;
    if (current.draft_sync_blocked) return { draft: await getDraftRow(db, current.id), conflict, message, imported: false };
  }

  if (!caseIsOpen(caseDetail)) return { draft: await getDraftRow(db, current.id), conflict, message, imported: false };
  const serverId = caseDetail.my_draft_id ?? current.server_draft_id;
  if (!serverId) return { draft: await getDraftRow(db, current.id), conflict, message, imported: false };
  if (current.server_draft_id && current.server_draft_id !== serverId) {
    return { draft: await getDraftRow(db, current.id), conflict: true, message: LOCAL_CHANGE_MESSAGE, imported: false };
  }

  const fetched = current.draft_sync_dirty === 0 && current.server_draft_id === serverId
    ? await fetchForLocalSnapshot(userId, db, current)
    : await fetchServerDraft(userId, serverId);
  if (!serverIdentityMatches(fetched.draft, caseDraftIdentity(caseDetail))) throw new Error("server_draft_case_mismatch");
  if (current.base_updated_at && Date.parse(fetched.draft.updated_at) > Date.parse(current.base_updated_at)) {
    const storedPrefill = await getDraftPrefill<Record<string, unknown>>(db, current.id);
    const prefill = Object.keys(fetched.prefill).length ? fetched.prefill : prefillFromStored(storedPrefill);
    const applied = await storeServerWinner(db, current, fetched, defaults ?? {
      instrumentId: parseLocalEnvelope(current).instrumentId,
      instrumentVersion: parseLocalEnvelope(current).instrumentVersion,
      currentSection: parseLocalEnvelope(current).currentSection
    }, prefill);
    if (!applied) return { draft: await getDraftRow(db, current.id), conflict: true, message: LOCAL_CHANGE_MESSAGE, imported: false };
    return { draft: await getDraftRow(db, current.id), conflict: true, message: SYNC_MESSAGE, imported: false };
  }
  return { draft: await getDraftRow(db, current.id), conflict, message, imported: false };
}
