/** Access, intake and draft endpoints. They call the transport through ../api, so its single module state is shared. */
import type { SubmissionData } from "@drguptavivek/who-2022-va";
import { ApiError, INTAKE_API, requestClientJson, requestJson } from "../api";
import type { IdentifierWarning } from "../identifiers";
import type { Translations } from "../translations";
import { safeActionUrl } from "./url";
import {
  intakeContextFromAccess, parseAccessSummary, parseRegisteredDeathPage,
} from "./types";
import type {
  AccessSummary, CaseDetail, CaseRow, ClientCsrf, DraftResponse, DraftSummary, FormOptions, IntakeBootstrap,
  IntakeScope, RegisteredDeathPage, RegistrationInput,
} from "./types";

/** Refresh current grants for either credential; a refusal propagates unchanged. */
export async function getAccessSummary(csrf?: ClientCsrf, server = "", token?: string): Promise<AccessSummary> {
  return parseAccessSummary((await requestJson<unknown>(server, "/api/v1/me/access", { csrf, token })).body);
}

/** Read one bounded page of the caller's own registered deaths. */
export async function getRegisteredDeaths(
  csrf: ClientCsrf,
  registeredMine: boolean,
  cursor?: string | null,
  training = false,
): Promise<RegisteredDeathPage> {
  const params = new URLSearchParams({ limit: "50" });
  if (training) params.set("training", "1");
  if (registeredMine) params.set("registered", "mine");
  if (cursor) params.set("cursor", cursor);
  return parseRegisteredDeathPage(await requestClientJson<unknown>(`${INTAKE_API}/deaths?${params}`, { csrf }));
}

/** Read collection sites, modes, and unit scope from the authoritative access answer. */
export async function getIntakeContext(
  csrf: ClientCsrf,
  action: "interview" | "register_death" = "interview",
  scope: IntakeScope = csrf.training ? "training" : "normal",
): Promise<IntakeBootstrap> {
  const access = await getAccessSummary(csrf);
  const contexts = intakeContextFromAccess(access, action, scope);
  return {
    user: access.user,
    context: contexts,
    links: { deaths: `${INTAKE_API}/deaths`, drafts: `${INTAKE_API}/drafts`, cases: `${INTAKE_API}/cases` }
  };
}

/** Read project options and reject malformed intake mode or instrument version. */
export async function getProjectFormOptions(
  projectId: string,
  csrf: ClientCsrf,
): Promise<FormOptions> {
  const options = await requestClientJson<unknown>(
    `/api/v1/organization/${encodeURIComponent(projectId)}/form-options`,
    { csrf },
  );
  return parseProjectFormOptions(options);
}

/** Validate shared form-options data before using its project-owned settings. */
export function parseProjectFormOptions(value: unknown): FormOptions {
  const options = value as FormOptions;
  if (!options || typeof options !== "object" || Array.isArray(options) ||
      (options.web_intake_mode !== undefined && !["off", "direct", "death_register", "both"].includes(options.web_intake_mode)) ||
      (options.instrument_version !== undefined && options.instrument_version !== null && typeof options.instrument_version !== "string") ||
      (options.definition_sha256 !== undefined && options.definition_sha256 !== null && typeof options.definition_sha256 !== "string") ||
      (options.narration_languages !== undefined && (!Array.isArray(options.narration_languages) || options.narration_languages.some((language) => !language || typeof language !== "object" || typeof language.code !== "string" || typeof language.label !== "string")))) {
    throw new ApiError(200, "malformed_response");
  }
  return options;
}

export function getInstrumentTranslations(
  instrumentCode: string,
  locale: string,
  csrf: ClientCsrf,
): Promise<Translations> {
  return requestClientJson<Translations>(
    `/api/v1/instruments/${encodeURIComponent(instrumentCode)}/translations/${encodeURIComponent(locale)}`,
    { csrf },
  );
}

export function getCases(
  link: string,
  csrf: ClientCsrf,
  cursor?: string | null,
  projectId?: string,
  training = false,
): Promise<{
  cases: CaseRow[];
  counts?: Record<string, number>;
  next_cursor?: string | null;
}> {
  const params = new URLSearchParams();
  if (training) params.set("training", "1");
  if (projectId) params.set("project_id", projectId);
  if (cursor) params.set("cursor", cursor);
  const query = params.toString();
  return requestClientJson(query ? `${link}?${query}` : link, { csrf });
}

export function getCaseDetail(
  link: string,
  deathId: string,
  csrf: ClientCsrf,
): Promise<{ case: CaseDetail }> {
  const base = link.replace(/\/+$/, "");
  const path = `${base}/${encodeURIComponent(deathId)}`;
  return requestClientJson(csrf.training ? `${path}?training=1` : path, { csrf });
}

export type CaseActionAck = CaseDetail;

export function logContactAttempt(
  link: string,
  deathId: string,
  body: {
    outcome: "reached" | "no_answer" | "wrong_number" | "moved" | "refused";
    next_visit_at?: string;
  },
  csrf: ClientCsrf,
): Promise<{ case: CaseActionAck }> {
  const base = link.replace(/\/+$/, "");
  return requestClientJson(`${base}/${encodeURIComponent(deathId)}/attempts`, {
    method: "POST",
    json: body,
    csrf,
  });
}

export function setCaseVisit(
  link: string,
  deathId: string,
  body: { next_visit_at: string | null },
  csrf: ClientCsrf,
): Promise<{ case: CaseActionAck }> {
  const base = link.replace(/\/+$/, "");
  return requestClientJson(`${base}/${encodeURIComponent(deathId)}/visit`, {
    method: "POST",
    json: body,
    csrf,
  });
}

export function getDrafts(
  link: string,
  csrf: ClientCsrf,
  training = Boolean(csrf.training),
): Promise<{ drafts: DraftSummary[] }> {
  return requestClientJson(training ? `${link}?training=1` : link, { csrf });
}

export function registerDeath(
  link: string,
  input: RegistrationInput,
  csrf: ClientCsrf,
): Promise<{ case: CaseDetail; warnings?: IdentifierWarning[] }> {
  return requestClientJson(link, { method: "POST", json: input, csrf });
}

export function startDraft(
  link: string,
  input: {
    project_id: string;
    site_id: string;
    org_unit_id?: string;
    death_id?: string;
  },
  csrf: ClientCsrf,
): Promise<{ draft: DraftSummary }> {
  return requestClientJson(link, { method: "POST", json: input, csrf });
}

export function getDraft(
  link: string,
  draftId: string,
  csrf: ClientCsrf,
): Promise<DraftResponse> {
  const path = `${link}/${encodeURIComponent(draftId)}`;
  return requestClientJson(csrf.training ? `${path}?training=1` : path, { csrf });
}

export function submitDraft(
  link: string,
  draftId: string,
  completion: { valid: boolean; issues: unknown[]; data?: SubmissionData },
  csrf: ClientCsrf,
  ifUpdatedAt?: string,
): Promise<
  | {
      va_sid: string;
      draft: DraftSummary;
      superseded: false;
      validation_err: unknown[];
      kept?: "incoming" | "server";
      locked?: boolean;
      can_code_now?: boolean;
    }
  | { va_sid: null; draft: DraftSummary; superseded: true; validation_err: null; can_code_now?: false }
> {
  const path = safeActionUrl(`${link}/${encodeURIComponent(draftId)}/submit`);
  if (!path) throw new ApiError(400, "invalid_request");
  return requestJson<unknown>("", path, {
    method: "POST",
    json: { completion, ...(ifUpdatedAt ? { if_updated_at: ifUpdatedAt } : {}) },
    csrf,
  }).then(({ status, body }) => {
    const record = (value: unknown): value is Record<string, unknown> =>
      !!value && typeof value === "object" && !Array.isArray(value);
    if (!record(body)) throw new ApiError(status, "malformed_response");
    const draft = record(body.draft) &&
      typeof body.draft.draft_id === "string" &&
      typeof body.draft.project_id === "string" &&
      typeof body.draft.site_id === "string";
    if (
      status === 201 && draft && typeof body.va_sid === "string" && body.va_sid.length > 0 &&
      body.superseded === false && Array.isArray(body.validation_err)
    ) {
      return { ...body, can_code_now: body.can_code_now === true } as unknown as {
        va_sid: string; draft: DraftSummary; superseded: false; validation_err: unknown[]; can_code_now: boolean;
      };
    }
    if (
      status === 200 && draft && typeof body.va_sid === "string" && body.va_sid.length > 0 &&
      body.superseded === false && Array.isArray(body.validation_err) &&
      (body.kept === "incoming" || body.kept === "server") && typeof body.locked === "boolean"
    ) {
      return { ...body, can_code_now: body.can_code_now === true } as unknown as {
        va_sid: string;
        draft: DraftSummary;
        superseded: false;
        validation_err: unknown[];
        kept: "incoming" | "server";
        locked: boolean;
        can_code_now: boolean;
      };
    }
    if (
      status === 200 && draft && body.va_sid === null &&
      body.superseded === true && body.validation_err === null
    ) {
      return { ...body, can_code_now: false } as unknown as {
        va_sid: null; draft: DraftSummary; superseded: true; validation_err: null; can_code_now: false;
      };
    }
    throw new ApiError(status, "malformed_response");
  });
}
