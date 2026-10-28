import { ApiError, parseAccessSummary, type AccessSummary } from "../src/api";
import { loadAccessProfile, parseSavedAccessProfile, profileQuestionnaireLanguages, projectAccessProfile } from "../src/accessProfile";
import type { Account, Slot } from "../src/auth";
import type { ReferenceData } from "../src/sync";

const mockServer = "https://digitvav3.causeofdeathindia.com";
let mockSlot: Slot = "active";
let mockAccount: Account;
let mockUnlocked = true;
let mockStored: unknown;
let mockReference: ReferenceData | undefined;
const mockRefresh = jest.fn();
const mockProfile = jest.fn(async () => null);
const mockWrite = jest.fn(async (_db: unknown, _key: string, value: unknown) => { mockStored = value; });
const mockDigest = jest.fn<Promise<string>, unknown[]>(async () => "a".repeat(64));
jest.mock("expo-crypto", () => ({ CryptoDigestAlgorithm: { SHA256: "SHA256" }, digestStringAsync: (...args: unknown[]) => mockDigest(...args) }));
jest.mock("../src/auth", () => ({
  loadActiveSlot: async () => mockSlot,
  loadAccounts: async () => [mockAccount],
  loadDevice: async () => ({ server: mockServer }),
  refreshAccessSummaryForAction: (...args: unknown[]) => mockRefresh(...args),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked, openInterviewerDb: async () => ({}) }));
jest.mock("../src/drafts", () => ({ getMeta: async () => mockStored, setMeta: (...args: [unknown, string, unknown]) => mockWrite(...args) }));
jest.mock("../src/sync", () => ({ getCachedReferenceData: async () => mockReference }));
jest.mock("../src/offlineProfile", () => ({ getOfflineProfile: () => mockProfile() }));

const summary = (): AccessSummary => parseAccessSummary({
  user: { user_id: "U", name: "Asha", coding_languages: ["en", "hi"] },
  is_admin: false, roles: ["interviewer", "coder"], demo_coding: { available: false, project_ids: [] },
  projects: [{ project_id: "P", project_name: "Project One", has_tree: false,
    settings: { web_intake_mode: "both", coding_scope: null },
    self_coding: { enabled: true, code_now: true, offline_coding: { enabled: true, project_mode: "unmasked_doris", icd_classification: "icd11" } },
    grants: [
      { role: "coder", scope: "project", active: true, codes: true, source: "assigned" },
      { role: "interviewer", scope: "project_site", site_id: "S", active: true, source: "assigned" },
      { role: "interviewer", scope: "org_unit", org_unit_id: "opaque-unit-id", unit_name: "North district", active: true, source: "assigned" },
    ],
    sites: [{ site_id: "S", site_name: "Health centre", roles: ["interviewer"] }],
    actions: { interview: [{ site_id: "S", site_name: "Health centre", web_intake_mode: "both", org_units: [] }], register_death: [] },
  }],
  tokens: "must never be saved", answers: { patient: "must never be saved" },
});
const scope = { slot: "active" as const, server: mockServer, userId: "U", accessDigest: "a".repeat(64) };

beforeEach(() => {
  jest.clearAllMocks();
  mockSlot = "active";
  mockUnlocked = true;
  mockReference = undefined;
  mockAccount = { user_id: "U", name: "Asha", server: mockServer, coding_history_access: scope.accessDigest };
  mockStored = projectAccessProfile(summary(), scope);
  mockRefresh.mockResolvedValue(summary());
  mockDigest.mockResolvedValue(scope.accessDigest);
});

test("projects readable rights and settings while storing only display metadata", async () => {
  const result = await loadAccessProfile("U", "active", mockServer, false);
  expect(result).toMatchObject({ kind: "server", current: true, profile: {
    name: "Asha", codingLanguages: ["en", "hi"], projects: [{ name: "Project One", selfCoding: "Enabled", localCoding: "Eligible", classification: "ICD11" }],
  } });
  expect((mockStored as { projects: Array<{ rights: string[] }> }).projects[0].rights.join("\n")).toContain("Health centre");
  expect(JSON.stringify(mockStored)).toContain("North district");
  expect(JSON.stringify(mockStored)).not.toMatch(/must never|opaque-unit-id|"grants"|"tokens"|"answers"/);
  expect(mockWrite).toHaveBeenCalledTimes(1);
});

test.each([true, false])("offline/network failure uses a matching saved projection (%s)", async (offline) => {
  mockRefresh.mockRejectedValue(new TypeError("Network request failed"));
  expect(await loadAccessProfile("U", "active", mockServer, offline)).toMatchObject({ kind: "server", current: false });
  expect(mockRefresh).toHaveBeenCalledTimes(offline ? 0 : 1);
  expect(mockWrite).not.toHaveBeenCalled();
});

test.each([new ApiError(401, "session_revoked"), new ApiError(403, "project_forbidden"), new ApiError(403, "terms_required"), new ApiError(200, "malformed_response"), new ApiError(503, "maintenance")])("refusals never fall back to saved grants", async (error) => {
  mockRefresh.mockRejectedValue(error);
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toBe(error);
  expect(mockStored).toBeNull();
});

test.each(["slot", "server", "userId", "accessDigest"]) ("saved metadata rejects a changed %s", (key) => {
  expect(parseSavedAccessProfile(mockStored, scope)).toBeDefined();
  expect(parseSavedAccessProfile(mockStored, { ...scope, [key]: "other" })).toBeUndefined();
});

test.each([undefined, "", "bad", "b".repeat(64)])("missing or changed access digest prevents offline fallback", async (digest) => {
  mockAccount.coding_history_access = digest;
  await expect(loadAccessProfile("U", "active", mockServer, true)).rejects.toThrow("profile_access_unavailable");
});

test.each(["signed_out", "needs_sign_in", "access_removed", "terms_required", "access_blocked"]) ("account gate %s blocks all reads and requests", async (gate) => {
  Object.assign(mockAccount, { [gate]: gate === "access_blocked" ? "maintenance" : true });
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toThrow("profile_access_unavailable");
  expect(mockRefresh).not.toHaveBeenCalled();
});

test("locks, unknown accounts, server replacement and demo-slot crossover fail closed", async () => {
  mockUnlocked = false;
  await expect(loadAccessProfile("U", "active", mockServer, true)).rejects.toThrow();
  mockUnlocked = true;
  await expect(loadAccessProfile("someone-else", "active", mockServer, true)).rejects.toThrow();
  await expect(loadAccessProfile("U", "active", "https://other.causeofdeathindia.com", true)).rejects.toThrow();
  await expect(loadAccessProfile("U", "demo", mockServer, true)).rejects.toThrow();
  mockSlot = "demo";
  await expect(loadAccessProfile("U", "demo", mockServer, true)).rejects.toThrow();
});

test("fresh loss of all projects replaces saved rights and digest races do not save stale rights", async () => {
  const access = { ...summary(), roles: [], projects: [] };
  mockRefresh.mockImplementation(async () => {
    mockAccount.coding_history_access = "b".repeat(64);
    return access;
  });
  mockDigest.mockResolvedValue("b".repeat(64));
  expect(await loadAccessProfile("U", "active", mockServer, false)).toMatchObject({ profile: { roles: [], projects: [] } });
  expect(mockStored).toMatchObject({ accessDigest: "b".repeat(64), projects: [] });
  mockDigest.mockResolvedValue("c".repeat(64));
  mockWrite.mockClear();
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toThrow();
  expect(mockWrite).not.toHaveBeenCalled();
});

test("standalone reads only its local profile and never uses a retained server or grants", async () => {
  mockAccount = { user_id: "U", name: "Local coder", standalone: true };
  expect(await loadAccessProfile("U", "active", undefined, false)).toEqual({ kind: "standalone", userId: "U", slot: "active", name: "Local coder", profile: null });
  expect(mockProfile).toHaveBeenCalledTimes(1);
  expect(mockRefresh).not.toHaveBeenCalled();
  expect(mockWrite).not.toHaveBeenCalled();
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toThrow();
});

test("malformed user languages, project settings and saved schema fail closed", () => {
  expect(() => parseAccessSummary({ ...summary(), user: { user_id: "U", name: "Asha", coding_languages: [1] } })).toThrow(ApiError);
  expect(() => parseAccessSummary({ ...summary(), projects: [{ ...summary().projects[0], settings: { web_intake_mode: "bad", coding_scope: null } }] })).toThrow(ApiError);
  expect(parseSavedAccessProfile({ ...(mockStored as object), schema: 2 }, scope)).toBeUndefined();
  expect(parseSavedAccessProfile({ ...(mockStored as object), refreshedAt: "yesterday" }, scope)).toBeUndefined();
  expect(parseSavedAccessProfile({ ...(mockStored as object), projects: [{ rights: [1] }] }, scope)).toBeUndefined();
});

test("a fresh answer for a different user clears saved display data without fallback", async () => {
  mockRefresh.mockResolvedValue({ ...summary(), user: { user_id: "other", name: "Someone else" } });
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toMatchObject({ code: "malformed_response" });
  expect(mockStored).toBeNull();
});

test("a slot change while refreshing prevents a completed result or metadata write", async () => {
  mockRefresh.mockImplementation(async () => {
    mockSlot = "demo";
    return summary();
  });
  await expect(loadAccessProfile("U", "active", mockServer, false)).rejects.toThrow("profile_access_unavailable");
  expect(mockWrite).not.toHaveBeenCalled();
});

test("an inactive coder grant never displays coding as allowed", () => {
  const access = summary();
  access.projects[0].grants[0].active = false;
  const project = projectAccessProfile(access, scope).projects[0];
  expect(project.rights[0]).toContain("Inactive · Coding unavailable");
  expect(project.localCoding).toBe("Unavailable");
});

test("questionnaire languages come only from a current matching project reference", () => {
  const reference = { projects: [{ project: { project_id: "P", form_options: { available_locales: [{ code: "hi", label: "Hindi", under_review: true }], default_locale: "hi" } } }] } as ReferenceData;
  expect(profileQuestionnaireLanguages("P", reference)).toBe("Hindi (hi) · Default · Under review");
  expect(profileQuestionnaireLanguages("P2", reference)).toBeUndefined();
  expect(profileQuestionnaireLanguages("P")).toBeUndefined();
});
