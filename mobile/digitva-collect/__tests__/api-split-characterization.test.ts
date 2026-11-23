/** Pins the public surface and the request/parse behaviour of src/api before it is split into modules (bead digitva-r8nh.20). */
import * as api from "../src/api";

const csrf = { header: "X-CSRFToken", token: "csrf" };
const trainingCsrf = { ...csrf, training: true } as typeof csrf;

function response(body: unknown, status = 200): Response {
  return {
    status, ok: status >= 200 && status < 300, redirected: false,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "application/json" : null },
    json: async () => body, text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const minimalAccess = {
  user: { user_id: "u1", name: "Worker" }, is_admin: false, roles: ["coder", "death_reporter"],
  demo_coding: { available: false, project_ids: [] }, projects: [],
};

afterEach(() => jest.restoreAllMocks());

const EXPORTS: string[] = [
  "AUTH_API",
  "ApiError",
  "ClientApiError",
  "INTAKE_API",
  "SUPERVISION_ROLES",
  "abortClientRequests",
  "accessCapabilities",
  "createMentorInstituteStaff",
  "createMentorNote",
  "decommissionUserDevice",
  "fetchClientBootstrap",
  "fetchStationEnrolmentFile",
  "fetchStationFacility",
  "fetchStationSettings",
  "getAccessSummary",
  "getCaseDetail",
  "getCases",
  "getDraft",
  "getDrafts",
  "getInstrumentTranslations",
  "getIntakeContext",
  "getLocalStationLaunchToken",
  "getMentorCoderCases",
  "getMentorCoders",
  "getMentorDistricts",
  "getMentoringSummary",
  "getMyMentorFeedback",
  "getProjectFormOptions",
  "getRegisteredDeaths",
  "hasInterviewRegistrationAccess",
  "intakeContextFromAccess",
  "isSignedOutError",
  "isSmartVaTarget",
  "listMentorInstituteStaff",
  "listUserDevices",
  "logContactAttempt",
  "markMentorFeedbackRead",
  "maskApiPath",
  "parseAccessSummary",
  "parseProjectFormOptions",
  "parseRegisteredDeathPage",
  "readLastChange",
  "registerDeath",
  "removeMentorInstituteStaff",
  "requestClientJson",
  "requestJson",
  "requestRaw",
  "retractMentorNote",
  "runAsBackground",
  "saveStationFacility",
  "saveStationSettings",
  "setCaseVisit",
  "startDraft",
  "submitDraft",
];

it("exports exactly the same names", () => {
  expect(Object.keys(api).sort()).toEqual(EXPORTS);
});

type Call = [string, () => Promise<unknown>, string, string, unknown, unknown];
const calls: Call[] = [
  ["getAccessSummary", () => api.getAccessSummary(csrf), "/api/v1/me/access", "GET", undefined, minimalAccess],
  ["getRegisteredDeaths", () => api.getRegisteredDeaths(csrf, true, "c1", true), "/api/v1/intake/deaths?limit=50&training=1&registered=mine&cursor=c1", "GET", undefined, { deaths: [], next_cursor: null }],
  ["getProjectFormOptions", () => api.getProjectFormOptions("p/1", csrf), "/api/v1/organization/p%2F1/form-options", "GET", undefined, { web_intake_mode: "both" }],
  ["getInstrumentTranslations", () => api.getInstrumentTranslations("who/2022", "hi", csrf), "/api/v1/instruments/who%2F2022/translations/hi", "GET", undefined, { a: "b" }],
  ["getCases", () => api.getCases("/api/v1/intake/cases", csrf, "c1", "p1", true), "/api/v1/intake/cases?training=1&project_id=p1&cursor=c1", "GET", undefined, { cases: [] }],
  ["getCaseDetail", () => api.getCaseDetail("/api/v1/intake/cases/", "d/1", trainingCsrf), "/api/v1/intake/cases/d%2F1?training=1", "GET", undefined, { case: {} }],
  ["logContactAttempt", () => api.logContactAttempt("/api/v1/intake/cases/", "d1", { outcome: "reached" }, csrf), "/api/v1/intake/cases/d1/attempts", "POST", { outcome: "reached" }, { case: {} }],
  ["setCaseVisit", () => api.setCaseVisit("/api/v1/intake/cases", "d1", { next_visit_at: null }, csrf), "/api/v1/intake/cases/d1/visit", "POST", { next_visit_at: null }, { case: {} }],
  ["getDrafts", () => api.getDrafts("/api/v1/intake/drafts", csrf, true), "/api/v1/intake/drafts?training=1", "GET", undefined, { drafts: [] }],
  ["registerDeath", () => api.registerDeath("/api/v1/intake/deaths", { project_id: "p", site_id: "s", deceased_name: "n", deceased_sex: "f", date_of_death: "2026-01-01" }, csrf), "/api/v1/intake/deaths", "POST", { project_id: "p", site_id: "s", deceased_name: "n", deceased_sex: "f", date_of_death: "2026-01-01" }, { case: {} }],
  ["startDraft", () => api.startDraft("/api/v1/intake/drafts", { project_id: "p", site_id: "s" }, csrf), "/api/v1/intake/drafts", "POST", { project_id: "p", site_id: "s" }, { draft: {} }],
  ["getDraft", () => api.getDraft("/api/v1/intake/drafts", "d/1", trainingCsrf), "/api/v1/intake/drafts/d%2F1?training=1", "GET", undefined, { draft: {} }],
  ["fetchStationEnrolmentFile", () => api.fetchStationEnrolmentFile(csrf), "/api/v1/station/enrolment-file", "GET", undefined, { device_id: "d", signing_public_key: "k" }],
  ["fetchStationFacility", () => api.fetchStationFacility(csrf), "/api/v1/station/facility", "GET", undefined, { name: "n" }],
  ["saveStationFacility", () => api.saveStationFacility({ name: "n", code: "c", type: "t", address: "a", district: "d", state: "s" }, csrf), "/api/v1/station/facility", "PUT", { name: "n", code: "c", type: "t", address: "a", district: "d", state: "s" }, { name: "n" }],
  ["fetchStationSettings", () => api.fetchStationSettings(csrf), "/api/v1/station/settings", "GET", undefined, { modules: [] }],
  ["saveStationSettings", () => api.saveStationSettings({ coding_mode: "icd10" }, csrf), "/api/v1/station/settings", "PUT", { coding_mode: "icd10" }, { modules: [] }],
  ["getMentoringSummary", () => api.getMentoringSummary(csrf), "/api/v1/me/mentoring", "GET", undefined, { is_member: true }],
  ["listMentorInstituteStaff", () => api.listMentorInstituteStaff("i/1", csrf), "/admin/api/mentor-institutes/i%2F1/staff", "GET", undefined, { staff: [] }],
  ["createMentorInstituteStaff", () => api.createMentorInstituteStaff("i/1", { name: "n", email: "e", email_confirm: "e", languages: [] }, csrf), "/admin/api/mentor-institutes/i%2F1/staff", "POST", { name: "n", email: "e", email_confirm: "e", languages: [] }, { staff: {} }],
  ["removeMentorInstituteStaff", () => api.removeMentorInstituteStaff("i/1", "u/1", csrf), "/admin/api/mentor-institutes/i%2F1/staff/u%2F1/remove", "POST", undefined, { user_id: "u/1" }],
  ["getMentorDistricts", () => api.getMentorDistricts(csrf), "/api/v1/mentor/districts", "GET", undefined, { districts: [] }],
  ["getMentorCoders", () => api.getMentorCoders("d/1", "90d", csrf), "/api/v1/mentor/coders?district=d%2F1&period=90d", "GET", undefined, { coders: [] }],
  ["getMentorCoderCases", () => api.getMentorCoderCases("d/1", "c/1", "all", "a b", csrf), "/api/v1/mentor/coders/c%2F1/cases?district=d%2F1&period=all&after=a%20b", "GET", undefined, { cases: [] }],
  ["createMentorNote", () => api.createMentorNote("s/1", "hi", csrf), "/api/v1/mentor/cases/s%2F1/notes", "POST", { body: "hi" }, { note_id: "n" }],
  ["retractMentorNote", () => api.retractMentorNote("n/1", csrf), "/api/v1/mentor/notes/n%2F1/retract", "POST", undefined, {}],
  ["getMyMentorFeedback", () => api.getMyMentorFeedback(csrf), "/api/v1/mentor/feedback/mine", "GET", undefined, { notes: [] }],
  ["markMentorFeedbackRead", () => api.markMentorFeedbackRead("n/1", csrf), "/api/v1/mentor/feedback/n%2F1/read", "POST", undefined, {}],
];

describe.each(calls)("%s", (_name, run, path, method, body, reply) => {
  it("sends the pinned request and returns the pinned result", async () => {
    const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(response(reply));
    const result = await run();
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(path);
    expect(init?.method).toBe(method);
    expect(init?.body).toBe(body === undefined ? undefined : JSON.stringify(body));
    expect((init?.headers as Record<string, string>)["X-CSRFToken"]).toBe("csrf");
    expect(JSON.stringify(result ?? null)).toBe(
      _name.startsWith("retract") || _name.startsWith("mark") ? "null" : JSON.stringify(reply),
    );
  });
});

it("getIntakeContext reads access and shapes the links", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(response(minimalAccess));
  expect(await api.getIntakeContext(csrf)).toEqual({
    user: { user_id: "u1", name: "Worker" }, context: [],
    links: { deaths: "/api/v1/intake/deaths", drafts: "/api/v1/intake/drafts", cases: "/api/v1/intake/cases" },
  });
});

it("pure helpers keep their results", () => {
  expect(api.parseAccessSummary(minimalAccess)).toBe(minimalAccess);
  expect(() => api.parseAccessSummary({})).toThrow(api.ApiError);
  expect(api.accessCapabilities(minimalAccess as never)).toEqual({
    intake: false, registerDeath: false, registeredDeaths: true, coding: true, reviewing: false, supervision: false,
  });
  expect(api.intakeContextFromAccess(minimalAccess as never)).toEqual([]);
  expect(api.hasInterviewRegistrationAccess(minimalAccess as never, "p", "s")).toBe(false);
  expect(api.parseProjectFormOptions({ web_intake_mode: "off" })).toEqual({ web_intake_mode: "off" });
  expect(() => api.parseProjectFormOptions({ web_intake_mode: "bogus" })).toThrow(api.ApiError);
  expect(() => api.parseRegisteredDeathPage({ deaths: [{ death_id: "a" }], next_cursor: null })).toThrow(api.ApiError);
  expect(api.parseRegisteredDeathPage({ deaths: [], next_cursor: "x" })).toEqual({ deaths: [], next_cursor: "x" });
  expect(api.readLastChange({ at: "2026-01-01T00:00:00Z", via: "phone", name: " A " })).toEqual({
    at: "2026-01-01T00:00:00Z", via: "phone", by_you: null, name: "A", refusal: false,
  });
  expect(api.readLastChange({ at: "nope" })).toBeUndefined();
  expect(api.isSmartVaTarget(null)).toBe(false);
  expect(api.SUPERVISION_ROLES).toEqual(["interview_supervisor", "data_manager"]);
});
