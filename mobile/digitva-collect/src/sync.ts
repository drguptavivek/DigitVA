/**
 * Push and purge for one interviewer, in dependency order:
 *
 * 1. deaths registered offline (POST /deaths, idempotent on client_death_id);
 *    each acknowledgement rebinds the drafts and actions waiting on it;
 * 2. queued contact attempts and visit dates (idempotent on client_attempt_id;
 *    a visit is idempotent by value);
 * 3. completed interviews (POST /submissions, idempotent on client_draft_id),
 *    with their case's death_id, so a case registered and interviewed offline
 *    arrives registration first;
 * 4. the outstanding-work report (what is still on the phone);
 * 5. the case download (GET /cases, every page), replacing the stored cases.
 *
 * Each item is deleted once the server acknowledges it. A 422 reopens it for
 * editing (a draft goes back to in progress; a registration or action is
 * marked needs_edit); a 404/409 on an action also marks it needs_edit, since
 * it can no longer apply and would be refused on every sync. Also the
 * per-interviewer reference data the device API serves (bootstrap,
 * organization units, form translations), cached in that interviewer's own
 * database and wiped with it.
 *
 * Logs carry client ids and error codes only, never answers or names.
 */
import { ApiError, DEVICE_API } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import {
  acknowledgeRegistration,
  deleteAction,
  listActions,
  listRegistrations,
  replaceCases,
  setActionState,
  setRegistrationState,
  type CaseRow
} from "./cases";
import {
  completedDrafts,
  countDrafts,
  deleteDraft,
  draftIds,
  draftUniqueIds,
  getMeta,
  reopenDraft,
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

/** The case download: pages of the server's maximum, at most this many (5000 cases). */
export const CASE_PAGE_SIZE = 200;
export const CASE_PAGES_MAX = 25;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Whether the server will take this interview: the form said valid, or the interviewer recorded an incomplete outcome. */
export function isUploadable(data: CompletedDraft["draft"]["data"] | undefined, completion: Completion | null): boolean {
  if (completion?.valid === true) return true;
  const outcome = data?.interview_outcome;
  return typeof outcome === "string" && (INCOMPLETE_OUTCOMES as readonly string[]).includes(outcome);
}

/** Session and network failures stop the run with everything kept; anything but an API refusal is rethrown. */
function refusal(error: unknown): ApiError {
  if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
  if (!(error instanceof ApiError)) throw error;
  return error;
}

export async function syncInterviewer(userId: string, db: Db): Promise<SyncResult> {
  let sent = 0;
  let failed = 0;

  for (const reg of await listRegistrations(db)) {
    if (reg.state !== "pending") continue;
    try {
      const { body } = await authedRequest<{ case: CaseRow }>(userId, `${DEVICE_API}/deaths`, {
        method: "POST",
        body: {
          client_death_id: reg.client_death_id,
          site_id: reg.site_id,
          ...(reg.org_unit_id ? { org_unit_id: reg.org_unit_id } : {}),
          ...reg.fields
        }
      });
      await acknowledgeRegistration(db, reg.client_death_id, body.case);
      sent += 1;
    } catch (error) {
      const refused = refusal(error);
      console.warn(`registration refused id=${reg.client_death_id} status=${refused.status} code=${refused.code ?? "-"}`);
      if (refused.status === 422) await setRegistrationState(db, reg.client_death_id, "needs_edit");
      failed += 1;
    }
  }

  for (const action of await listActions(db)) {
    if (action.state !== "pending" || !action.death_id) continue; // waits for its registration
    const path = `${DEVICE_API}/cases/${encodeURIComponent(action.death_id)}/${action.kind === "attempt" ? "attempts" : "visit"}`;
    try {
      await authedRequest(userId, path, {
        method: "POST",
        body:
          action.kind === "attempt"
            ? { client_attempt_id: action.client_id, ...action.body }
            : { next_visit_at: action.body.next_visit_at ?? null }
      });
      await deleteAction(db, action.client_id);
      sent += 1;
    } catch (error) {
      const refused = refusal(error);
      console.warn(`case action refused id=${action.client_id} status=${refused.status} code=${refused.code ?? "-"}`);
      if ([404, 409, 422].includes(refused.status)) await setActionState(db, action.client_id, "needs_edit");
      failed += 1;
    }
  }

  for (const item of await completedDrafts(db)) {
    if (!isUploadable(item.draft.data, item.completion)) continue; // stays on the phone, counted as remaining
    if (item.client_death_id && !item.death_id) continue; // its registration is not accepted yet
    try {
      await authedRequest(userId, `${DEVICE_API}/submissions`, {
        method: "POST",
        body: {
          client_draft_id: item.id,
          site_id: item.site_id,
          ...(item.org_unit_id ? { org_unit_id: item.org_unit_id } : {}),
          ...(item.death_id ? { death_id: item.death_id } : {}),
          draft: item.draft,
          completion: { valid: item.completion?.valid === true, issues: item.completion?.issues ?? [] }
        }
      });
      await deleteDraft(db, item.id);
      sent += 1;
    } catch (error) {
      // A per-draft refusal (409/413/422) keeps that draft and moves on; a
      // 422 (the interview as it stands) also reopens it for editing.
      const refused = refusal(error);
      console.warn(`submission refused draft=${item.id} status=${refused.status} code=${refused.code ?? "-"}`);
      if (refused.status === 422) await reopenDraft(db, item.id);
      failed += 1;
    }
  }

  const remaining = await countDrafts(db);
  await authedRequest(userId, `${DEVICE_API}/outstanding`, {
    method: "POST",
    body: {
      count: remaining,
      unique_ids: await draftUniqueIds(db),
      client_draft_ids: (await draftIds(db)).filter((id) => UUID.test(id)),
      client_death_ids: (await listRegistrations(db)).map((reg) => reg.client_death_id)
    }
  });
  await refreshCases(userId, db);
  return { sent, failed, remaining };
}

/**
 * GET every page of /cases and make the stored cases exactly that list, so
 * a case the server no longer offers (submitted, closed, out of scope, or
 * started by a teammate) leaves the phone. A failure part way leaves the
 * stored cases as they were.
 */
export async function refreshCases(userId: string, db: Db): Promise<CaseRow[]> {
  const rows: CaseRow[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < CASE_PAGES_MAX; page += 1) {
    const query: string = `?limit=${CASE_PAGE_SIZE}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const { body } = await authedRequest<{ cases: CaseRow[]; next_cursor: string | null }>(
      userId,
      `${DEVICE_API}/cases${query}`
    );
    rows.push(...body.cases);
    cursor = body.next_cursor;
    if (!cursor) break;
  }
  await replaceCases(db, rows);
  return rows;
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

/** Whether a site's project mode takes death registrations (web_intake_service._mode_allows). */
export function registersDeaths(bootstrap: Bootstrap | undefined, siteId?: string): boolean {
  return (bootstrap?.context ?? []).some(
    (entry) => (!siteId || entry.site_id === siteId) && ["death_register", "both"].includes(entry.web_intake_mode ?? "")
  );
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
    /** off, direct, death_register or both (web_intake_service.WEB_INTAKE_MODES). */
    web_intake_mode?: string;
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
