import { ClientApiError, requestClientJson, type ClientCsrf, type DraftSummary } from "./api";

const INTAKE_DRAFTS = "/api/v1/intake/drafts";

export interface SubmittedRevisionSummary extends DraftSummary {
  status: "submitted";
  va_sid: string;
  created_at: string;
  updated_at: string;
}

/** Return only the server's bounded, newest-first submitted metadata list. */
export async function getSubmittedRevisions(csrf: ClientCsrf, training = false): Promise<SubmittedRevisionSummary[]> {
  const result = await requestClientJson<{ drafts: SubmittedRevisionSummary[] }>(
    `${INTAKE_DRAFTS}?status=submitted${training ? "&training=1" : ""}`,
    { csrf },
  );
  if (!Array.isArray(result?.drafts) || result.drafts.length > 200 || !result.drafts.every(isSubmittedSummary)) {
    throw new ClientApiError(200, "malformed_response");
  }
  return result.drafts.slice(0, 200);
}

function isSubmittedSummary(value: unknown): value is SubmittedRevisionSummary {
  return isRecord(value) && value.status === "submitted" && validId(value.draft_id) &&
    validId(value.project_id) && validId(value.site_id) && validId(value.va_sid) &&
    typeof value.created_at === "string" && typeof value.updated_at === "string" &&
    !("envelope" in value) && !("prefill" in value) && !("answers_json" in value) && !("data" in value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function validId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}
