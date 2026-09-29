/**
 * Push and purge for one interviewer: upload each completed draft the form
 * engine let through, delete it once the server acknowledges it (201 new,
 * 200 resend of the same client_draft_id), then report what is still on the
 * phone to /outstanding. Also the per-interviewer reference data the device
 * API serves (bootstrap, organization units, form translations), cached in
 * that interviewer's own database and wiped with it.
 *
 * Logs carry draft ids and error codes only, never answers or names.
 */
import { ApiError, DEVICE_API } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import {
  completedDrafts,
  countDrafts,
  deleteDraft,
  draftIds,
  getMeta,
  setMeta,
  type CompletedDraft,
  type Completion,
  type Db
} from "./drafts";
import type { Translations } from "./translations";

export interface SyncResult {
  sent: number;
  failed: number;
  remaining: number;
}

/** Outcomes the server accepts for a questionnaire the form reports invalid (web_intake_service._interview_outcome). */
export const INCOMPLETE_OUTCOMES = ["partially_completed", "respondent_unavailable"] as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether the server will take this interview: the form said valid, or the interviewer recorded an incomplete outcome. */
export function isUploadable(data: CompletedDraft["draft"]["data"] | undefined, completion: Completion | null): boolean {
  if (completion?.valid === true) return true;
  const outcome = data?.interview_outcome;
  return typeof outcome === "string" && (INCOMPLETE_OUTCOMES as readonly string[]).includes(outcome);
}

export async function syncInterviewer(userId: string, db: Db): Promise<SyncResult> {
  let sent = 0;
  let failed = 0;
  for (const item of await completedDrafts(db)) {
    if (!isUploadable(item.draft.data, item.completion)) continue; // stays on the phone, counted as remaining
    try {
      await authedRequest(userId, `${DEVICE_API}/submissions`, {
        method: "POST",
        body: {
          client_draft_id: item.id,
          site_id: item.site_id,
          ...(item.org_unit_id ? { org_unit_id: item.org_unit_id } : {}),
          draft: item.draft,
          completion: { valid: item.completion?.valid === true, issues: item.completion?.issues ?? [] }
        }
      });
      await deleteDraft(db, item.id);
      sent += 1;
    } catch (error) {
      // Revocation already wiped the store; sign-in and network errors stop
      // the run with the rest kept. A per-draft refusal (409/413/422) keeps
      // that draft and moves on.
      if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
      if (!(error instanceof ApiError)) throw error;
      console.warn(`submission refused draft=${item.id} status=${error.status} code=${error.code ?? "-"}`);
      failed += 1;
    }
  }
  const remaining = await countDrafts(db);
  const ids = (await draftIds(db)).filter((id) => UUID.test(id));
  // unique_ids are case ids; phase 2a drafts are new interviews with no case yet.
  await authedRequest(userId, `${DEVICE_API}/outstanding`, {
    method: "POST",
    body: { count: remaining, unique_ids: [], client_draft_ids: ids }
  });
  return { sent, failed, remaining };
}

/**
 * GET /bootstrap and /units and cache both in the interviewer's own
 * database. A 403 on /units (no unit reachable) clears the cached tree, so
 * the picker offers nothing rather than a stale choice.
 */
export async function refreshBootstrap(userId: string, db: Db): Promise<{ bootstrap: Bootstrap; units?: Units }> {
  const { body } = await authedRequest<Bootstrap>(userId, `${DEVICE_API}/bootstrap`);
  await setMeta(db, "bootstrap", body);
  let units: Units | undefined;
  try {
    units = (await authedRequest<Units>(userId, `${DEVICE_API}/units`)).body;
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 403)) throw error;
  }
  await setMeta(db, "units", units ?? null);
  return { bootstrap: body, units };
}

/**
 * A locale's questionnaire strings from /device/instruments/.../translations,
 * cached per version (the bootstrap's `translation_versions`) so an edited
 * locale is fetched again. English needs none. Any failure falls back to
 * English for this form, as the web form does.
 */
export async function translationsFor(
  userId: string,
  db: Db,
  code: string,
  locale: string,
  version: number | undefined
): Promise<Translations | null> {
  if (locale === "en") return null;
  const key = `translations:${code}:${locale}:${version ?? "?"}`;
  const cached = await getMeta<Translations>(db, key);
  if (cached) return cached;
  try {
    const path = `${DEVICE_API}/instruments/${encodeURIComponent(code)}/translations/${encodeURIComponent(locale)}`;
    const { body } = await authedRequest<Translations>(userId, path);
    await setMeta(db, key, body);
    return body;
  } catch {
    return null;
  }
}

export interface Target {
  key: string;
  label: string;
  siteId: string;
  orgUnitId?: string;
}

/**
 * What "New interview" offers: one choice per site, or, when the project has
 * an organization tree, one per (site, unit the interviewer may pick). With
 * a tree but no cached units (never fetched, or none reachable) it offers
 * nothing: an interview with no unit could not be routed to a coder.
 */
export function targetsFrom(bootstrap: Bootstrap | undefined, units: Units | null | undefined): Target[] {
  const sites = bootstrap?.context ?? [];
  if (!units) return [];
  const choices = units.units.filter((unit) => unit.selectable && unit.is_active !== false);
  return sites.flatMap((entry) => {
    const site = entry.site_name ?? entry.site_id;
    if (units.levels.length === 0) return [{ key: entry.site_id, label: site, siteId: entry.site_id }];
    return choices.map((unit) => ({
      key: `${entry.site_id}:${unit.org_unit_id}`,
      label: `${site} · ${unit.unit_name}`,
      siteId: entry.site_id,
      orgUnitId: unit.org_unit_id
    }));
  });
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
  }>;
  instrument_version?: string;
  form_options?: {
    enabled_extensions?: string[];
    form_types?: Array<{ instrument_code: string | null; is_default: boolean }>;
    available_locales?: Array<{ code: string; label: string; under_review?: boolean }>;
    default_locale?: string;
    translation_versions?: Record<string, number>;
  };
}

/** GET /device/units: the /api/v1/organization/<p>/units?role=interviewer body. */
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
  }>;
}
