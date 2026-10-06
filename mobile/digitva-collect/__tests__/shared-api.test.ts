import {
  ApiError, ClientApiError, accessCapabilities, fetchClientBootstrap, getAccessSummary,
  getCaseDetail, getCases, getIntakeContext, getProjectFormOptions, intakeContextFromAccess, parseAccessSummary, registerDeath,
  requestClientJson, requestJson, requestRaw, submitDraft, type AccessSummary
} from "../src/api";
import { Platform } from "react-native";

const csrf = { header: "X-CSRFToken", token: "csrf" };
const unit = (id: string, roles: string[], selectable = true, can_code = false) => ({
  org_unit_id: id, unit_code: id, unit_name: id, level_code: "phc", path: `root.${id}`,
  is_active: true, roles, selectable, can_code
});
const access: AccessSummary = {
  user: { user_id: "u1", name: "Worker" }, is_admin: false, roles: ["coder"],
  demo_coding: { available: false, project_ids: [] },
  projects: [{
    project_id: "P1", project_name: "Project", has_tree: true,
    grants: [{ role: "interviewer", scope: "org_unit", org_unit_id: "i", unit_name: "i", active: true, source: "assigned" },
      { role: "coder", scope: "org_unit", org_unit_id: "c", unit_name: "c", codes: true, active: true, source: "assigned" }],
    actions: { interview: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [
      { org_unit_id: "i", unit_code: "i", unit_name: "i", path: "root.i" },
    ] }] },
    sites: [{ site_id: "S1", site_name: "Site", roles: ["interviewer"] },
      { site_id: "S2", site_name: "Other", roles: ["coder"] }],
    levels: [{ level_code: "phc", level_name: "PHC", depth: 1 }],
    units: [{ ...unit("ancestor", [], false), path: "root" }, unit("i", ["interviewer"]), unit("i.child", []),
      unit("i.disabled", [], false), unit("c", ["coder"], true, true)]
  }]
};

function response(body: unknown, status = 200, contentType = "application/json", csrfToken?: string): Response {
  return {
    status, ok: status >= 200 && status < 300, redirected: false,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? contentType : name.toLowerCase() === "x-csrftoken" ? csrfToken ?? null : null }, json: async () => body,
    text: async () => body === undefined ? "" : JSON.stringify(body)
  } as unknown as Response;
}

function rawResponse(input: {
  status: number;
  body?: string;
  contentType?: string;
  etag?: string;
  definitionSha256?: string;
  contentEncoding?: string;
  contentLength?: string;
  redirected?: boolean;
}): Response {
  const headers = new Map<string, string>([
    ["content-type", input.contentType ?? "application/json"],
    ["etag", input.etag ?? '"etag"'],
    ["x-definition-sha256", input.definitionSha256 ?? "a".repeat(64)],
    ["content-encoding", input.contentEncoding ?? ""],
    ["content-length", input.contentLength ?? ""],
  ]);
  return {
    status: input.status,
    ok: input.status >= 200 && input.status < 300,
    redirected: input.redirected ?? false,
    headers: { get: (name: string) => headers.get(name.toLowerCase()) ?? null },
    text: jest.fn(async () => input.body ?? ""),
  } as unknown as Response;
}

afterEach(() => jest.restoreAllMocks());

it("uses one path and body for bearer and cookie credentials", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ case: { death_id: "d1" } }));
  const body = { next_visit_at: "2026-10-04T12:00:00Z" };
  const native = await requestJson("https://digitva.test", "/api/v1/intake/cases/d1/visit", { method: "POST", body, token: "access" });
  const browser = await requestClientJson("/api/v1/intake/cases/d1/visit", { method: "POST", json: body, csrf });
  expect(browser).toEqual(native.body);
  expect(fetch).toHaveBeenNthCalledWith(1, "https://digitva.test/api/v1/intake/cases/d1/visit", expect.objectContaining({
    credentials: "omit", cache: "no-store", headers: expect.objectContaining({ Authorization: "Bearer access" }), body: JSON.stringify(body)
  }));
  expect(fetch).toHaveBeenNthCalledWith(2, "/api/v1/intake/cases/d1/visit", expect.objectContaining({
    credentials: "include", headers: expect.objectContaining({ "X-CSRFToken": "csrf" }), body: JSON.stringify(body)
  }));
  expect((fetch.mock.calls[0][1]?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
  expect((fetch.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBeUndefined();
  expect(ClientApiError).toBe(ApiError);
});

it("accepts the empty 204 outstanding acknowledgement", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(undefined, 204, ""));
  await expect(requestJson("https://digitva.test", "/api/v1/intake/outstanding", { method: "POST", body: { count: 0 }, token: "access" }))
    .resolves.toEqual({ status: 204, body: undefined });
});

it("returns exact raw JSON text and definition headers without parsing it", async () => {
  const text = '\uFEFF{"label":"नमस्कार"}\n';
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(rawResponse({
    status: 200, body: text, etag: '"project-etag"', definitionSha256: "b".repeat(64), contentEncoding: "gzip",
  }));
  const result = await requestRaw("https://digitva.test", "/definition", {
    token: "access", ifNoneMatch: `"${"a".repeat(64)}"`, acceptGzip: true,
  });
  expect(result).toEqual({
    status: 200, body: text,
    headers: { etag: '"project-etag"', definitionSha256: "b".repeat(64), contentEncoding: "gzip" },
  });
  expect(fetch).toHaveBeenCalledWith("https://digitva.test/definition", expect.objectContaining({
    credentials: "omit", cache: "no-store", headers: expect.objectContaining({
      Authorization: "Bearer access", "If-None-Match": `"${"a".repeat(64)}"`,
    }),
  }));
  const acceptEncoding = (fetch.mock.calls[0][1]?.headers as Record<string, string>)["Accept-Encoding"];
  if (Platform.OS === "web") expect(acceptEncoding).toBeUndefined();
  else expect(acceptEncoding).toBe("gzip");
});

it("rejects an invalid ETag before sending a raw request", async () => {
  const fetch = jest.spyOn(globalThis, "fetch");
  await expect(requestRaw("https://digitva.test", "/definition", { ifNoneMatch: '"bad\r\netag"' }))
    .rejects.toMatchObject({ code: "invalid_request" });
  expect(fetch).not.toHaveBeenCalled();
});

it("rejects a declared oversized body before reading it", async () => {
  const oversized = rawResponse({ status: 200, contentLength: String(9 * 1024 * 1024) });
  const text = oversized.text as jest.Mock;
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(oversized);
  await expect(requestRaw("https://digitva.test", "/definition"))
    .rejects.toMatchObject({ code: "response_too_large" });
  expect(text).not.toHaveBeenCalled();
});

it("bounds decoded raw bodies by UTF-8 bytes, not JavaScript characters", async () => {
  const body = "é".repeat(4 * 1024 * 1024 + 1);
  expect(body.length).toBeLessThan(8 * 1024 * 1024);
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(rawResponse({ status: 200, body }));
  await expect(requestRaw("https://digitva.test", "/definition"))
    .rejects.toMatchObject({ code: "response_too_large" });
});

it("keeps 304 bodyless and rejects redirected or non-JSON raw responses", async () => {
  const notModified = rawResponse({ status: 304, body: "should-not-be-read", contentType: "" });
  const text = notModified.text as jest.Mock;
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(notModified);
  await expect(requestRaw("https://digitva.test", "/definition", { ifNoneMatch: `"${"a".repeat(64)}"` }))
    .resolves.toMatchObject({ status: 304, body: null });
  expect(text).not.toHaveBeenCalled();

  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(rawResponse({ status: 304, redirected: true, contentType: "" }));
  await expect(requestRaw("https://digitva.test", "/definition"))
    .rejects.toMatchObject({ code: "redirected_response" });
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(rawResponse({ status: 200, contentType: "text/html", body: "<html/>" }));
  await expect(requestRaw("https://digitva.test", "/definition"))
    .rejects.toMatchObject({ code: "redirected_response" });
});

it("dispatches the browser access-stale event before refusing an HTML 403", async () => {
  const dispatch = jest.fn();
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { dispatchEvent: dispatch } });
  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(rawResponse({ status: 403, contentType: "text/html", body: "<html/>" }));
  await expect(requestRaw("", "/api/v1/intake/form-definition", { csrf }))
    .rejects.toMatchObject({ status: 403, code: "redirected_response" });
  expect(dispatch).toHaveBeenCalledWith(expect.any(Event));
  Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow });
});

it("keeps the total deadline active while reading raw response text", async () => {
  jest.useFakeTimers();
  const fetch = jest.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    const signal = init?.signal as AbortSignal;
    return {
      status: 200, ok: true, redirected: false,
      headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "application/json" : null },
      text: () => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true })),
    } as unknown as Response;
  });
  const pending = requestRaw("https://digitva.test", "/slow", { timeoutMs: 25 }).catch((error: unknown) => error);
  await jest.advanceTimersByTimeAsync(25);
  expect(await pending).toMatchObject({ name: "AbortError" });
  expect((fetch.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
  expect(jest.getTimerCount()).toBe(0);
  jest.useRealTimers();
});

it("branches only on code, never on error text", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "factor_setup_required" }, 403));
  await expect(requestClientJson("/api/v1/profile/security")).rejects.toMatchObject({ status: 403, code: undefined, payload: { error: "factor_setup_required" } });
});

it("aborts while consuming the response body and clears its timeout", async () => {
  jest.useFakeTimers();
  const fetch = jest.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    const signal = init?.signal as AbortSignal;
    return {
      status: 200,
      ok: true,
      redirected: false,
      headers: { get: () => "application/json" },
      json: () => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }))
    } as unknown as Response;
  });
  const pending = requestJson("https://digitva.test", "/slow", { timeoutMs: 25 }).catch((error: unknown) => error);
  await jest.advanceTimersByTimeAsync(25);
  expect(await pending).toMatchObject({ name: "AbortError" });
  expect((fetch.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
  expect(jest.getTimerCount()).toBe(0);
  jest.useRealTimers();
});

it("composes caller abort with the timeout and removes its listener after success", async () => {
  jest.useFakeTimers();
  const caller = new AbortController();
  const remove = jest.spyOn(caller.signal, "removeEventListener");
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ ok: true }));
  await requestJson("https://digitva.test", "/fast", { signal: caller.signal, timeoutMs: 50 });
  expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  expect(jest.getTimerCount()).toBe(0);

  const pendingFetch = jest.spyOn(globalThis, "fetch").mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
    const signal = init?.signal as AbortSignal;
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  const pending = requestJson("https://digitva.test", "/cancelled", { signal: caller.signal, timeoutMs: 50 });
  caller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect((pendingFetch.mock.calls.at(-1)?.[1]?.signal as AbortSignal).aborted).toBe(true);
  expect(jest.getTimerCount()).toBe(0);
  jest.useRealTimers();
});

it("rejects external browser request paths before sending credentials", async () => {
  const fetch = jest.spyOn(globalThis, "fetch");
  await expect(requestClientJson("//outside.test/steal", { csrf })).rejects.toMatchObject({ code: "invalid_request" });
  await expect(requestClientJson("javascript:alert(1)", { csrf })).rejects.toMatchObject({ code: "invalid_request" });
  expect(fetch).not.toHaveBeenCalled();
});

it("uses authoritative interview entries and preserves only authorized subtrees with ancestors", () => {
  const context = intakeContextFromAccess(parseAccessSummary(access));
  expect(context).toHaveLength(1);
  expect(context[0].site_id).toBe("S1");
  expect(context[0].org_units?.map((entry) => entry.org_unit_id)).toEqual(["ancestor", "i", "i.child", "i.disabled"]);
  expect(context[0].org_units?.[0].selectable).toBe(false);
  expect(context[0].org_units?.[1].selectable).toBe(true);
  expect(context[0].org_units?.[2].selectable).toBe(true);
  expect(context[0].org_units?.[3].selectable).toBe(false);
  expect(context[0].web_intake_mode).toBe("both");
  expect(accessCapabilities(access)).toEqual({ intake: true, coding: true, reviewing: false });
  expect(accessCapabilities({ ...access, roles: ["reviewer"] }).reviewing).toBe(true);
  expect(accessCapabilities({ ...access, roles: [], demo_coding: { available: true, project_ids: ["D"] } }).coding).toBe(true);
});

it("treats empty interview unit roots as unrestricted tree access", () => {
  const broad = { ...access, projects: [{ ...access.projects[0], actions: { interview: [
    { ...access.projects[0].actions.interview[0], org_units: [] },
  ] } }] };
  const units = intakeContextFromAccess(parseAccessSummary(broad))[0].org_units;
  expect(units?.map((entry) => entry.org_unit_id)).toEqual(["ancestor", "i", "i.child", "i.disabled", "c"]);
  expect(units?.map((entry) => entry.selectable)).toEqual([false, true, true, false, true]);
});

it.each([null, {}, { ...access, user: { user_id: 42, name: "Worker" } },
  { ...access, projects: [{ ...access.projects[0], sites: [{ site_id: "S1", roles: "interviewer" }] }] },
  { ...access, projects: [{ ...access.projects[0], units: [unit("i", ["interviewer"]), { org_unit_id: "broken" }] }] }
])("rejects malformed access before building pickers", (value) => {
  expect(() => parseAccessSummary(value)).toThrow(ApiError);
});

it("gets interview sites, mode, and unit roots from the access answer", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(access));
  const context = await getIntakeContext(csrf);
  expect(context.links?.deaths).toBe("/api/v1/intake/deaths");
  expect(context.context[0].web_intake_mode).toBe("both");
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/me/access"]);
});

it("accepts the backend narration option objects and nullable non-WHO versions", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({
    project_id: "P1", web_intake_mode: "both", instrument_version: null,
    definition_sha256: null, narration_languages: [{ code: "hi", label: "Hindi" }],
  }));
  await expect(getProjectFormOptions("P1", csrf)).resolves.toMatchObject({
    instrument_version: null,
    definition_sha256: null,
    narration_languages: [{ code: "hi", label: "Hindi" }],
  });
  expect(fetch).toHaveBeenCalledWith("/api/v1/organization/P1/form-options", expect.any(Object));

  jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({ narration_languages: ["hi"] }));
  await expect(getProjectFormOptions("P1", csrf)).rejects.toMatchObject({ code: "malformed_response" });
});

it("fetches validated access with either credential", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(access));
  await expect(getAccessSummary(csrf)).resolves.toEqual(access);
  await expect(getAccessSummary(undefined, "https://digitva.test", "access")).resolves.toEqual(access);
});

it("loads browser access without probing project metadata and uses its CSRF header on mutations", async () => {
  const fetch = jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(access, 200, "application/json", "session-csrf"))
    .mockResolvedValueOnce(response({ case: { death_id: "d1" } }));
  const result = await fetchClientBootstrap();
  expect(result).toMatchObject({ authenticated: true, bootstrap: {
    user: { user_id: "u1", name: "Worker" }, csrf: { header: "X-CSRFToken", token: "session-csrf" },
    capabilities: { intake: true, coding: true, reviewing: false },
    links: { login: "/vaauth/valogin?next=%2Fapp%2F", logout: "/vaauth/valogout", intakeCases: "/api/v1/intake/cases" }
  } });
  if (!result.authenticated) throw new Error("Expected browser session");
  await requestClientJson("/api/v1/intake/cases/d1/visit", { method: "POST", json: {}, csrf: result.bootstrap.csrf });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/me/access", "/api/v1/intake/cases/d1/visit"]);
  expect(fetch.mock.calls[1][1]?.headers).toMatchObject({ "X-CSRFToken": "session-csrf" });
});

it("keeps collection closed when interview entries are empty despite misleading roles", async () => {
  const noInterview = { ...access, roles: ["interviewer"], projects: [{
    ...access.projects[0], actions: { interview: [] },
  }] };
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(noInterview, 200, "application/json", "session-csrf"));

  const result = await fetchClientBootstrap();

  expect(result).toMatchObject({ authenticated: true, bootstrap: { capabilities: { intake: false } } });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/me/access"]);
});

it("does not show coding for an inactive coder grant absent from top-level roles", () => {
  const inactiveCoder = { ...access, roles: [], projects: [{
    ...access.projects[0], has_tree: false,
    grants: [{ role: "coder", scope: "project", codes: true, active: false, source: "assigned" }],
    actions: { interview: [] },
  }] };
  expect(accessCapabilities(parseAccessSummary(inactiveCoder)).coding).toBe(false);
});

it("does not fetch intake resources for coder-only access", async () => {
  const coderAccess: AccessSummary = { ...access, projects: [{
    project_id: "P2", project_name: "Coding", has_tree: false,
    grants: [{ role: "coder", scope: "project", codes: true, active: true, source: "assigned" }],
    actions: { interview: [] }, sites: [],
  }] };
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(coderAccess, 200, "application/json", "session-csrf"));

  const result = await fetchClientBootstrap();

  expect(result).toMatchObject({ authenticated: true, bootstrap: { capabilities: { intake: false, coding: true } } });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/me/access"]);
});

it.each(["broken", "off", null, 4])("rejects malformed or closed interview entries at the access boundary: %s", (mode) => {
  const malformed = { ...access, projects: [{ ...access.projects[0], actions: { interview: [
    { ...access.projects[0].actions.interview[0], web_intake_mode: mode },
  ] } }] };

  expect(() => parseAccessSummary(malformed)).toThrow(ApiError);
});

it("rejects incomplete interview entries and unit roots at the access boundary", () => {
  const entry = access.projects[0].actions.interview[0];
  expect(() => parseAccessSummary({ ...access, projects: [{ ...access.projects[0], actions: { interview: [{ ...entry, org_units: undefined }] } }] })).toThrow(ApiError);
  expect(() => parseAccessSummary({ ...access, projects: [{ ...access.projects[0], actions: { interview: [{ ...entry, org_units: [{ org_unit_id: "i" }] }] } }] })).toThrow(ApiError);
});

it.each([undefined, null, "yes"])("rejects an absent or malformed top-level roles field: %s", (roles) => {
  expect(() => parseAccessSummary({ ...access, roles })).toThrow(ApiError);
});

it.each([undefined, null, "yes"])("rejects grants without an active flag: %s", (active) => {
  const grants = [{ ...access.projects[0].grants[0], active }];
  expect(() => parseAccessSummary({ ...access, projects: [{ ...access.projects[0], grants }] })).toThrow(ApiError);
});

it.each([undefined, null, "other"])("rejects grants without a known source: %s", (source) => {
  const grants = [{ ...access.projects[0].grants[0], source }];
  expect(() => parseAccessSummary({ ...access, projects: [{ ...access.projects[0], grants }] })).toThrow(ApiError);
});

it("does not expose or send a CSRF header on bearer calls", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response(access, 200, "application/json", "should-be-ignored"));
  const result = await requestJson("https://digitva.test", "/api/v1/me/access", { token: "access", csrf });
  expect(result.csrf).toBeUndefined();
  expect((fetch.mock.calls[0][1]?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
});

it("requires the cookie access CSRF header before opening browser actions", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(access));
  await expect(fetchClientBootstrap()).rejects.toMatchObject({ code: "malformed_response" });
});

it("reads case from registration replies without requiring prefill", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ case: { death_id: "d1", unique_id: "X", state: "registered" } }, 201));
  const result = await registerDeath("/api/v1/intake/deaths", { project_id: "P1", site_id: "S1", deceased_name: "Name", deceased_sex: "female", date_of_death: "2026-10-01" }, csrf);
  expect(result.case.death_id).toBe("d1");
  expect(result.case.prefill).toBeUndefined();
});

it("validates normal, superseded, and server-kept draft submission acknowledgements by status", async () => {
  const draft = { draft_id: "draft-1", project_id: "P1", site_id: "S1" };
  const fetch = jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response({ va_sid: "sid-1", draft: { ...draft, unique_id: "VA-1" }, superseded: false, validation_err: [], can_code_now: true }, 201))
    .mockResolvedValueOnce(response({ va_sid: null, draft, superseded: true, validation_err: null, can_code_now: true }, 200))
    .mockResolvedValueOnce(response({
      va_sid: "sid-1", draft, superseded: false, validation_err: [], kept: "server", locked: true, can_code_now: "yes"
    }, 200))
    .mockResolvedValueOnce(response({
      va_sid: "sid-1", draft, superseded: false, validation_err: [], kept: "incoming", locked: false, can_code_now: true
    }, 200))
    .mockResolvedValueOnce(response({ va_sid: "sid-1", draft, superseded: false, validation_err: [] }, 201));
  await expect(submitDraft("/api/v1/intake/drafts", "draft-1", { valid: true, issues: [] }, csrf, "revision-1"))
    .resolves.toEqual({ va_sid: "sid-1", draft: { ...draft, unique_id: "VA-1" }, superseded: false, validation_err: [], can_code_now: true });
  await expect(submitDraft("/api/v1/intake/drafts", "draft-2", { valid: true, issues: [] }, csrf))
    .resolves.toEqual({ va_sid: null, draft, superseded: true, validation_err: null, can_code_now: false });
  await expect(submitDraft("/api/v1/intake/drafts", "draft-3", {
    valid: true, issues: [], data: { Id10013: "yes" }
  }, csrf, "revision-1"))
    .resolves.toEqual({ va_sid: "sid-1", draft, superseded: false, validation_err: [], kept: "server", locked: true, can_code_now: false });
  await expect(submitDraft("/api/v1/intake/drafts", "draft-4", { valid: true, issues: [] }, csrf))
    .resolves.toMatchObject({ va_sid: "sid-1", kept: "incoming", can_code_now: true });
  await expect(submitDraft("/api/v1/intake/drafts", "draft-5", { valid: true, issues: [] }, csrf))
    .resolves.toMatchObject({ va_sid: "sid-1", can_code_now: false });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    "/api/v1/intake/drafts/draft-1/submit",
    "/api/v1/intake/drafts/draft-2/submit",
    "/api/v1/intake/drafts/draft-3/submit",
    "/api/v1/intake/drafts/draft-4/submit",
    "/api/v1/intake/drafts/draft-5/submit"
  ]);
  expect(fetch.mock.calls.map(([, init]) => init?.method)).toEqual(["POST", "POST", "POST", "POST", "POST"]);
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ completion: { valid: true, issues: [] }, if_updated_at: "revision-1" });
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ completion: { valid: true, issues: [] } });
  expect(JSON.parse(String(fetch.mock.calls[2][1]?.body))).toEqual({
    completion: { valid: true, issues: [], data: { Id10013: "yes" } }, if_updated_at: "revision-1"
  });
});

it("leaves case-row presentation flags for strict true-only rendering", async () => {
  jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response({ cases: [
      { death_id: "d1", unique_id: "A", code_now: true },
      { death_id: "d2", unique_id: "B", code_now: "true" },
      { death_id: "d3", unique_id: "C" },
    ] }))
    .mockResolvedValueOnce(response({ case: { death_id: "d1", unique_id: "A", code_now: "true" } }));
  const rows = await getCases("/api/v1/intake/cases", csrf);
  const detail = await getCaseDetail("/api/v1/intake/cases", "d1", csrf);
  expect(rows.cases.map((row) => row.code_now)).toEqual([true, "true", undefined]);
  expect(detail.case.code_now).toBe("true");
});

it.each([
  [200, { va_sid: null, draft: { draft_id: "d", project_id: "P", site_id: "S" }, superseded: false, validation_err: null }],
  [200, { va_sid: "sid", draft: { draft_id: "d", project_id: "P", site_id: "S" }, superseded: true, validation_err: null }],
  [200, { va_sid: "sid", draft: { draft_id: "d", project_id: "P", site_id: "S" }, superseded: false, validation_err: [], kept: "server" }],
  [200, { va_sid: "sid", draft: { draft_id: "d", project_id: "P", site_id: "S" }, superseded: false, validation_err: [], kept: "other", locked: true }],
  [201, { va_sid: null, draft: { draft_id: "d", project_id: "P", site_id: "S" }, superseded: true, validation_err: null }],
  [201, { va_sid: "sid", draft: { draft_id: "d", project_id: "P" }, superseded: false, validation_err: [] }]
])("rejects malformed submit response combinations at HTTP %s", async (status, body) => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(body, status));
  await expect(submitDraft("/api/v1/intake/drafts", "draft-1", { valid: true, issues: [] }, csrf))
    .rejects.toMatchObject({ status, code: "malformed_response" });
});

it("an explicitly empty bearer token never falls back to a cookie", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "Authentication required", code: "unauthorized" }, 401));
  await expect(requestJson("", "/api/v1/me/access", { token: "", csrf })).rejects.toMatchObject({ status: 401, code: "unauthorized" });
  const init = fetch.mock.calls[0][1];
  expect(init?.credentials).toBe("omit");
  expect(init?.headers).toMatchObject({ Authorization: "Bearer " });
  expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
});

it("preserves server interview entry order and modes for multiple sites", async () => {
  const twoSites = { ...access, projects: [{ ...access.projects[0], actions: { interview: [
    { ...access.projects[0].actions.interview[0], site_id: "S1", site_name: "One", web_intake_mode: "both" as const },
    { ...access.projects[0].actions.interview[0], site_id: "S2", site_name: "Two", web_intake_mode: "direct" as const },
  ] } }] };
  const fetch = jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(twoSites));
  const context = await getIntakeContext(csrf);
  expect(context.context.map((entry) => [entry.site_id, entry.web_intake_mode])).toEqual([["S1", "both"], ["S2", "direct"]]);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("preserves cookie CSRF metadata while terms prevent access", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "Accept terms", code: "terms_required" }, 403, "application/json", "terms-csrf"));
  await expect(fetchClientBootstrap()).resolves.toMatchObject({
    authenticated: false, actionCode: "terms_required", csrf: { header: "X-CSRFToken", token: "terms-csrf" }
  });
});

it.each([null, [], "success", 42])("rejects non-object successful JSON: %s", async (body) => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(body));
  await expect(requestClientJson("/api/v1/intake/drafts")).rejects.toMatchObject({ code: "malformed_response" });
});
