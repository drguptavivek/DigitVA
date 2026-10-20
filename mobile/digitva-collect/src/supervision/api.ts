/** Supervisor calls over the browser session. Every request goes through the shared JSON requester, which sends X-CSRFToken on mutations. */
import type { JsonRequester } from "../workspace/api";

const SUPERVISION_API = "/api/v1/intake/supervision";

export type PendingFlag = "duplicate" | "cancel" | null;

/** One supervisor row: who registered and started the case, no contact details. */
export interface SupervisedCase {
  death_id: string;
  va_sid: string | null;
  unique_id: string;
  /** Where the case came from: "odk" cases are revised in ODK, not reopened here. */
  source: string;
  project_id: string;
  state: string;
  pending_flag: PendingFlag;
  details_pending: boolean;
  deceased_name: string | null;
  deceased_sex: string | null;
  age_years: number | null;
  date_of_death: string | null;
  unit_name: string | null;
  registered_by_name: string | null;
  started_by_name: string | null;
  /** When the death was reported (registered). */
  created_at: string | null;
  updated_at: string | null;
  other_complete_interview: boolean;
}

/** The attention tiles: whole-scope counts, filters ignored (same predicates as the `needs_decision` / `overdue` / `stuck` filters). */
export interface SupervisionTiles {
  needs_decision: number;
  overdue: number;
  stuck: number;
  total: number;
}

export interface SupervisedCasePage {
  cases: SupervisedCase[];
  counts: Record<string, number>;
  tiles: SupervisionTiles;
  next_cursor: string | null;
}

export interface InterviewCandidate {
  draft_id: string;
  interviewer_name: string | null;
  completed_at: string | null;
  outcome: string;
}

export interface VisitNote {
  date: string | null;
  address: string | null;
  remarks: string | null;
  redacted: boolean;
}

export interface SupervisedCaseDetail {
  case: SupervisedCase;
  candidates: InterviewCandidate[];
  visit_note: VisitNote | null;
}

export interface PossibleDuplicate {
  death_id: string;
  unique_id: string;
  state: string;
  deceased_name: string | null;
  date_of_death: string | null;
}

export interface ListQuery {
  state: string;
  visitNotesOnly: boolean;
  /** Attention filters (a tile): a flag waits or a second interview is to be chosen; open and past its revisit date; open and untouched 30 days. */
  needsDecision?: boolean;
  overdue?: boolean;
  stuck?: boolean;
  /** `oldest` pages updated_at ascending; the server default is newest first. */
  sort?: "newest" | "oldest";
  cursor?: string | null;
  limit?: number;
}

/** Case states a supervisor can filter on, in the Flask page's order. */
export const SUPERVISION_STATES = [
  "draft_identity", "registered", "scheduled", "in_progress", "paused",
  "not_reachable", "refused", "submitted", "duplicate", "cancelled",
] as const;

/** Reason codes the API accepts (app/routes/api/intake.py, supervision routes). */
export const CHOOSE_INTERVIEW_REASONS = ["better_quality", "more_complete", "original_incorrect", "switch_back"] as const;
export const REVISION_REASONS = ["cod_review_requested", "new_information", "data_correction"] as const;

export function listCasesPath(query: ListQuery): string {
  const params = new URLSearchParams();
  if (query.needsDecision) params.set("needs_decision", "true");
  if (query.overdue) params.set("overdue", "true");
  if (query.stuck) params.set("stuck", "true");
  if (query.state) params.set("state", query.state);
  if (query.visitNotesOnly) params.set("visit_note", "1");
  if (query.sort === "oldest") params.set("sort", "oldest");
  if (query.limit) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);
  return `${SUPERVISION_API}/cases?${params.toString()}`;
}

export function listCases(request: JsonRequester, query: ListQuery): Promise<SupervisedCasePage> {
  return request(listCasesPath(query)) as Promise<SupervisedCasePage>;
}

export function getCaseDetail(request: JsonRequester, deathId: string): Promise<SupervisedCaseDetail> {
  return request(`${SUPERVISION_API}/cases/${encodeURIComponent(deathId)}`) as Promise<SupervisedCaseDetail>;
}

export async function getPossibleDuplicates(request: JsonRequester, deathId: string): Promise<PossibleDuplicate[]> {
  const reply = (await request(`${SUPERVISION_API}/cases/${encodeURIComponent(deathId)}/possible-duplicates`)) as {
    possible_duplicates: PossibleDuplicate[];
  };
  return reply.possible_duplicates;
}

function caseAction(
  request: JsonRequester,
  deathId: string,
  action: string,
  json: Record<string, unknown>,
): Promise<{ case: SupervisedCase }> {
  return request(`${SUPERVISION_API}/cases/${encodeURIComponent(deathId)}/${action}`, { method: "POST", json }) as Promise<{ case: SupervisedCase }>;
}

export function resolveFlag(request: JsonRequester, deathId: string, confirm: boolean, reason: string) {
  return caseAction(request, deathId, "resolve-flag", { confirm, reason });
}

export function markDuplicate(request: JsonRequester, deathId: string, duplicateOf: string, reason: string) {
  return caseAction(request, deathId, "duplicate", { duplicate_of: duplicateOf, reason });
}

export function cancelCase(request: JsonRequester, deathId: string, reason: string) {
  return caseAction(request, deathId, "cancel", { reason });
}

export function reopenCase(request: JsonRequester, deathId: string, reason: string) {
  return caseAction(request, deathId, "reopen", { reason });
}

export function chooseInterview(request: JsonRequester, deathId: string, draftId: string, reasonCode: string) {
  return caseAction(request, deathId, "choose-interview", { draft_id: draftId, reason_code: reasonCode });
}

export function reopenForRevision(request: JsonRequester, vaSid: string, reasonCode: string): Promise<unknown> {
  return request(`${SUPERVISION_API}/submissions/${encodeURIComponent(vaSid)}/reopen-for-revision`, {
    method: "POST",
    json: { reason_code: reasonCode },
  });
}
