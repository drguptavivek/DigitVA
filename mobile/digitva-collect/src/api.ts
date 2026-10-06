/**
 * JSON calls to the DigitVA API (`/api/v1`). Errors follow the
 * contract {"error": "<message>", "code": "<machine_code>"}. Parsed error
 * payloads are available for handling and must never be logged.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | undefined,
    public readonly redirectUrl?: string,
    public readonly csrf?: ClientCsrf,
    public readonly payload?: Record<string, unknown>
  ) {
    super(`HTTP ${status}${code ? ` ${code}` : ""}`);
    this.name = "ApiError";
  }
}

export const AUTH_API = "/api/v1/auth";

export const INTAKE_API = "/api/v1/intake";

import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";
import { Platform } from "react-native";
import type { Translations } from "./translations";

export interface AccessUnit {
  org_unit_id: string;
  unit_code: string;
  unit_name: string;
  level_code: string;
  path: string;
  is_active: boolean;
  selectable: boolean;
  roles: string[];
  can_code: boolean;
}

export interface AccessProject {
  project_id: string;
  project_name: string;
  has_tree: boolean;
  grants: Array<{ role: string; scope: string; site_id?: string; org_unit_id?: string; unit_name?: string; codes?: boolean; active: boolean; source: "assigned" | "self_coding" }>;
  sites: Array<{ site_id: string; site_name: string; roles: string[] }>;
  actions: { interview: Array<{
    site_id: string;
    site_name: string;
    web_intake_mode: "direct" | "death_register" | "both";
    org_units: Array<{ org_unit_id: string; unit_code: string; unit_name: string; path: string }>;
  }> };
  units?: AccessUnit[];
  levels?: Array<{ level_code: string; level_name: string; depth: number }>;
}

export interface AccessSummary {
  user: { user_id: string; name: string };
  is_admin: boolean;
  roles: string[];
  demo_coding: { available: boolean; project_ids: string[] };
  projects: AccessProject[];
}

/** Validate the access boundary before using server data to gate screens or pickers. */
export function parseAccessSummary(value: unknown): AccessSummary {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const strings = (item: unknown): item is string[] => Array.isArray(item) && item.every((part) => typeof part === "string");
  if (!record(value) || !record(value.user) || typeof value.user.user_id !== "string" || typeof value.user.name !== "string" ||
      typeof value.is_admin !== "boolean" || !record(value.demo_coding) || typeof value.demo_coding.available !== "boolean" ||
      !strings(value.roles) || !strings(value.demo_coding.project_ids) || !Array.isArray(value.projects)) throw new ApiError(200, "malformed_response");
  for (const project of value.projects) {
    if (!record(project) || typeof project.project_id !== "string" || typeof project.project_name !== "string" ||
        typeof project.has_tree !== "boolean" || !Array.isArray(project.grants) || !Array.isArray(project.sites) ||
        !record(project.actions) || !Array.isArray(project.actions.interview)) throw new ApiError(200, "malformed_response");
    for (const grant of project.grants) {
      if (!record(grant) || typeof grant.role !== "string" || !["project", "project_site", "org_unit"].includes(String(grant.scope)) ||
          typeof grant.active !== "boolean" || !["assigned", "self_coding"].includes(String(grant.source)) ||
          (grant.scope === "project_site" && typeof grant.site_id !== "string") ||
          (grant.scope === "org_unit" && (typeof grant.org_unit_id !== "string" || typeof grant.unit_name !== "string")) ||
          (["coder", "coding_tester", "reviewer"].includes(grant.role) && typeof grant.codes !== "boolean")) throw new ApiError(200, "malformed_response");
    }
    for (const entry of project.actions.interview) {
      if (!record(entry) || typeof entry.site_id !== "string" || typeof entry.site_name !== "string" ||
          !["direct", "death_register", "both"].includes(String(entry.web_intake_mode)) || !Array.isArray(entry.org_units) ||
          entry.org_units.some((unit) => !record(unit) ||
            !["org_unit_id", "unit_code", "unit_name", "path"].every((field) => typeof unit[field] === "string"))) {
        throw new ApiError(200, "malformed_response");
      }
    }
    for (const site of project.sites) {
      if (!record(site) || typeof site.site_id !== "string" || typeof site.site_name !== "string" || !strings(site.roles)) throw new ApiError(200, "malformed_response");
    }
    if (project.has_tree && (!Array.isArray(project.units) || !Array.isArray(project.levels))) throw new ApiError(200, "malformed_response");
    if (Array.isArray(project.units)) for (const unit of project.units) {
      if (!record(unit) || !["org_unit_id", "unit_code", "unit_name", "level_code", "path"].every((field) => typeof unit[field] === "string") ||
          !strings(unit.roles) || typeof unit.selectable !== "boolean" || typeof unit.can_code !== "boolean" || typeof unit.is_active !== "boolean") throw new ApiError(200, "malformed_response");
    }
    if (Array.isArray(project.levels)) for (const level of project.levels) {
      if (!record(level) || typeof level.level_code !== "string" || typeof level.level_name !== "string" || typeof level.depth !== "number") throw new ApiError(200, "malformed_response");
    }
  }
  return value as unknown as AccessSummary;
}

/** Refresh current grants for either credential; a refusal propagates unchanged. */
export async function getAccessSummary(csrf?: ClientCsrf, server = "", token?: string): Promise<AccessSummary> {
  return parseAccessSummary((await requestJson<unknown>(server, "/api/v1/me/access", { csrf, token })).body);
}

/** Navigation is advisory; each action remains authorised by the server. */
export function accessCapabilities(access: AccessSummary): ClientBootstrap["capabilities"] {
  return {
    intake: access.projects.some((project) => project.actions.interview.length > 0),
    coding: access.roles.some((role) => ["coder", "coding_tester"].includes(role)) || access.demo_coding.available,
    reviewing: access.roles.includes("reviewer")
  };
}

/** Expand server interview roots in tree order and retain their ancestor context. */
export function intakeContextFromAccess(access: AccessSummary): IntakeContextEntry[] {
  return access.projects.flatMap((project) => project.actions.interview.map((entry) => {
    const roots = entry.org_units;
    const units = project.units?.filter((unit) => !roots.length || roots.some((root) =>
      unit.path === root.path || unit.path.startsWith(`${root.path}.`) || root.path.startsWith(`${unit.path}.`),
    )).map((unit) => roots.length ? ({
      ...unit,
      selectable: unit.selectable && roots.some((root) => unit.path === root.path || unit.path.startsWith(`${root.path}.`)),
    }) : unit);
    return {
      project_id: project.project_id, project_name: project.project_name, site_id: entry.site_id,
      site_name: entry.site_name, web_intake_mode: entry.web_intake_mode,
      org_units: units ?? roots.map((unit) => ({ ...unit, selectable: true })),
    };
  }));
}

export interface ClientCsrf {
  header: string;
  token: string;
}

export interface ClientLinks {
  login: string;
  logout: string;
  intakeCases: string;
  intakeDrafts: string;
  coding?: string;
  reviewing?: string;
}

export interface ClientBootstrap {
  user: { user_id: string; name: string };
  csrf: ClientCsrf;
  capabilities: { intake: boolean; coding: boolean; reviewing: boolean };
  access: AccessSummary;
  links: ClientLinks;
}

export interface AuthenticationRequired {
  authenticated: false;
  loginUrl: string;
  actionCode?: "terms_required" | "factor_setup_required";
  csrf?: ClientCsrf;
}

export interface AuthenticatedBootstrap {
  authenticated: true;
  bootstrap: ClientBootstrap;
}

export type BootstrapResult = AuthenticationRequired | AuthenticatedBootstrap;

export { ApiError as ClientApiError };

export interface IntakeContextEntry {
  project_id: string;
  project_name?: string;
  site_id: string;
  site_name?: string;
  web_intake_mode?: string;
  org_units?: Array<{
    org_unit_id: string;
    unit_code?: string;
    unit_name?: string;
    level_code?: string;
    level_name?: string;
    path?: string;
    is_active?: boolean;
    selectable?: boolean;
  }>;
}

export interface FormOptions {
  web_intake_mode?: "off" | "direct" | "death_register" | "both";
  instrument_version?: string | null;
  definition_sha256?: string | null;
  narration_languages?: Array<{ code: string; label: string }>;
  project_id?: string;
  enabled_extensions?: string[];
  form_types?: Array<{ instrument_code: string | null; is_default: boolean }>;
  available_locales?: Array<{
    code: string;
    label: string;
    under_review?: boolean;
  }>;
  default_locale?: string;
  translation_versions?: Record<string, number>;
  intake_note?: string | null;
}

export interface IntakeBootstrap {
  user?: { user_id: string; name: string };
  context: IntakeContextEntry[];
  form_options?: FormOptions;
  instrument_version?: string;
  /** Server-provided action links; callers must not reconstruct prefixed paths. */
  links?: { deaths?: string; drafts?: string; cases?: string };
}

export interface CaseRow {
  death_id: string;
  unique_id: string;
  deceased_name?: string;
  deceased_sex?: string;
  date_of_death?: string;
  age_years?: number | null;
  status?: string;
  state?: string;
  project_id?: string;
  site_id?: string;
  site_name?: string;
  org_unit_id?: string | null;
  org_unit_name?: string | null;
  unit_name?: string | null;
  informant_phone_masked?: string | null;
  informant_phone_2_masked?: string | null;
  last_contact_at?: string | null;
  next_visit_at?: string | null;
  my_draft_id?: string | null;
  other_draft_active?: boolean;
  other_draft_started_at?: string | null;
  other_complete_interview?: boolean;
  code_now?: boolean;
  [key: string]: unknown;
}

export interface CaseDetailDeceased {
  name?: string | null;
  sex?: string | null;
  age_years?: number | null;
  date_of_birth?: string | null;
  date_of_birth_partial?: string | null;
  date_of_death?: string | null;
  place_of_death?: string | null;
}

export interface CaseDetailAddress {
  address?: string | null;
  house_street?: string | null;
  village_ward?: string | null;
  landmark?: string | null;
}

export interface CaseDetailInformant {
  name?: string | null;
  phone?: string | null;
  phone_2?: string | null;
}

export interface CaseDetailLinks {
  self?: string;
  attempts?: string;
  visit?: string;
  start_interview?: string;
  form?: string;
}

export interface CaseDetail extends CaseRow {
  prefill?: Record<string, unknown>;
  deceased?: CaseDetailDeceased | null;
  household_address?: CaseDetailAddress | null;
  informant?: CaseDetailInformant | null;
  remarks?: string | null;
  details_pending?: boolean;
  pending_flag?: string | null;
  registered_by_me?: boolean;
  started_by_me?: boolean;
  va_sid?: string | null;
  created_at?: string;
  updated_at?: string;
  links?: CaseDetailLinks;
}

export interface DraftSummary {
  draft_id: string;
  unique_id?: string;
  project_id: string;
  site_id: string;
  site_name?: string;
  org_unit_id?: string | null;
  org_unit_name?: string | null;
  death_id?: string | null;
  status?: string;
  current_section?: string | null;
  updated_at?: string;
  [key: string]: unknown;
}

export interface DraftEnvelope extends WhoVaDraft {
  data: SubmissionData;
  locale?: string;
  translation_version?: number;
}

export interface DraftResponse {
  draft: DraftSummary;
  envelope: DraftEnvelope;
  prefill: Record<string, unknown>;
}

export interface RegistrationInput {
  project_id: string;
  site_id: string;
  org_unit_id?: string;
  deceased_name: string;
  deceased_sex: string;
  date_of_death: string;
  date_of_birth?: string;
  date_of_birth_partial?: string;
  age_years?: string;
  abha_number?: string;
  abha_address?: string;
  place_of_death?: string;
  address?: string;
  address_house_street?: string;
  address_village_ward?: string;
  address_landmark?: string;
  informant_name?: string;
  father_name?: string;
  mother_name?: string;
  informant_phone?: string;
  informant_phone_2?: string;
  remarks?: string;
}

export interface ClientRequestOptions {
  method?: string;
  json?: unknown;
  csrf?: ClientCsrf;
  signal?: AbortSignal;
  /** Total request and response-body deadline; defaults to 30 seconds. */
  timeoutMs?: number;
  /** Accept the Flask logout redirect without following its HTML landing page. */
  allowRedirect?: boolean;
}

export interface RawApiResponse {
  status: number;
  body: string | null;
  headers: {
    etag: string | null;
    definitionSha256: string | null;
    contentEncoding: string | null;
  };
  csrf?: ClientCsrf;
}

function sameOriginRedirect(response: Response): string | undefined {
  if (!response.redirected || typeof window === "undefined") return undefined;
  try {
    const target = new URL(response.url, window.location.href);
    return target.origin === window.location.origin
      ? target.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function safeActionUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || !value) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  if (typeof window === "undefined") return undefined;
  try {
    const target = new URL(value, window.location.href);
    return target.origin === window.location.origin
      ? target.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Send JSON with bearer or cookie credentials. Refusals expose only status/code;
 * malformed success and HTML redirects fail explicitly, while network errors propagate.
 */
export async function requestJson<T>(
  server: string,
  path: string,
  options: ClientRequestOptions & { body?: unknown; token?: string } = {},
): Promise<{ status: number; body: T; csrf?: ClientCsrf }> {
  const json = options.body !== undefined ? options.body : options.json;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  if (options.token !== undefined) headers.Authorization = `Bearer ${options.token}`;
  else if (options.csrf) headers["X-CSRFToken"] = options.csrf.token;
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 30_000;
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${server}${path}`, {
      method: options.method ?? "GET",
      credentials: options.token !== undefined || server ? "omit" : "include",
      cache: "no-store",
      headers,
      body: json === undefined ? undefined : JSON.stringify(json),
      signal: controller.signal,
      redirect: options.allowRedirect ? "manual" : "follow",
    });
    const csrfToken = options.token === undefined && !server ? response.headers.get("X-CSRFToken") : null;
    const csrf = typeof csrfToken === "string" && csrfToken.trim() ? { header: "X-CSRFToken", token: csrfToken } : undefined;
    if (response.status === 204) return { status: 204, body: undefined as T };
    const contentType = response.headers.get("content-type") ?? "";
    let body: Record<string, unknown> = {};
    let malformedJson = false;
    if (contentType.includes("json")) {
      try {
        const parsed = await response.json();
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          body = parsed as Record<string, unknown>;
        } else {
          malformedJson = true;
        }
      } catch (error) {
        if (controller.signal.aborted) throw error;
        malformedJson = true;
        body = {};
      }
    } else {
      try {
        await response.text();
      } catch (error) {
        if (controller.signal.aborted) throw error;
      }
    }
    const redirectUrl = sameOriginRedirect(response);
    const manualRedirect =
      options.allowRedirect &&
      (response.status === 0 ||
        response.type === "opaqueredirect" ||
        (response.status >= 300 && response.status < 400));
    if (manualRedirect) return { status: response.status, body: body as T };
    if (response.redirected || !contentType.includes("json")) {
      throw new ApiError(
        response.status,
        "redirected_response",
        redirectUrl,
      );
    }
    if (malformedJson && response.ok) {
      throw new ApiError(
        response.status,
        "malformed_response",
        redirectUrl,
      );
    }
    if (!response.ok) {
      const code =
        typeof body.code === "string"
          ? body.code
          : undefined;
      if (response.status === 403 && options.token === undefined && path !== "/api/v1/me/access" && typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new Event("digitva-access-stale"));
      }
      throw new ApiError(response.status, code, redirectUrl, csrf, body);
    }
    return { status: response.status, body: body as T, ...(csrf ? { csrf } : {}) };
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

/** Count UTF-8 bytes without relying on TextEncoder in the native runtime. */
function utf8ByteLength(value: string): number {
  let bytes = 0;
  for (let index = 0; index < value.length; ) {
    const code = value.charCodeAt(index);
    if (code <= 0x7f) {
      bytes += 1;
      index += 1;
    } else if (code <= 0x7ff) {
      bytes += 2;
      index += 1;
    } else if (code >= 0xd800 && code <= 0xdbff && index + 1 < value.length &&
        value.charCodeAt(index + 1) >= 0xdc00 && value.charCodeAt(index + 1) <= 0xdfff) {
      bytes += 4;
      index += 2;
    } else {
      // Lone surrogates are represented by the UTF-8 replacement character.
      bytes += 3;
      index += 1;
    }
  }
  return bytes;
}

/**
 * Read response text for definition hashing and reject declared or decoded UTF-8 bodies over 8 MiB.
 * Native fetch exposes text() rather than a portable streaming reader, so its string is materialized
 * before the decoded-byte check. A 304 has no body; other refusals use the machine-code ApiError contract.
 */
export async function requestRaw(
  server: string,
  path: string,
  options: ClientRequestOptions & {
    token?: string;
    ifNoneMatch?: string;
    acceptGzip?: boolean;
  } = {},
): Promise<RawApiResponse> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.token !== undefined) headers.Authorization = `Bearer ${options.token}`;
  else if (options.csrf) headers["X-CSRFToken"] = options.csrf.token;
  if (options.ifNoneMatch !== undefined) {
    if (!/^"[0-9a-f]{64}"$/.test(options.ifNoneMatch)) throw new ApiError(400, "invalid_request");
    headers["If-None-Match"] = options.ifNoneMatch;
  }
  if (options.acceptGzip && Platform.OS !== "web") headers["Accept-Encoding"] = "gzip";

  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 30_000;
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${server}${path}`, {
      method: options.method ?? "GET",
      credentials: options.token !== undefined || server ? "omit" : "include",
      cache: "no-store",
      headers,
      signal: controller.signal,
      redirect: options.allowRedirect ? "manual" : "follow",
    });
    const csrfToken = options.token === undefined && !server ? response.headers.get("X-CSRFToken") : null;
    const csrf = typeof csrfToken === "string" && csrfToken.trim()
      ? { header: "X-CSRFToken", token: csrfToken }
      : undefined;
    const responseHeaders = {
      etag: response.headers.get("ETag"),
      definitionSha256: response.headers.get("X-Definition-SHA256"),
      contentEncoding: response.headers.get("Content-Encoding"),
    };
    const redirectUrl = sameOriginRedirect(response);
    const manualRedirect = options.allowRedirect &&
      (response.status === 0 || response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400));
    if (manualRedirect || response.redirected) throw new ApiError(response.status, "redirected_response", redirectUrl);
    if (response.status === 403 && options.token === undefined && path !== "/api/v1/me/access" && typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new Event("digitva-access-stale"));
    }
    if (response.status !== 304) {
      const contentLength = Number(response.headers.get("Content-Length"));
      if (Number.isFinite(contentLength) && contentLength > 8 * 1024 * 1024) {
        throw new ApiError(response.status, "response_too_large");
      }
    }
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType && !contentType.toLowerCase().includes("json")) {
      throw new ApiError(response.status, "redirected_response", redirectUrl);
    }
    if (response.status === 304) return { status: 304, body: null, headers: responseHeaders, ...(csrf ? { csrf } : {}) };
    if (!contentType.toLowerCase().includes("json")) throw new ApiError(response.status, "redirected_response", redirectUrl);

    let body: string;
    try {
      body = await response.text();
    } catch (error) {
      if (controller.signal.aborted) throw error;
      throw new ApiError(response.status, "malformed_response");
    }
    if (utf8ByteLength(body) > 8 * 1024 * 1024) throw new ApiError(response.status, "response_too_large");
    if (!response.ok) {
      let payload: Record<string, unknown> = {};
      try {
        const parsed: unknown = JSON.parse(body);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
      } catch {
        // Keep the JSON client's generic error shape for malformed refusal bodies.
      }
      const code = typeof payload.code === "string" ? payload.code : undefined;
      throw new ApiError(response.status, code, redirectUrl, csrf, payload);
    }
    return { status: response.status, body, headers: responseHeaders, ...(csrf ? { csrf } : {}) };
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

/** Cookie-session wrapper over the same transport used by bearer clients. */
export async function requestClientJson<T>(path: string, options: ClientRequestOptions = {}): Promise<T> {
  const internalPath = safeActionUrl(path);
  if (!internalPath) throw new ApiError(400, "invalid_request");
  return (await requestJson<T>("", internalPath, options)).body;
}

/** Build browser session state from the shared access body and cookie-only CSRF header. */
export async function fetchClientBootstrap(): Promise<BootstrapResult> {
  const login = "/vaauth/valogin?next=%2Fapp%2F";
  try {
    const response = await requestJson<unknown>("", "/api/v1/me/access");
    const access = parseAccessSummary(response.body);
    if (!response.csrf) throw new ApiError(200, "malformed_response");
    return { authenticated: true, bootstrap: {
      user: access.user, csrf: response.csrf, access,
      capabilities: accessCapabilities(access),
      links: { login, logout: "/vaauth/valogout", coding: "/coding/", reviewing: "/reviewing/", intakeCases: `${INTAKE_API}/cases`, intakeDrafts: `${INTAKE_API}/drafts` }
    } };
  } catch (error) {
    if (error instanceof ApiError && error.code === "unauthorized") {
      return { authenticated: false, loginUrl: login };
    }
    if (error instanceof ApiError && error.status === 403 &&
        (error.code === "terms_required" || error.code === "factor_setup_required")) {
      return { authenticated: false,
        loginUrl: error.code === "terms_required" ? "/profile/force-password-change" : "/profile/#passkeys-card",
        actionCode: error.code, ...(error.csrf ? { csrf: error.csrf } : {})
      };
    }
    throw error;
  }
}

/** Read collection sites, modes, and unit scope from the authoritative access answer. */
export async function getIntakeContext(csrf: ClientCsrf): Promise<IntakeBootstrap> {
  const access = await getAccessSummary(csrf);
  const contexts = intakeContextFromAccess(access);
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
): Promise<{
  cases: CaseRow[];
  counts?: Record<string, number>;
  next_cursor?: string | null;
}> {
  const suffix = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return requestClientJson(`${link}${suffix}`, { csrf });
}

export function getCaseDetail(
  link: string,
  deathId: string,
  csrf: ClientCsrf,
): Promise<{ case: CaseDetail }> {
  const base = link.replace(/\/+$/, "");
  return requestClientJson(`${base}/${encodeURIComponent(deathId)}`, { csrf });
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
): Promise<{ drafts: DraftSummary[] }> {
  return requestClientJson(link, { csrf });
}

export function registerDeath(
  link: string,
  input: RegistrationInput,
  csrf: ClientCsrf,
): Promise<{ case: CaseDetail }> {
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
  return requestClientJson(`${link}/${encodeURIComponent(draftId)}`, { csrf });
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
