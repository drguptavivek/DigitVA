/**
 * Offline cases (phase 3): the sync queue's order and idempotent resends,
 * refusals reopening items for editing, the case download's pruning, the
 * draft's case binding and prefill, and the register form's rules. Against a
 * mocked server and a real SQLite engine (node:sqlite).
 */
import { DatabaseSync } from "node:sqlite";

import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key))
}));
jest.mock("../src/interviewerDb", () => ({ deleteInterviewerDb: jest.fn(async () => undefined) }));

import {
  getCase,
  getRegistration,
  listActions,
  listCases,
  listRegistrations,
  normalisePhone,
  prefillFromRegistration,
  queueAction,
  replaceCases,
  resolveDraftHost,
  saveRegistration,
  validateRegistration,
  visitAt,
  type CaseRow,
  type RegistrationFields
} from "../src/cases";
import { createDraftStore, getDraftRow, markCompleted, migrate, type Db } from "../src/drafts";
import { refreshCases, registersDeaths, syncInterviewer } from "../src/sync";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const REG = "bbbbbbbb-0000-4000-8000-000000000001";
const ATTEMPT = "cccccccc-0000-4000-8000-000000000001";
const DRAFT = "aaaaaaaa-0000-4000-8000-000000000001";
const DIRECT = "aaaaaaaa-0000-4000-8000-000000000002";
const DEATH = "dddddddd-0000-4000-8000-000000000001";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) =>
      (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close()
  };
}

const envelope = (id: string, data: Record<string, unknown> = { Id10013: "yes" }): WhoVaDraft => ({
  schemaVersion: 1,
  formVersion: "f1",
  id,
  instrumentId: "who-va-2022",
  instrumentVersion: "1",
  currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z",
  updatedAt: "2026-09-30T01:00:00Z",
  data: data as WhoVaDraft["data"]
});

const caseRow = (deathId: string, extra: Partial<CaseRow> = {}): CaseRow => ({
  death_id: deathId,
  unique_id: `U-${deathId.slice(0, 4)}`,
  site_id: "S1",
  org_unit_id: "u1",
  unit_name: "PHC",
  state: "registered",
  deceased_name: "Ram Lal",
  deceased_sex: "male",
  age_years: 58,
  date_of_death: "2026-09-28",
  next_visit_at: null,
  last_contact_at: null,
  informant_phone_masked: "******3210",
  informant_phone_2_masked: null,
  prefill: { deceased: { givenNames: "Ram", surname: "Lal" }, answers: { Id10007: "Sita" }, lockedQuestionNames: ["Id10010c"] },
  ...extra
});

const fields: RegistrationFields = {
  deceased_name: "Ram Lal Verma",
  deceased_sex: "male",
  date_of_death: "2026-09-28",
  age_years: "58",
  informant_name: "Sita",
  informant_phone: "+91 98765-43210"
};

const json = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }) as Response;

type Call = { url: string; body?: Record<string, unknown> };
let calls: Call[];
function mockServer(handler: (call: Call) => Response) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(url), body: init?.body ? JSON.parse(init.body as string) : undefined };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}

/** A server that accepts everything; `listed` is what /cases returns. */
const accepting = (listed: CaseRow[] = []) => (call: Call) => {
  if (call.url.endsWith("/deaths")) return json(201, { case: caseRow(DEATH) });
  if (call.url.includes("/cases?")) return json(200, { cases: listed, next_cursor: null });
  if (call.url.endsWith("/attempts")) return json(201, { case: { death_id: DEATH } });
  if (call.url.endsWith("/visit")) return json(200, { case: { death_id: DEATH } });
  if (call.url.endsWith("/submissions")) return json(201, { va_sid: "x" });
  return json(204, null);
};

const path = (call: Call) => call.url.slice(SERVER.length).split("?")[0];

async function freshDb(): Promise<Db> {
  const db = memoryDb();
  await migrate(db);
  await migrate(db); // idempotent with the phase-3 tables
  return db;
}

/** A death registered offline, an attempt logged on it, its interview finished, and an unrelated direct interview. */
async function offlineVisit(db: Db) {
  await saveRegistration(db, { client_death_id: REG, site_id: "S1", org_unit_id: "u1", fields });
  await queueAction(db, { client_id: ATTEMPT, kind: "attempt", client_death_id: REG, body: { outcome: "reached" } });
  const host = await resolveDraftHost(db, DRAFT, { clientDeathId: REG });
  if (!host || host === "completed") throw new Error("no host");
  await createDraftStore(db, host).save(envelope(DRAFT));
  await markCompleted(db, DRAFT, { valid: true, issues: [] });
  await createDraftStore(db, { siteId: "S1" }).save(envelope(DIRECT));
  await markCompleted(db, DIRECT, { valid: true, issues: [] });
}

beforeEach(() => {
  mockSecure.clear();
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P", project_name: "P" }));
  mockSecure.set("device_secret", "s");
  mockSecure.set("accounts", JSON.stringify([{ user_id: USER, name: "A" }]));
  mockSecure.set(
    `tokens.${USER}`,
    JSON.stringify({ access_token: "a", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" })
  );
});

describe("sync queue", () => {
  it("sends registrations, then attempts, then interviews, then the report and the case download, and purges each", async () => {
    const db = await freshDb();
    await offlineVisit(db);
    mockServer(accepting([caseRow(DEATH)]));

    expect(await syncInterviewer(USER, db)).toEqual({ sent: 4, failed: 0, remaining: 0 });

    expect(calls.map(path)).toEqual([
      "/api/v1/device/deaths",
      `/api/v1/device/cases/${DEATH}/attempts`,
      "/api/v1/device/submissions",
      "/api/v1/device/submissions",
      "/api/v1/device/outstanding",
      "/api/v1/device/cases"
    ]);
    expect(calls[0].body).toMatchObject({ client_death_id: REG, site_id: "S1", org_unit_id: "u1", ...fields });
    expect(calls[1].body).toEqual({ client_attempt_id: ATTEMPT, outcome: "reached" });
    const uploads = calls.filter((c) => path(c).endsWith("/submissions")).map((c) => c.body!);
    expect(uploads.find((u) => u.client_draft_id === DRAFT)).toMatchObject({ death_id: DEATH });
    expect(uploads.find((u) => u.client_draft_id === DIRECT)).not.toHaveProperty("death_id");
    expect(await listRegistrations(db)).toEqual([]);
    expect(await listActions(db)).toEqual([]);
    expect(await getDraftRow(db, DRAFT)).toBeNull();
    expect((await listCases(db)).map((c) => c.death_id)).toEqual([DEATH]);
  });

  it("resends with the same client ids after a lost response, so the server can answer with the first result", async () => {
    const db = await freshDb();
    await offlineVisit(db);
    mockServer((call) => {
      if (path(call).endsWith("/deaths")) throw new TypeError("Network request failed");
      return accepting()(call);
    });
    await expect(syncInterviewer(USER, db)).rejects.toThrow(TypeError);
    // Nothing sent past the registration and nothing purged.
    expect(calls.map(path)).toEqual(["/api/v1/device/deaths"]);
    expect((await getRegistration(db, REG))?.state).toBe("pending");
    expect(await getDraftRow(db, DRAFT)).not.toBeNull();

    mockServer((call) => (path(call).endsWith("/deaths") ? json(200, { case: caseRow(DEATH) }) : accepting()(call)));
    await syncInterviewer(USER, db);
    expect(calls[0].body?.client_death_id).toBe(REG);
    expect(calls[1].body?.client_attempt_id).toBe(ATTEMPT);
    expect(await listRegistrations(db)).toEqual([]);

    // An attempt whose acknowledgement was lost is resent with its id.
    await queueAction(db, { client_id: ATTEMPT, kind: "attempt", death_id: DEATH, body: { outcome: "no_answer" } });
    mockServer((call) => (path(call).endsWith("/attempts") ? json(200, { case: {} }) : accepting()(call)));
    await syncInterviewer(USER, db);
    expect(calls[0].body).toEqual({ client_attempt_id: ATTEMPT, outcome: "no_answer" });
    expect(await listActions(db)).toEqual([]);
  });

  it("reopens a refused registration for editing, holds what depends on it, and reports it outstanding", async () => {
    const db = await freshDb();
    await offlineVisit(db);
    mockServer((call) =>
      path(call).endsWith("/deaths") ? json(422, { code: "invalid_registration" }) : accepting()(call)
    );
    expect(await syncInterviewer(USER, db)).toEqual({ sent: 1, failed: 1, remaining: 1 });
    expect((await getRegistration(db, REG))?.state).toBe("needs_edit");
    expect(calls.some((c) => path(c).endsWith("/attempts"))).toBe(false);
    expect(calls.filter((c) => path(c).endsWith("/submissions")).map((c) => c.body!.client_draft_id)).toEqual([DIRECT]);
    const report = calls.find((c) => path(c).endsWith("/outstanding"))!.body;
    expect(report).toEqual({ count: 1, unique_ids: [], client_draft_ids: [DRAFT], client_death_ids: [REG] });

    // Not resent while it waits for the interviewer; an edit makes it pending again.
    mockServer(accepting());
    await syncInterviewer(USER, db);
    expect(calls.some((c) => path(c).endsWith("/deaths"))).toBe(false);
    await saveRegistration(db, { client_death_id: REG, site_id: "S1", fields: { ...fields, informant_phone: "9876543210" } });
    expect((await getRegistration(db, REG))?.state).toBe("pending");
  });

  it("marks an attempt the server refuses or can no longer apply as needing an edit", async () => {
    const db = await freshDb();
    await queueAction(db, { client_id: ATTEMPT, kind: "attempt", death_id: DEATH, body: { outcome: "moved" } });
    await queueAction(db, { client_id: REG, kind: "visit", death_id: DEATH, body: { next_visit_at: "2026-10-02T03:30:00.000Z" } });
    mockServer((call) => {
      if (path(call).endsWith("/attempts")) return json(409, { code: "conflict" });
      if (path(call).endsWith("/visit")) return json(422, { code: "invalid_visit" });
      return accepting()(call);
    });
    expect(await syncInterviewer(USER, db)).toEqual({ sent: 0, failed: 2, remaining: 0 });
    expect(calls.find((c) => path(c).endsWith("/visit"))!.body).toEqual({ next_visit_at: "2026-10-02T03:30:00.000Z" });
    expect((await listActions(db)).map((a) => a.state)).toEqual(["needs_edit", "needs_edit"]);
  });

  it("reports the case ids of interviews on downloaded cases", async () => {
    const db = await freshDb();
    await replaceCases(db, [caseRow(DEATH)]);
    const host = await resolveDraftHost(db, DRAFT, { deathId: DEATH });
    if (!host || host === "completed") throw new Error("no host");
    await createDraftStore(db, host).save(envelope(DRAFT));
    mockServer(accepting([caseRow(DEATH)]));
    await syncInterviewer(USER, db);
    expect(calls.find((c) => path(c).endsWith("/outstanding"))!.body).toMatchObject({
      count: 1,
      unique_ids: ["U-dddd"],
      client_draft_ids: [DRAFT]
    });
  });
});

describe("case download", () => {
  it("reads every page and drops cases the server no longer lists, keeping drafts bound to them", async () => {
    const db = await freshDb();
    const second = "dddddddd-0000-4000-8000-000000000002";
    mockServer((call) =>
      call.url.includes("cursor=")
        ? json(200, { cases: [caseRow(second)], next_cursor: null })
        : json(200, { cases: [caseRow(DEATH)], next_cursor: "c 1" })
    );
    await refreshCases(USER, db);
    expect(calls.map((c) => c.url)).toEqual([
      `${SERVER}/api/v1/device/cases?limit=200`,
      `${SERVER}/api/v1/device/cases?limit=200&cursor=c%201`
    ]);
    expect((await listCases(db)).map((c) => c.death_id)).toEqual([DEATH, second]);

    const host = await resolveDraftHost(db, DRAFT, { deathId: DEATH });
    if (!host || host === "completed") throw new Error("no host");
    await createDraftStore(db, host).save(envelope(DRAFT));

    mockServer(() => json(200, { cases: [caseRow(second)], next_cursor: null }));
    await refreshCases(USER, db);
    expect((await listCases(db)).map((c) => c.death_id)).toEqual([second]);
    expect(await getCase(db, DEATH)).toBeUndefined();
    // The draft still knows its case and prefill.
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ death_id: DEATH, unique_id: "U-dddd" });
    expect(await resolveDraftHost(db, DRAFT, {})).toMatchObject({ siteId: "S1", prefill: caseRow(DEATH).prefill });

    mockServer(() => json(200, { cases: [], next_cursor: null }));
    await refreshCases(USER, db);
    expect(await listCases(db)).toEqual([]);
  });

  it("keeps the stored cases when a page fails", async () => {
    const db = await freshDb();
    await replaceCases(db, [caseRow(DEATH)]);
    mockServer((call) =>
      call.url.includes("cursor=") ? json(500, {}) : json(200, { cases: [], next_cursor: "c1" })
    );
    await expect(refreshCases(USER, db)).rejects.toThrow();
    expect((await listCases(db)).map((c) => c.death_id)).toEqual([DEATH]);
  });
});

describe("draft binding", () => {
  it("binds a draft started on a case on its first save, from that case's prefill, and never rebinds it", async () => {
    const db = await freshDb();
    await replaceCases(db, [caseRow(DEATH)]);
    const host = await resolveDraftHost(db, DRAFT, { deathId: DEATH });
    expect(host).toEqual({
      siteId: "S1",
      orgUnitId: "u1",
      binding: { deathId: DEATH, uniqueId: "U-dddd", prefill: caseRow(DEATH).prefill },
      prefill: caseRow(DEATH).prefill
    });
    if (!host || host === "completed") throw new Error("no host");
    await createDraftStore(db, host).save(envelope(DRAFT));
    await createDraftStore(db, { siteId: "S2", binding: { deathId: "other" } }).save(envelope(DRAFT, { Id10007: "x" }));
    expect(await getDraftRow(db, DRAFT)).toMatchObject({ site_id: "S1", death_id: DEATH, client_death_id: null });
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    expect(await resolveDraftHost(db, DRAFT, {})).toBe("completed");
    expect(await resolveDraftHost(db, "missing", { deathId: "gone" })).toBeUndefined();
  });

  it("binds a draft on an offline registration by its client id and prefills it from the registration", async () => {
    const db = await freshDb();
    await saveRegistration(db, { client_death_id: REG, site_id: "S1", org_unit_id: "u1", fields });
    const host = await resolveDraftHost(db, DRAFT, { clientDeathId: REG });
    expect(host).toMatchObject({ siteId: "S1", orgUnitId: "u1", binding: { clientDeathId: REG } });
    expect(prefillFromRegistration(fields)).toEqual({
      deceased: { givenNames: "Ram", surname: "Lal Verma", sex: "male", dateOfDeath: "2026-09-28", ageInYears: 58 },
      answers: { Id10007: "Sita" },
      lockedQuestionNames: []
    });
    expect(prefillFromRegistration({ ...fields, deceased_name: "Asha", deceased_sex: "unknown", age_years: "5" }).deceased).toEqual({
      givenNames: "Asha",
      sex: "undetermined",
      dateOfDeath: "2026-09-28"
    });
  });
});

describe("register form rules", () => {
  const today = "2026-09-30";

  it("accepts a complete registration", () => {
    expect(validateRegistration(fields, today)).toEqual({});
    expect(
      validateRegistration({ ...fields, date_of_birth: "1968-01-31", abha_number: "12-3456-7890-1234", abha_address: "ram.lal@abdm" }, today)
    ).toEqual({});
  });

  it("flags each rule the server enforces", () => {
    expect(validateRegistration({ deceased_name: " ", deceased_sex: "", date_of_death: "" }, today)).toEqual({
      deceased_name: "errRequired",
      deceased_sex: "errRequired",
      date_of_death: "errRequired"
    });
    expect(validateRegistration({ ...fields, date_of_death: "2026-10-01" }, today)).toEqual({ date_of_death: "errFutureDate" });
    expect(validateRegistration({ ...fields, date_of_death: "2026-02-30" }, today)).toEqual({ date_of_death: "errDate" });
    expect(validateRegistration({ ...fields, date_of_birth: "2026-09-29" }, today)).toEqual({ date_of_birth: "errBirthAfterDeath" });
    expect(validateRegistration({ ...fields, age_years: "131" }, today)).toEqual({ age_years: "errAge" });
    expect(validateRegistration({ ...fields, age_years: "4.5" }, today)).toEqual({ age_years: "errAge" });
    expect(validateRegistration({ ...fields, abha_number: "123" }, today)).toEqual({ abha_number: "errAbhaNumber" });
    expect(validateRegistration({ ...fields, abha_address: "x@gmail" }, today)).toEqual({ abha_address: "errAbhaAddress" });
    expect(validateRegistration({ ...fields, informant_phone: "12345", informant_phone_2: "5876543210" }, today)).toEqual({
      informant_phone: "errPhone",
      informant_phone_2: "errPhone"
    });
  });

  it("normalises phones as the server does", () => {
    expect(normalisePhone("+91 98765-43210")).toBe("9876543210");
    expect(normalisePhone("09876543210")).toBe("9876543210");
    expect(normalisePhone("9876543210")).toBe("9876543210");
    expect(normalisePhone("5876543210")).toBeNull();
    expect(normalisePhone("98765432101")).toBeNull();
  });

  it("turns a picked visit date into a date-time with a time zone", () => {
    expect(visitAt("2026-10-02")).toBe(new Date("2026-10-02T09:00:00").toISOString());
    expect(visitAt("2026-13-02")).toBeNull();
    expect(visitAt("tomorrow")).toBeNull();
  });
});

describe("project mode", () => {
  it("offers registration only at sites whose project takes death registrations", () => {
    const bootstrap = {
      context: [
        { project_id: "P", site_id: "S1", web_intake_mode: "direct" },
        { project_id: "P", site_id: "S2", web_intake_mode: "both" }
      ]
    };
    expect(registersDeaths(bootstrap)).toBe(true);
    expect(registersDeaths(bootstrap, "S1")).toBe(false);
    expect(registersDeaths(bootstrap, "S2")).toBe(true);
    expect(registersDeaths(undefined)).toBe(false);
  });
});
