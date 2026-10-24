/** Project scoped reference refresh and upload ordering. */
import { DatabaseSync } from "node:sqlite";

import { recordServerDate, resetPhoneClock } from "../src/phoneClock";
import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockSecure = new Map<string, string>();
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
  digest: async (_algorithm: string, data: Uint8Array) => require("node:crypto").createHash("sha256").update(data).digest().buffer
}));
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key))
}));
jest.mock("@drguptavivek/who-2022-va", () => ({
  createWhoVa2022Instrument: () => ({
    id: "WHO_2022_VA",
    version: "v1",
    sections: [{ name: "start" }],
    questions: [],
  }),
  decodeWhoVaDraft: (value: unknown) => value,
  reduceNationalIdData: (data: unknown) => data,
}), { virtual: true });
jest.mock("../src/interviewerDb", () => ({ deleteInterviewerDb: jest.fn(async () => undefined) }));

import { createDraftStore, getDraftRow, getMeta, markCompleted, migrate, retryHeldDraft, setMeta, type Db } from "../src/drafts";
import type { AccessSummary } from "../src/api";
import { canUseBundledFallbackForProject, listPausedProjects, fetchCaseDetail, fetchCasePage, getCachedReferenceData, markProjectDefinitionServed, reconcileReferenceAccess, refreshCases, refreshReferenceData, syncInterviewer, targetsFrom, translationsFor, translationsForDraft, type Bootstrap, type ProjectSettings, type ReferenceData } from "../src/sync";
import { beginRevision, getRevisionRow, queueRevision } from "../src/revisions";
import { createNativeDefinitionCache } from "../src/formDefinitionCache";
import { computeUtf8Sha256HexSync, type ConsentRecordEnvelope } from "../src/consent";
import { consentForDraft, getConsentConfig, inheritedConsentRefused, loadConsents, refreshConsentConfig, saveDraftConsent, saveRegistrationConsent, type StoredConsent } from "../src/consentStore";
import { pendingErrors, resetErrorLog } from "../src/errorLog";
import { sendRefusal, summariseWork } from "../src/unsentWork";
import { draftAttachments, saveAttachment } from "../src/attachmentStore";
import { getCase, getRegistration, getRegistrationRefusal, listCases, queueAction, saveRegistration, upsertCase, type CaseDetail, type CaseRow } from "../src/cases";

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

const access = (projects = [project()]): AccessSummary => ({
  user: { user_id: USER, name: "A" },
  is_admin: false,
  roles: ["interviewer"],
  demo_coding: { available: false, project_ids: [] },
  projects: projects.map((item) => ({
    project_id: item.project_id,
    project_name: item.project_name,
    has_tree: true,
    grants: [{ role: "interviewer", scope: "project", active: true, source: "assigned" as const }],
    actions: { interview: item.sites.map((site) => ({
      site_id: site.site_id, site_name: site.site_name ?? site.site_id,
      web_intake_mode: "both" as const,
      org_units: [{ org_unit_id: item.project_id === "P2" ? "U2" : "U1", unit_code: "U", unit_name: "Unit", path: "U" }],
    })), register_death: [] },
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
  has_informant_phone: false,
  has_informant_phone_2: false
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

type Call = { url: string; auth?: string; body?: Record<string, unknown>; raw?: Uint8Array };
let calls: Call[];
const json = (status: number, body: unknown) => Object.assign({ ok: status >= 200 && status < 300, status, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) }, { __body: body }) as unknown as Response;

function submissionSuccess(call: Call, extra: Record<string, unknown> = {}, status = 201): Response {
  const body = call.body ?? {};
  const deathId = typeof body.death_id === "string" ? body.death_id : DEATH;
  return json(status, {
    answers_sha256: body.answers_sha256,
    received_sha256: body.answers_sha256,
    kept: extra.kept ?? (extra.superseded === true ? "server" : "incoming"),
    locked: extra.locked ?? (extra.superseded === true),
    case: { death_id: deathId, unique_id: "U-1", status: "registered" },
    superseded: false,
    ...extra
  });
}

function server(handler: (call: Call) => Response): void {
  calls = [];
  let referenceFixtureBody: Bootstrap | undefined;
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const headers = init?.headers as Record<string, string> | undefined;
    const call = {
      url: String(url),
      auth: headers?.Authorization ?? headers?.authorization,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      raw: init?.body && typeof init.body !== "string" ? (init.body as Uint8Array) : undefined
    };
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
  it("keeps the first-served definition marker encrypted and project-scoped until revocation", async () => {
    const db = memoryDb();
    await migrate(db);
    expect(await canUseBundledFallbackForProject(USER, db, "P1")).toBe(true);
    await markProjectDefinitionServed(USER, db, "P1");
    expect(await canUseBundledFallbackForProject(USER, db, "P1")).toBe(false);
    expect(await canUseBundledFallbackForProject(USER, db, "P2")).toBe(true);

    await reconcileReferenceAccess(db, access([]));
    expect(await canUseBundledFallbackForProject(USER, db, "P1")).toBe(true);
  });

  it("restores the native definition cache only for projects in authoritative interviewer access", async () => {
    const db = memoryDb();
    await migrate(db);
    const cache = createNativeDefinitionCache(db as never, USER);
    const restoreProject = jest.spyOn(cache, "restoreProject");

    await reconcileReferenceAccess(db, access([project("P1")]));
    expect(restoreProject).toHaveBeenCalledTimes(1);
    expect(restoreProject).toHaveBeenCalledWith("P1");
    restoreProject.mockClear();

    server((call) => call.url.endsWith("/fixture-reference")
      ? json(200, referenceFixture([project("P1")]))
      : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    expect(restoreProject).toHaveBeenCalledWith("P1");
  });

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
    const refreshedAccess = access([project("P1"), project("P2")]);
    refreshedAccess.projects[1].grants[0].active = false;
    refreshedAccess.projects[1].actions.interview = [];
    const reconciled = await reconcileReferenceAccess(db, refreshedAccess);
    expect(reconciled?.projects.map(({ project: item }) => item.project_id)).toEqual(["P1"]);
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", ["P2"])).toBeNull();
    expect(calls).toEqual([]);
  });

  it("retains registration data while hiding projects that have only reporter access", async () => {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture()) : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    await saveRegistration(db, { project_id: PROJECT, client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    await createDraftStore(db, { projectId: PROJECT, siteId: SITE }).save(draft());

    const reporterAccess = access([]);
    reporterAccess.roles = ["death_reporter"];
    reporterAccess.projects = [{
      ...access([project()]).projects[0],
      grants: [],
      actions: { interview: [], register_death: [{
        site_id: SITE, site_name: SITE, web_intake_mode: "death_register", org_units: [],
      }] },
    }];
    const cached = await reconcileReferenceAccess(db, reporterAccess);

    expect(cached).toBeUndefined();
    expect(await db.getFirstAsync("SELECT * FROM registrations WHERE project_id = ?", [PROJECT])).not.toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM drafts WHERE project_id = ?", [PROJECT])).not.toBeNull();
    expect(await listPausedProjects(db, new Set())).toEqual([{ projectId: PROJECT, projectName: PROJECT }]);
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

  it("keeps every removed project's unsent queue, draft and config, and drops its cases and settings", async () => {
    const db = memoryDb();
    await migrate(db);
    const removed = "P2";
    await saveRegistration(db, { project_id: removed, client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    await queueAction(db, { project_id: removed, client_id: "cccccccc-0000-4000-8000-000000000001", kind: "attempt", death_id: DEATH, body: { outcome: "reached" } });
    await upsertCase(db, detail(removed));
    await createDraftStore(db, { projectId: removed, siteId: SITE }).save(draft());
    await setMeta(db, "draft-config:removed", { projectId: removed });
    await setMeta(db, "units", { stale: true }, removed);
    const projects = [project(PROJECT), project(removed)];
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture(projects)) : json(200, { scoped: false, levels: [], units: [] }));
    const fetch = globalThis.fetch;
    const refreshedAccess = access(projects);
    refreshedAccess.projects[1].grants[0].active = false;
    refreshedAccess.projects[1].actions.interview = [];
    globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const response = await fetch(url, init);
      if (!String(url).endsWith("/me/access")) return response;
      const body = await response.json() as Record<string, unknown>;
      return json(200, { ...body, projects: refreshedAccess.projects });
    }) as typeof fetch;
    await expect(refreshReferenceData(USER, db, { force: true })).resolves.toBeDefined();
    expect(calls.filter(({ url }) => url.endsWith("/form-options")).map(({ url }) => url)).toEqual([
      expect.stringContaining(`/organization/${PROJECT}/form-options`),
    ]);
    expect(await db.getFirstAsync("SELECT * FROM registrations WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM case_actions WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM drafts WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await getMeta(db, "draft-config:removed")).toEqual({ projectId: removed });
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", [removed])).toBeNull();
    expect(await getMeta(db, "units", removed)).toBeUndefined();
    expect(await listPausedProjects(db, new Set([PROJECT]))).toEqual([{ projectId: removed, projectName: removed }]);
  });

  it("keeps unsent work, drops cases and fetches no content for a coder-only account", async () => {
    const db = memoryDb();
    await migrate(db);
    const removed = "P2";
    await saveRegistration(db, { project_id: removed, client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    await queueAction(db, { project_id: removed, client_id: "cccccccc-0000-4000-8000-000000000001", kind: "attempt", death_id: DEATH, body: { outcome: "reached" } });
    await upsertCase(db, detail(removed));
    await createDraftStore(db, { projectId: removed, siteId: SITE }).save(draft());
    await setMeta(db, "draft-config:removed", { projectId: removed });
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture([project(removed)])) : json(200, { scoped: false, levels: [], units: [] }));
    const fetch = globalThis.fetch;
    const refreshedAccess = access([project(removed)]);
    refreshedAccess.roles = ["coder"];
    refreshedAccess.projects[0].grants[0].active = false;
    refreshedAccess.projects[0].actions.interview = [];
    globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const response = await fetch(url, init);
      if (!String(url).endsWith("/me/access")) return response;
      const body = await response.json() as Record<string, unknown>;
      return json(200, { ...body, ...refreshedAccess });
    }) as typeof fetch;

    await expect(refreshReferenceData(USER, db, { force: true })).rejects.toMatchObject({ status: 403, code: "no_collection_access" });
    expect(calls.map(({ url }) => url)).toEqual([expect.stringMatching(/\/api\/v1\/me\/access$/)]);
    expect(await db.getFirstAsync("SELECT * FROM registrations WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM case_actions WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM drafts WHERE project_id = ?", [removed])).not.toBeNull();
    expect(await getMeta(db, "draft-config:removed")).toEqual({ projectId: removed });
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", [removed])).toBeNull();
  });
});

describe("unsent work in a project that leaves access", () => {
  async function pausedSetup(): Promise<Db> {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.endsWith("/fixture-reference")
      ? json(200, referenceFixture([project("P1"), project("P2")]))
      : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    await saveRegistration(db, { project_id: "P2", client_death_id: REG, site_id: SITE, fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" } });
    await createDraftStore(db, { projectId: "P2", siteId: SITE }).save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    return db;
  }

  it("keeps it, lists it as paused and still tries to send it; a refusal is kept and recorded", async () => {
    const db = await pausedSetup();
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture([project("P1")]));
      if (call.url.endsWith("/deaths") || call.url.endsWith("/submissions")) return json(403, { code: "project_forbidden" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null, scoped: false, levels: [], units: [] });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 2, remaining: 1 });

    expect(calls.some(({ url, body }) => url.endsWith("/deaths") && body?.project_id === "P2")).toBe(true);
    expect(calls.some(({ url, body }) => url.endsWith("/submissions") && body?.project_id === "P2")).toBe(true);
    expect(await getRegistration(db, REG)).toMatchObject({ project_id: "P2", state: "pending" });
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ project_id: "P2", completed: 1, upload_issue: null });
    expect(calls.find(({ url }) => url.endsWith("/outstanding"))?.body).toMatchObject({ count: 1, client_draft_ids: [DRAFT], client_death_ids: [REG] });
    expect(await listPausedProjects(db, new Set(["P1"]))).toEqual([
      { projectId: "P2", projectName: "P2", refusal: { status: 403, code: "project_forbidden" } },
    ]);
  });

  it("deletes paused work the server acknowledges, and the pause notice with it", async () => {
    const db = await pausedSetup();
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture([project("P1")]));
      if (call.url.endsWith("/deaths")) return json(201, { case: detail("P2") });
      if (call.url.endsWith("/submissions")) return submissionSuccess(call);
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null, scoped: false, levels: [], units: [] });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 2, failed: 0, remaining: 0 });

    expect(await getRegistration(db, REG)).toBeUndefined();
    expect(await getDraftRow(db, DRAFT)).toBeNull();
    expect(await db.getFirstAsync("SELECT * FROM cases WHERE project_id = ?", ["P2"])).toBeNull();
    expect(await listPausedProjects(db, new Set(["P1"]))).toEqual([]);
    expect(await getMeta(db, "paused:P2")).toBeUndefined();
  });

  it("keeps the uploads already sent when the access refresh then refuses every project", async () => {
    const db = await pausedSetup();
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture([]));
      if (call.url.endsWith("/submissions")) return submissionSuccess(call);
      return json(403, { code: "project_forbidden" });
    });

    await expect(syncInterviewer(USER, db)).rejects.toThrow();
    expect(calls.some(({ url }) => url.endsWith("/submissions"))).toBe(true);
    expect(await getDraftRow(db, DRAFT)).toBeNull();
    expect(await getRegistration(db, REG)).toMatchObject({ project_id: "P2", state: "pending" });
  });
});

describe("attachments are sent before the interview", () => {
  const FILE = "55555555-5555-4555-8555-555555555555";
  const SERVER_DRAFT = "99999999-9999-4999-8999-999999999999";
  async function withFile(): Promise<Db> {
    const db = memoryDb();
    await migrate(db);
    server((call) => call.url.endsWith("/fixture-reference") ? json(200, referenceFixture()) : json(200, { scoped: false, levels: [], units: [] }));
    await refreshReferenceData(USER, db, { force: true });
    await createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } }).save(
      draft(DRAFT, { Id10476_audio: { id: FILE, uri: `who-va-attachment:${FILE}` } as never }));
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    await saveAttachment(db, { id: FILE, draftId: DRAFT, projectId: PROJECT, question: "Id10476_audio", kind: "audio", mimeType: "audio/mp4", ext: "m4a", bytes: new Uint8Array([1, 2, 3]) });
    return db;
  }
  const happy = (call: Call): Response => {
    if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
    if (call.url.endsWith("/intake/drafts")) return json(201, { draft: { draft_id: SERVER_DRAFT } });
    if (call.url.includes("/attachments/")) return json(201, { created: true });
    if (call.url.endsWith("/submissions")) return submissionSuccess(call);
    if (call.url.endsWith("/outstanding")) return json(204, null);
    return json(200, { cases: [], next_cursor: null, scoped: false, levels: [], units: [] });
  };

  it("uploads the file, then the interview, then deletes both from the phone", async () => {
    const db = await withFile();
    server(happy);
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1, failed: 0, remaining: 0 });
    const order = calls.map(({ url }) => url).filter((url) => /\/intake\/drafts$|attachments|submissions/.test(url));
    expect(order).toEqual([
      expect.stringMatching(/\/intake\/drafts$/),
      expect.stringContaining(`/intake/drafts/${SERVER_DRAFT}/attachments/${FILE}`),
      expect.stringMatching(/\/submissions$/),
    ]);
    expect([...calls.find(({ url }) => url.includes("/attachments/"))!.raw!]).toEqual([1, 2, 3]);
    expect(await getDraftRow(db, DRAFT)).toBeNull();
    expect(await draftAttachments(db, DRAFT)).toEqual([]);
  });

  it("does not send the interview while a file is not on the server, and keeps both for the next Send", async () => {
    const db = await withFile();
    server((call) => call.url.includes("/attachments/") ? json(503, { code: "unavailable" }) : happy(call));
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(calls.some(({ url }) => url.endsWith("/submissions"))).toBe(false);
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
    expect(await draftAttachments(db, DRAFT)).toHaveLength(1);
    const work = await summariseWork(db);
    expect(work.items.map((item) => item.kind).sort()).toEqual(["attachment", "interview"]);
  });

  it("sends the files again when the server says it lost them (409 attachments_pending)", async () => {
    const db = await withFile();
    server((call) => call.url.endsWith("/submissions") ? json(409, { code: "attachments_pending", error: "Files are still being sent." }) : happy(call));
    await syncInterviewer(USER, db);
    expect((await draftAttachments(db, DRAFT))[0]!.uploaded_at).toBeNull();
    expect((await getDraftRow(db, DRAFT))!.upload_issue).toBeNull();
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

describe("translations for a draft pinned to an older definition", () => {
  const key = (v: number) => `translations:WHO_2022_VA:hi:${v}`;

  it("uses the current pack by name when the pin's own version is not cached", async () => {
    const db = memoryDb();
    await migrate(db);
    await setMeta(db, key(2), { questions: { Id10007: { label: "current" } } }, PROJECT);
    server(() => json(500, {}));
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", 1, 2)).toMatchObject({ questions: { Id10007: { label: "current" } } });
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", undefined, 2)).toMatchObject({ questions: { Id10007: { label: "current" } } });
    expect(calls).toHaveLength(0);
  });

  it("prefers the pin's own cached version, and the same-version case is unchanged", async () => {
    const db = memoryDb();
    await migrate(db);
    await setMeta(db, key(1), { questions: { Id10007: { label: "old" } } }, PROJECT);
    await setMeta(db, key(2), { questions: { Id10007: { label: "current" } } }, PROJECT);
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", 1, 2)).toMatchObject({ questions: { Id10007: { label: "old" } } });
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", 2, 2)).toMatchObject({ questions: { Id10007: { label: "current" } } });
  });

  it("fetches and caches the current pack when none is on the phone and it is online", async () => {
    const db = memoryDb();
    await migrate(db);
    server(() => json(200, { questions: { Id10007: { label: "fetched" } } }));
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", 1, 2)).toMatchObject({ questions: { Id10007: { label: "fetched" } } });
    expect(calls).toHaveLength(1);
    expect(await getMeta(db, key(2), PROJECT)).toMatchObject({ questions: { Id10007: { label: "fetched" } } });
  });

  it("is null when offline with nothing cached, and for English", async () => {
    const db = memoryDb();
    await migrate(db);
    globalThis.fetch = jest.fn(async () => { throw new TypeError("Network request failed"); }) as unknown as typeof fetch;
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "hi", 1, 2)).toBeNull();
    expect(await translationsForDraft(USER, db, PROJECT, "WHO_2022_VA", "en", 1, 2)).toBeNull();
  });
});

describe("registered phone draft sync", () => {
  const serverDraftId = "eeeeeeee-0000-4000-8000-000000000001";
  const serverUpdatedAt = "2026-10-01T01:00:00Z";

  function draftSyncSuccess(call: Call): Response {
    return json(200, {
      draft: {
        draft_id: serverDraftId,
        project_id: PROJECT,
        site_id: SITE,
        org_unit_id: null,
        death_id: DEATH,
        unique_id: "U-1",
        status: "draft",
        created_at: "2026-09-30T00:00:00Z",
        updated_at: serverUpdatedAt,
      },
      kept: "incoming",
      conflict: false,
      answers_sha256: call.body?.answers_sha256,
      message: null,
    });
  }

  it("sends an offline registration and completed uploads before the access refresh, then its unfinished draft", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveRegistration(db, {
      project_id: PROJECT,
      client_death_id: REG,
      site_id: SITE,
      fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" },
    });
    const waiting = createDraftStore(db, {
      projectId: PROJECT,
      siteId: SITE,
      binding: { projectId: PROJECT, clientDeathId: REG },
    });
    await waiting.save(draft(DRAFT, { Id10013: "unfinished" } as SubmissionData));
    const completeId = "aaaaaaaa-0000-4000-8000-000000000014";
    const completed = createDraftStore(db, {
      projectId: PROJECT,
      siteId: SITE,
      binding: { projectId: PROJECT, deathId: DEATH },
    });
    await completed.save(draft(completeId, { Id10013: "complete" } as SubmissionData));
    await markCompleted(db, completeId, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/deaths")) return json(201, { case: detail() });
      if (call.url.endsWith("/drafts/sync")) return draftSyncSuccess(call);
      if (call.url.endsWith("/submissions")) return submissionSuccess(call);
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 3, failed: 0, remaining: 1 });
    const registrations = calls.findIndex(({ url }) => url.endsWith("/deaths"));
    const unfinished = calls.findIndex(({ url }) => url.endsWith("/drafts/sync"));
    const submissions = calls.findIndex(({ url }) => url.endsWith("/submissions"));
    const accessRefresh = calls.findIndex(({ url }) => url.endsWith("/me/access"));
    expect(registrations).toBeGreaterThanOrEqual(0);
    expect(submissions).toBeGreaterThan(registrations);
    expect(accessRefresh).toBeGreaterThan(submissions);
    expect(unfinished).toBeGreaterThan(accessRefresh);
    expect(calls[unfinished].body).toMatchObject({
      project_id: PROJECT,
      death_id: DEATH,
      client_draft_id: DRAFT,
    });
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ server_draft_id: serverDraftId, draft_sync_dirty: 0 });
  });

  it("leaves an offline registration's draft waiting when registration is refused", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveRegistration(db, {
      project_id: PROJECT,
      client_death_id: REG,
      site_id: SITE,
      fields: { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29" },
    });
    const store = createDraftStore(db, {
      projectId: PROJECT,
      siteId: SITE,
      binding: { projectId: PROJECT, clientDeathId: REG },
    });
    await store.save(draft(DRAFT));
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/deaths")) return json(422, { code: "invalid_registration" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(calls.some(({ url }) => url.endsWith("/drafts/sync"))).toBe(false);
    expect(calls.some(({ url }) => url.endsWith("/submissions"))).toBe(false);
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
  });

  it("keeps the refused registration number's message with the needs_edit registration, and clears it on re-save", async () => {
    const db = memoryDb();
    await migrate(db);
    const fields = { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29", identifiers: { mccd: "BAD" } };
    await saveRegistration(db, { project_id: PROJECT, client_death_id: REG, site_id: SITE, fields });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/deaths")) return json(422, { code: "invalid_registration", error: "MCCD number must look like MCCD123", fields: ["identifiers.mccd"] });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await syncInterviewer(USER, db);
    expect(await getRegistration(db, REG)).toMatchObject({ state: "needs_edit" });
    expect(await getRegistrationRefusal(db, REG)).toEqual({ mccd: "MCCD number must look like MCCD123" });
    await saveRegistration(db, { project_id: PROJECT, client_death_id: REG, site_id: SITE, fields });
    expect(await getRegistrationRefusal(db, REG)).toEqual({});
  });

  it("blocks a closed unfinished draft but still submits its later completed copy", async () => {
    const db = memoryDb();
    await migrate(db);
    const id = "aaaaaaaa-0000-4000-8000-000000000015";
    const store = createDraftStore(db, {
      projectId: PROJECT,
      siteId: SITE,
      binding: { projectId: PROJECT, deathId: DEATH },
    });
    await store.save(draft(id));
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/drafts/sync")) return json(409, { code: "conflict" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(await getDraftRow(db, id)).toMatchObject({ draft_sync_blocked: 1 });
    await markCompleted(db, id, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { superseded: true });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1, failed: 0, remaining: 0 });
    expect(calls.some(({ url }) => url.endsWith("/drafts/sync"))).toBe(false);
    expect(calls.some(({ url }) => url.endsWith("/submissions"))).toBe(true);
    expect(await getDraftRow(db, id)).toBeNull();
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
      if (call.url.endsWith("/submissions")) return submissionSuccess(call);
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toEqual({
      sent: 2, failed: 0, remaining: 2, supersededUniqueIds: [],
      definitionRefresh: [{ projectId: PROJECT, available: false, error: "current_definition_unavailable" }],
    });
    const uploads = calls.filter(({ url }) => url.endsWith("/submissions"));
    expect(uploads.map(({ body }) => body?.client_draft_id)).toEqual([valid, partial]);
    expect(uploads[0].body).toMatchObject({ project_id: PROJECT, completion: { valid: true, issues: [] } });
    expect(uploads[0].body?.answers_sha256).toBe(require("node:crypto").createHash("sha256").update(uploads[0].body?.answers_json as string, "utf8").digest("hex"));
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
    await expect(syncInterviewer(USER, db)).resolves.toEqual({
      sent: 0, failed: 2, remaining: 2, supersededUniqueIds: [],
      definitionRefresh: [{ projectId: PROJECT, available: false, error: "current_definition_unavailable" }],
    });
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

  it("treats a public-demo limit (429 demo_limit) as final: kept, marked, never resent until the interviewer asks", async () => {
    const db = memoryDb();
    await migrate(db);
    const id = "aaaaaaaa-0000-4000-8000-000000000014";
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(id, { Id10013: "no" }));
    await markCompleted(db, id, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(429, { code: "demo_limit" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(await getDraftRow(db, id)).toMatchObject({ completed: 1, upload_issue: "demo_limit" });
    const sends = () => calls.filter(({ url }) => url.endsWith("/submissions")).length;
    expect(sends()).toBe(1);
    // The next syncs do not send it again, however often they run.
    await syncInterviewer(USER, db);
    await syncInterviewer(USER, db);
    expect(sends()).toBe(1);
    await retryHeldDraft(db, id);
    expect(await getDraftRow(db, id)).toMatchObject({ completed: 1, upload_issue: null });
    await syncInterviewer(USER, db);
    expect(sends()).toBe(2);
  });

  it("does not make an ordinary 429 terminal", async () => {
    const db = memoryDb();
    await migrate(db);
    const id = "aaaaaaaa-0000-4000-8000-000000000015";
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(id, { Id10013: "no" }));
    await markCompleted(db, id, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return json(429, { code: "rate_limited" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await syncInterviewer(USER, db);
    expect(await getDraftRow(db, id)).toMatchObject({ completed: 1, upload_issue: null });
  });

  it("sends the exact Unicode answers JSON and accepts a nullable-case direct acknowledgement", async () => {
    const db = memoryDb();
    await migrate(db);
    const unicodeData = { Id10013: "हिन्दी ☕", number: 1 } as SubmissionData;
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft(DRAFT, unicodeData));
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, {
        case: { death_id: null, unique_id: null, status: null }
      }, 200);
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    const onSuperseded = jest.fn();
    await expect(syncInterviewer(USER, db, onSuperseded)).resolves.toEqual({
      sent: 1, failed: 0, remaining: 0, supersededUniqueIds: [],
      definitionRefresh: [{ projectId: PROJECT, available: false, error: "current_definition_unavailable" }],
    });
    expect(onSuperseded).not.toHaveBeenCalled();
    const upload = calls.find((call) => call.url.endsWith("/submissions"))!;
    const exactJson = '{"Id10013":"हिन्दी ☕","number":1}';
    expect(upload.body?.answers_json).toBe(exactJson);
    expect(upload.body?.answers_sha256).toBe(require("node:crypto").createHash("sha256").update(exactJson, "utf8").digest("hex"));
    expect(upload.body?.death_id).toBeUndefined();
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it("refreshes once after an upload 401 and builds a fresh device clock for the retry", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    let uploadAttempts = 0;
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/sessions/refresh")) {
        return json(200, {
          access_token: "fresh-access",
          access_expires_at: "2026-10-01T19:00:00Z",
          refresh_token: "fresh-refresh",
          refresh_expires_at: "2026-10-02T19:00:00Z",
          access: access()
        });
      }
      if (call.url.endsWith("/submissions")) {
        if (uploadAttempts++ === 0) {
          jest.setSystemTime(new Date("2026-10-01T18:31:01Z"));
          return json(401, { code: "token_expired" });
        }
        return submissionSuccess(call);
      }
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T18:31:00Z"));
    recordServerDate(new Date("2026-10-01T18:00:00Z").toUTCString(), Date.parse("2026-10-01T18:00:30Z"));
    try {
      await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1, failed: 0, remaining: 0 });
    } finally {
      jest.useRealTimers();
      resetPhoneClock();
    }

    const uploads = calls.filter((call) => call.url.endsWith("/submissions"));
    expect(uploads).toHaveLength(2);
    expect((uploads[0].body!.draft as { clockOffsetSeconds?: number }).clockOffsetSeconds).toBe(30);
    expect(uploads[0].auth).toBe("Bearer a");
    expect(uploads[1].auth).toBe("Bearer fresh-access");
    const firstBody = uploads[0].body!;
    const retryBody = uploads[1].body!;
    expect(firstBody.answers_json).toBe(retryBody.answers_json);
    expect(firstBody.answers_sha256).toBe(retryBody.answers_sha256);
    const firstDraft = firstBody.draft as { deviceClockAt?: string };
    const retryDraft = retryBody.draft as { deviceClockAt?: string };
    expect(firstDraft.deviceClockAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(retryDraft.deviceClockAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(retryDraft.deviceClockAt).not.toBe(firstDraft.deviceClockAt);
    expect(calls.filter((call) => call.url.endsWith("/sessions/refresh"))).toHaveLength(1);
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it("refreshes once after a revision 401 while keeping its frozen answers and refreshing only deviceClockAt", async () => {
    const db = memoryDb();
    await migrate(db);
    const completedId = "aaaaaaaa-0000-4000-8000-000000000099";
    const completedStore = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await completedStore.save(draft(completedId));
    await markCompleted(db, completedId, { valid: true, issues: [] });
    const revisionDraft = {
      ...draft(DRAFT, { interview_outcome: "completed", Id10013: "yes" }),
      locale: "en",
      translation_version: 3
    };
    const submitted = {
      draft_id: DRAFT, project_id: PROJECT, site_id: SITE, death_id: DEATH,
      unique_id: "U-1", va_sid: "va-sid-1", status: "submitted", updated_at: "2026-10-01T00:00:00Z"
    };
    server((call) => {
      if (call.url.endsWith("/drafts?status=submitted")) return json(200, { drafts: [submitted] });
      if (call.url.endsWith(`/drafts/${DRAFT}`)) return json(200, {
        draft: submitted,
        envelope: revisionDraft,
        prefill: {},
        answers_sha256: "a".repeat(64)
      });
      return json(200, {});
    });
    await beginRevision(USER, db, DRAFT);
    const queued = await queueRevision(db, DRAFT, "interviewer_correction", { valid: true, issues: [] });

    let revisionAttempts = 0;
    const currentProject = project();
    currentProject.form_options = {
      ...currentProject.form_options,
      instrument_version: "current-v2",
      definition_sha256: "b".repeat(64),
      enabled_extensions: [],
    };
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture([currentProject]));
      if (call.url.endsWith("/sessions/refresh")) return json(200, {
        access_token: "fresh-access", access_expires_at: "2026-10-01T19:00:00Z",
        refresh_token: "fresh-refresh", refresh_expires_at: "2026-10-02T19:00:00Z", access: access()
      });
      if (call.url.endsWith("/submissions")) return submissionSuccess(call);
      if (call.url.endsWith("/revisions")) {
        if (revisionAttempts++ === 0) {
          jest.setSystemTime(new Date("2026-10-01T18:31:01Z"));
          return json(401, { code: "token_expired" });
        }
        return json(200, {
          changed: false, va_sid: "va-sid-1", payload_version_id: "payload-1",
          answers_sha256: call.body?.answers_sha256, outcome: "completed", workflow_state: "smartva_pending"
        });
      }
      if (call.url.includes("/instruments/WHO_2022_VA/definition")) return json(503, { code: "unavailable" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T18:31:00Z"));
    try {
      await expect(syncInterviewer(USER, db)).resolves.toMatchObject({
        sent: 2, failed: 0, remaining: 0,
        definitionRefresh: [{ projectId: PROJECT, available: false, error: "unavailable" }],
      });
    } finally {
      jest.useRealTimers();
    }

    const uploads = calls.filter((call) => call.url.endsWith("/revisions"));
    expect(calls.findIndex((call) => call.url.endsWith("/submissions"))).toBeLessThan(
      calls.findIndex((call) => call.url.endsWith("/revisions")),
    );
    expect(calls.findIndex((call) => call.url.endsWith("/revisions"))).toBeLessThan(
      calls.findIndex((call) => call.url.includes("/instruments/WHO_2022_VA/definition")),
    );
    expect(uploads).toHaveLength(2);
    expect(uploads[0].auth).toBe("Bearer a");
    expect(uploads[1].auth).toBe("Bearer fresh-access");
    expect(uploads[0].body?.answers_json).toBe(queued.frozen_json);
    expect(uploads[1].body?.answers_json).toBe(queued.frozen_json);
    expect(uploads[0].body?.answers_sha256).toBe(queued.answers_sha256);
    expect(uploads[1].body?.answers_sha256).toBe(queued.answers_sha256);
    const firstDraft = uploads[0].body?.draft as { deviceClockAt?: string; startedAt?: string };
    const retryDraft = uploads[1].body?.draft as { deviceClockAt?: string; startedAt?: string };
    expect(firstDraft.startedAt).toBeUndefined();
    expect(retryDraft.startedAt).toBeUndefined();
    expect(retryDraft.deviceClockAt).not.toBe(firstDraft.deviceClockAt);
    expect(calls.filter((call) => call.url.endsWith("/sessions/refresh"))).toHaveLength(1);
    expect(await getRevisionRow(db, DRAFT)).toBeNull();
  });

  it("accepts a server-kept upload using the received hash and reports its lock state", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, {
        answers_sha256: "0".repeat(64),
        received_sha256: String(call.body?.answers_sha256).toUpperCase(),
        kept: "server",
        locked: true,
        case: { death_id: DEATH, unique_id: "U-77", status: "registered" }
      });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    const onServerKept = jest.fn();
    await expect(syncInterviewer(USER, db, undefined, undefined, onServerKept)).resolves.toMatchObject({
      sent: 1, failed: 0, remaining: 0, serverKeptUploads: [{ uniqueId: "U-77", locked: true }]
    });
    expect(onServerKept).toHaveBeenCalledWith({ uniqueId: "U-77", locked: true });
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it("holds a completed draft with a partial definition pin for attention before upload", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    const stored = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [DRAFT]);
    await db.runAsync("UPDATE drafts SET envelope = ? WHERE id = ?", [
      JSON.stringify({ ...JSON.parse(stored!.envelope), definitionSha256: "c".repeat(64) }), DRAFT,
    ]);
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(calls.filter((call) => call.url.endsWith("/submissions"))).toHaveLength(0);
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ completed: 1, upload_issue: "invalid_definition_pin" });
    const retained = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [DRAFT]);
    expect(JSON.parse(retained!.envelope)).toMatchObject({ data: { Id10013: "yes" }, definitionSha256: "c".repeat(64) });
  });

  it("recomputes the same answers hash once, then marks repeated hash refusal editable", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    let attempts = 0;
    let submissions = 0;
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) {
        if (submissions++ === 0) {
          jest.setSystemTime(new Date("2026-10-01T18:31:01Z"));
        }
        return json(422, { code: "answers_hash_invalid" });
      }
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).endsWith("/submissions")) attempts += 1;
      return originalFetch(url, init);
    }) as typeof fetch;

    jest.useFakeTimers().setSystemTime(new Date("2026-10-01T18:31:00Z"));
    try {
      await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    } finally {
      jest.useRealTimers();
    }
    const uploads = calls.filter((call) => call.url.endsWith("/submissions"));
    expect(attempts).toBe(2);
    expect(uploads).toHaveLength(2);
    expect(uploads[1].body?.answers_json).toBe(uploads[0].body?.answers_json);
    expect(uploads[1].body?.answers_sha256).toBe(uploads[0].body?.answers_sha256);
    const firstDraft = uploads[0].body?.draft as { startedAt?: string; completedAt?: string; deviceClockAt?: string };
    const retryDraft = uploads[1].body?.draft as { startedAt?: string; completedAt?: string; deviceClockAt?: string };
    expect(firstDraft.startedAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(firstDraft.completedAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(firstDraft.deviceClockAt).toMatch(/^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$/);
    expect(retryDraft.deviceClockAt).not.toBe(firstDraft.deviceClockAt);
    const storedEnvelope = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [DRAFT]);
    expect(JSON.parse(storedEnvelope!.envelope)).not.toHaveProperty("deviceClockAt");
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ completed: 0, upload_issue: "answers_hash_invalid" });

    await store.save(draft(DRAFT, { Id10013: "corrected" } as SubmissionData));
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ completed: 0, upload_issue: null });
  });

  it("keeps a draft when the acknowledgement hash is wrong", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, {
        received_sha256: "0".repeat(64),
        superseded: true,
        case: { death_id: DEATH, unique_id: "U-77", status: "registered" }
      });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    const onSuperseded = jest.fn();
    const onCanCodeNow = jest.fn();
    await expect(syncInterviewer(USER, db, onSuperseded, undefined, undefined, onCanCodeNow)).rejects.toThrow("invalid_answers_ack");
    expect(onSuperseded).not.toHaveBeenCalled();
    expect(onCanCodeNow).not.toHaveBeenCalled();
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
  });

  it("purges a valid upload when its optional coding hint is malformed", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { can_code_now: "true" });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    const onCanCodeNow = jest.fn();
    await expect(syncInterviewer(USER, db, undefined, undefined, undefined, onCanCodeNow))
      .resolves.toMatchObject({ sent: 1, failed: 0, remaining: 0 });
    expect(onCanCodeNow).not.toHaveBeenCalled();
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it("emits the coding hint after a valid incoming acknowledgement", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { can_code_now: true, case: { death_id: DEATH, unique_id: "U-CODE", status: "registered" } });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    const onCanCodeNow = jest.fn();
    await expect(syncInterviewer(USER, db, undefined, undefined, undefined, onCanCodeNow))
      .resolves.toMatchObject({ canCodeNowUniqueIds: ["U-CODE"], remaining: 0 });
    expect(onCanCodeNow).toHaveBeenCalledWith("U-CODE");
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it("keeps an unbound direct draft when the received hash does not match", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, {
        received_sha256: "0".repeat(64),
        case: { death_id: null, unique_id: null, status: null }
      });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).rejects.toThrow("invalid_answers_ack");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
  });

  it.each([
    { kept: "other" },
    { locked: "true" },
  ])("keeps a draft when upload acknowledgement metadata is malformed (%o)", async (metadata) => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, metadata);
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });

    await expect(syncInterviewer(USER, db)).rejects.toThrow("invalid_upload_ack");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
  });

  it("reports a valid superseded acknowledgement before a later request fails", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, {
        superseded: true,
        case: { death_id: DEATH, unique_id: "U-77", status: "registered" }
      });
      if (call.url.endsWith("/outstanding")) throw new TypeError("Network request failed");
      return json(200, { cases: [], next_cursor: null });
    });

    const onSuperseded = jest.fn();
    await expect(syncInterviewer(USER, db, onSuperseded)).rejects.toThrow("Network request failed");
    expect(onSuperseded).toHaveBeenCalledTimes(1);
    expect(onSuperseded).toHaveBeenCalledWith("U-77");
    expect(await getDraftRow(db, DRAFT)).toBeNull();
  });

  it.each([null, "other-death"])("keeps a bound draft when the acknowledged death id is %s", async (deathId) => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, deathId: DEATH } });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { case: { death_id: deathId, unique_id: "U-1", status: "registered" } });
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).rejects.toThrow("invalid_case_ack");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();
  });

  it("retains an edit made while the uploaded snapshot is in flight", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { projectId: PROJECT, siteId: SITE });
    await store.save(draft());
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) {
        void store.save(draft(DRAFT, { Id10013: "edited during upload" } as SubmissionData));
        return submissionSuccess(call);
      }
      if (call.url.endsWith("/outstanding")) return json(204, null);
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1, remaining: 1 });
    expect((await store.load!(DRAFT))?.data).toEqual({ Id10013: "edited during upload" });
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
    expect(targetsFrom(selected, units)).toEqual([{ key: "P2:S2:P1", label: "Site 2 · Unit P1", projectId: "P2", siteId: "S2", orgUnitId: "P1", siteName: "Site 2", unitName: "Unit P1" }]);
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
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { va_sid: "V1" });
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
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { case: undefined });
      return json(200, { cases: [], next_cursor: null });
    });
    await expect(syncInterviewer(USER, db)).rejects.toThrow("invalid_case_ack");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();

    server((call) => {
      if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
      if (call.url.endsWith("/submissions")) return submissionSuccess(call, { case: { death_id: DEATH, unique_id: "U-1", status: "submitted" } });
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

describe("respondent consent and refusals on the phone", () => {
  const NOTICE = "Notice text";
  const configBody = (required = true) => ({
    project_id: PROJECT, consent_required: required, refusal_behaviour: "interview_without_informant_data",
    notice_versions: [{
      notice_version_id: "nnnnnnnn-0000-4000-8000-000000000001", version: 1, language: "en", text: NOTICE,
      text_sha256: computeUtf8Sha256HexSync(NOTICE), purposes: [{ code: "record", label: "Record", required: true }],
      covered_fields: ["informant_name", "Id10007"], allowed_modes: ["spoken"], witness_allowed: false,
    }],
    contacts: {}, retention: { period_days: null, expiry_action: "erase" },
  });
  const envelope = (decision: "granted" | "refused", draftId: string | null): ConsentRecordEnvelope => ({
    client_id: "cccccccc-0000-4000-8000-000000000001", client_draft_id: draftId, notice_version_id: "nnnnnnnn-0000-4000-8000-000000000001",
    notice_language: "en", notice_sha256: computeUtf8Sha256HexSync(NOTICE), decision,
    purposes: [{ code: "record", granted: decision === "granted" }], mode: "spoken", witness_present: false,
    supersedes_client_id: null, recorded_at: "2026-10-23T10:00:00+05:30",
  });
  const record = (decision: "granted" | "refused", draftId: string | null): StoredConsent => ({
    envelope: envelope(decision, draftId), project_id: PROJECT, covered_fields: ["informant_name", "Id10007"], recorded_by: USER,
  });
  const readyServer = (onSubmission: (call: Call) => Response) => server((call) => {
    if (call.url.endsWith("/fixture-reference")) return json(200, referenceFixture());
    if (call.url.endsWith("/submissions")) return onSubmission(call);
    if (call.url.endsWith("/deaths")) return json(201, { case: detail() });
    if (call.url.endsWith("/outstanding")) return json(204, null);
    return json(200, { cases: [], next_cursor: null });
  });
  const complete = async (db: Db, id: string, data: SubmissionData, binding: { clientDeathId?: string; deathId?: string } = {}) => {
    await createDraftStore(db, { projectId: PROJECT, siteId: SITE, binding: { projectId: PROJECT, ...binding } }).save(draft(id, data));
    await markCompleted(db, id, { valid: true, issues: [] });
  };
  const ID = "aaaaaaaa-0000-4000-8000-000000000031";

  it("keeps the project's consent settings for offline use and keeps the old copy when a refresh fails", async () => {
    const db = memoryDb();
    await migrate(db);
    server(() => json(200, configBody()));
    await expect(refreshConsentConfig(USER, db, PROJECT)).resolves.toMatchObject({ consent_required: true });
    server(() => { throw new TypeError("offline"); });
    await expect(refreshConsentConfig(USER, db, PROJECT)).resolves.toBeUndefined();
    expect(await getConsentConfig(db, PROJECT)).toMatchObject({ consent_required: true, notice_versions: [expect.objectContaining({ text: NOTICE })] });
    server(() => json(200, { consent_required: "yes" }));
    await refreshConsentConfig(USER, db, PROJECT);
    expect(await getConsentConfig(db, PROJECT)).toMatchObject({ consent_required: true });
  });

  it("sends the interview's own consent in the submission body and nothing else", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha" });
    await saveDraftConsent(db, ID, record("granted", ID));
    readyServer((call) => submissionSuccess(call));
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1 });
    const body = calls.find(({ url }) => url.endsWith("/submissions"))!.body!;
    expect(body.consent).toEqual(envelope("granted", ID));
    expect(JSON.parse(body.answers_json as string)).toEqual({ Id10013: "yes", Id10007: "Asha" });
    expect(await loadConsents(db)).toEqual(new Map());
  });

  it("under a refusal strips the covered answers from the answers, their hash and the draft sent", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha", Id10019: "female" });
    await saveDraftConsent(db, ID, record("refused", ID));
    readyServer((call) => submissionSuccess(call));
    await syncInterviewer(USER, db);
    const body = calls.find(({ url }) => url.endsWith("/submissions"))!.body!;
    expect(body.consent).toMatchObject({ decision: "refused", client_draft_id: ID });
    expect(JSON.parse(body.answers_json as string)).toEqual({ Id10013: "yes", Id10019: "female" });
    expect(body.answers_sha256).toBe(require("node:crypto").createHash("sha256").update(body.answers_json as string, "utf8").digest("hex"));
    expect((body.draft as { data: object }).data).toEqual({ Id10013: "yes", Id10019: "female" });
  });

  it("under a refusal deletes the files of the covered questions before sending, and keeps the others", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha" });
    const bytes = new Uint8Array([1, 2]);
    const row = (id: string, question: string) => ({ id, draftId: ID, projectId: PROJECT, question, kind: "audio" as const, mimeType: "audio/mp4", ext: "m4a", bytes });
    await saveAttachment(db, row("11111111-1111-4111-8111-111111111111", "Id10007"));
    await saveAttachment(db, row("22222222-2222-4222-8222-222222222222", "Id10013"));
    expect((await draftAttachments(db, ID)).map((f) => f.question).sort()).toEqual(["Id10007", "Id10013"]);
    await saveDraftConsent(db, ID, record("refused", ID));
    readyServer(() => json(409, { error: "closed", code: "case_closed" })); // the draft stays, so its rows can be read
    await syncInterviewer(USER, db);
    const left = (await draftAttachments(db, ID)).map((f) => f.question);
    expect(left).toContain("Id10013");
    expect(left).not.toContain("Id10007");
  });

  it("reuses a registration's consent without sending it again, and honours its refusal", async () => {
    const db = memoryDb();
    await migrate(db);
    const reg = "bbbbbbbb-0000-4000-8000-000000000031";
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha" }, { clientDeathId: reg, deathId: DEATH });
    await db.runAsync("UPDATE drafts SET client_death_id = ?, death_id = ? WHERE id = ?", [reg, DEATH, ID]);
    await saveRegistrationConsent(db, reg, record("granted", null));
    expect(await consentForDraft(db, { id: ID, client_death_id: reg })).toMatchObject({ own: false });
    readyServer((call) => submissionSuccess(call));
    await syncInterviewer(USER, db);
    const body = calls.find(({ url }) => url.endsWith("/submissions"))!.body!;
    expect(body).not.toHaveProperty("consent");
    expect(JSON.parse(body.answers_json as string)).toHaveProperty("Id10007", "Asha");

    const second = "aaaaaaaa-0000-4000-8000-000000000032";
    await complete(db, second, { Id10013: "yes", Id10007: "Asha" }, { clientDeathId: reg, deathId: DEATH });
    await db.runAsync("UPDATE drafts SET client_death_id = ?, death_id = ? WHERE id = ?", [reg, DEATH, second]);
    await saveRegistrationConsent(db, reg, record("refused", null));
    readyServer((call) => submissionSuccess(call));
    await syncInterviewer(USER, db);
    const refusedBody = calls.find(({ url }) => url.endsWith("/submissions"))!.body!;
    expect(refusedBody).not.toHaveProperty("consent");
    expect(JSON.parse(refusedBody.answers_json as string)).not.toHaveProperty("Id10007");
  });

  it("sends a registration's consent with POST /deaths, strips informant fields under a refusal, and hands the decision to the case", async () => {
    const db = memoryDb();
    await migrate(db);
    const reg = "bbbbbbbb-0000-4000-8000-000000000032";
    const fields = { deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29", informant_name: "Asha" };
    await saveRegistration(db, { project_id: PROJECT, client_death_id: reg, site_id: SITE, fields });
    await saveRegistrationConsent(db, reg, record("granted", null));
    readyServer((call) => submissionSuccess(call));
    await syncInterviewer(USER, db);
    const granted = calls.find(({ url }) => url.endsWith("/deaths"))!.body!;
    expect(granted).toMatchObject({ informant_name: "Asha", consent: envelope("granted", null) });
    expect((await loadConsents(db)).has(`consent:death:${DEATH}`)).toBe(true);

    const refusedReg = "bbbbbbbb-0000-4000-8000-000000000033";
    await saveRegistration(db, { project_id: PROJECT, client_death_id: refusedReg, site_id: SITE, fields });
    await saveRegistrationConsent(db, refusedReg, record("refused", null));
    readyServer((call) => submissionSuccess(call));
    await syncInterviewer(USER, db);
    const refused = calls.filter(({ url }) => url.endsWith("/deaths")).map(({ body }) => body!).find((body) => body.client_death_id === refusedReg)!;
    expect(refused).not.toHaveProperty("informant_name");
    expect(refused).toMatchObject({ consent: { decision: "refused", client_draft_id: null } });
  });

  it("stores a 422 refusal with the server's message, fields and Ref, reopens the draft, and shows it in the Sync summary", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes" });
    readyServer(() => json(422, { error: "Record the name, date of death and sex of the deceased before submitting.", code: "invalid_interview", fields: ["Id10017", "Id10018", "Id10019"] }));
    await syncInterviewer(USER, db);
    expect(await getDraftRow(db, ID)).toMatchObject({ completed: 0, upload_issue: null });
    const stored = await sendRefusal(db, ID);
    expect(stored).toMatchObject({
      status: 422, code: "invalid_interview", fields: ["Id10017", "Id10018", "Id10019"],
      message: "Record the name, date of death and sex of the deceased before submitting.",
    });
    expect(stored?.ref).toContain("HTTP 422 invalid_interview POST /api/v1/intake/submissions");
    expect(stored?.at).toMatch(/^\d{4}-/);
    // Reopened, so the Sync sheet lists nothing for it as sendable; the card and the form read the stored refusal.
    expect(await summariseWork(db)).toMatchObject({ unsent: 0 });
  });

  it("drops the interview's consent on a refused consent so the form asks again", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha" });
    await saveDraftConsent(db, ID, record("granted", ID));
    readyServer(() => json(422, { error: "Respondent consent must be recorded.", code: "consent_required", fields: ["consent"] }));
    await syncInterviewer(USER, db);
    expect(await getDraftRow(db, ID)).toMatchObject({ completed: 0 });
    expect(await consentForDraft(db, { id: ID })).toBeUndefined();
    expect(await sendRefusal(db, ID)).toMatchObject({ code: "consent_required", message: "Respondent consent must be recorded." });
  });

  it("keeps the registration's decision on a refused inherited consent and tells only this draft to ask again", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes", Id10007: "Asha" }, { deathId: DEATH });
    await setMeta(db, `consent:death:${DEATH}`, record("granted", null));
    readyServer((call) => !call.url.endsWith("/submissions") ? json(404, { error: "x", code: "not_found" }) : json(422, { error: "Respondent consent must be recorded.", code: "consent_required", fields: ["consent"] }));
    // The reopened draft then goes through the in-progress draft sync, which this fake server does not answer.
    await syncInterviewer(USER, db).catch(() => undefined);
    expect((await loadConsents(db)).has(`consent:death:${DEATH}`)).toBe(true); // shared: not deleted
    expect(await inheritedConsentRefused(db, ID)).toBe(true);
    expect(await getDraftRow(db, ID)).toMatchObject({ completed: 0 });
    // Its own new decision clears the flag.
    await saveDraftConsent(db, ID, record("granted", ID));
    expect(await inheritedConsentRefused(db, ID)).toBe(false);
  });

  it("holds an interview refused with 409, shows why, stops retrying, keeps the answers, and sends again only when asked", async () => {
    const db = memoryDb();
    await migrate(db);
    await complete(db, ID, { Id10013: "yes" });
    let status = 409;
    readyServer((call) => status === 409 ? json(409, { error: "This case is closed.", code: "conflict" }) : submissionSuccess(call));
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 0, failed: 1, remaining: 1 });
    expect(await getDraftRow(db, ID)).toMatchObject({ completed: 1, upload_issue: "case_conflict" });
    expect(await sendRefusal(db, ID)).toMatchObject({ status: 409, message: "This case is closed." });
    const sends = () => calls.filter(({ url }) => url.endsWith("/submissions")).length;
    expect(sends()).toBe(1);
    await syncInterviewer(USER, db);
    await syncInterviewer(USER, db);
    expect(sends()).toBe(1);
    expect(await summariseWork(db)).toMatchObject({ unsent: 0, attention: 1, items: [expect.objectContaining({ state: "attention", reason: "This case is closed." })] });
    status = 201;
    await retryHeldDraft(db, ID);
    await expect(syncInterviewer(USER, db)).resolves.toMatchObject({ sent: 1 });
    expect(await getDraftRow(db, ID)).toBeNull();
    expect(await sendRefusal(db, ID)).toBeUndefined();
  });

  it("files each refusal in the error log as a Ref line only", async () => {
    const db = memoryDb();
    await migrate(db);
    resetErrorLog();
    await complete(db, ID, { Id10013: "yes" });
    readyServer(() => json(409, { error: "A questionnaire has already been submitted for this death.", code: "conflict" }));
    await syncInterviewer(USER, db);
    const logged = pendingErrors().map((entry) => entry.what).join("\n");
    expect(logged).toContain("send HTTP 409 conflict POST /api/v1/intake/submissions");
    expect(logged).not.toContain("questionnaire");
  });
});
