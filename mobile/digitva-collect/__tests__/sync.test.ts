/**
 * Upload gating and payload, the outstanding report, and the device API's
 * reference data (units, translations) against a mocked server and a real
 * SQLite engine (node:sqlite).
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

import { createDraftStore, getDraftRow, getMeta, markCompleted, migrate, type Db } from "../src/drafts";
import { refreshBootstrap, syncInterviewer, targetsFrom, translationsFor, type Units } from "../src/sync";

const SERVER = "http://10.0.2.2:8051";
const USER = "11111111-1111-4111-8111-111111111111";
const ids = {
  valid: "aaaaaaaa-0000-4000-8000-000000000001",
  partial: "aaaaaaaa-0000-4000-8000-000000000002",
  invalid: "aaaaaaaa-0000-4000-8000-000000000003",
  open: "aaaaaaaa-0000-4000-8000-000000000004"
};

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

const envelope = (id: string, data: Record<string, unknown>): WhoVaDraft => ({
  schemaVersion: 1,
  formVersion: "f1",
  id,
  instrumentId: "who-va-2022",
  instrumentVersion: "1",
  currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z",
  updatedAt: `2026-09-30T0${Object.values(ids).indexOf(id)}:00:00Z`,
  data: data as WhoVaDraft["data"]
});

const json = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }) as Response;

type Call = { url: string; body?: unknown };
let calls: Call[];
function mockServer(handler: (call: Call) => Response) {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(url), body: init?.body ? JSON.parse(init.body as string) : undefined };
    calls.push(call);
    return handler(call);
  }) as typeof fetch;
}

const issue = [{ question: "Id10120", code: "required" as const, message: "Required" }];

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

describe("syncInterviewer", () => {
  it("uploads only what the server accepts, with the form's verdict, and reports the rest by draft id", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { siteId: "S1", orgUnitId: "u1" });
    await store.save(envelope(ids.valid, { Id10013: "yes" }));
    await store.save(envelope(ids.partial, { Id10013: "yes", interview_outcome: "partially_completed" }));
    await store.save(envelope(ids.invalid, { Id10013: "yes" }));
    await store.save(envelope(ids.open, {}));
    await markCompleted(db, ids.valid, { valid: true, issues: [] });
    await markCompleted(db, ids.partial, { valid: false, issues: issue });
    await markCompleted(db, ids.invalid, { valid: false, issues: issue });

    mockServer((call) => (call.url.endsWith("/submissions") ? json(201, { va_sid: "x" }) : json(204, null)));
    const result = await syncInterviewer(USER, db);

    const uploads = calls.filter((c) => c.url.endsWith("/submissions")).map((c) => c.body as Record<string, unknown>);
    expect(uploads.map((u) => u.client_draft_id)).toEqual([ids.valid, ids.partial]);
    expect(uploads[0]).toMatchObject({ site_id: "S1", org_unit_id: "u1", completion: { valid: true, issues: [] } });
    expect(uploads[1]).toMatchObject({ completion: { valid: false, issues: issue } });
    expect(result).toEqual({ sent: 2, failed: 0, remaining: 2 });
    const report = calls.find((c) => c.url.endsWith("/outstanding"))!.body;
    expect(report).toEqual({ count: 2, unique_ids: [], client_draft_ids: [ids.invalid, ids.open] });
  });

  it("keeps a draft the server refuses and moves on", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { siteId: "S1" });
    await store.save(envelope(ids.valid, {}));
    await markCompleted(db, ids.valid, { valid: true, issues: [] });
    mockServer((call) => (call.url.endsWith("/submissions") ? json(409, { code: "conflict" }) : json(204, null)));
    expect(await syncInterviewer(USER, db)).toEqual({ sent: 0, failed: 1, remaining: 1 });
    expect((await getDraftRow(db, ids.valid))?.completed).toBe(1);
  });

  it("reopens a draft the server refuses as invalid (422) so it can be corrected, answers kept", async () => {
    const db = memoryDb();
    await migrate(db);
    const store = createDraftStore(db, { siteId: "S1" });
    await store.save(envelope(ids.valid, { Id10013: "no" }));
    await markCompleted(db, ids.valid, { valid: true, issues: [] });
    mockServer((call) => (call.url.endsWith("/submissions") ? json(422, { code: "invalid_interview" }) : json(204, null)));
    expect(await syncInterviewer(USER, db)).toEqual({ sent: 0, failed: 1, remaining: 1 });
    expect((await getDraftRow(db, ids.valid))?.completed).toBe(0);
    expect((await store.load!(ids.valid))?.data).toEqual({ Id10013: "no" });
    expect(calls.filter((c) => c.url.endsWith("/submissions"))).toHaveLength(1);
    await syncInterviewer(USER, db); // not resent while being corrected
    expect(calls.filter((c) => c.url.endsWith("/submissions"))).toHaveLength(1);
  });
});

describe("reference data", () => {
  it("fetches bootstrap and units from the device API and caches both", async () => {
    const db = memoryDb();
    await migrate(db);
    const units: Units = { scoped: true, levels: [], units: [] };
    mockServer((call) =>
      call.url.endsWith("/api/v1/device/units") ? json(200, units) : json(200, { context: [{ project_id: "P", site_id: "S1" }] })
    );
    const fresh = await refreshBootstrap(USER, db);
    expect(calls.map((c) => c.url)).toEqual([`${SERVER}/api/v1/device/bootstrap`, `${SERVER}/api/v1/device/units`]);
    expect(fresh.units).toEqual(units);
    expect(await getMeta(db, "units")).toEqual(units);

    mockServer((call) => (call.url.endsWith("/units") ? json(403, { code: "forbidden" }) : json(200, { context: [] })));
    expect((await refreshBootstrap(USER, db)).units).toBeUndefined();
    expect(await getMeta(db, "units")).toBeNull();
  });

  it("fetches translations from the device API and caches them per version", async () => {
    const db = memoryDb();
    await migrate(db);
    mockServer(() => json(200, { questions: { Id10007: { label: "नाम" } } }));
    expect(await translationsFor(USER, db, "WHO_2022_VA", "en", 0)).toBeNull();
    expect(calls).toHaveLength(0);
    const first = await translationsFor(USER, db, "WHO_2022_VA", "hi", 3);
    expect(first?.questions?.Id10007?.label).toBe("नाम");
    expect(calls.map((c) => c.url)).toEqual([`${SERVER}/api/v1/device/instruments/WHO_2022_VA/translations/hi`]);
    await translationsFor(USER, db, "WHO_2022_VA", "hi", 3);
    expect(calls).toHaveLength(1);
    await translationsFor(USER, db, "WHO_2022_VA", "hi", 4); // the locale was edited
    expect(calls).toHaveLength(2);
  });

  it("builds picker choices from the units the interviewer may pick", () => {
    const bootstrap = { context: [{ project_id: "P", site_id: "S1", site_name: "Site 1" }] };
    const unit = (id: string, selectable: boolean) => ({
      org_unit_id: id, unit_code: id, unit_name: `Unit ${id}`, level_code: "phc", path: id, selectable
    });
    expect(targetsFrom(bootstrap, undefined)).toEqual([]);
    expect(targetsFrom(bootstrap, { scoped: false, levels: [], units: [] })).toEqual([
      { key: "S1", label: "Site 1", siteId: "S1" }
    ]);
    const tree = { scoped: true, levels: [{ level_code: "phc", level_name: "PHC", depth: 1 }], units: [unit("D1", false), unit("P1", true)] };
    expect(targetsFrom(bootstrap, tree)).toEqual([
      { key: "S1:P1", label: "Site 1 · Unit P1", siteId: "S1", orgUnitId: "P1" }
    ]);
    expect(targetsFrom(bootstrap, { ...tree, units: [] })).toEqual([]);
  });
});
