import type { SubmissionData } from "@drguptavivek/who-2022-va";

import { ClientApiError, requestClientJson, type ClientCsrf, type DraftResponse, type DraftSummary } from "./api";
import { localDateTimeWithOffset } from "../drafts";
import type { DefinitionPin } from "../formDefinitionRuntime";

const INTAKE_DRAFTS = "/api/v1/intake/drafts";
const INCOMPLETE_OUTCOMES = new Set(["partially_completed", "respondent_unavailable", "refused"]);
const PARTIAL_OUTCOMES = new Set(["partially_completed", "respondent_unavailable"]);
const REVISION_OUTCOMES = new Set(["completed", "partially_completed", "respondent_unavailable", "refused"]);

export type RevisionReasonCode =
  | "interviewer_correction"
  | "respondent_correction"
  | "more_information"
  | "finish_partial";

export interface SubmittedRevisionSummary extends DraftSummary {
  status: "submitted";
  va_sid: string;
  created_at: string;
  updated_at: string;
}

export interface RevisionDetail extends DraftResponse {
  draft: SubmittedRevisionSummary;
  envelope: DraftResponse["envelope"] & {
    data: SubmissionData;
    startedAt?: string;
    completedAt?: string;
    definitionSha256?: DefinitionPin["definitionSha256"];
    definitionExtensions?: DefinitionPin["definitionExtensions"];
  };
  answers_sha256: string | null;
}

export interface RevisionSummaryIdentity {
  draft_id: string;
  project_id: string;
  site_id: string;
  va_sid: string;
}

export interface RevisionSnapshot {
  vaSid: string;
  reasonCode: RevisionReasonCode;
  answersJson: string;
  answersSha256: string;
  completion: { valid: boolean; issues: unknown[] };
  draft: {
    startedAt?: string;
    completedAt?: string;
    instrumentVersion: string;
    definitionSha256?: DefinitionPin["definitionSha256"];
    definitionExtensions?: DefinitionPin["definitionExtensions"];
  };
  generation: number;
}

export interface RevisionAck {
  changed: boolean;
  va_sid: string;
  payload_version_id: string;
  answers_sha256: string;
  outcome: string;
  workflow_state: string;
}

/** Return only the server's bounded, newest-first submitted metadata list. */
export async function getSubmittedRevisions(csrf: ClientCsrf): Promise<SubmittedRevisionSummary[]> {
  const result = await requestClientJson<{ drafts: SubmittedRevisionSummary[] }>(
    `${INTAKE_DRAFTS}?status=submitted`,
    { csrf },
  );
  if (!Array.isArray(result?.drafts) || result.drafts.length > 200 || !result.drafts.every(isSubmittedSummary)) {
    throw new ClientApiError(200, "malformed_response");
  }
  return result.drafts.slice(0, 200);
}

/** Fetch raw submitted answers only after the interviewer opens a revision. */
export async function getRevisionDetail(
  link: string,
  draftId: string,
  csrf: ClientCsrf,
  expected?: RevisionSummaryIdentity,
): Promise<RevisionDetail> {
  const response = await requestClientJson<RevisionDetail>(
    `${link.replace(/\/+$/, "")}/${encodeURIComponent(draftId)}`,
    { csrf },
  );
  if (
    response?.draft?.draft_id !== draftId ||
    (!!expected && response.draft.draft_id !== expected.draft_id) ||
    response.draft.status !== "submitted" ||
    typeof response.draft.va_sid !== "string" ||
    !response.draft.va_sid ||
    !validId(response.draft.project_id) ||
    !validId(response.draft.site_id) ||
    typeof response.draft.created_at !== "string" ||
    typeof response.draft.updated_at !== "string" ||
    (!!expected && response.draft.project_id !== expected.project_id) ||
    (!!expected && response.draft.site_id !== expected.site_id) ||
    (!!expected && response.draft.va_sid !== expected.va_sid) ||
    response.envelope?.id !== draftId ||
    response.envelope.schemaVersion !== 1 ||
    typeof response.envelope.formVersion !== "string" ||
    typeof response.envelope.instrumentId !== "string" ||
    typeof response.envelope.instrumentVersion !== "string" ||
    typeof response.envelope.currentSection !== "string" ||
    typeof response.envelope.createdAt !== "string" ||
    typeof response.envelope.updatedAt !== "string" ||
    (response.envelope.locale !== undefined && typeof response.envelope.locale !== "string") ||
    (response.envelope.translation_version !== undefined &&
      (!Number.isInteger(response.envelope.translation_version) || response.envelope.translation_version < 0)) ||
    (response.envelope.startedAt !== undefined && typeof response.envelope.startedAt !== "string") ||
    (response.envelope.completedAt !== undefined && typeof response.envelope.completedAt !== "string") ||
    !isRecord(response.envelope?.data) ||
    !isRecord(response.prefill) ||
    (response.prefill.lockedQuestionNames !== undefined &&
      (!Array.isArray(response.prefill.lockedQuestionNames) || !response.prefill.lockedQuestionNames.every((name) => typeof name === "string"))) ||
    (response.answers_sha256 !== null && !isHash(response.answers_sha256))
  ) {
    throw new ClientApiError(200, "malformed_response");
  }
  return response;
}

/** Capture the exact answer text and fixed completion/reason values for retries. */
export async function createRevisionSnapshot(
  input: {
    vaSid: string;
    reasonCode: RevisionReasonCode;
    data: SubmissionData;
    completion: { valid: boolean; issues: unknown[] };
    draft: {
      startedAt?: string;
      completedAt?: string;
      instrumentVersion: string;
      definitionSha256?: DefinitionPin["definitionSha256"];
      definitionExtensions?: DefinitionPin["definitionExtensions"];
    };
    generation: number;
  },
): Promise<RevisionSnapshot> {
  const answersJson = JSON.stringify(input.data);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(answersJson));
  const answersSha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return {
    vaSid: input.vaSid,
    reasonCode: input.reasonCode,
    answersJson,
    answersSha256,
    completion: { valid: input.completion.valid, issues: input.completion.issues.slice() },
    draft: {
      ...(input.draft.startedAt ? { startedAt: input.draft.startedAt } : {}),
      completedAt: localDateTimeWithOffset(),
      instrumentVersion: input.draft.instrumentVersion,
      ...(input.draft.definitionSha256 ? { definitionSha256: input.draft.definitionSha256 } : {}),
      ...(input.draft.definitionExtensions ? { definitionExtensions: [...input.draft.definitionExtensions] } : {}),
    },
    generation: input.generation,
  };
}

/** Submit a frozen revision snapshot and require a complete matching acknowledgement. */
export async function postRevision(csrf: ClientCsrf, snapshot: RevisionSnapshot): Promise<RevisionAck> {
  const draft = {
    ...snapshot.draft,
    deviceClockAt: localDateTimeWithOffset(),
  };
  const response = await requestClientJson<RevisionAck>(
    `/api/v1/intake/submissions/${encodeURIComponent(snapshot.vaSid)}/revisions`,
    {
      method: "POST",
      csrf,
      timeoutMs: 120_000,
      json: {
        reason_code: snapshot.reasonCode,
        answers_json: snapshot.answersJson,
        answers_sha256: snapshot.answersSha256,
        completion: snapshot.completion,
        draft,
      },
    },
  );
  if (
    typeof response?.changed !== "boolean" ||
    response.va_sid !== snapshot.vaSid ||
    response.answers_sha256 !== snapshot.answersSha256 ||
    !validId(response.payload_version_id) ||
    !validId(response.outcome) || !REVISION_OUTCOMES.has(response.outcome) ||
    !validId(response.workflow_state)
  ) {
    throw new ClientApiError(200, "malformed_response");
  }
  return response;
}

/** Include refused and respondent-unavailable submissions among incomplete outcomes. */
export function isIncompleteOutcome(value: unknown): boolean {
  return typeof value === "string" && INCOMPLETE_OUTCOMES.has(value);
}

/** True only for an interview that can be completed with `finish_partial`. */
export function isPartialOutcome(value: unknown): boolean {
  return typeof value === "string" && PARTIAL_OUTCOMES.has(value);
}

/** Match the server's consent-first, then validation-based submission outcome. */
export function revisionOutcome(data: SubmissionData, valid: boolean): string | undefined {
  const consent = String(data.Id10013 ?? "").trim().toLowerCase();
  if (consent === "no") return "refused";
  if (valid) return consent ? "completed" : undefined;
  return typeof data.interview_outcome === "string" && isPartialOutcome(data.interview_outcome)
    ? data.interview_outcome
    : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isSubmittedSummary(value: unknown): value is SubmittedRevisionSummary {
  return isRecord(value) && value.status === "submitted" && validId(value.draft_id) &&
    validId(value.project_id) && validId(value.site_id) && validId(value.va_sid) &&
    typeof value.created_at === "string" && typeof value.updated_at === "string" &&
    !("envelope" in value) && !("prefill" in value) && !("answers_json" in value) && !("data" in value);
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

function validId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
