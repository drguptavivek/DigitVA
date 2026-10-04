import {
  ApiError, ClientApiError, accessCapabilities, fetchClientBootstrap, getAccessSummary,
  getIntakeContext, intakeContextFromAccess, parseAccessSummary, registerDeath,
  requestClientJson, requestJson, type AccessSummary
} from "../src/api";

const csrf = { header: "X-CSRFToken", token: "csrf" };
const unit = (id: string, roles: string[], selectable = true, can_code = false) => ({
  org_unit_id: id, unit_code: id, unit_name: id, level_code: "phc", path: `root.${id}`,
  is_active: true, roles, selectable, can_code
});
const access: AccessSummary = {
  user: { user_id: "u1", name: "Worker" }, is_admin: false,
  demo_coding: { available: false, project_ids: [] },
  projects: [{
    project_id: "P1", project_name: "Project", has_tree: true,
    grants: [{ role: "interviewer", scope: "org_unit", org_unit_id: "i", unit_name: "i" },
      { role: "coder", scope: "org_unit", org_unit_id: "c", unit_name: "c", codes: true }],
    sites: [{ site_id: "S1", site_name: "Site", roles: ["interviewer"] },
      { site_id: "S2", site_name: "Other", roles: ["coder"] }],
    levels: [{ level_code: "phc", level_name: "PHC", depth: 1 }],
    units: [unit("ancestor", [], false), unit("i", ["interviewer"]), unit("c", ["coder"], true, true)]
  }]
};

function response(body: unknown, status = 200, contentType = "application/json", csrfToken?: string): Response {
  return {
    status, ok: status >= 200 && status < 300, redirected: false,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? contentType : name.toLowerCase() === "x-csrftoken" ? csrfToken ?? null : null }, json: async () => body,
    text: async () => body === undefined ? "" : JSON.stringify(body)
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

it("branches only on code, never on error text", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "factor_setup_required" }, 403));
  await expect(requestClientJson("/api/v1/profile/security")).rejects.toMatchObject({ status: 403, code: undefined });
});

it("rejects external browser request paths before sending credentials", async () => {
  const fetch = jest.spyOn(globalThis, "fetch");
  await expect(requestClientJson("//outside.test/steal", { csrf })).rejects.toMatchObject({ code: "invalid_request" });
  await expect(requestClientJson("javascript:alert(1)", { csrf })).rejects.toMatchObject({ code: "invalid_request" });
  expect(fetch).not.toHaveBeenCalled();
});

it("filters intake units and sites by interviewer reach and preserves ancestor context", () => {
  const context = intakeContextFromAccess(parseAccessSummary(access));
  expect(context).toHaveLength(1);
  expect(context[0].site_id).toBe("S1");
  expect(context[0].org_units?.map((entry) => entry.org_unit_id)).toEqual(["ancestor", "i"]);
  expect(context[0].org_units?.[0].selectable).toBe(false);
  expect(context[0].web_intake_mode).toBeUndefined();
  expect(accessCapabilities(access)).toEqual({ intake: true, coding: true, reviewing: false });
  const withoutCode = { ...access, projects: [{ ...access.projects[0], units: access.projects[0].units?.map((entry) => ({ ...entry, can_code: false })) }] };
  expect(accessCapabilities(withoutCode).coding).toBe(false);
});

it.each([null, {}, { ...access, user: { user_id: 42, name: "Worker" } },
  { ...access, projects: [{ ...access.projects[0], sites: [{ site_id: "S1", roles: "interviewer" }] }] },
  { ...access, projects: [{ ...access.projects[0], units: [unit("i", ["interviewer"]), { org_unit_id: "broken" }] }] }
])("rejects malformed access before building pickers", (value) => {
  expect(() => parseAccessSummary(value)).toThrow(ApiError);
});

it("gets intake reach from access and mode from project form options without old copies", async () => {
  const fetch = jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(access))
    .mockResolvedValueOnce(response({ project_id: "P1", web_intake_mode: "death_register", instrument_version: "bundle" }));
  const context = await getIntakeContext(csrf);
  expect(context.links?.deaths).toBe("/api/v1/intake/deaths");
  expect(context.context[0].web_intake_mode).toBe("death_register");
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/v1/me/access", "/api/v1/organization/P1/form-options"]);
});

it("fetches validated access with either credential", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(access));
  await expect(getAccessSummary(csrf)).resolves.toEqual(access);
  await expect(getAccessSummary(undefined, "https://digitva.test", "access")).resolves.toEqual(access);
});

it("starts the browser with me/access alone and uses its CSRF header on mutations", async () => {
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

it("an explicitly empty bearer token never falls back to a cookie", async () => {
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ error: "Authentication required", code: "unauthorized" }, 401));
  await expect(requestJson("", "/api/v1/me/access", { token: "", csrf })).rejects.toMatchObject({ status: 401, code: "unauthorized" });
  const init = fetch.mock.calls[0][1];
  expect(init?.credentials).toBe("omit");
  expect(init?.headers).toMatchObject({ Authorization: "Bearer " });
  expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
});

it.each([undefined, "invalid_mode", null, false])("fails closed on absent or invalid form-options mode: %s", async (mode) => {
  jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(access))
    .mockResolvedValueOnce(response({ project_id: "P1", web_intake_mode: mode }));
  if (mode === undefined) {
    expect((await getIntakeContext(csrf)).context[0].web_intake_mode).toBeUndefined();
  } else {
    await expect(getIntakeContext(csrf)).rejects.toMatchObject({ code: "malformed_response" });
  }
});

it("loads form options once per project even with multiple interviewer sites", async () => {
  const twoSites = { ...access, projects: [{ ...access.projects[0], sites: [
    { site_id: "S1", site_name: "One", roles: ["interviewer"] },
    { site_id: "S2", site_name: "Two", roles: ["interviewer"] }
  ] }] };
  const fetch = jest.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(response(twoSites))
    .mockResolvedValueOnce(response({ web_intake_mode: "both" }));
  const context = await getIntakeContext(csrf);
  expect(context.context.map((entry) => entry.web_intake_mode)).toEqual(["both", "both"]);
  expect(fetch).toHaveBeenCalledTimes(2);
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
