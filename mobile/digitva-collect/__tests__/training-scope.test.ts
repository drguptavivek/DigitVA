import type { AccessProject, ClientBootstrap } from "../src/api";
import { getCases, getDrafts, getIntakeContext, getRegisteredDeaths, intakeContextFromAccess, parseAccessSummary, requestClientJson } from "../src/api";
import { getSubmittedRevisions as getSubmittedRevisionsList } from "../src/client/revisionList";
import { getSubmittedRevisions } from "../src/client/revisions";
import { activeTab, navEntries } from "../src/web/navTabs";
import { takeTrainingRedirect, trainingBootstrap, trainingRequester } from "../src/training";
import { createWorkspaceApi } from "../src/workspace/api";

const mockFetch = jest.fn();

const csrf = { header: "X-CSRFToken", token: "t" };
const context = [{ site_id: "S1", site_name: "Site", web_intake_mode: "both" as const, org_units: [] }];
const project = (id: string, roles: string[]): AccessProject => ({
  project_id: id, project_name: id, has_tree: false,
  grants: roles.map((role) => ({ role, scope: "project" as const, active: true, source: "assigned" as const })),
  sites: [], actions: { interview: context, register_death: context },
});

const access = (areas: string[], extra: object = {}) => ({
  user: { user_id: "u", name: "U" }, is_admin: false, roles: [], demo_coding: { available: false, project_ids: [] },
  projects: [project("REAL01", ["interviewer"])],
  training: { project_id: "TRN01", areas, pending: true, project: project("TRN01", ["coder", "interviewer"]) },
  ...extra,
}) as any;

const boot = (a: any) => ({
  user: a.user, csrf, access: a, links: { intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" },
  capabilities: { intake: false, registerDeath: false, registeredDeaths: false, supervision: false },
}) as unknown as ClientBootstrap;

beforeEach(() => {
  mockFetch.mockReset().mockImplementation(async () => new Response(
    JSON.stringify({ cases: [], drafts: [], deaths: [], next_cursor: null }),
    { status: 200, headers: { "content-type": "application/json" } },
  ));
  (globalThis as { fetch: unknown }).fetch = mockFetch;
});
/** The URL of the last request the api module sent. */
const lastUrl = () => String(mockFetch.mock.calls.at(-1)?.[0]);

describe("Training menu", () => {
  const menu = (areas: string[]) => navEntries(boot(access(areas))).primary.find((entry) => entry.key === "/training");

  test("shows only with an active participation, with a sub-item per area held", () => {
    expect(menu([])).toBeUndefined();
    expect(menu(["coding"])?.children?.map((child) => child.route)).toEqual(["/training/coding"]);
    expect(menu(["interview", "coding", "review"])?.children?.map((child) => child.labelKey))
      .toEqual(["trainingInterview", "trainingCoding", "trainingReview"]);
    expect(menu(["review"])?.children?.map((child) => child.route)).toEqual(["/training/reviewing"]);
    expect(menu(["interview"])?.labelKey).toBe("navTraining");
  });

  test("an access body without training (feature off or older server) has no Training item", () => {
    const { primary, more } = navEntries(boot(access([], { training: null })));
    expect([...primary, ...more].some((entry) => entry.key.startsWith("/training"))).toBe(false);
    const missing = { ...access([]) };
    delete missing.training;
    expect(navEntries(boot(missing)).primary.some((entry) => entry.key === "/training")).toBe(false);
  });

  test("the current item follows /training/*, and a case opened from Training keeps it", () => {
    expect(activeTab("/training")).toBe("/training");
    expect(activeTab("/training/coding")).toBe("/training/coding");
    expect(activeTab("/training/register")).toBe("/training");
    expect(activeTab("/workspace", { mode: "coding", training: "1" })).toBe("/training/coding");
    expect(activeTab("/workspace", { mode: "reviewing", training: "1" })).toBe("/training/reviewing");
    expect(activeTab("/workspace", { mode: "coding" })).toBe("/coding");
  });
});

describe("the training scope is asked for by the Training screens only", () => {
  const paths = async (training: boolean) => {
    const calls: string[] = [];
    const api = createWorkspaceApi(async (path) => { calls.push(path); return {}; }, { training });
    const attempts: Array<() => Promise<unknown>> = [
      () => api.getCodingStats(), () => api.getCodingAvailable(), () => api.getCodingHistory(), () => api.getCodingProjects(),
      () => api.getCodingAllocation(), () => api.allocateCoding("sid"), () => api.getReviewerProjects(), () => api.getReviewerStats(),
      () => api.getReviewerAvailable(), () => api.getReviewerHistory(), () => api.getReviewerAllocation(), () => api.allocateReviewer("sid"),
      () => api.getWorkspace("sid", "coding"),
    ];
    for (const attempt of attempts) await attempt().catch(() => undefined); // replies are junk: only the requests matter
    return calls;
  };

  test("training=1 on every queue, count and allocation call, and on nothing else", async () => {
    const scoped = await paths(true);
    expect(scoped).toHaveLength(13);
    expect(scoped.slice(0, 12).every((path) => /[?&]training=1(&|$)/.test(path))).toBe(true);
    expect(scoped[12]).not.toContain("training"); // the case workspace
    expect((await paths(false)).some((path) => path.includes("training"))).toBe(false);
  });

  test("the intake lists", async () => {
    await getCases("/api/v1/intake/cases", csrf, "c1", "P1", true);
    expect(lastUrl()).toBe("/api/v1/intake/cases?training=1&project_id=P1&cursor=c1");
    await getCases("/api/v1/intake/cases", csrf);
    expect(lastUrl()).toBe("/api/v1/intake/cases");
    await getDrafts("/api/v1/intake/drafts", csrf, true);
    expect(lastUrl()).toBe("/api/v1/intake/drafts?training=1");
    await getDrafts("/api/v1/intake/drafts", csrf);
    expect(lastUrl()).toBe("/api/v1/intake/drafts");
    await getRegisteredDeaths(csrf, true, null, true).catch(() => undefined);
    expect(lastUrl()).toContain("training=1");
    await getRegisteredDeaths(csrf, true).catch(() => undefined);
    expect(lastUrl()).not.toContain("training");
    await getSubmittedRevisions(csrf, true).catch(() => undefined);
    expect(lastUrl()).toContain("&training=1");
    await getSubmittedRevisions(csrf).catch(() => undefined);
    expect(lastUrl()).not.toContain("training");
    await getSubmittedRevisionsList({ ...csrf, training: true }).catch(() => undefined);
    expect(lastUrl()).toContain("&training=1");
    await getSubmittedRevisionsList(csrf).catch(() => undefined);
    expect(lastUrl()).not.toContain("training");
    await getDrafts("/api/v1/intake/drafts", { ...csrf, training: true });
    expect(lastUrl()).toBe("/api/v1/intake/drafts?training=1");
  });

  test("trainingRequester appends the scope to a path with or without a query", async () => {
    const seen: string[] = [];
    const request = trainingRequester(async (path) => { seen.push(path); return {}; });
    await request("/api/v1/intake/supervision/cases?");
    await request("/api/v1/intake/supervision/cases?state=open");
    await request("/api/v1/intake/supervision/cases");
    expect(seen).toEqual([
      "/api/v1/intake/supervision/cases?&training=1",
      "/api/v1/intake/supervision/cases?state=open&training=1",
      "/api/v1/intake/supervision/cases?training=1",
    ]);
  });
});

describe("the two project sets never mix", () => {
  const a = access(["interview", "coding"]);

  test("the normal context has no training project; the training one has only it", async () => {
    expect(intakeContextFromAccess(a, "interview").map((entry) => entry.project_id)).toEqual(["REAL01"]);
    expect(intakeContextFromAccess(a, "interview", "training").map((entry) => entry.project_id)).toEqual(["TRN01"]);
    expect(intakeContextFromAccess(a, "interview", "all").map((entry) => entry.project_id)).toEqual(["REAL01", "TRN01"]);
    expect(intakeContextFromAccess({ ...a, training: null }, "interview", "training")).toEqual([]);
    mockFetch.mockImplementationOnce(async () => new Response(JSON.stringify(a), { status: 200, headers: { "content-type": "application/json" } }));
    expect((await getIntakeContext({ ...csrf, training: true })).context.map((entry) => entry.project_id)).toEqual(["TRN01"]);
    mockFetch.mockImplementationOnce(async () => new Response(JSON.stringify(a), { status: 200, headers: { "content-type": "application/json" } }));
    expect((await getIntakeContext(csrf)).context.map((entry) => entry.project_id)).toEqual(["REAL01"]);
  });

  test("the training bootstrap holds only the training project, its roles and the training scope", () => {
    const view = trainingBootstrap(boot(a))!;
    expect(view.scope).toBe("training");
    expect(view.access.projects.map((p) => p.project_id)).toEqual(["TRN01"]);
    expect(view.access.roles).toEqual(["coder", "interviewer"]);
    expect(view.capabilities.intake).toBe(true);
    expect(view.csrf).toEqual({ ...csrf, training: true });
    expect(boot(a).csrf.training).toBeUndefined();
    expect(boot(a).scope).toBeUndefined();
    expect(trainingBootstrap(boot(access([])))).toBeUndefined(); // no participation, no training view
    expect(trainingBootstrap(boot({ ...a, training: null }))).toBeUndefined();
  });
});

describe("writes from the Training screens", () => {
  const view = trainingBootstrap(boot(access(["interview"])))!;

  test("carry training=1 on reads and writes, while explicit or normal requests stay unchanged", async () => {
    await requestClientJson("/api/v1/intake/drafts", { method: "POST", json: {}, csrf: view.csrf });
    expect(lastUrl()).toBe("/api/v1/intake/drafts?training=1");
    await requestClientJson("/api/v1/intake/drafts/x/submit?a=1", { method: "POST", json: {}, csrf: view.csrf });
    expect(lastUrl()).toBe("/api/v1/intake/drafts/x/submit?a=1&training=1");
    await requestClientJson("/api/v1/intake/drafts?training=1", { method: "POST", json: {}, csrf: view.csrf });
    expect(lastUrl()).toBe("/api/v1/intake/drafts?training=1");
    await requestClientJson("/api/v1/intake/drafts", { csrf: view.csrf });
    expect(lastUrl()).toBe("/api/v1/intake/drafts?training=1");
    await requestClientJson("/api/v1/intake/drafts", { method: "POST", json: {}, csrf });
    expect(lastUrl()).toBe("/api/v1/intake/drafts");
  });
});

describe("the one-time redirect to /training", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => void store.set(key, value) },
    });
  });
  afterAll(() => { delete (globalThis as { sessionStorage?: unknown }).sessionStorage; });

  test("fires once per browser session while Start is pending, never without a participation or after Start", () => {
    expect(takeTrainingRedirect(access([]))).toBe(false);
    expect(takeTrainingRedirect({ ...access(["coding"]), training: { ...access(["coding"]).training, pending: false } })).toBe(false);
    expect(takeTrainingRedirect(access(["coding"]))).toBe(true);
    expect(takeTrainingRedirect(access(["coding"]))).toBe(false);
    expect(takeTrainingRedirect(undefined)).toBe(false);
  });

  test("where storage is blocked it still fires once per page load", () => {
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, get() { throw new Error("blocked"); } });
    let fresh!: typeof takeTrainingRedirect;
    jest.isolateModules(() => { fresh = require("../src/training").takeTrainingRedirect; });
    expect(fresh(access(["coding"]))).toBe(true);
    expect(fresh(access(["coding"]))).toBe(false);
  });
});

describe("the access body's training key", () => {
  test("is optional, null when training is off, and validated when present", () => {
    const base = { user: { user_id: "u", name: "U" }, is_admin: false, roles: [], demo_coding: { available: false, project_ids: [] }, projects: [] };
    expect(parseAccessSummary(base).training).toBeUndefined();
    expect(parseAccessSummary({ ...base, training: null }).training).toBeNull();
    expect(parseAccessSummary({ ...base, training: { project_id: "TRN01", areas: ["coding"], pending: true, project: null } }).training?.areas).toEqual(["coding"]);
    for (const bad of [{ areas: "coding", pending: true, project_id: "TRN01" }, { areas: [], pending: "yes", project_id: "TRN01" }, { areas: [], pending: true, project_id: 3 }, "x"]) {
      expect(() => parseAccessSummary({ ...base, training: bad })).toThrow();
    }
  });
});
