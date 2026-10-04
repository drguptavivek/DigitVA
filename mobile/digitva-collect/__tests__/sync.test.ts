/** Project scoped reference refresh and upload ordering. */
import { DatabaseSync } from "node:sqlite";

import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key))
}));
jest.mock("../src/interviewerDb", () => ({ deleteInterviewerDb: jest.fn(async () => undefined) }));

import { createDraftStore, getDraftRow, getMeta, markCompleted, migrate, setMeta, type Db } from "../src/drafts";
import { fetchCaseDetail, fetchCasePage, getCachedReferenceData, reconcileReferenceAccess, refreshCases, refreshReferenceData, syncInterviewer, targetsFrom, translationsFor, type Bootstrap, type ProjectSettings, type ReferenceData } from "../src/sync";
import { getCase, listCases, queueAction, saveRegistration, upsertCase, type CaseDetail, type CaseRow } from "../src/cases";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const PROJECT = "P1";
const SITE = "S1";
const REG = "bbbbbbbb-0000-4000-8000-000000000001";
const DRAFT = "aaaaaaaa-0000-4000-8000-000000000001";
const DEATH = "dddddddd-0000-4000-8000-000000000001";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close()
  };
}

const project = (projectId = PROJECT): ProjectSettings => ({
  project_id: projectId,
  project_name: projectId,
  web_intake_mode: "both",
  sites: [{ project_id: projectId, site_id: SITE, site_name: SITE, web_intake_mode: "both" }],
  form_options: { available_locales: [{ code: "en", label: "English" }], default_locale: "en", web_intake_mode: "both", instrument_version: "server" },
  prefill_policy: { direct: {}, units: {}, answer_fields: {}, locked_fields: [] }
});

const referenceFixture = (projects = [project()]): Bootstrap => ({
  user: { user_id: USER, name: "A" },
  instrument_version: "server",
  projects
});

const access = (projects = [project()]) => ({
  user: { user_id: USER, name: "A" },
  is_admin: false,
  demo_coding: { available: false, project_ids: [] },
  projects: projects.map((item) => ({
    project_id: item.project_id,
    project_name: item.project_name,
    has_tree: true,
    grants: [{ role: "interviewer", scope: "project" }],
    sites: item.sites.map((site) => ({ site_id: site.site_id, site_name: site.site_name ?? site.site_id, roles: ["interviewer"] })),
    levels: [],
    units: [{ org_unit_id: item.project_id === "P2" ? "U2" : "U1", unit_code: "U", unit_name: "Unit", level_code: "phc", path: "U", is_active: true, selectable: true, roles: ["interviewer"], can_code: false }]
  }))
});

const detail = (projectId = PROJECT, deathId = DEATH): CaseDetail => ({
  death_id: deathId,
  unique_id: "U-1",
  project_id: projectId,
  site_id: SITE,
  org_unit_id: null,
  unit_name: null,
  state: "registered",
  source: "registration",
  details_pending: false,
  pending_flag: false,
  registered_by_me: true,
  started_by_me: false,
  my_draft_id: null,
  va_sid: null,
  created_at: "2026-09-30T00:00:00Z",
  updated_at: "2026-09-30T00:00:00Z",
  next_visit_at: null,
  last_contact_at: null,
  deceased: { name: "A", sex: "male", age_years: 40, date_of_birth: null, date_of_birth_partial: null, date_of_death: "2026-09-29", place_of_death: null },
  household_address: { address: null, house_street: null, village_ward: null, landmark: null },
  informant: { name: null, phone: null, phone_2: null },
  remarks: null,
  prefill: {},
  links: { self: `/cases/${deathId}`, attempts: `/cases/${deathId}/attempts`, visit: `/cases/${deathId}/visit` }
});

const summary = (deathId: string, projectId = PROJECT): CaseRow => ({
  death_id: deathId,
  unique_id: `U-${deathId.slice(-4)}`,
  project_id: projectId,
  site_id: SITE,
  org_unit_id: null,
  unit_name: null,
  state: "registered",
  source: "registration",
  details_pending: false,
  pending_flag: false,
  deceased_name: "A",
  deceased_sex: "male",
  age_years: 40,
  date_of_death: "2026-09-29",
  registered_by_me: true,
  started_by_me: false,
  my_draft_id: null,
  va_sid: null,
  created_at: "2026-09-30T00:00:00Z",
  updated_at: "2026-09-30T00:00:00Z",
  next_visit_at: null,
  last_contact_at: null,
  informant_phone_masked: null,
  informant_phone_2_masked: null
});

const reference = (projects: ProjectSettings[] = [project()]): ReferenceData => ({
  bootstrap: referenceFixture(projects),
  projects: projects.map((item) => ({ project: item, units: null }))
});

const draft = (id = DRAFT, data: SubmissionData = { Id10013: "yes" }): WhoVaDraft => ({
  schemaVersion: 1,
  formVersion: "f1",
  id,
  instrumentId: "who-va-2022",
  instrumentVersion: "1",
  currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z",
  updatedAt: "2026-09-30T01:00:00Z",
  data
});

type Call = { url: string; body?: Record<string, unknown> };
let calls: Call[];
const json = (status: number, body: unknown) => Object.assign({ ok: status >= 200 && status < 300, status, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) }, { __body: body }) as unknown as Response;

function server(handler: (call: Call) => Response): void {
  calls = [];
  let referenceFixtureBody: Bootstrap | undefined;
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(url), body: init?.body ? JSON.parse(init.body as string) : undefined };
    calls.push(call);
    if (call.url.endsWith("/me/access")) {
      const source = handler({ ...call, url: `${SERVER}/fixture-reference` });
      const body = (source as Response & { __body?: Bootstrap }).__body;
      referenceFixtureBody = body && typeof body === "object" && Array.isArray(body.projects) ? body : referenceFixtureBody ?? referenceFixture();
      return json(200, access(referenceFixtureBody.projects));
    }
    if (call.url.endsWith("/form-options") && referenceFixtureBody) {
      const override = handler(call);
      if (!override.ok) return override;
      const projectId = call.url.split("/organization/")[1]?.split("/")[0];
      return json(200, referenceFixtureBody.projects.find((project) => project.project_id === projectId)?.form_options ?? {});
    }
    if (call.url.includes("/prefill-policy") && referenceFixtureBody) {
      const override = handler(call);
      if (!override.ok) return override;
      const projectId = call.url.split("/projects/")[1]?.split("/")[0];
      return json(200, referenceFixtureBody.projects.find((project) => project.project_id === projectId)?.prefill_policy ?? { direct: {}, units: {}, answer_fields: {}, locked_fields: [] });
    }
    let response = handler(call);
    if (call.url.endsWith("/fixture-reference")) {
      // Older tests used a catch-all 204 for bootstrap because the previous
      // implementation only needed units in the few tests that exercised it.
      // The unified client always needs metadata plus a validated access body.
      const body = (response as Response & { __body?: Bootstrap }).__body;
      referenceFixtureBody = body && typeof body === "object" ? body : referenceFixture();
      if (!body) response = json(200, referenceFixtureBody);
    }
    return response;
  }) as typeof fetch;
}

beforeEach(() => {
  mockSecure.clear();
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: PROJECT, project_name: PROJECT }));
  mockSecure.set("device_secret", "s");
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER, name: "A" }]));
  mockSecure.set(`tokens.${USER}`, JSON.stringify({ access_token: "a", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" }));
});

describe("project scoped reference data", () => {
  it("fetches every project and keeps units isolated by project", async () => {
    const db = memoryDb();
    await migrate(db);
    const projects = [project("P1"), project("P2")];
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture(projects));
      if (call.url.includes("project_id=P1")) return json(200, { scoped: false, levels: [], units: [{ org_unit_id: "U1" }] });
      return json(200, { scoped: false, levels: [], units: [{ org_unit_id: "U2" }] });
    });
    const result = await refreshReferenceData(USER, db, { force: true });
    expect(result.projects.map(({ project: item }) => item.project_id)).toEqual(["P1", "P2"]);
    expect(result.projects[0].units?.units[0].org_unit_id).toBe("U1");
    expect(result.projects[1].units?.units[0].org_unit_id).toBe("U2");
    expect(await getMeta(db, "units", "P1")).toEqual(expect.objectContaining({
      units: [expect.objectContaining({ org_unit_id: "U1" })]
    }));
    expect(await getCachedReferenceData(db)).toEqual(result);
  });

  it("prefers the shared form-options mode over temporary bootstrap metadata", async () => {
    const db = memoryDb();
    await migrate(db);
    const configured = project();
    configured.form_options = { ...configured.form_options, web_intake_mode: "direct", instrument_version: "shared" };
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture([configured])) : json(200, { scoped: false, levels: [], units: [] }));
    const result = await refreshReferenceData(USER, db, { force: true });
    expect(result.projects[0].project.web_intake_mode).toBe("direct");
    expect(result.projects[0].project.form_options.instrument_version).toBe("shared");
  });

  it("rejects an incompatible shared instrument before publishing the pack", async () => {
    const db = memoryDb();
    await migrate(db);
    const configured = project();
    configured.form_options = { ...configured.form_options, form_types: [{ instrument_code: "OTHER", is_default: true }] };
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture([configured])) : json(200, { scoped: false, levels: [], units: [] }));
    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toThrow("instrument_incompatible");
    expect(await getCachedReferenceData(db)).toBeUndefined();
  });

  it("rejects a malformed shared prefill policy before publishing the pack", async () => {
    const db = memoryDb();
    await migrate(db);
    const configured = project();
    configured.prefill_policy = {} as ProjectSettings["prefill_policy"];
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture([configured])) : json(200, { scoped: false, levels: [], units: [] }));
    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toThrow("instrument_incompatible");
    expect(await getCachedReferenceData(db)).toBeUndefined();
  });

  it("reconciles current grants without downloading stable settings", async () => {
    const db = memoryDb();
    await migrate(db);
    const projects = [project("P1"), project("P2")];
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture(projects)) : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    await db.runAsync("INSERT INTO cases (death_id, project_id, position, row) VALUES (?, ?, ?, ?)", [DEATH, "P2", 0, JSON.stringify(detail("P2"))]);
    calls = [];
    const reconciled = await reconcileReferenceAccess(db, access([project("P1")]));
    expect(reconciled?.projects.map(({ project: item }) => item.project_id)).toEqual(["P1"]);
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", ["P2"])).toBeNull();
    expect(calls).toEqual([]);
  });

  it("throttles a failed automatic refresh for one day but retries on force", async () => {
    const db = memoryDb();
    await migrate(db);
    server(() => {
      throw new TypeError("offline");
    });
    await expect(refreshReferenceData(USER, db)).rejects.toThrow("offline");

    server(() => json(200, referenceFixture()));
    await expect(refreshReferenceData(USER, db)).rejects.toThrow("reference_refresh_throttled");
    expect(calls).toHaveLength(0);

    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture()) : json(200, { scoped: false, levels: [], units: [] }));
    await expect(refreshReferenceData(USER, db, { force: true })).resolves.toMatchObject({ projects: [{ project: { project_id: PROJECT } }] });
    expect(calls.filter(({ url }) => url.endsWith("/me/access"))).toHaveLength(1);
  });

  it("queues a forced refresh behind an automatic request and performs a fresh bootstrap", async () => {
    const db = memoryDb();
    await migrate(db);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let bootstraps = 0;
    calls = [];
    globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const call = { url: String(url), body: init?.body ? JSON.parse(init.body as string) : undefined };
      calls.push(call);
      if (call.url.endsWith("/me/access")) {
        bootstraps += 1;
        if (bootstraps === 1) await gate;
        return json(200, access());
      }
      if (call.url.endsWith("/form-options")) return json(200, project().form_options);
      if (call.url.includes("/prefill-policy")) return json(200, project().prefill_policy);
      return json(200, { scoped: false, levels: [], units: [] });
    }) as typeof fetch;
    const automatic = refreshReferenceData(USER, db);
    const forced = refreshReferenceData(USER, db, { force: true });
    release();
    await expect(automatic).resolves.toBeDefined();
    await expect(forced).resolves.toBeDefined();
    expect(bootstraps).toBe(2);
  });

  it("purges a removed project before a later reference request fails", async () => {
    const db = memoryDb();
    await migrate(db);
    await db.runAsync("INSERT INTO cases (death_id, project_id, position, row) VALUES (?, ?, ?, ?)", [DEATH, "P2", 0, JSON.stringify(detail("P2"))]);
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture([project("P1")]));
      return json(503, { code: "offline" });
    });
    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toThrow("HTTP 503 offline");
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", ["P2"])).toBeNull();
    expect(await getCachedReferenceData(db)).toBeUndefined();
  });

  it("rejects malformed project lists without purging existing work", async () => {
    const db = memoryDb();
    await migrate(db);
    await db.runAsync("INSERT INTO cases (death_id, project_id, position, row) VALUES (?, ?, ?, ?)", [DEATH, PROJECT, 0, JSON.stringify(detail())]);
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, { ...referenceFixture(), projects: [{}] }) : json(200, {}));
    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toThrow();
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", [PROJECT])).not.toBeNull();
  });

  it("keeps the complete previous pack when one project fails during refresh", async () => {
    const db = memoryDb();
    await migrate(db);
    const projects = [project("P1"), project("P2")];
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture(projects)) : json(200, { scoped: false, levels: [], units: [] }));
    const previous = await refreshReferenceData(USER, db, { force: true });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture(projects));
      if (call.url.includes("/organization/P2/") || call.url.includes("/projects/P2/")) return json(503, { code: "units_failed" });
      return json(200, { scoped: false, levels: [], units: [] });
    });
    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toThrow("HTTP 503 units_failed");
    expect(await getCachedReferenceData(db)).toEqual(previous);
  });

  it("purges every removed project's queue, case, draft, and config before upload", async () => {
    const db = memoryDb();
    await migrate(db);
    const removed = "P2";
    await saveRegistration(db, { project_id: removed, client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    await queueAction(db, { project_id: removed, client_id: "cccccccc-0000-4000-8000-000000000001", kind: "attempt", death_id: DEATH, body: { outcome: "reached" } });
    await upsertCase(db, detail(removed));
    await createDraftStore(db, { projectId: removed, siteId: SITE }).save(draft());
    await setMeta(db, "draft-config:removed", { projectId: removed });
    await setMeta(db, "units", { stale: true }, removed);
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture([project(PROJECT)])) : json(200, { scoped: false, levels: [], units: [] }));
    await expect(refreshReferenceData(USER, db, { force: true })).resolves.toBeDefined();
    expect(await db.getFirstAsync("SELECT * FROM registrations WHERE project_id = ?", [removed])).toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM case_actions WHERE project_id = ?", [removed])).toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", [removed])).toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM drafts WHERE project_id = ?", [removed])).toBeNull();
    expect(await getMeta(db, "draft-config:removed")).toBeUndefined();
    expect(await getMeta(db, "units", removed)).toBeUndefined();
  });
});

describe("translations", () => {
  const hindiProject = (projectId: string): ProjectSettings => ({
    ...project(projectId),
    form_options: {
      available_locales: [{ code: "en", label: "English" }, { code: "hi", label: "Hindi" }],
      default_locale: "en",
      translation_versions: { hi: 1 },
      web_intake_mode: "both",
      instrument_version: "server"
    }
  });

  it("keeps Hindi translations isolated by project and version, with English fallback", async () => {
    const db = memoryDb();
    await migrate(db);
    const projects = [hindiProject("P1"), hindiProject("P2")];
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture(projects));
      if (call.url.includes("project_id=P1")) return json(200, { questions: { Id10007: { label: "P1 Hindi" } } });
      return json(200, { questions: { Id10007: { label: "P2 Hindi" } } });
    });
    await refreshReferenceData(USER, db, { force: true });
    expect(await translationsFor(USER, db, "P1", "WHO_2022_VA", "hi", 1)).toMatchObject({ questions: { Id10007: { label: "P1 Hindi" } } });
    expect(await translationsFor(USER, db, "P2", "WHO_2022_VA", "hi", 1)).toMatchObject({ questions: { Id10007: { label: "P2 Hindi" } } });
    const callsBeforeEnglish = calls.length;
    expect(await translationsFor(USER, db, "P1", "WHO_2022_VA", "en", undefined)).toBeNull();
    expect(calls).toHaveLength(callsBeforeEnglish);

    server((call) => call.url.includes("project_id=P1") ? json(200, { questions: { Id10007: { label: "P1 v2" } } }) : json(500, { code: "translation_failed" }));
    expect(await translationsFor(USER, db, "P1", "WHO_2022_VA", "hi", 2)).toMatchObject({ questions: { Id10007: { label: "P1 v2" } } });
    expect(await translationsFor(USER, db, "P2", "WHO_2022_VA", "hi", 1)).toMatchObject({ questions: { Id10007: { label: "P2 Hindi" } } });
  });

  it("uses null only for an unavailable translation and propagates server failures", async () => {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.includes("/translations/hi") ? json(404, { code: "not_found" }) : json(204, null));
    await expect(translationsFor(USER, db, PROJECT, "WHO_2022_VA", "hi", 7)).resolves.toBeNull();
    server(() => json(500, { code: "translation_failed" }));
    await expect(translationsFor(USER, db, PROJECT, "WHO_2022_VA", "hi", 8)).rejects.toThrow("HTTP 500 translation_failed");
  });
});

describe("sync upload ordering", () => {
  it("uploads only valid and explicitly incomplete outcomes and reports outstanding ids", async () => {
    const db = memoryDb();
    await migrate(db);
    const valid = "aaaaaaaa-0000-4000-8000-000000000001";
    const partial = "aaaaaaaa-0000-4000-8000-000000000002";
    const invalid = "aaaaaaaa-0000-4000-8000-000000000003";
    const open = "aaaaaaaa-0000-4000-8000-000000000004";
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(valid));
    await store.save(draft(partial, { Id10013: "yes", interview_outcome: "partially_completed" }));
    await store.save(draft(invalid));
    await store.save(draft(open, {}));
    await markCompleted(db, valid, { valid: true, issues: [] });
    await markCompleted(db, partial, { valid: false, issues: [{ question: "Id10120", code: "required", message: "Required" }] });
    await markCompleted(db, invalid, { valid: false, issues: [{ question: "Id10120", code: "required", message: "Required" }] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(201, { case: { death_id: DEATH, state: "registered" } });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toEqual({ sent: 2, failed: 0, remaining: 2 });
    const uploads = calls.filter(({ url }) => url.endsWith("/submissions"));
    expect(uploads.map(({ body }) => body?.client_draft_id)).toEqual([valid, partial]);
    expect(uploads[0].body).toMatchObject({ project_id: PROJECT, completion: { valid: true, issues: [] } });
    expect(uploads[1].body).toMatchObject({ completion: { valid: false } });
    expect(calls.find(({ url }) => url.endsWith("/outstanding"))?.body).toMatchObject({
      count: 2,
      client_draft_ids: [invalid, open]
    });
  });

  it("keeps 409 and 413 submission refusals queued and continues to the outstanding report", async () => {
    const db = memoryDb();
    await migrate(db);
    const first = "aaaaaaaa-0000-4000-8000-000000000011";
    const second = "aaaaaaaa-0000-4000-8000-000000000012";
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(first));
    await store.save(draft(second));
    await markCompleted(db, first, { valid: true, issues: [] });
    await markCompleted(db, second, { valid: true, issues: [] });
    let submission = 0;
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(submission++ === 0 ? 409 : 413, { code: submission === 1 ? "conflict" : "too_large" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toEqual({ sent: 0, failed: 2, remaining: 2 });
    expect(await getDraftRow(db, first)).toMatchObject({ completed: 1 });
    expect(await getDraftRow(db, second)).toMatchObject({ completed: 1 });
  });

  it("reopens a 422 submission while retaining answers and does not resend it", async () => {
    const db = memoryDb();
    await migrate(db);
    const id = "aaaaaaaa-0000-4000-8000-000000000013";
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(id, { Id10013: "no" }));
    await markCompleted(db, id, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(422, { code: "invalid_interview" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(await getDraftRow(db, id)).toMatchObject({ completed: 0 });
    expect((await store.load!(id))?.data).toEqual({ Id10013: "no" });
    const firstSubmissionCount = calls.filter(({ url }) => url.endsWith("/submissions")).length;
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 0, remaining: 1 });
    expect(calls.filter(({ url }) => url.endsWith("/submissions")).length).toBe(firstSubmissionCount);
  });

  it("builds project and unit picker choices from scoped reference data", () => {
    const selected = project("P2");
    selected.sites = [{ project_id: "P2", site_id: "S2", site_name: "Site 2", web_intake_mode: "both" }];
    const units = {
      scoped: true,
      levels: [{ level_code: "phc", level_name: "PHC", depth: 1 }],
      units: [
        { org_unit_id: "D1", unit_code: "D1", unit_name: "Unit D1", level_code: "phc", path: "D1", selectable: false },
        { org_unit_id: "P1", unit_code: "P1", unit_name: "Unit P1", level_code: "phc", path: "P1", selectable: true }
      ]
    };
    expect(targetsFrom(selected, units)).toEqual([{ key: "P2:S2:P1", label: "Site 2 · Unit P1", projectId: "P2", siteId: "S2", orgUnitId: "P1" }]);
  });

  it("downloads active cases page by page, then fetches and stores each full detail", async () => {
    const db = memoryDb();
    await migrate(db);
    const second = "dddddddd-0000-4000-8000-000000000002";
    server((call) => {
      if (call.url.includes("/cases?") && call.url.includes("cursor=")) return json(200, { cases: [summary(second)], next_cursor: null });
      if (call.url.includes("/cases?")) return json(200, { cases: [summary(DEATH)], next_cursor: "next-1" });
      if (call.url.endsWith(`/cases/${DEATH}`)) return json(200, { case: detail(PROJECT, DEATH) });
      if (call.url.endsWith(`/cases/${second}`)) return json(200, { case: detail(PROJECT, second) });
      return json(204, null);
    });
    await expect(refreshCases(USER, db, reference())).resolves.toHaveLength(2);
    expect((await listCases(db)).map((item) => item.death_id)).toEqual([DEATH, second]);
    expect(calls.filter(({ url }) => url.includes("/cases?")).map(({ url }) => url)).toHaveLength(2);
    expect(calls.filter(({ url }) => /\/cases\/[^?]+$/.test(url))).toHaveLength(2);
  });

  it("refreshes authorization, uploads registration before its draft, and includes project_id", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveRegistration(db, { project_id: PROJECT, client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, clientDeathId: REG } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/deaths")) return json(201, { case: detail() });
      if (call.url.endsWith("/submissions")) return json(201, { va_sid: "V1", case: { death_id: DEATH, state: "registered" } });
      if (call.url.includes("/cases?")) return json(200, { cases: [], next_cursor: null });
      return json(204, null);
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 2, failed: 0 });
    const paths = calls.map(({ url }) => url.split("?")[0].slice(SERVER.length));
    expect(paths.indexOf("/api/v1/intake/deaths")).toBeLessThan(paths.indexOf("/api/v1/intake/submissions"));
    expect(calls.find(({ url }) => url.endsWith("/deaths"))?.body).toMatchObject({ project_id: PROJECT });
    expect(calls.find(({ url }) => url.endsWith("/submissions"))?.body).toMatchObject({ project_id: PROJECT });
  });

  it("uses the explicit project query for case pages", async () => {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.includes("/cases?") ? json(200, { cases: [], counts: { registered: 0 }, next_cursor: null }) : json(204, null));
    await expect(fetchCasePage(USER, "P2", { state: "registered", mine: true, limit: 20 })).resolves.toEqual({ cases: [], counts: { registered: 0 }, next_cursor: null });
    expect(calls[0].url).toContain("project_id=P2");
    expect(calls[0].url).toContain("state=registered");
  });

  it("keeps a draft on a malformed success and purges a case on terminal acknowledgement", async () => {
    const db = memoryDb();
    await migrate(db);
    await upsertCase(db, detail());
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(200, {});
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).rejects.toThrow("invalid_case_ack");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();

    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(200, { case: { death_id: DEATH, unique_id: "U-1", status: "submitted" } });
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1 });
    expect(await getCase(db, DEATH)).toBeUndefined();
  });

  it("purges cached cases on terminal detail and on a 404", async () => {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture()) : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    await upsertCase(db, detail());
    server((call) => call.url.endsWith(`/cases/${DEATH}`) ? json(200, { case: { ...detail(), state: "submitted" } }) : json(204, null));
    await expect(fetchCaseDetail(USER, db, DEATH)).resolves.toMatchObject({ state: "submitted" });
    expect(await getCase(db, DEATH)).toBeUndefined();

    await upsertCase(db, detail());
    server((call) => call.url.endsWith(`/cases/${DEATH}`) ? json(404, { code: "not_found" }) : json(204, null));
    await expect(fetchCaseDetail(USER, db, DEATH)).rejects.toThrow("HTTP 404 not_found");
    expect(await getCase(db, DEATH)).toBeUndefined();
  });
});
