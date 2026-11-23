/**
 * A supervisor's correction of a submitted interview on the phone (docs/policy/interview-revisions.md, "Supervisor
 * correction"; docs/policy/mobile-sign-in.md). Online only: the answers are read with GET /intake/drafts/<id>, held in
 * memory by the screen, and sent at once with POST /submissions/<va_sid>/revisions. Nothing here touches the encrypted
 * `revision_drafts` queue, which is the interviewer's.
 */
import { ApiError, INTAKE_API } from "../api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "../auth";
import { clockOffsetField } from "../phoneClock";
import { localDateTimeWithOffset } from "../client/localDateTime";
import type { RevisionSnapshot } from "../client/revisions";
import { t } from "../i18n";
import { loadFailureMessage } from "../revisionMessages";
import { validateDetail, type RevisionRow } from "../revisions";
import { isAccountGate } from "../uploadRefusal";
import type { SupervisedCaseDetail } from "./api";

export type InterviewEditTarget = NonNullable<SupervisedCaseDetail["edit_interview"]>;

/** Read the submitted interview the supervisor may correct; a body about another draft or project is refused. */
export async function loadSupervisorDraft(userId: string, target: InterviewEditTarget): Promise<RevisionRow> {
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/drafts/${encodeURIComponent(target.draft_id)}`, {
    projectId: target.project_id,
  });
  const draft = (body as { draft?: Record<string, unknown> } | null)?.draft;
  if (!draft || draft.draft_id !== target.draft_id || draft.va_sid !== target.va_sid ||
      draft.project_id !== target.project_id || draft.site_id !== target.site_id) {
    throw new ApiError(200, "malformed_response");
  }
  return validateDetail({ ...target, death_id: draft.death_id as string | null, status: "submitted" }, body);
}

/** Send the frozen snapshot over the bearer session; the same snapshot may be sent again after a network error. */
export async function sendSupervisorRevision(userId: string, projectId: string, snapshot: RevisionSnapshot): Promise<void> {
  const { body } = await authedRequest<{ changed?: unknown; va_sid?: unknown; answers_sha256?: unknown }>(
    userId,
    `${INTAKE_API}/submissions/${encodeURIComponent(snapshot.vaSid)}/revisions`,
    {
      method: "POST",
      projectId,
      timeoutMs: 120_000,
      bodyFactory: () => ({
        reason_code: snapshot.reasonCode,
        answers_json: snapshot.answersJson,
        answers_sha256: snapshot.answersSha256,
        completion: snapshot.completion,
        draft: { ...snapshot.draft, deviceClockAt: localDateTimeWithOffset(), ...clockOffsetField() },
      }),
    },
  );
  if (typeof body?.changed !== "boolean" || body.va_sid !== snapshot.vaSid || body.answers_sha256 !== snapshot.answersSha256) {
    throw new ApiError(200, "malformed_response");
  }
}

/** The account itself is gated or signed out: nothing on this screen can be retried, so the screen is left. */
export const leavesScreen = (error: unknown): boolean =>
  isAccountGate(error) || error instanceof SessionRevokedError || error instanceof SignInRequiredError;

/** Words for a refused or failed send; the answers stay on the form either way. */
export function sendFailureMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) return t("serverValidation");
  return loadFailureMessage(error);
}
