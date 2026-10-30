/**
 * Push and purge for one interviewer, in dependency order:
 *
 * 1. deaths registered offline (POST /deaths, idempotent on client_death_id);
 *    each acknowledgement rebinds the drafts and actions waiting on it;
 * 2. queued contact attempts and visit dates (idempotent on client_attempt_id;
 *    a visit is idempotent by value);
 * 3. completed interviews (POST /submissions, idempotent on client_draft_id);
 *    steps 1-3 run for every project on the phone, before the access refresh,
 *    so a project that has left the worker's access still has its unsent
 *    work tried (owner decision 2026-10-22: unsent work is never purged);
 * 4. the access and settings refresh;
 * 5. unfinished registered-case drafts (POST /drafts/sync) and revisions of
 *    the projects still in access;
 * 6. the outstanding-work report (what is still on the phone);
 * 7. the case download (GET /cases, every page), replacing the stored cases.
 *
 * Each item is deleted once the server acknowledges it. A 422 reopens it for
 * editing (a draft goes back to in progress; a registration or action is
 * marked needs_edit); a 404/409 on an action also marks it needs_edit, since
 * it can no longer apply and would be refused on every sync. A 409 on an
 * interview holds it (upload_issue case_conflict) until the interviewer
 * sends it again; the server's reason is kept per item (src/unsentWork.ts)
 * and shown. A respondent consent decision travels with the registration
 * and with the interview it was taken for; a refusal strips the covered
 * answers from what is sent (src/consentStore.ts). Also the
 * per-interviewer reference data (access-scoped organization units, form
 * options, prefill policy and translations), cached in that interviewer's own
 * database and wiped with it. A validated superseded acknowledgement is
 * reported immediately, so a later refresh failure cannot hide its notice.
 *
 * Logs carry client ids and error codes only, never answers or names.
 */
import { clockOffsetField } from "./phoneClock";
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";
import { ApiError, INTAKE_API, isSmartVaTarget, parseAccessSummary, type AccessSummary, type SmartVaTarget } from "./api";
import { authedRawRequest, authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import { identifierFieldErrors, type IdentifierType } from "./identifiers";
import {
  acknowledgeRegistration,
  ACTIVE_CASE_STATES,
  deleteCase,
  getCase,
  isCaseDetail,
  isActiveCaseState,
  deleteAction,
  listActions,
  listRegistrations,
  replaceCases,
  listCases,
  setActionState,
  setRegistrationRefusal,
  setRegistrationState,
  upsertCase,
  type CaseDetail,
  type CaseRow
} from "./cases";
import {
  completedDraft,
  completedDrafts,
  clearRefusedDraft,
  invalidateCodingHistory,
  countDrafts,
  countUnsentWork,
  draftIds,
  draftUniqueIds,
  getMeta,
  deleteDraftSnapshot,
  getOfflineCoding,
  pruneDraftAttachments,
  localDateTimeWithOffset,
  projectIds,
  purgeProjectData,
  reopenDraft,
  setDraftUploadIssue,
  setMeta,
  unfinishedDraftsForSync,
  type CompletedDraft,
  type Completion,
  type Db,
  type OfflineCodingRow,
  type OfflineCodingSnapshot
} from "./drafts";
import { getOrCreatePlusDeviceIdentity } from "./offlineIdentity";
import { codingReceiptSha256 } from "./codingReceipt";
import { recordCodingOutcome } from "./codingUploadNotices";
import { acquireDraftUpload } from "./localCodingLeases";
import { getStandaloneConsent } from "./standaloneConsentStore";
import { syncDraftSnapshot, type DraftSyncDefaults } from "./draftSync";
import { syncQueuedRevisions } from "./revisions";
import { deleteCoveredAttachments, markDraftUnconfirmed } from "./attachmentStore";
import { uploadDraftAttachments } from "./attachmentUpload";
import { clearSendError, INCOMPLETE_OUTCOMES, isUploadableVerdict, noteSendError } from "./unsentWork";
import { consentFor, deleteDraftConsent, getRegistrationConsent, holdServerRefusal, loadConsents, markInheritedConsentRefused, refreshConsentConfig, type ConsentIndex } from "./consentStore";
import { isRefused, refusalAnswers } from "./refusalBoundary";
import { runInTransaction } from "./dbTransaction";
import { PinnedDefinitionError, readDefinitionPin } from "./formDefinitionRuntime";
import { createNativeDefinitionCache } from "./formDefinitionCache";
import {
  FormDefinitionError,
  downloadCurrentDefinition,
  type DefinitionIdentity,
} from "./formDefinitions";
import { FormDefinitionHistoryError, readDefinitionExtensions } from "./formDefinitionHistory";
import { questionnaireLocales } from "./i18n";
import type { Translations } from "./translations";

export interface SyncResult {
  sent: number;
  failed: number;
  remaining: number;
  supersededUniqueIds: string[];
  serverKeptUploads?: { uniqueId: string; locked: boolean }[];
  canCodeNowUniqueIds?: string[];
  draftConflictIds?: string[];
  revisionAttentionIds?: string[];
  definitionRefresh?: DefinitionRefreshStatus[];
  codingOutcomes?: OfflineCodingOutcome[];
}

/** Outcomes the server accepts for a questionnaire the form reports invalid (web_intake_service._interview_outcome). */
export { INCOMPLETE_OUTCOMES };

/** The case download: pages of the server's maximum, at most this many (5000 cases). */
export const CASE_PAGE_SIZE = 200;
export const CASE_PAGES_MAX = 25;
const DRAFT_SYNC_PAGE_SIZE = 100;

/** Reference settings are stable project configuration, not live work. */
export const REFERENCE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const REFERENCE_META_KEY = "referenceData";
const REFERENCE_ATTEMPT_META_KEY = "referenceDataAttemptAt";
const SERVED_DEFINITION_META_KEY = "servedDefinition";
const BUNDLED_INSTRUMENT_CODE = "WHO_2022_VA";
// Keep this cache identity tied to the generated instrument shipped by the
// vendored package. The device bootstrap's instrument_version is a web
// bundle checksum, so it is intentionally not compared to this value.
const BUNDLED_INSTRUMENT_VERSION = "2026081401";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Compose the current project instrument identity for validating imported drafts. */
export function draftSyncDefaults(project: ProjectSettings): DraftSyncDefaults {
  const instrumentCode = project.form_options?.form_types?.find((item) => item.is_default)?.instrument_code;
  if (instrumentCode && instrumentCode !== BUNDLED_INSTRUMENT_CODE) throw new Error("instrument_incompatible");
  const instrument = createWhoVa2022Instrument(project.form_options?.enabled_extensions ?? []);
  const currentSection = instrument.sections[0]?.name;
  if (!currentSection) throw new Error("instrument_incompatible");
  return { instrumentId: instrument.id, instrumentVersion: instrument.version, currentSection };
}

/** Whether the server will take this interview: the form said valid, or the interviewer recorded an incomplete outcome. */
export function isUploadable(data: CompletedDraft["draft"]["data"] | undefined, completion: Completion | null): boolean {
  return isUploadableVerdict(completion?.valid === true, data?.interview_outcome);
}

/** 403 codes that gate the whole account rather than one project's rows. */
const ACCOUNT_GATE_CODES = new Set(["terms_required", "password_change_required", "maintenance", "no_collection_access"]);

/**
 * Session, network and account-wide failures stop the run with everything
 * kept; anything but an API refusal is rethrown. A per-project 403 (a paused
 * project, a withdrawn grant) is a refusal of that row only, so it cannot
 * stop the other projects' work from being sent.
 */
function refusal(error: unknown): ApiError {
  if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 403 && ACCOUNT_GATE_CODES.has(error.code ?? "")) throw error;
  return error;
}

/** The public demo's per-account limits (docs/policy/public-demo.md section 8): 429 `demo_limit`. */
export const isDemoLimit = (error: ApiError) => error.status === 429 && error.code === "demo_limit";

const PAUSED_META_PREFIX = "paused:";

/** A project with unsent work on the phone that is no longer in this worker's access. */
export interface PausedProject {
  projectId: string;
  projectName?: string;
  /** The server's last refusal of this project's work (status and code only). */
  refusal?: { status: number; code?: string };
}

/** Remember the server's refusal of a paused project's row so the worklist can show it. */
async function notePausedRefusal(db: Db, projectId: string | null, refused: ApiError): Promise<void> {
  if (!projectId || refused.status !== 403) return;
  const current = await getMeta<Omit<PausedProject, "projectId">>(db, PAUSED_META_PREFIX + projectId);
  await setMeta(db, PAUSED_META_PREFIX + projectId, {
    ...current,
    refusal: { status: refused.status, ...(refused.code ? { code: refused.code } : {}) },
  });
}

/**
 * Keep or clear the pause notice of each local project after an access
 * change: a project back in access loses it; one out of access with unsent
 * work keeps its name for the worklist.
 */
async function recordPausedProjects(
  db: Db,
  localProjectIds: Iterable<string>,
  interviewProjectIds: Set<string>,
  names: Map<string, string>,
): Promise<void> {
  // The interview set matches the worklist's (listPausedProjects): a project
  // kept only for registration still shows its unsent drafts as paused.
  for (const projectId of localProjectIds) {
    const key = PAUSED_META_PREFIX + projectId;
    if (interviewProjectIds.has(projectId) || (await countUnsentWork(db, projectId)) === 0) {
      await db.runAsync("DELETE FROM meta WHERE key = ?", [key]);
      continue;
    }
    const current = await getMeta<Omit<PausedProject, "projectId">>(db, key);
    const projectName = names.get(projectId) ?? current?.projectName;
    await setMeta(db, key, { ...current, ...(projectName ? { projectName } : {}) });
  }
}

/** Projects with unsent work on the phone that have left this worker's access, with the reason recorded. */
export async function listPausedProjects(db: Db, authorizedProjectIds: Set<string>): Promise<PausedProject[]> {
  const paused: PausedProject[] = [];
  for (const projectId of await projectIds(db)) {
    if (authorizedProjectIds.has(projectId) || (await countUnsentWork(db, projectId)) === 0) continue;
    const notice = await getMeta<Omit<PausedProject, "projectId">>(db, PAUSED_META_PREFIX + projectId);
    paused.push({ ...notice, projectId });
  }
  return paused;
}

function acknowledgedCase(body: unknown): { deathId: string; state: string } {
  if (!body || typeof body !== "object") throw new Error("invalid_case_ack");
  const acknowledged = (body as { case?: unknown }).case;
  if (!acknowledged || typeof acknowledged !== "object") throw new Error("invalid_case_ack");
  const deathId = (acknowledged as { death_id?: unknown }).death_id;
  // Offline submission serialization still exposes the case's `status`; case
  // action replies use the unified detail field `state`.
  const state = (acknowledged as { state?: unknown }).state ?? (acknowledged as { status?: unknown }).status;
  if (typeof deathId !== "string" || deathId.length === 0 || typeof state !== "string" || state.length === 0) {
    throw new Error("invalid_case_ack");
  }
  return { deathId, state };
}

/** Validate an upload's case envelope, allowing nullable fields only for an unbound direct interview. */
function acknowledgedUploadCase(body: unknown, expectedDeathId: string | null): void {
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("invalid_case_ack");
  const acknowledged = (body as { case?: unknown }).case;
  if (!acknowledged || typeof acknowledged !== "object" || Array.isArray(acknowledged)) {
    throw new Error("invalid_case_ack");
  }
  const deathId = (acknowledged as { death_id?: unknown }).death_id;
  const state = (acknowledged as { state?: unknown; status?: unknown }).state ??
    (acknowledged as { status?: unknown }).status;
  if (expectedDeathId !== null) {
    if (typeof deathId !== "string" || !deathId || deathId !== expectedDeathId || typeof state !== "string" || !state) {
      throw new Error("invalid_case_ack");
    }
  } else if (
    (deathId !== null && (typeof deathId !== "string" || !deathId)) ||
    (state !== null && (typeof state !== "string" || !state))
  ) {
    throw new Error("invalid_case_ack");
  }
}

async function purgeTerminalAcknowledgement(db: Db, projectId: string, body: unknown): Promise<void> {
  if (!body || typeof body !== "object" || !("case" in body)) return;
  const acknowledged = (body as { case?: unknown }).case;
  if (!acknowledged || typeof acknowledged !== "object") return;
  const deathId = (acknowledged as { death_id?: unknown }).death_id;
  const state = (acknowledged as { state?: unknown }).state;
  if (typeof deathId === "string" && deathId.length > 0 && typeof state === "string" && !isActiveCaseState(state)) {
    await deleteCase(db, projectId, deathId);
  }
}

/**
 * The answers an upload sends for one completed draft, their JSON and its SHA-256: a refused consent (this
 * interview's or its registration's) never sends the covered answers. The one definition of the hash, so the
 * offline coding screen binds a coding to exactly what the push will send (contract 17 coded_answers_sha256).
 */
export async function sentAnswers(item: CompletedDraft, consents: ConsentIndex) {
  const applied = consentFor(consents, item);
  const sentData = isRefused(item.draft.data, applied?.record.envelope.decision)
    ? refusalAnswers(item.draft.data)
    : item.draft.data;
  const answersJson = JSON.stringify(sentData);
  const answersHash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, answersJson)).toLowerCase();
  return { applied, sentData, answersJson, answersHash };
}

/** The hash a coding saved now is bound to; null when the draft is not a completed interview. */
export async function draftAnswersSha256(db: Db, draftId: string): Promise<string | null> {
  const item = await completedDraft(db, draftId);
  return item ? (await sentAnswers(item, await loadConsents(db))).answersHash : null;
}

/** A coding made on other answers (or before its hash was kept) is stale: it is never sent for these answers. */
export const isCodingStale = (row: Pick<OfflineCodingRow, "answers_sha256">, answersHash: string) =>
  !row.answers_sha256 || row.answers_sha256.toLowerCase() !== answersHash.toLowerCase();

/** Where a standalone (Path C) store's interviews go once the user adopted them into an enrolled account (contract 17). */
export interface StandalonePush {
  projectId: string;
  siteId: string;
  clientDeviceUuid: string;
  profileSnapshot: { name: string | null; designation: string | null; facility: string | null; country: string | null };
  /** A unit code claim, already checked against the server's pattern; null routes by the project's fallback. */
  orgCode: string | null;
}

/** The reply's verdict on the offline coding sent with a standalone interview. */
export type OfflineCodingOutcome = { draftId: string; status: "pending" | "applied" | "refused"; code: string | null; codingSha256: string };

const PROCESS_TOKEN = /^local-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HEX64 = /^[0-9a-f]{64}$/;
const hex64OrNull = (value: string | null) => (value && HEX64.test(value.toLowerCase()) ? value.toLowerCase() : null);
const parsedObject = (text: string | null) => {
  if (!text) return null;
  const value: unknown = JSON.parse(text);
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
};

/**
 * The contract 17 `offline_coding` object for a coding row, or null when it must not be sent: not a coded final,
 * no allowability provenance, coded on other answers (stale) or on another phone, or a token the server refuses.
 * conclusive_cod is the code alone: the phone keeps no title and the server takes it from its own MMS row.
 */
export function offlineCodingBody(row: OfflineCodingRow, answersHash: string, clientDeviceUuid: string) {
  if (row.status !== "coded" || !row.ucod_code || !row.provenance || isCodingStale(row, answersHash)) return null;
  if (row.device_uuid !== clientDeviceUuid || !PROCESS_TOKEN.test(row.process_token)) return null;
  // `packVersions` (which engine coded this, src/workspace/offlineDoris.ts) travels as the contract's `pack_versions`,
  // not inside `provenance`, whose keys the server fixes.
  const { packVersions, ...provenance } = JSON.parse(row.provenance) as { allowability?: { rules?: unknown }; packVersions?: unknown };
  if (!provenance.allowability) return null;
  const rules = provenance.allowability.rules;
  const engineVersions = Object.fromEntries(
    Object.entries(packVersions && typeof packVersions === "object" && !Array.isArray(packVersions) ? packVersions : {}).filter(([, version]) => typeof version === "string"),
  );
  return {
    coded_answers_sha256: answersHash,
    device_uuid: clientDeviceUuid,
    process_token: row.process_token,
    conclusive_cod: row.ucod_code,
    remark: null,
    certificate: parsedObject(row.certificate),
    result: parsedObject(row.result),
    codedit_result: parsedObject(row.codedit_result),
    certificate_digest: hex64OrNull(row.certificate_digest),
    result_digest: hex64OrNull(row.result_digest),
    provenance,
    pack_versions: { ...engineVersions, ...(typeof rules === "string" ? { allowability: rules } : {}) },
  };
}

/** The reply's `offline_coding`, required whenever one was sent: without it the coding was not received. */
function codingOutcome(body: { offline_coding?: unknown }, draftId: string, sentDigest: string): OfflineCodingOutcome {
  const value = body.offline_coding as { status?: unknown; code?: unknown; coding_sha256?: unknown } | null | undefined;
  if (!value || typeof value !== "object" || !["pending", "applied", "refused"].includes(value.status as string) ||
      (value.code !== null && typeof value.code !== "string") ||
      typeof value.coding_sha256 !== "string" || !HEX64.test(value.coding_sha256) || value.coding_sha256 !== sentDigest) {
    throw new Error("invalid_upload_ack");
  }
  return { draftId, status: value.status as OfflineCodingOutcome["status"], code: (value.code as string | null) ?? null,
    codingSha256: value.coding_sha256 };
}

/** Standalone refusals shown and held, never resent or reopened on their own (contract 17: consent is terminal). */
const STANDALONE_HELD_422 = new Set(["consent_invalid", "consent_required", "consent_conflict", "standalone_invalid", "offline_coding_invalid"]);

/** What one upload pass sent, refused and learned; the rows themselves stay until acknowledged. */
export interface UploadResult {
  sent: number;
  failed: number;
  supersededUniqueIds: string[];
  serverKeptUploads: { uniqueId: string; locked: boolean }[];
  canCodeNowUniqueIds: string[];
  /** The server's verdict on each offline coding sent, for enrolled and standalone pushes alike. */
  codingOutcomes: OfflineCodingOutcome[];
  /** Standalone push only: the drafts whose coding was stale and therefore was not sent. */
  staleCodingDraftIds?: string[];
}

/**
 * Send every queued registration, contact attempt or visit, and completed
 * interview on the phone, in every project it holds, including a project
 * that has left this worker's access: the server decides, and a refusal
 * keeps the row and is recorded for the worklist (listPausedProjects).
 *
 * With `standalone`, `db` is a standalone store and `userId` the enrolled
 * account it was adopted into: each interview goes to that project and site
 * with the contract 17 `standalone` object and, when fresh, its offline
 * coding; the draft and its coding are deleted together on the 2xx only.
 */
export async function uploadQueuedWork(
  userId: string,
  db: Db,
  callbacks: {
    onSuperseded?: (uniqueId: string) => void;
    onServerKept?: (notice: { uniqueId: string; locked: boolean }) => void;
    onCanCodeNow?: (uniqueId: string) => void;
    standalone?: StandalonePush;
  } = {}
): Promise<UploadResult> {
  const { onSuperseded, onServerKept, onCanCodeNow, standalone } = callbacks;
  const codingOutcomes: OfflineCodingOutcome[] = [];
  const staleCodingDraftIds: string[] = [];
  let enrolledDeviceUuid: string | null | undefined;
  let sent = 0;
  let failed = 0;
  const supersededUniqueIds: string[] = [];
  const serverKeptUploads: { uniqueId: string; locked: boolean }[] = [];
  const canCodeNowUniqueIds: string[] = [];

  async function currentEnrolledDeviceUuid(): Promise<string | null> {
    if (enrolledDeviceUuid === undefined) {
      try {
        enrolledDeviceUuid = (await getOrCreatePlusDeviceIdentity())?.uuid ?? null;
      } catch {
        enrolledDeviceUuid = null;
      }
    }
    return enrolledDeviceUuid;
  }

  for (const reg of await listRegistrations(db)) {
    if (reg.state !== "pending") continue;
    const registrationFields = reg.fields as unknown as Record<string, unknown>;
    const refusalOnly = registrationFields.refusal_only === true;
    try {
      // The consent decision taken for the informant details travels with the registration (contract 5.4);
      // a refusal never sends them.
      const consent = await getRegistrationConsent(db, reg.client_death_id);
      if (refusalOnly) {
        if (consent?.envelope.decision !== "refused") throw new ApiError(422, "consent_invalid");
        const profile = refusalAnswers(registrationFields);
        const { body } = await authedRequest<{ client_draft_id?: unknown }>(userId, `${INTAKE_API}/refusals`, {
          method: "POST", body: { client_draft_id: reg.client_death_id, project_id: reg.project_id, site_id: reg.site_id,
            ...(reg.org_unit_id ? { org_unit_id: reg.org_unit_id } : {}), ...profile, consent: consent.envelope },
        });
        if (body?.client_draft_id !== reg.client_death_id) throw new Error("invalid_refusal_receipt");
        await runInTransaction(db, async (tx) => {
          const result = await tx.runAsync("DELETE FROM registrations WHERE client_death_id = ? AND fields = ? AND state = 'pending'", [reg.client_death_id, JSON.stringify(reg.fields)]);
          if (result && typeof result === "object" && "changes" in result && Number(result.changes) === 1) {
            await tx.runAsync("DELETE FROM meta WHERE key = ?", [`consent:reg:${reg.client_death_id}`]);
          }
        });
        await clearSendError(db, reg.client_death_id);
        sent += 1;
        continue;
      }
      if (consent?.envelope.decision === "refused") {
        await setRegistrationState(db, reg.client_death_id, "needs_edit");
        await noteSendError(db, reg.client_death_id, "consent_refused");
        failed += 1;
        continue;
      }
      const fields = reg.fields;
      const { body } = await authedRequest<{ case: CaseDetail }>(userId, `${INTAKE_API}/deaths`, {
        method: "POST",
        body: {
          project_id: reg.project_id,
          client_death_id: reg.client_death_id,
          site_id: reg.site_id,
          ...(reg.org_unit_id ? { org_unit_id: reg.org_unit_id } : {}),
          ...fields,
          ...(consent ? { consent: consent.envelope } : {})
        }
      });
      if (!isCaseDetail(body?.case) || body.case.project_id !== reg.project_id) throw new Error("invalid_case_detail");
      await acknowledgeRegistration(db, reg.client_death_id, body.case);
      await clearSendError(db, reg.client_death_id);
      sent += 1;
    } catch (error) {
      await noteSendError(db, reg.client_death_id, error);
      const refused = refusal(error);
      console.warn(`registration refused id=${reg.client_death_id} status=${refused.status} code=${refused.code ?? "-"}`);
      await notePausedRefusal(db, reg.project_id, refused);
      // The public demo's limit (429 demo_limit) is final: shown as needing the
      // interviewer, never resent by the next sync.
      if (isDemoLimit(refused)) await setRegistrationState(db, reg.client_death_id, "needs_edit");
      if (refused.status === 422) {
        // An unusable consent decision is dropped so the registration screen asks again.
        if (!refusalOnly && refused.code?.startsWith("consent_")) await db.runAsync("DELETE FROM meta WHERE key = ?", [`consent:reg:${reg.client_death_id}`]);
        const numbers = identifierFieldErrors(refused);
        if (Object.keys(numbers).length) await setRegistrationRefusal(db, reg.client_death_id, numbers);
        await setRegistrationState(db, reg.client_death_id, "needs_edit");
      }
      if (refusalOnly && refused.status === 409) await setRegistrationState(db, reg.client_death_id, "needs_edit");
      failed += 1;
    }
  }

  for (const action of await listActions(db)) {
    if (action.state !== "pending" || !action.death_id) continue; // waits for its registration
    const path = `${INTAKE_API}/cases/${encodeURIComponent(action.death_id)}/${action.kind === "attempt" ? "attempts" : "visit"}`;
    try {
      const acknowledgement = await authedRequest<unknown>(userId, path, {
        method: "POST",
        body:
          action.kind === "attempt"
            ? { client_attempt_id: action.client_id, ...action.body }
            : { next_visit_at: action.body.next_visit_at ?? null }
      });
      await purgeTerminalAcknowledgement(db, action.project_id, acknowledgement.body);
      await deleteAction(db, action.client_id);
      await clearSendError(db, action.client_id);
      sent += 1;
    } catch (error) {
      await noteSendError(db, action.client_id, error);
      const refused = refusal(error);
      console.warn(`case action refused id=${action.client_id} status=${refused.status} code=${refused.code ?? "-"}`);
      await notePausedRefusal(db, action.project_id, refused);
      if ([404, 409, 422].includes(refused.status)) await setActionState(db, action.client_id, "needs_edit");
      failed += 1;
    }
  }

  draftLoop: for (const candidate of await completedDrafts(db)) {
    let item = candidate;
    if (!item.project_id) continue;
    const releaseUpload = acquireDraftUpload(userId, item.id);
    if (!releaseUpload) continue;
    try {
      const consents = await loadConsents(db);
      const decision = consentFor(consents, item)?.record.envelope.decision;
      if (isRefused(item.draft.data, decision)) {
        await clearRefusedDraft(db, item.id);
        const cleaned = await completedDraft(db, item.id);
        if (!cleaned) continue draftLoop;
        item = cleaned;
      }
      if (!item.project_id) continue draftLoop;
      try {
        readDefinitionPin(item.draft);
      } catch (error) {
        if (!(error instanceof PinnedDefinitionError)) throw error;
        await setDraftUploadIssue(db, item.id, "invalid_definition_pin");
        await noteSendError(db, item.id, "invalid_definition_pin");
        failed += 1;
        continue draftLoop;
      }
    if (!isUploadable(item.draft.data, item.completion)) {
      // Stays on the phone; the Sync sheet lists it as needing attention rather than leaving it silent.
      await noteSendError(db, item.id, "not_ready");
      continue;
    }
    if (item.client_death_id && !item.death_id) continue; // its registration is not accepted yet
    // A refusal (this interview's, or its registration's) never sends the covered answers, so the hash covers
    // only what is sent. A decision taken for this interview travels with it (contract 5.3).
    const { applied, sentData, answersJson, answersHash: sentHash } = await sentAnswers(item, consents);
    const refusedInterview = isRefused(item.draft.data, applied?.record.envelope.decision);
    const resumeRefused = !refusedInterview && !!item.base_updated_at && await getMeta<boolean>(db, `consent:resume-who:${item.id}`) === true;
    if (applied?.record.envelope.decision === "refused") await deleteCoveredAttachments(db, item.id, applied.record.covered_fields);
    const sentDraft = sentData === item.draft.data ? item.draft : { ...item.draft, data: sentData };
    // A standalone interview goes to the adopted project and site; the server routes it by the org code claim.
    const target = standalone ? { ...item, project_id: standalone.projectId, site_id: standalone.siteId, org_unit_id: null } : item;
    let standaloneFields: Record<string, unknown> = {};
    let codingSent = false;
    let codingSnapshot: OfflineCodingSnapshot | null = null;
    const row = refusedInterview ? null : await getOfflineCoding(db, item.id);
    if (row) codingSnapshot = { updated_at: row.updated_at };
    let coding: ReturnType<typeof offlineCodingBody> = null;
    if (!standalone && row) {
      const deviceUuid = await currentEnrolledDeviceUuid();
      try {
        coding = deviceUuid ? offlineCodingBody(row, sentHash, deviceUuid) : null;
      } catch {
        coding = null;
      }
      if (!coding) {
        await noteSendError(db, item.id, "offline_coding_not_sendable");
        failed += 1;
        continue draftLoop;
      }
      codingSent = true;
      standaloneFields = { offline_coding: coding };
    }
    if (standalone) {
      coding = row ? offlineCodingBody(row, sentHash, standalone.clientDeviceUuid) : null;
      if (row?.status === "coded" && isCodingStale(row, sentHash)) staleCodingDraftIds.push(item.id);
      codingSent = coding !== null;
      standaloneFields = {
        standalone: {
          client_device_uuid: standalone.clientDeviceUuid,
          profile_snapshot: standalone.profileSnapshot,
          org_code: standalone.orgCode,
          // The standalone record replaces the 5.3 consent key: the server refuses both (400).
          consent: (await getStandaloneConsent(db, item.id)) ?? null,
        },
        ...(coding ? { offline_coding: coding } : {}),
      };
    }
    // Files first, and the interview only when the server holds every one (owner rule, digitva-jkvl).
    const files = refusedInterview ? { state: "done" as const } : await uploadDraftAttachments(userId, db, target, sentData);
    if (files.state !== "done") {
      const refused = files.error instanceof Error ? refusal(files.error) : undefined;
      if (refused) await notePausedRefusal(db, item.project_id, refused);
      if (refused?.status === 422 && refused.code === "consent_refused") await holdServerRefusal(db, item.id);
      console.warn(`attachment upload ${files.state} draft=${item.id} status=${refused?.status ?? "-"} code=${refused?.code ?? "-"}`);
      failed += 1;
      continue draftLoop;
    }
    let answersHash = sentHash;
    try {
      const codingDigest = coding ? codingReceiptSha256(coding) : null;
      const send = () => authedRequest<unknown>(userId, `${INTAKE_API}/submissions`, {
        method: "POST",
        timeoutMs: 120_000,
        bodyFactory: () => ({
          client_draft_id: item.id,
          project_id: target.project_id,
          site_id: target.site_id,
          ...(target.org_unit_id ? { org_unit_id: target.org_unit_id } : {}),
          ...(item.death_id ? { death_id: item.death_id } : {}),
          draft: { ...sentDraft, deviceClockAt: localDateTimeWithOffset(), ...clockOffsetField() },
          answers_json: answersJson,
          answers_sha256: answersHash,
          completion: { valid: item.completion?.valid === true, issues: item.completion?.issues ?? [] },
          ...(item.base_updated_at ? { base_updated_at: item.base_updated_at } : {}),
          ...(resumeRefused ? { resume_refused: true } : {}),
          ...(applied?.own && !standalone ? { consent: applied.record.envelope } : {}),
          ...standaloneFields
        })
      });
      let acknowledgement;
      try {
        acknowledgement = await send();
      } catch (error) {
        if (error instanceof ApiError && error.status === 422 && error.code === "answers_hash_invalid") {
          answersHash = (await digestStringAsync(CryptoDigestAlgorithm.SHA256, answersJson)).toLowerCase();
          try {
            acknowledgement = await send();
          } catch (retryError) {
            if (retryError instanceof ApiError && retryError.status === 422 && retryError.code === "answers_hash_invalid") {
              await setDraftUploadIssue(db, item.id, "answers_hash_invalid");
              await noteSendError(db, item.id, retryError);
              console.warn(`submission refused draft=${item.id} status=${retryError.status} code=${retryError.code}`);
              failed += 1;
              continue draftLoop;
            }
            throw retryError;
          }
        } else {
          throw error;
        }
      }
      const responseBody = acknowledgement.body;
      if (!responseBody || typeof responseBody !== "object" || Array.isArray(responseBody)) {
        throw new Error("invalid_upload_ack");
      }
      const body = responseBody as {
        received_sha256?: unknown;
        kept?: unknown;
        locked?: unknown;
        superseded?: unknown;
        can_code_now?: unknown;
        case?: { unique_id?: unknown };
      };
      if (typeof body?.received_sha256 !== "string" || body.received_sha256.toLowerCase() !== answersHash) {
        throw new Error("invalid_answers_ack");
      }
      if (
        (body.kept !== "incoming" && body.kept !== "server") ||
        typeof body.locked !== "boolean" ||
        typeof body.superseded !== "boolean" ||
        (body.superseded && (body.kept !== "server" || !body.locked))
      ) {
        throw new Error("invalid_upload_ack");
      }
      acknowledgedUploadCase(responseBody, item.death_id);
      // pending, applied and refused are all receipt of the coding; a refusal is kept for the user to read.
      if (codingSent) {
        const outcome = codingOutcome(responseBody as { offline_coding?: unknown }, item.id, codingDigest!);
        await recordCodingOutcome(db, outcome);
        await invalidateCodingHistory(db).catch(() => undefined);
        codingOutcomes.push(outcome);
      }
      const acknowledgedUniqueId = body.case?.unique_id;
      if (
        body.can_code_now === true && !body.superseded &&
        typeof acknowledgedUniqueId === "string" && acknowledgedUniqueId.trim()
      ) {
        canCodeNowUniqueIds.push(acknowledgedUniqueId);
        onCanCodeNow?.(acknowledgedUniqueId);
      }
      if (body.superseded || body.kept === "server") {
        if (typeof body.case?.unique_id !== "string" || !body.case.unique_id.trim()) throw new Error("invalid_case_ack");
        if (body.superseded) {
          supersededUniqueIds.push(body.case.unique_id);
          onSuperseded?.(body.case.unique_id);
        } else {
          const notice = { uniqueId: body.case.unique_id, locked: body.locked };
          serverKeptUploads.push(notice);
          onServerKept?.(notice);
        }
      }
      await purgeTerminalAcknowledgement(db, item.project_id, acknowledgement.body);
      // Edited during the send: the draft stays, and files its answers no longer name go.
      if (!(await deleteDraftSnapshot(db, item.id, item.envelope, codingSnapshot))) await pruneDraftAttachments(db, item.id);
      await clearSendError(db, item.id);
      sent += 1;
    } catch (error) {
      // A per-draft refusal (409/413/422) keeps that draft and moves on, with the server's reason stored by
      // noteSendError for the Interviews card and the form. A 422 (the interview as it stands) also reopens it
      // for editing; a refused consent is dropped so the form asks again. A 409 (the case is closed, already
      // submitted or changed) is held until the interviewer retries or discards it: never retried on its own,
      // and never deleted, since this row is the only copy of the answers.
      await noteSendError(db, item.id, error);
      const refused = refusal(error);
      console.warn(`submission refused draft=${item.id} status=${refused.status} code=${refused.code ?? "-"}`);
      await notePausedRefusal(db, item.project_id, refused);
      // A standalone record refused as it stands is held and shown (a 409 by case_conflict below), never reopened.
      const standaloneHeld = standalone && ((refused.status === 403 && refused.code === "device_mismatch") ||
        (refused.status === 422 && STANDALONE_HELD_422.has(refused.code ?? "")));
      if (refused.status === 409 && refused.code === "refusal_stale") {
        const serverId = refused.payload?.draft_id;
        if (typeof serverId === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(serverId)) {
          await db.runAsync("UPDATE drafts SET server_draft_id = ? WHERE id = ? AND (server_draft_id IS NULL OR server_draft_id = ?)", [serverId, item.id, serverId]);
        }
        await setDraftUploadIssue(db, item.id, "refusal_stale");
      } else if (refused.status === 422 && refused.code === "consent_refused") {
        await holdServerRefusal(db, item.id);
      } else if (standaloneHeld) {
        await setDraftUploadIssue(db, item.id, "standalone_refused");
      } else if (refused.status === 422 && refused.code !== "answers_hash_invalid") {
        // Its own decision is dropped; an inherited one (the registration's) is shared, so only this draft is told to ask again.
        if (refused.code?.startsWith("consent_")) {
          if (applied?.own) await deleteDraftConsent(db, item.id);
          else await markInheritedConsentRefused(db, item.id);
        }
        await reopenDraft(db, item.id);
      }
      // The server lost the files (its draft was purged): send them again on the next pass, hold nothing.
      if (refused.status === 409 && refused.code === "attachments_pending") await markDraftUnconfirmed(db, item.id);
      else if (refused.status === 409 && refused.code !== "refusal_stale") await setDraftUploadIssue(db, item.id, "case_conflict");
      // Final until the interviewer asks again (retryHeldDraft): sync skips it.
      if (isDemoLimit(refused)) await setDraftUploadIssue(db, item.id, "demo_limit");
      failed += 1;
    }
    } finally {
      releaseUpload();
    }
  }

  return {
    sent, failed, supersededUniqueIds, serverKeptUploads, canCodeNowUniqueIds,
    codingOutcomes,
    ...(standalone ? { staleCodingDraftIds } : {}),
  };
}

export async function syncInterviewer(
  userId: string,
  db: Db,
  onSuperseded?: (uniqueId: string) => void,
  onDraftConflict?: (draftId: string) => void,
  onServerKept?: (notice: { uniqueId: string; locked: boolean }) => void,
  onCanCodeNow?: (uniqueId: string) => void
): Promise<SyncResult> {
  // Upload before the access refresh: a project that has just left this
  // worker's access still has its unsent work tried, and the server's answer
  // (not a local purge) decides what happens to it.
  const uploads = await uploadQueuedWork(userId, db, { onSuperseded, onServerKept, onCanCodeNow });
  let { sent, failed } = uploads;
  const { supersededUniqueIds, serverKeptUploads, canCodeNowUniqueIds, codingOutcomes } = uploads;
  const draftConflictIds: string[] = [];

  const referenceData = await refreshReferenceData(userId, db, { force: true });
  const authorizedProjects = new Set(referenceData.projects.map(({ project }) => project.project_id));

  // Page by stable local id so a large encrypted draft queue stays bounded.
  // Query one authorized project at a time; each item is sent sequentially.
  for (const { project } of referenceData.projects) {
    let afterId: string | undefined;
    while (true) {
      const snapshots = await unfinishedDraftsForSync(
        db,
        project.project_id,
        afterId,
        DRAFT_SYNC_PAGE_SIZE,
      );
      if (snapshots.length === 0) break;
      for (const item of snapshots) {
        afterId = item.id;
        if (!authorizedProjects.has(item.project_id) || !item.death_id) continue;
        try {
          const result = await syncDraftSnapshot(userId, db, item);
          if (result.conflict) {
            draftConflictIds.push(item.id);
            onDraftConflict?.(item.id);
          }
          if (result.applied) sent += 1;
        } catch (error) {
          const refused = refusal(error);
          console.warn(`draft sync refused draft=${item.id} status=${refused.status} code=${refused.code ?? "-"}`);
          if (isDemoLimit(refused)) await setDraftUploadIssue(db, item.id, "demo_limit");
          failed += 1;
        }
      }
      if (snapshots.length < DRAFT_SYNC_PAGE_SIZE) break;
    }
  }

  const revisionSync = await syncQueuedRevisions(userId, db, authorizedProjects);
  sent += revisionSync.sent;
  failed += revisionSync.failed;

  const definitionRefresh = await refreshAuthorizedProjectDefinitions(userId, db, referenceData);

  const remaining = await countDrafts(db);
  await authedRequest(userId, `${INTAKE_API}/outstanding`, {
    method: "POST",
    body: {
      count: remaining,
      unique_ids: await draftUniqueIds(db),
      client_draft_ids: (await draftIds(db)).filter((id) => UUID.test(id)),
      client_death_ids: (await listRegistrations(db)).map((reg) => reg.client_death_id)
    }
  });
  await refreshCases(userId, db, referenceData);
  return {
    sent,
    failed,
    remaining,
    supersededUniqueIds,
    ...(serverKeptUploads.length ? { serverKeptUploads } : {}),
    ...(canCodeNowUniqueIds.length ? { canCodeNowUniqueIds: [...new Set(canCodeNowUniqueIds)] } : {}),
    ...(draftConflictIds.length ? { draftConflictIds } : {}),
    ...(revisionSync.attentionIds.length ? { revisionAttentionIds: revisionSync.attentionIds } : {}),
    ...(definitionRefresh.length ? { definitionRefresh } : {}),
    ...(codingOutcomes.length ? { codingOutcomes } : {})
  };
}

/**
 * GET every page of /cases and make the stored cases exactly that list, so
 * a case the server no longer offers (submitted, closed, out of scope, or
 * started by a teammate) leaves the phone. A failure part way leaves the
 * stored cases as they were.
 */
export interface CasePageOptions {
  state?: string;
  mine?: boolean;
  cursor?: string;
  limit?: number;
}

export async function fetchCasePage(
  userId: string,
  projectId: string,
  options: CasePageOptions = {}
): Promise<{ cases: CaseRow[]; counts?: Record<string, number>; next_cursor: string | null }> {
  const limit = options.limit ?? CASE_PAGE_SIZE;
  if (!Number.isInteger(limit) || limit < 1 || limit > CASE_PAGE_SIZE) throw new Error("case_page_limit");
  const params = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  if (options.state) params.set("state", options.state);
  if (options.mine !== undefined) params.set("mine", String(options.mine));
  if (options.cursor) params.set("cursor", options.cursor);
  const { body } = await authedRequest<{
    cases: CaseRow[];
    counts?: Record<string, number>;
    next_cursor?: string | null;
  }>(userId, `${INTAKE_API}/cases?${params.toString()}`);
  if (!body || !Array.isArray(body.cases)) throw new Error("invalid_case_page");
  return { cases: body.cases, counts: body.counts, next_cursor: body.next_cursor ?? null };
}

export async function fetchCaseDetail(
  userId: string,
  db: Db,
  deathId: string,
  options: { persist?: boolean; expectedProjectId?: string } = {}
): Promise<CaseDetail> {
  let body: { case: CaseDetail };
  try {
    body = (await authedRequest<{ case: CaseDetail }>(
      userId,
      `${INTAKE_API}/cases/${encodeURIComponent(deathId)}`
    )).body;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const cached = await getCase(db, deathId);
      if (cached) await deleteCase(db, cached.project_id, deathId);
    }
    if (error instanceof TypeError) {
      const cached = await getCase(db, deathId);
      if (
        cached &&
        isActiveCaseState(cached.state) &&
        (!options.expectedProjectId || cached.project_id === options.expectedProjectId) &&
        await cachedProjectIsAuthorized(db, cached.project_id)
      ) {
        return cached;
      }
    }
    throw error;
  }
  const detail = body?.case;
  if (!isCaseDetail(detail) || detail.death_id !== deathId) {
    throw new Error("invalid_case_detail");
  }
  if (options.expectedProjectId && detail.project_id !== options.expectedProjectId) {
    throw new Error("project_mismatch");
  }
  if (options.persist !== false) {
    if (!(await cachedProjectIsAuthorized(db, detail.project_id))) throw new Error("project_forbidden");
    if (isActiveCaseState(detail.state)) await upsertCase(db, detail);
    else await deleteCase(db, detail.project_id, deathId);
  }
  return detail;
}

async function cachedProjectIsAuthorized(db: Db, projectId: string): Promise<boolean> {
  const reference = await getCachedReferenceData(db);
  return Boolean(reference?.projects.some(({ project }) => project.project_id === projectId));
}

/** Download every active case for every authorized project atomically per project. */
export async function refreshCases(
  userId: string,
  db: Db,
  referenceData?: ReferenceData
): Promise<CaseDetail[]> {
  const reference = referenceData ?? (await getCachedReferenceData(db));
  if (!reference) throw new Error("reference_data_required");
  const all: CaseDetail[] = [];
  const activeState = ACTIVE_CASE_STATES.join(",");
  for (const { project } of reference.projects) {
    const rows: CaseRow[] = [];
    let cursor: string | undefined;
    let complete = false;
    for (let page = 0; page < CASE_PAGES_MAX; page += 1) {
      const result = await fetchCasePage(userId, project.project_id, {
        state: activeState,
        cursor,
        limit: CASE_PAGE_SIZE
      });
      rows.push(...result.cases);
      cursor = result.next_cursor ?? undefined;
      if (!cursor) {
        complete = true;
        break;
      }
    }
    if (!complete) throw new Error("case_page_limit");
    const details: CaseDetail[] = [];
    const stored = new Map((await listCases(db)).map((c) => [c.death_id, c]));
    for (const row of rows) {
      if (row.project_id !== project.project_id) throw new Error("project_mismatch");
      // Unchanged since the stored copy was downloaded: skip the request.
      const sig = JSON.stringify(row);
      const cached = stored.get(row.death_id);
      if (cached && cached.project_id === project.project_id && cached.list_sig === sig && isActiveCaseState(cached.state)) {
        details.push(cached);
        continue;
      }
      let detail: CaseDetail;
      try {
        detail = await fetchCaseDetail(userId, db, row.death_id, {
          persist: false,
          expectedProjectId: project.project_id
        });
      } catch (error) {
        // A case can disappear between the page and its detail request. It is
        // already absent from the authoritative list, so purge its stale copy
        // and continue downloading the rest of this project.
        if (error instanceof ApiError && error.status === 404) continue;
        throw error;
      }
      if (isActiveCaseState(detail.state)) details.push({ ...detail, list_sig: sig });
    }
    await replaceCases(db, project.project_id, details);
    all.push(...details);
    await refreshIdentifierTypes(userId, db, project.project_id);
    await refreshConsentConfig(userId, db, project.project_id);
  }
  return all;
}

const IDENTIFIER_TYPES_META_KEY = "identifierTypes";

/**
 * Cache the project's active registration-number types in the encrypted store, with the case list, for
 * offline registration (docs/policy/death-registration-identifiers.md, "Offline"). Best effort: the
 * server answers 403 where the user neither registers nor supervises, and a failure keeps the old copy.
 * Session errors still propagate.
 */
export async function refreshIdentifierTypes(userId: string, db: Db, projectId: string): Promise<IdentifierType[] | undefined> {
  try {
    const { body } = await authedRequest<{ identifier_types?: IdentifierType[] }>(
      userId,
      `${INTAKE_API}/identifier-types?project_id=${encodeURIComponent(projectId)}`
    );
    if (!body || !Array.isArray(body.identifier_types)) return undefined;
    await setMeta(db, IDENTIFIER_TYPES_META_KEY, body.identifier_types, projectId);
    return body.identifier_types;
  } catch (error) {
    if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
    return undefined;
  }
}

/** The cached types of a project ([] before the first refresh). */
export async function getCachedIdentifierTypes(db: Db, projectId: string): Promise<IdentifierType[]> {
  return (await getMeta<IdentifierType[]>(db, IDENTIFIER_TYPES_META_KEY, projectId)) ?? [];
}

/** The complete, validated settings pack retained for offline form use. */
export interface ReferenceData {
  bootstrap: Bootstrap;
  projects: ProjectReferenceData[];
}

export interface DefinitionRefreshStatus {
  projectId: string;
  available: boolean;
  error?: string;
}

interface ReferencePack {
  bootstrap: Bootstrap;
  projects: Array<ProjectReferenceData & { translations: Record<string, Translations | null> }>;
  /** Version of the instrument shipped in this Expo bundle. */
  bundledInstrumentVersion: string;
  readyAt: number;
}

/** One refresh per database/interviewer, even when several screens focus together. */
const referenceRefreshes = new WeakMap<Db, Map<string, Promise<ReferenceData>>>();
const definitionRefreshes = new WeakMap<Db, Map<string, Promise<DefinitionRefreshStatus[]>>>();

function configuredTranslationLocales(project: ProjectSettings): string[] {
  return questionnaireLocales(project.form_options?.available_locales)
    .map((locale) => locale.code).filter((locale) => locale !== "en").sort();
}

function compatibleBootstrap(bootstrap: Bootstrap): boolean {
  // The server's `instrument_version` identifies the shared form bundle. The
  // form type is the stable contract shared by the API and this package.
  return validBootstrapShape(bootstrap) && bootstrap.projects.length > 0 && bootstrap.projects.every((project) => {
    const code = project.form_options?.form_types?.find((formType) => formType.is_default)?.instrument_code;
    return (code ?? BUNDLED_INSTRUMENT_CODE) === BUNDLED_INSTRUMENT_CODE;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function validProjectSettings(value: unknown): value is ProjectSettings {
  if (!isRecord(value)) return false;
  if (
    typeof value.project_id !== "string" ||
    value.project_id.length === 0 ||
    typeof value.project_name !== "string" ||
    typeof value.web_intake_mode !== "string" ||
    !["off", "direct", "death_register", "both"].includes(value.web_intake_mode) ||
    !Array.isArray(value.sites) ||
    !isRecord(value.form_options) ||
    !isRecord(value.prefill_policy)
  ) {
    return false;
  }
  if (value.smartva_targets !== undefined &&
      (!Array.isArray(value.smartva_targets) || !value.smartva_targets.every(isSmartVaTarget))) return false;
  const policy = value.prefill_policy;
  if (
    !isRecord(policy.direct) ||
    !isRecord(policy.units) ||
    !isRecord(policy.answer_fields) ||
    !Array.isArray(policy.locked_fields)
  ) {
    return false;
  }
  return value.sites.every((site) => {
    if (!isRecord(site) || typeof site.project_id !== "string" || site.project_id !== value.project_id || typeof site.site_id !== "string" || site.site_id.length === 0) {
      return false;
    }
    return site.web_intake_mode === undefined || ["off", "direct", "death_register", "both"].includes(String(site.web_intake_mode));
  });
}

function validBootstrapShape(value: unknown): value is Bootstrap {
  if (!isRecord(value) || !isRecord(value.user) || typeof value.user.user_id !== "string" || typeof value.user.name !== "string" || typeof value.instrument_version !== "string" || !Array.isArray(value.projects)) {
    return false;
  }
  const ids = new Set<string>();
  return value.projects.every((project) => {
    if (!validProjectSettings(project) || ids.has(project.project_id)) return false;
    ids.add(project.project_id);
    return true;
  });
}

function exposedReference(pack: ReferencePack): ReferenceData {
  return { bootstrap: pack.bootstrap, projects: pack.projects.map(({ project, units }) => ({ project, units })) };
}

async function readReferencePack(db: Db): Promise<ReferencePack | undefined> {
  try {
    const pack = await getMeta<ReferencePack>(db, REFERENCE_META_KEY);
    if (!pack || !pack.bootstrap || !Array.isArray(pack.bootstrap.projects) || !Array.isArray(pack.projects)) {
      return undefined;
    }
    return pack;
  } catch (error) {
    // Only malformed JSON is an unusable cache row. Surface database errors so
    // callers do not mistake storage failures for an ordinary cache miss.
    if (error instanceof SyntaxError) return undefined;
    throw error;
  }
}

/** Display names of every project the worker had or has, for the pause notice. */
function projectNames(previous: ReferencePack | undefined, access: AccessSummary): Map<string, string> {
  const names = new Map<string, string>();
  for (const { project } of previous?.projects ?? []) names.set(project.project_id, project.project_name);
  for (const project of access.projects) names.set(project.project_id, project.project_name);
  return names;
}

/**
 * Reconcile an already downloaded settings pack with a fresh access summary.
 * This intentionally performs no network work: stable form options and
 * translations remain cached while project/site/unit reach is replaced by the
 * authoritative grant snapshot.
 */
export async function reconcileReferenceAccess(
  db: Db,
  access: AccessSummary,
): Promise<ReferenceData | undefined> {
  const previous = await readReferencePack(db);
  const authorized = new Map(
    access.projects
      .filter((project) => project.actions.interview.length > 0)
      .map((project) => [project.project_id, project]),
  );
  const retainedProjectIds = new Set(access.projects
    .filter((project) => project.actions.interview.length > 0 || project.actions.register_death.length > 0)
    .map((project) => project.project_id));
  const localProjectIds = new Set(await projectIds(db));
  for (const item of previous?.projects ?? []) localProjectIds.add(item.project.project_id);
  for (const projectId of localProjectIds) {
    if (!retainedProjectIds.has(projectId)) await purgeProjectData(db, projectId, access.user.user_id);
  }
  await recordPausedProjects(db, localProjectIds, new Set(authorized.keys()), projectNames(previous, access));
  const definitions = createNativeDefinitionCache(
    db as Parameters<typeof createNativeDefinitionCache>[0],
    access.user.user_id,
  );
  for (const project of authorized.values()) definitions.restoreProject(project.project_id);
  if (!authorized.size) return undefined;
  if (!previous || !referenceIsComplete(previous)) return undefined;

  const projects: ReferencePack["projects"] = [];
  for (const item of previous.projects) {
    const accessProject = authorized.get(item.project.project_id);
    if (!accessProject) continue;
    const project: ProjectSettings = {
      ...item.project,
      smartva_targets: accessProject.smartva_targets,
      sites: accessProject.sites
        .filter((site) => site.roles.includes("interviewer"))
        .map((site) => ({
          project_id: accessProject.project_id,
          site_id: site.site_id,
          site_name: site.site_name,
          web_intake_mode: item.project.web_intake_mode,
        })),
    };
    const units: Units | null = accessProject.has_tree
      ? {
          scoped: true,
          levels: accessProject.levels ?? [],
          units: (accessProject.units ?? []).filter((unit) =>
            unit.selectable ? unit.roles.includes("interviewer") : true,
          ),
        }
      : { scoped: false, levels: [], units: [] };
    projects.push({ ...item, project, units });
  }
  const normalizedBootstrap: Bootstrap = {
    user: access.user,
    instrument_version: previous.bootstrap.instrument_version,
    projects: projects.map(({ project }) => project),
  };
  if (!compatibleBootstrap(normalizedBootstrap)) {
    throw new Error("instrument_incompatible");
  }
  const next: ReferencePack = {
    ...previous,
    bootstrap: normalizedBootstrap,
    projects,
    readyAt: Date.now(),
  };
  await setMeta(db, REFERENCE_META_KEY, next);
  await setMeta(db, "bootstrap", normalizedBootstrap);
  for (const { project, units } of projects) {
    await setMeta(db, "project", project, project.project_id);
    await setMeta(db, "units", units, project.project_id);
  }
  return exposedReference(next);
}

function referenceIsComplete(pack: ReferencePack | undefined): pack is ReferencePack {
  if (
    !pack ||
    pack.bundledInstrumentVersion !== BUNDLED_INSTRUMENT_VERSION ||
    !validBootstrapShape(pack.bootstrap) ||
    !compatibleBootstrap(pack.bootstrap) ||
    !Number.isFinite(pack.readyAt)
  ) {
    return false;
  }
  return pack.projects.every(({ project, translations }) =>
    configuredTranslationLocales(project).every((locale) => Object.prototype.hasOwnProperty.call(translations, locale))
  );
}

function referenceIsFresh(pack: ReferencePack | undefined, now = Date.now()): pack is ReferencePack {
  return (
    referenceIsComplete(pack) &&
    Number.isFinite(pack.readyAt) &&
    now >= pack.readyAt &&
    now - pack.readyAt < REFERENCE_MAX_AGE_MS
  );
}

/** Return a complete compatible settings pack, including when it is stale but offline. */
export async function getCachedReferenceData(db: Db): Promise<ReferenceData | undefined> {
  const pack = await readReferencePack(db);
  return referenceIsComplete(pack) ? exposedReference(pack) : undefined;
}

/** Explicit bootstrap refresh retained for callers that only need reference state. */
export async function refreshBootstrap(userId: string, db: Db): Promise<ReferenceData> {
  return refreshReferenceData(userId, db, { force: true });
}

async function fetchTranslation(
  userId: string,
  db: Db,
  projectId: string,
  code: string,
  locale: string,
  version: number | undefined
): Promise<Translations | null> {
  const key = `translations:${code}:${locale}:${version ?? "?"}`;
  const cached = await getMeta<Translations>(db, key, projectId);
  if (cached) return cached;
  const path = `/api/v1/instruments/${encodeURIComponent(code)}/translations/${encodeURIComponent(locale)}?project_id=${encodeURIComponent(projectId)}`;
  try {
    const { body } = await authedRequest<Translations>(userId, path);
    return body && typeof body === "object" ? body : null;
  } catch (error) {
    if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
    if (error instanceof ApiError) {
      if (error.status === 404) return null;
      throw error;
    }
    if (error instanceof TypeError) return null;
    throw error;
  }
}

async function loadReferenceData(userId: string, db: Db): Promise<ReferencePack> {
  const access = parseAccessSummary((await authedRequest<unknown>(userId, "/api/v1/me/access")).body);
  const accessProjects = access.projects.filter((project) => project.actions.interview.length > 0);
  const authorized = new Set(accessProjects.map((project) => project.project_id));
  const retainedProjectIds = new Set(access.projects
    .filter((project) => project.actions.interview.length > 0 || project.actions.register_death.length > 0)
    .map((project) => project.project_id));
  // Older app versions stored a different reference shape under this key.
  // Treat it as absent so a malformed cache cannot block a fresh bootstrap.
  const previous = await readReferencePack(db);
  const localProjectIds = new Set(await projectIds(db));
  for (const project of previous?.projects ?? []) localProjectIds.add(project.project.project_id);
  for (const projectId of localProjectIds) {
    if (!retainedProjectIds.has(projectId)) await purgeProjectData(db, projectId, userId);
  }
  await recordPausedProjects(db, localProjectIds, authorized, projectNames(previous, access));
  const removedFromPrevious = previous?.projects.some(({ project }) => !authorized.has(project.project_id)) ?? false;
  if (previous && removedFromPrevious) {
    await setMeta(db, REFERENCE_META_KEY, {
      ...previous,
      bootstrap: {
        ...previous.bootstrap,
        user: access.user,
        projects: previous.projects.filter(({ project }) => authorized.has(project.project_id)).map(({ project }) => project),
      },
      // Keep only authorized projects visible while units/translations are
      // being rebuilt, but deliberately mark this intermediate pack
      // incomplete so a partial refresh cannot masquerade as a complete one.
      projects: previous.projects.filter(({ project }) => authorized.has(project.project_id)),
      bundledInstrumentVersion: "partial",
      readyAt: 0
    });
  }
  // Clear project compatibility keys while rebuilding. This prevents a later
  // options/prefill failure from restoring a revoked project through a legacy
  // cache reader while the complete reference pack is rebuilt.
  await db.runAsync("DELETE FROM meta WHERE key IN ('units', 'project') OR key LIKE 'translations:%'", []);
  if (accessProjects.length === 0) throw new ApiError(403, "no_collection_access");
  const settings = await Promise.all(accessProjects.map(async (accessProject) => {
      const formOptions = await fetchProjectFormOptions(userId, accessProject.project_id);
      const prefillPolicy = await fetchPrefillPolicy(userId, accessProject.project_id);
      if (!["off", "direct", "death_register", "both"].includes(String(formOptions.web_intake_mode)) || typeof formOptions.instrument_version !== "string") {
        throw new Error("instrument_incompatible");
      }
      const sites = accessProject.sites
        .filter((site) => site.roles.includes("interviewer"))
        .map((site) => ({
          project_id: accessProject.project_id,
          site_id: site.site_id,
          site_name: site.site_name,
          web_intake_mode: String(formOptions.web_intake_mode),
        }));
      const project: ProjectSettings = {
        project_id: accessProject.project_id,
        project_name: accessProject.project_name,
        web_intake_mode: String(formOptions.web_intake_mode),
        smartva_targets: accessProject.smartva_targets,
        sites,
        form_options: formOptions,
        prefill_policy: prefillPolicy,
      };
      const units: Units | null = accessProject.has_tree
        ? {
            scoped: true,
            levels: accessProject.levels ?? [],
            // Keep only interviewer reach plus the non-selectable ancestor
            // rows the server supplies as context for that reach.
            units: (accessProject.units ?? []).filter((unit) => unit.selectable ? unit.roles.includes("interviewer") : true),
          }
        : { scoped: false, levels: [], units: [] };
      const translations = await loadTranslations(userId, db, project);
      return { project, units, translations };
    }));
  const projects: ReferencePack["projects"] = [];
  projects.push(...settings);
  const normalizedBootstrap: Bootstrap = {
    user: access.user,
    instrument_version: settings[0]?.project.form_options.instrument_version ?? "",
    projects: settings.map(({ project }) => project),
  };
  // Validate the normalized, access-scoped settings before returning or
  // publishing them. Bootstrap metadata is temporary and cannot certify the
  // shared form-options or prefill-policy responses.
  if (!compatibleBootstrap(normalizedBootstrap)) {
    throw new Error("instrument_incompatible");
  }
  return {
    bootstrap: normalizedBootstrap,
    projects,
    bundledInstrumentVersion: BUNDLED_INSTRUMENT_VERSION,
    readyAt: Date.now()
  };
}

async function fetchProjectFormOptions(userId: string, projectId: string): Promise<ProjectSettings["form_options"]> {
  const { body } = await authedRequest<unknown>(userId, `/api/v1/organization/${encodeURIComponent(projectId)}/form-options`);
  if (!isRecord(body)) throw new Error("invalid_form_options");
  return body as ProjectSettings["form_options"];
}

async function fetchPrefillPolicy(userId: string, projectId: string): Promise<PrefillPolicy> {
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/projects/${encodeURIComponent(projectId)}/prefill-policy`);
  if (!isRecord(body)) throw new Error("invalid_prefill_policy");
  return body as unknown as PrefillPolicy;
}

async function loadTranslations(userId: string, db: Db, project: ProjectSettings): Promise<Record<string, Translations | null>> {
  const code = project.form_options?.form_types?.find((formType) => formType.is_default)?.instrument_code ?? BUNDLED_INSTRUMENT_CODE;
  const translations: Record<string, Translations | null> = {};
  for (const locale of configuredTranslationLocales(project)) {
    translations[locale] = await fetchTranslation(
      userId,
      db,
      project.project_id,
      code,
      locale,
      project.form_options?.translation_versions?.[locale]
    );
  }
  return translations;
}

/**
 * Fetch and atomically publish the complete reference pack. An automatic
 * failed attempt is throttled for 24 hours; an explicit force always retries.
 * The prior complete pack remains available when any request fails.
 */
export function refreshReferenceData(
  userId: string,
  db: Db,
  options: { force?: boolean } = {}
): Promise<ReferenceData> {
  let byUser = referenceRefreshes.get(db);
  if (!byUser) {
    byUser = new Map();
    referenceRefreshes.set(db, byUser);
  }
  const existing = byUser.get(userId);
  if (existing) {
    // A forced sync waits for an in-flight automatic request, then performs
    // its own authoritative request instead of inheriting a throttled cache.
    if (!options.force) return existing;
    const queued = existing.then(
      () => refreshReferenceDataOnce(userId, db, true),
      () => refreshReferenceDataOnce(userId, db, true)
    );
    let pending!: Promise<ReferenceData>;
    pending = queued.finally(() => {
      if (byUser?.get(userId) === pending) byUser.delete(userId);
    });
    byUser.set(userId, pending);
    return pending;
  }

  let pending!: Promise<ReferenceData>;
  pending = refreshReferenceDataOnce(userId, db, options.force === true).finally(() => {
    if (byUser?.get(userId) === pending) byUser.delete(userId);
  });
  byUser.set(userId, pending);
  return pending;
}

/** Refresh each authorized project's current form after queued work uploads. */
export async function refreshAuthorizedProjectDefinitions(
  userId: string,
  db: Db,
  referenceData?: ReferenceData,
): Promise<DefinitionRefreshStatus[]> {
  let byUser = definitionRefreshes.get(db);
  if (!byUser) {
    byUser = new Map();
    definitionRefreshes.set(db, byUser);
  }
  const active = byUser.get(userId);
  if (active) return active;
  let pending!: Promise<DefinitionRefreshStatus[]>;
  pending = refreshAuthorizedProjectDefinitionsOnce(userId, db, referenceData).finally(() => {
    if (byUser?.get(userId) === pending) byUser.delete(userId);
  });
  byUser.set(userId, pending);
  return pending;
}

async function refreshAuthorizedProjectDefinitionsOnce(
  userId: string,
  db: Db,
  referenceData?: ReferenceData,
): Promise<DefinitionRefreshStatus[]> {
  const reference = referenceData ?? await getCachedReferenceData(db);
  if (!reference) throw new Error("reference_data_required");
  const cache = createNativeDefinitionCache(
    db as Parameters<typeof createNativeDefinitionCache>[0],
    userId,
  );
  await cache.initialize();
  const statuses: DefinitionRefreshStatus[] = [];
  for (const { project } of reference.projects) {
    const options = project.form_options;
    const code = options?.form_types?.find((item) => item.is_default)?.instrument_code;
    if ((code ?? BUNDLED_INSTRUMENT_CODE) !== BUNDLED_INSTRUMENT_CODE) continue;
    if (!options?.instrument_version || !options.definition_sha256) {
      statuses.push({ projectId: project.project_id, available: false, error: "current_definition_unavailable" });
      continue;
    }
    const identity: DefinitionIdentity = {
      accountId: userId,
      projectId: project.project_id,
      instrumentCode: BUNDLED_INSTRUMENT_CODE,
      composedVersion: options.instrument_version,
      sha256: options.definition_sha256,
    };
    try {
      const cached = await cache.get(identity);
      const definition = cached ?? (await downloadCurrentDefinition({
        identity,
        request: (path, requestOptions) => authedRawRequest(userId, path, {
          ifNoneMatch: requestOptions.ifNoneMatch,
          acceptGzip: true,
        }),
      })).value;
      const actualExtensions = readDefinitionExtensions(definition);
      const expectedExtensions = [...(options.enabled_extensions ?? [])].sort();
      if (actualExtensions.length !== expectedExtensions.length ||
          actualExtensions.some((extension, index) => extension !== expectedExtensions[index])) {
        throw new FormDefinitionError("invalid_definition");
      }
      if (!cached) await cache.put(definition);
      await markProjectDefinitionServed(userId, db, project.project_id);
      statuses.push({ projectId: project.project_id, available: true });
    } catch (error) {
      if (error instanceof SessionRevokedError || error instanceof SignInRequiredError ||
          (error instanceof ApiError && (error.status === 401 || error.status === 403))) throw error;
      if (error instanceof FormDefinitionError || error instanceof FormDefinitionHistoryError || error instanceof TypeError ||
          (error instanceof ApiError && (error.status === 404 || error.status === 408 || error.status === 429 || error.status >= 500))) {
        const code = error instanceof FormDefinitionError || error instanceof FormDefinitionHistoryError || error instanceof ApiError
          ? error.code
          : "network_error";
        statuses.push({ projectId: project.project_id, available: false, error: code ?? "definition_unavailable" });
        continue;
      }
      throw error;
    }
  }
  return statuses;
}

/** Allow bundled new interviews only until this project has served a verified definition. */
export async function canUseBundledFallbackForProject(
  userId: string,
  db: Db,
  projectId: string,
): Promise<boolean> {
  assertDefinitionProjectIdentity(userId, projectId);
  const served = await getMeta<unknown>(db, SERVED_DEFINITION_META_KEY, projectId);
  if (served === undefined) return true;
  if (typeof served !== "boolean") throw new Error("invalid_definition_served_state");
  return !served;
}

/** Record first service in the account's encrypted, project-scoped metadata. */
export async function markProjectDefinitionServed(
  userId: string,
  db: Db,
  projectId: string,
): Promise<void> {
  assertDefinitionProjectIdentity(userId, projectId);
  await setMeta(db, SERVED_DEFINITION_META_KEY, true, projectId);
}

function assertDefinitionProjectIdentity(userId: string, projectId: string): void {
  if (typeof userId !== "string" || !userId.trim() || typeof projectId !== "string" || !projectId.trim()) {
    throw new Error("invalid_definition_identity");
  }
}

async function refreshReferenceDataOnce(userId: string, db: Db, force: boolean): Promise<ReferenceData> {
  const previous = await readReferencePack(db);
  const previousComplete = referenceIsComplete(previous) ? previous : undefined;
  if (!force && referenceIsFresh(previousComplete)) return exposedReference(previousComplete);

  if (!force) {
    const attemptedAt = await getMeta<number>(db, REFERENCE_ATTEMPT_META_KEY);
    if (typeof attemptedAt === "number" && Date.now() - attemptedAt < REFERENCE_MAX_AGE_MS) {
      if (previousComplete) return exposedReference(previousComplete);
      throw new Error("reference_refresh_throttled");
    }
  }

  let next: ReferencePack;
  try {
    next = await loadReferenceData(userId, db);
  } catch (error) {
    // Authentication/session failures and malformed or incompatible responses
    // must reach the caller. Only a known fetch-network failure may fall back
    // to an older pack during an automatic refresh.
    if (!(error instanceof TypeError)) throw error;
    // This timestamp is deliberately separate from readyAt: a failed refresh
    // must not make a previous successful pack look newly fetched.
    await setMeta(db, REFERENCE_ATTEMPT_META_KEY, Date.now());
    const current = await readReferencePack(db);
    const sanitized = referenceIsComplete(current) ? current : undefined;
    if (sanitized && !force) return exposedReference(sanitized);
    if (previousComplete && !force) {
      // Once a valid new bootstrap has been published, never fall back to a
      // complete pack that still contains a project it revoked. A network
      // failure before bootstrap remains eligible for the old-pack fallback.
      const currentIds = current?.bootstrap && validBootstrapShape(current.bootstrap)
        ? new Set(current.bootstrap.projects.map((project) => project.project_id))
        : undefined;
      const removedProject = currentIds && previousComplete.projects.some(({ project }) => !currentIds.has(project.project_id));
      if (!removedProject) return exposedReference(previousComplete);
    }
    throw error;
  }

  // Publish compatibility keys only before the single complete-pack write.
  // If any of these writes fail, the previous complete pack is untouched and
  // the storage error reaches the caller.
  await setMeta(db, "bootstrap", next.bootstrap);
  for (const { project, units, translations } of next.projects) {
    await setMeta(db, "project", project, project.project_id);
    await setMeta(db, "units", units, project.project_id);
    for (const [locale, translation] of Object.entries(translations)) {
      if (!translation) continue;
      const version = project.form_options?.translation_versions?.[locale];
      await setMeta(db, `translations:${project.form_options?.form_types?.find((formType) => formType.is_default)?.instrument_code ?? BUNDLED_INSTRUMENT_CODE}:${locale}:${version ?? "?"}`, translation, project.project_id);
    }
  }
  await setMeta(db, REFERENCE_META_KEY, next);
  // The complete pack is already durable; failure to clear the retry marker
  // must not make a successful refresh look like a failed one.
  await setMeta(db, REFERENCE_ATTEMPT_META_KEY, 0);
  const definitions = createNativeDefinitionCache(
    db as Parameters<typeof createNativeDefinitionCache>[0],
    userId,
  );
  for (const { project } of next.projects) definitions.restoreProject(project.project_id);
  return exposedReference(next);
}

/**
 * A locale's questionnaire strings from /api/v1/instruments/.../translations,
 * cached per version (the bootstrap's `translation_versions`) so an edited
 * locale is fetched again. English needs none. A missing translation or fetch
 * network error returns null for English fallback; API and storage failures
 * propagate.
 */
export async function translationsFor(
  userId: string,
  db: Db,
  projectId: string,
  code: string,
  locale: string,
  version: number | undefined
): Promise<Translations | null> {
  if (locale === "en") return null;
  const completePack = await readReferencePack(db);
  if (
    referenceIsComplete(completePack) &&
    completePack.projects.some(({ project, translations }) =>
      project.project_id === projectId &&
      (project.form_options?.form_types?.find((formType) => formType.is_default)?.instrument_code ?? BUNDLED_INSTRUMENT_CODE) === code &&
      project.form_options?.translation_versions?.[locale] === version &&
      Object.prototype.hasOwnProperty.call(translations, locale)
    )
  ) {
    return completePack.projects.find(({ project }) => project.project_id === projectId)?.translations[locale] ?? null;
  }
  const body = await fetchTranslation(userId, db, projectId, code, locale, version);
  if (body) await setMeta(db, `translations:${code}:${locale}:${version ?? "?"}`, body, projectId);
  return body;
}

/**
 * Translations for an open draft. They are keyed by question and choice name,
 * so a draft pinned to an older definition still gets them: its own cached
 * version if the phone holds one, else the current version (cached, or fetched
 * when online). applyTranslations leaves items absent from the pack in English.
 * Null only when no pack for the locale is available.
 */
export async function translationsForDraft(
  userId: string,
  db: Db,
  projectId: string,
  code: string,
  locale: string,
  draftVersion: number | undefined,
  currentVersion: number | undefined
): Promise<Translations | null> {
  if (locale === "en") return null;
  if (draftVersion !== undefined && draftVersion !== currentVersion) {
    const own = await getMeta<Translations>(db, `translations:${code}:${locale}:${draftVersion}`, projectId);
    if (own) return own;
  }
  return translationsFor(userId, db, projectId, code, locale, currentVersion);
}

export interface Target {
  key: string;
  label: string;
  projectId: string;
  siteId: string;
  orgUnitId?: string;
  /** The parts of `label`, so a picker can show the unit alone under a site header. */
  siteName?: string;
  unitName?: string;
}

/**
 * What "New interview" offers: one choice per site, or, when the project has
 * an organization tree, one per (site, unit the interviewer may pick). With
 * a tree but no cached units (never fetched, or none reachable) it offers
 * nothing: an interview with no unit could not be routed to a coder.
 */
export function targetsFrom(project: ProjectSettings | undefined, units: Units | null | undefined): Target[] {
  const sites = project?.sites ?? [];
  if (!project || !units) return [];
  const choices = units.units.filter((unit) => unit.selectable && unit.is_active !== false);
  return sites.flatMap((entry) => {
    const site = entry.site_name ?? entry.site_id;
    if (units.levels.length === 0) return [{ key: `${project.project_id}:${entry.site_id}`, label: site, projectId: project.project_id, siteId: entry.site_id, siteName: site }];
    return choices.map((unit) => ({
      key: `${project.project_id}:${entry.site_id}:${unit.org_unit_id}`,
      label: `${site} · ${unit.unit_name}`,
      projectId: project.project_id,
      siteId: entry.site_id,
      orgUnitId: unit.org_unit_id,
      siteName: site,
      unitName: unit.unit_name
    }));
  });
}

/** Whether a site's project mode takes death registrations (web_intake_service._mode_allows). */
export function registersDeaths(project: ProjectSettings | undefined, siteId?: string): boolean {
  return Boolean(project && project.sites.some(
    (entry) => (!siteId || entry.site_id === siteId) && ["death_register", "both"].includes(entry.web_intake_mode ?? project.web_intake_mode)
  ));
}

/** Whether a site starts a questionnaire directly, without a death record. */
export function startsDirectly(project: ProjectSettings | undefined, siteId?: string): boolean {
  return Boolean(project && project.sites.some(
    (entry) => (!siteId || entry.site_id === siteId) && ["direct", "both"].includes(entry.web_intake_mode ?? project.web_intake_mode)
  ));
}

/**
 * The fields this app reads. `form_options` is the project's form-options
 * body (the same one the web form reads from /api/v1/organization/<p>/form-options).
 */
export interface PrefillPolicy {
  direct: import("@drguptavivek/who-2022-va").WhoVaHostPrefill;
  units: Record<string, { answers: import("@drguptavivek/who-2022-va").SubmissionData; lockedQuestionNames: string[] }>;
  answer_fields: Record<string, string>;
  locked_fields: string[];
}

export interface ProjectSettings {
  project_id: string;
  project_name: string;
  /** off, direct, death_register or both. */
  web_intake_mode: string;
  /** Current server-approved SmartVA settings for exact interview targets. */
  smartva_targets?: SmartVaTarget[];
  sites: Array<{ project_id: string; site_id: string; site_name?: string; web_intake_mode?: string }>;
  form_options: {
    web_intake_mode?: string;
    instrument_version?: string;
    definition_sha256?: string | null;
    enabled_extensions?: string[];
    form_types?: Array<{ instrument_code: string | null; is_default: boolean }>;
    available_locales?: Array<{ code: string; label: string; under_review?: boolean }>;
    default_locale?: string;
    translation_versions?: Record<string, number>;
    intake_note?: string | null;
  };
  prefill_policy: PrefillPolicy;
}

export interface ProjectReferenceData {
  project: ProjectSettings;
  units: Units | null;
}

export interface Bootstrap {
  user: { user_id: string; name: string };
  instrument_version: string;
  projects: ProjectSettings[];
}

/** Shared `/api/v1/me/access` response used to scope native collection. */
export type { AccessProject, AccessSummary } from "./api";

/** Access-scoped organization units retained for offline target pickers. */
export interface Units {
  scoped: boolean;
  levels: Array<{ level_code: string; level_name: string; depth: number }>;
  units: Array<{
    org_unit_id: string;
    unit_code: string;
    unit_name: string;
    level_code: string;
    path: string;
    is_active?: boolean;
    selectable: boolean;
    roles?: string[];
    can_code?: boolean;
  }>;
}
