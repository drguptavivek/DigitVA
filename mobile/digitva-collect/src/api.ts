/**
 * JSON calls to the DigitVA API (`/api/v1`). Errors follow the
 * contract {"error": "<message>", "code": "<machine_code>"}. Parsed error
 * payloads are available for handling and must never be logged.
 */

import { ErrorCode } from "./errorCodes";
import { assertOnline, noteRequestOk, serverFetch } from "./network";
import { recordServerDate } from "./phoneClock";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | undefined,
    public readonly redirectUrl?: string,
    public readonly csrf?: ClientCsrf,
    public readonly payload?: Record<string, unknown>,
    /** Masked route of the failing request (see maskApiPath); for on-screen error references. */
    public path?: string,
    public method?: string
  ) {
    super(`HTTP ${status}${code ? ` ${code}` : ""}`);
    this.name = "ApiError";
  }
}

/** Route only: no origin or query, id-like segments (digits, UUIDs, 8+ char hex/opaque tokens) as :id. */
export function maskApiPath(path: string): string {
  return path.split(/[?#]/)[0].split("/").map((seg) =>
    /^\d+$/.test(seg) || /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(seg) || (seg.length >= 8 && /\d/.test(seg) && /^[\w~.-]+$/.test(seg)) ||
    /^[0-9a-f]{8,}$/i.test(seg) ? ":id" : seg).join("/");
}

function withRoute(error: ApiError, path: string, method?: string): ApiError {
  error.path = maskApiPath(path);
  error.method = method ?? "GET";
  return error;
}

export const AUTH_API = "/api/v1/auth";

export const INTAKE_API = "/api/v1/intake";

import { Platform } from "react-native";
import type {
  AccountDevicesResponse, BootstrapResult, ClientCsrf, DeviceDecommissionResponse,
} from "./api/types";
import { safeActionUrl } from "./api/url";

import * as typesModule from "./api/types";
import * as intakeModule from "./api/intake";
import * as stationModule from "./api/station";
import * as mentorModule from "./api/mentor";

// Plain assignments (not star re-exports, which are getter-only) so jest.spyOn on an api export keeps working.
// api.ts must be the entry point: these capture the modules' exports once they have finished loading.
export const isSmartVaTarget = typesModule.isSmartVaTarget;
export const parseAccessSummary = typesModule.parseAccessSummary;
export const SUPERVISION_ROLES = typesModule.SUPERVISION_ROLES;
export const accessCapabilities = typesModule.accessCapabilities;
export const intakeContextFromAccess = typesModule.intakeContextFromAccess;
export const hasInterviewRegistrationAccess = typesModule.hasInterviewRegistrationAccess;
export const parseRegisteredDeathPage = typesModule.parseRegisteredDeathPage;
export const readLastChange = typesModule.readLastChange;
export const getAccessSummary = intakeModule.getAccessSummary;
export const getRegisteredDeaths = intakeModule.getRegisteredDeaths;
export const getIntakeContext = intakeModule.getIntakeContext;
export const getProjectFormOptions = intakeModule.getProjectFormOptions;
export const parseProjectFormOptions = intakeModule.parseProjectFormOptions;
export const getInstrumentTranslations = intakeModule.getInstrumentTranslations;
export const getCases = intakeModule.getCases;
export const getCaseDetail = intakeModule.getCaseDetail;
export const logContactAttempt = intakeModule.logContactAttempt;
export const setCaseVisit = intakeModule.setCaseVisit;
export const getDrafts = intakeModule.getDrafts;
export const registerDeath = intakeModule.registerDeath;
export const startDraft = intakeModule.startDraft;
export const getDraft = intakeModule.getDraft;
export const submitDraft = intakeModule.submitDraft;
export const fetchStationEnrolmentFile = stationModule.fetchStationEnrolmentFile;
export const fetchStationFacility = stationModule.fetchStationFacility;
export const saveStationFacility = stationModule.saveStationFacility;
export const fetchStationSettings = stationModule.fetchStationSettings;
export const saveStationSettings = stationModule.saveStationSettings;
export const getMentoringSummary = mentorModule.getMentoringSummary;
export const listMentorInstituteStaff = mentorModule.listMentorInstituteStaff;
export const createMentorInstituteStaff = mentorModule.createMentorInstituteStaff;
export const removeMentorInstituteStaff = mentorModule.removeMentorInstituteStaff;
export const getMentorDistricts = mentorModule.getMentorDistricts;
export const getMentorCoders = mentorModule.getMentorCoders;
export const getMentorCoderCases = mentorModule.getMentorCoderCases;
export const createMentorNote = mentorModule.createMentorNote;
export const retractMentorNote = mentorModule.retractMentorNote;
export const getMyMentorFeedback = mentorModule.getMyMentorFeedback;
export const markMentorFeedbackRead = mentorModule.markMentorFeedbackRead;
export type * from "./api/types";
export type * from "./api/intake";
export type * from "./api/station";
export type * from "./api/mentor";

export { ApiError as ClientApiError };

export interface ClientRequestOptions {
  method?: string;
  json?: unknown;
  csrf?: ClientCsrf;
  signal?: AbortSignal;
  /** Total request and response-body deadline; defaults to 30 seconds. */
  timeoutMs?: number;
  /** Accept the Flask logout redirect without following its HTML landing page. */
  allowRedirect?: boolean;
  /** An automatic call, not user activity: it does not extend the server's idle timer (auth-decorator-rbac.md section 5). */
  background?: boolean;
  /** A file sent as the raw body (`application/octet-stream`) with its SHA-256 (hex); used instead of JSON. */
  rawBody?: { bytes: Uint8Array<ArrayBuffer>; sha256?: string };
  /** The route answers a JSON list on success (the ICD-10 coding search); any other route's list is malformed. */
  allowList?: boolean;
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

/**
 * Send JSON with bearer or cookie credentials. Refusals expose only status/code;
 * malformed success and HTML redirects fail explicitly, while network errors propagate.
 */
/**
 * Controllers of cookie-session requests still in flight. Sign-out aborts them first: the server saves
 * the session it loaded when such a request ends, which would otherwise bring the old login back.
 */
const cookieRequests = new Set<AbortController>();

/** Abort every in-flight cookie-session request; callers drop the results (they reject as aborted). */
export function abortClientRequests(): void {
  for (const controller of [...cookieRequests]) controller.abort();
  cookieRequests.clear();
}

/** Read the in-memory per-launch bearer token injected by the local station shell, if present. */
export function getLocalStationLaunchToken(): string | undefined {
  const candidate = (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: unknown }).__DIGITVA_LAUNCH_TOKEN__;
  return typeof candidate === "string" && candidate.trim() !== "" ? candidate.trim() : undefined;
}

/**
 * The newest CSRF token the cookie session (or the local station) sent in an X-CSRFToken response
 * header. flask-wtf tokens expire (WTF_CSRF_TIME_LIMIT, one hour by default), so a token captured in
 * a long-lived bootstrap snapshot goes stale; every same-origin cookie request sends this one instead
 * and falls back to the caller's snapshot only before any response has carried a token.
 */
let currentCsrf: ClientCsrf | undefined;

function rememberCsrf(response: Response): ClientCsrf | undefined {
  const token = response.headers.get("X-CSRFToken");
  if (typeof token !== "string" || !token.trim()) return undefined;
  currentCsrf = { header: "X-CSRFToken", token };
  return currentCsrf;
}

/** Every request made inside the Training screens carries `training=1`; reads must not fall back to the normal scope. */
function scopedPath(path: string, snapshot?: ClientCsrf): string {
  if (!snapshot?.training || /[?&]training=/.test(path)) return path;
  return `${path}${path.includes("?") ? "&" : "?"}training=1`;
}

function cookieCsrfHeader(server: string, snapshot?: ClientCsrf): string | undefined {
  return (server ? snapshot : currentCsrf ?? snapshot)?.token;
}

/**
 * 403 codes that mean the session's access itself changed, so the app re-reads /me/access. Business
 * refusals (`forbidden`, which also carries IDENTIFIER_FORBIDDEN and wrong-password answers,
 * `no_allocation`, `allocation_exists`, ...) must not: that reload resets open screens. A 403 with no
 * machine code (an HTML login or error page) is not a business refusal and still counts.
 */
const ACCESS_CHANGED_403_CODES = new Set(["terms_required", "project_forbidden"]);

const BACKGROUND_HEADER = "X-DigitVA-Background";
let backgroundDepth = 0;

/**
 * Label every cookie request issued while *task* runs as background. ponytail: a user request made
 * concurrently is labelled too (it then does not extend the server timer; the keep-alive ping covers it);
 * pass `background` per request if that ever matters.
 */
export async function runAsBackground<T>(task: () => Promise<T>): Promise<T> {
  backgroundDepth += 1;
  try {
    return await task();
  } finally {
    backgroundDepth -= 1;
  }
}

/** The server signed the session out for inactivity; the app goes to the sign-in page. */
function signalSessionIdle(code: string | undefined, cookie: boolean): void {
  if (cookie && code === ErrorCode.SESSION_EXPIRED && typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new Event("digitva-session-expired"));
    return;
  }
  if (code !== ErrorCode.SESSION_IDLE || !cookie) return;
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new Event("digitva-session-idle"));
  }
}

function signalAccessStale(status: number, code: string | undefined, path: string, cookie: boolean): void {
  if (status !== 403 || !cookie || path === "/api/v1/me/access" || (code !== undefined && !ACCESS_CHANGED_403_CODES.has(code))) return;
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new Event("digitva-access-stale"));
  }
}

/**
 * True when the cookie session is dead: 401, or 400 `csrf_failed` (older servers answered a dead session
 * with that before auth). Callers reach it only after requestJson's one token refresh already failed,
 * so retrying cannot help; they pause and ask the user to sign in (digitva-fvbc).
 */
export function isSignedOutError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || (error.status === 400 && error.code === ErrorCode.CSRF_FAILED));
}

/** Bearer token, or for cookie and local-station calls the CSRF, launch-token and background headers. */
function addCredentialHeaders(
  headers: Record<string, string>,
  server: string,
  options: { token?: string; csrf?: ClientCsrf; background?: boolean },
): void {
  if (options.token !== undefined) {
    headers.Authorization = `Bearer ${options.token}`;
    return;
  }
  const csrfToken = cookieCsrfHeader(server, options.csrf);
  if (csrfToken) headers["X-CSRFToken"] = csrfToken;
  const launchToken = !server ? getLocalStationLaunchToken() : undefined;
  if (launchToken) headers["X-DigitVA-Launch-Token"] = launchToken;
  if (options.background || backgroundDepth > 0) headers[BACKGROUND_HEADER] = "1";
}

/**
 * The one fetch path of requestOnce and requestRaw. Fails offline before fetching; aborts on the caller's
 * signal or after `timeoutMs` (default 30 s), and that deadline also covers *read*; tracks cookie-session
 * requests for abortClientRequests; keeps the response's CSRF token (cookie calls only); notes the server
 * Date and a good network on 2xx. *read* turns the response into the result or an ApiError while the
 * request is still tracked. *body* is built only once online, just before fetching; without it the fetch
 * options have no body key at all.
 */
async function send<R>(
  server: string,
  path: string,
  options: ClientRequestOptions & { token?: string },
  headers: Record<string, string>,
  body: (() => BodyInit | undefined) | undefined,
  read: (response: Response, csrf: ClientCsrf | undefined, signal: AbortSignal) => Promise<R>,
): Promise<R> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 30_000;
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const tracked = options.token === undefined && !server;
  if (tracked) cookieRequests.add(controller);
  try {
    assertOnline();
    const response = await serverFetch(`${server}${scopedPath(path, options.csrf)}`, {
      method: options.method ?? "GET",
      credentials: options.token !== undefined || server ? "omit" : "include",
      cache: "no-store",
      headers,
      ...(body ? { body: body() } : {}),
      signal: controller.signal,
      redirect: options.allowRedirect ? "manual" : "follow",
    });
    const csrf = tracked ? rememberCsrf(response) : undefined;
    if (response.ok) {
      recordServerDate(response.headers.get("Date"));
      noteRequestOk();
    }
    return await read(response, csrf, controller.signal);
  } finally {
    clearTimeout(timeout);
    if (tracked) cookieRequests.delete(controller);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

let csrfRefresh: Promise<unknown> | undefined;

/** Re-read /me/access once for a fresh token; concurrent csrf_failed refusals share the one request. */
function refreshCsrf(): Promise<unknown> {
  csrfRefresh ??= requestOnce("", "/api/v1/me/access", {}).finally(() => { csrfRefresh = undefined; });
  return csrfRefresh;
}

/**
 * A cookie request refused with 400 `csrf_failed` (an expired token) refreshes the token once and is
 * retried once; the server refused it before handling, so the retry cannot apply it twice. A second
 * refusal surfaces as `csrf_failed` for the screen's own message.
 */
export async function requestJson<T>(
  server: string,
  path: string,
  options: ClientRequestOptions & { body?: unknown; token?: string } = {},
): Promise<{ status: number; body: T; csrf?: ClientCsrf }> {
  try {
    return await requestOnce<T>(server, path, options);
  } catch (error) {
    const cookie = options.token === undefined && !server;
    if (!cookie || path === "/api/v1/me/access" || !(error instanceof ApiError)
      || error.status !== 400 || error.code !== ErrorCode.CSRF_FAILED || options.signal?.aborted) throw error;
    await refreshCsrf();
    return requestOnce<T>(server, path, options);
  }
}

async function requestOnce<T>(
  server: string,
  path: string,
  options: ClientRequestOptions & { body?: unknown; token?: string },
): Promise<{ status: number; body: T; csrf?: ClientCsrf }> {
  const json = options.body !== undefined ? options.body : options.json;
  const raw = options.rawBody;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (raw) {
    headers["Content-Type"] = "application/octet-stream";
    if (raw.sha256) headers["X-Content-SHA256"] = raw.sha256;
  } else if (json !== undefined) headers["Content-Type"] = "application/json";
  addCredentialHeaders(headers, server, options);
  const requestBody = () => (raw ? raw.bytes : json === undefined ? undefined : JSON.stringify(json));
  return send(server, path, options, headers, requestBody, async (response, csrf, signal) => {
    if (response.status === 204) return { status: 204, body: undefined as T };
    const contentType = response.headers.get("content-type") ?? "";
    let body: Record<string, unknown> = {};
    // A successful JSON list is accepted only from a route that answers one (`allowList`); a refusal is read as an
    // object only, for its code.
    let list: unknown[] | undefined;
    let malformedJson = false;
    if (contentType.includes("json")) {
      try {
        const parsed = await response.json();
        if (Array.isArray(parsed) && response.ok && options.allowList) {
          list = parsed;
        } else if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          body = parsed as Record<string, unknown>;
        } else {
          malformedJson = true;
        }
      } catch (error) {
        if (signal.aborted) throw error;
        malformedJson = true;
        body = {};
      }
    } else {
      try {
        await response.text();
      } catch (error) {
        if (signal.aborted) throw error;
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
      throw withRoute(new ApiError(
        response.status,
        "redirected_response",
        redirectUrl,
      ), path, options.method);
    }
    if (malformedJson && response.ok) {
      throw withRoute(new ApiError(
        response.status,
        "malformed_response",
        redirectUrl,
      ), path, options.method);
    }
    if (!response.ok) {
      const code =
        typeof body.code === "string"
          ? body.code
          : undefined;
      signalAccessStale(response.status, code, path, options.token === undefined);
      signalSessionIdle(code, options.token === undefined && !server);
      throw withRoute(new ApiError(response.status, code, redirectUrl, csrf, body), path, options.method);
    }
    return { status: response.status, body: (list ?? body) as T, ...(csrf ? { csrf } : {}) };
  });
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
  addCredentialHeaders(headers, server, options);
  if (options.ifNoneMatch !== undefined) {
    if (!/^"[0-9a-f]{64}"$/.test(options.ifNoneMatch)) throw withRoute(new ApiError(400, "invalid_request"), path, options.method);
    headers["If-None-Match"] = options.ifNoneMatch;
  }
  if (options.acceptGzip && Platform.OS !== "web") headers["Accept-Encoding"] = "gzip";

  // No body key at all: this transport never sends a request body.
  return send(server, path, options, headers, undefined, async (response, csrf, signal) => {
    const responseHeaders = {
      etag: response.headers.get("ETag"),
      definitionSha256: response.headers.get("X-Definition-SHA256"),
      contentEncoding: response.headers.get("Content-Encoding"),
    };
    const redirectUrl = sameOriginRedirect(response);
    const manualRedirect = options.allowRedirect &&
      (response.status === 0 || response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400));
    if (manualRedirect || response.redirected) throw withRoute(new ApiError(response.status, "redirected_response", redirectUrl), path, options.method);
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().includes("json")) signalAccessStale(response.status, undefined, path, options.token === undefined);
    if (response.status !== 304) {
      const contentLength = Number(response.headers.get("Content-Length"));
      if (Number.isFinite(contentLength) && contentLength > 8 * 1024 * 1024) {
        throw withRoute(new ApiError(response.status, "response_too_large"), path, options.method);
      }
    }
    if (contentType && !contentType.toLowerCase().includes("json")) {
      throw withRoute(new ApiError(response.status, "redirected_response", redirectUrl), path, options.method);
    }
    if (response.status === 304) return { status: 304, body: null, headers: responseHeaders, ...(csrf ? { csrf } : {}) };
    if (!contentType.toLowerCase().includes("json")) throw withRoute(new ApiError(response.status, "redirected_response", redirectUrl), path, options.method);

    let body: string;
    try {
      body = await response.text();
    } catch (error) {
      if (signal.aborted) throw error;
      throw withRoute(new ApiError(response.status, "malformed_response"), path, options.method);
    }
    if (utf8ByteLength(body) > 8 * 1024 * 1024) throw withRoute(new ApiError(response.status, "response_too_large"), path, options.method);
    if (!response.ok) {
      let payload: Record<string, unknown> = {};
      try {
        const parsed: unknown = JSON.parse(body);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
      } catch {
        // Keep the JSON client's generic error shape for malformed refusal bodies.
      }
      const code = typeof payload.code === "string" ? payload.code : undefined;
      signalAccessStale(response.status, code, path, options.token === undefined);
      signalSessionIdle(code, options.token === undefined && !server);
      throw withRoute(new ApiError(response.status, code, redirectUrl, csrf, payload), path, options.method);
    }
    return { status: response.status, body, headers: responseHeaders, ...(csrf ? { csrf } : {}) };
  });
}

/** Cookie-session wrapper over the same transport used by bearer clients. */
export async function requestClientJson<T>(path: string, options: ClientRequestOptions = {}): Promise<T> {
  const internalPath = safeActionUrl(path);
  if (!internalPath) throw new ApiError(400, "invalid_request");
  return (await requestJson<T>("", internalPath, options)).body;
}

/** Browser-session device management; the server scopes the user id to the caller's authorized view. */
export function listUserDevices(userId: string, csrf?: ClientCsrf): Promise<AccountDevicesResponse> {
  return requestClientJson<AccountDevicesResponse>(`/api/v1/users/${encodeURIComponent(userId)}/devices`, { csrf });
}

/** Browser-session decommission; CSRF is carried by the shared cookie transport for this state change. */
export function decommissionUserDevice(
  userId: string,
  deviceId: string,
  csrf?: ClientCsrf,
): Promise<DeviceDecommissionResponse> {
  return requestClientJson<DeviceDecommissionResponse>(
    `/api/v1/users/${encodeURIComponent(userId)}/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE", csrf },
  );
}

/** Build browser session state from the shared access body and cookie-only CSRF header. */
export async function fetchClientBootstrap(options: { background?: boolean } = {}): Promise<BootstrapResult> {
  const login = "/vaauth/valogin?next=%2Fapp%2F";
  try {
    const response = await requestJson<unknown>("", "/api/v1/me/access", { background: options.background });
    const access = parseAccessSummary(response.body);
    if (!response.csrf) throw new ApiError(200, "malformed_response");
    return { authenticated: true, bootstrap: {
      user: access.user, csrf: response.csrf, access,
      capabilities: accessCapabilities(access),
      links: { login, logout: "/vaauth/valogout", coding: "/coding/", reviewing: "/reviewing/", intakeCases: `${INTAKE_API}/cases`, intakeDrafts: `${INTAKE_API}/drafts` }
    } };
  } catch (error) {
    if (error instanceof ApiError && error.code === ErrorCode.UNAUTHORIZED) {
      return { authenticated: false, loginUrl: login };
    }
    if (error instanceof ApiError && error.status === 403 && error.code === ErrorCode.TERMS_REQUIRED) {
      return { authenticated: false,
        loginUrl: "/profile/force-password-change",
        actionCode: error.code, ...(error.csrf ? { csrf: error.csrf } : {})
      };
    }
    throw error;
  }
}

