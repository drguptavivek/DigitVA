/**
 * Push and purge for one interviewer: upload each completed draft, delete it
 * once the server acknowledges it (201 new, 200 resend of the same
 * client_draft_id), then report what is still on the phone to /outstanding.
 *
 * Logs carry draft ids and error codes only, never answers or names.
 */
import { ApiError, DEVICE_API } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import { completedDrafts, countDrafts, deleteDraft, setMeta, type Db } from "./drafts";

export interface SyncResult {
  sent: number;
  failed: number;
  remaining: number;
}

export async function syncInterviewer(userId: string, db: Db): Promise<SyncResult> {
  let sent = 0;
  let failed = 0;
  for (const item of await completedDrafts(db)) {
    try {
      await authedRequest(userId, `${DEVICE_API}/submissions`, {
        method: "POST",
        body: {
          client_draft_id: item.id,
          site_id: item.site_id,
          ...(item.org_unit_id ? { org_unit_id: item.org_unit_id } : {}),
          draft: item.draft
        }
      });
      await deleteDraft(db, item.id);
      sent += 1;
    } catch (error) {
      // Revocation already wiped the store; sign-in and network errors stop
      // the run with the rest kept. A per-draft refusal (409/422) keeps that
      // draft and moves on.
      if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
      if (!(error instanceof ApiError)) throw error;
      console.warn(`submission refused draft=${item.id} status=${error.status} code=${error.code ?? "-"}`);
      failed += 1;
    }
  }
  const remaining = await countDrafts(db);
  // unique_ids are case ids; phase 2a drafts are new interviews with no case yet.
  await authedRequest(userId, `${DEVICE_API}/outstanding`, {
    method: "POST",
    body: { count: remaining, unique_ids: [] }
  });
  return { sent, failed, remaining };
}

/** GET /bootstrap and cache it in the interviewer's own database (wiped with it). */
export async function refreshBootstrap(userId: string, db: Db): Promise<Bootstrap> {
  const { body } = await authedRequest<Bootstrap>(userId, `${DEVICE_API}/bootstrap`);
  await setMeta(db, "bootstrap", body);
  return body;
}

/**
 * The fields this app reads. `form_options` is the project's form-options
 * body (the same one the web form reads from /api/v1/organization/<p>/form-options).
 */
export interface Bootstrap {
  user?: { user_id: string; name: string };
  context: Array<{
    project_id: string;
    project_name?: string;
    site_id: string;
    site_name?: string;
    org_units?: Array<{ org_unit_id: string; unit_code?: string; unit_name?: string }>;
  }>;
  instrument_version?: string;
  form_options?: {
    enabled_extensions?: string[];
    form_types?: Array<{ instrument_code: string | null; is_default: boolean }>;
    available_locales?: Array<{ code: string; label: string; under_review?: boolean }>;
    default_locale?: string;
  };
}
