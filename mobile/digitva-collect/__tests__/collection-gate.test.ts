import { evaluateGate, gatesFromAccess, projectToday, type GateEntry } from "../src/collectionGate";
import type { AccessSummary } from "../src/api";
import { checkCollectionGate, rememberCollectionGate } from "../src/collectionGate";
import { resetNetwork, startNetworkWatch } from "../src/network";
import { DatabaseSync } from "node:sqlite";
import type { Db } from "../src/drafts";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

const entry = (over: Partial<GateEntry> = {}): GateEntry => ({
  site_id: "S1", enabled: true, start_date: null, end_date: null,
  daily_interviewer_limit: null, today_count: 0, display_name: "Site 1", ...over,
});

describe("evaluateGate", () => {
  it("allows with no gate (older server) and an open default gate", () => {
    expect(evaluateGate(undefined, "2026-11-06", 99)).toEqual({ open: true });
    expect(evaluateGate(entry(), "2026-11-06", 99)).toEqual({ open: true });
  });

  it("refuses when switched off", () => {
    expect(evaluateGate(entry({ enabled: false }), "2026-11-06", 0)).toMatchObject({ open: false, reason: "collection_paused", date: null, displayName: "Site 1" });
  });

  it("treats start and end dates as inclusive", () => {
    const window = entry({ start_date: "2026-11-06", end_date: "2026-11-30" });
    expect(evaluateGate(window, "2026-11-05", 0)).toMatchObject({ open: false, reason: "collection_not_started", date: "2026-11-06" });
    expect(evaluateGate(window, "2026-11-06", 0).open).toBe(true);
    expect(evaluateGate(window, "2026-11-30", 0).open).toBe(true);
    expect(evaluateGate(window, "2026-12-01", 0)).toMatchObject({ open: false, reason: "collection_ended", date: "2026-11-30" });
  });

  it("adds local starts to the server count", () => {
    const limited = entry({ daily_interviewer_limit: 3, today_count: 2 });
    expect(evaluateGate(limited, "2026-11-06", 0).open).toBe(true);
    expect(evaluateGate(limited, "2026-11-06", 1)).toMatchObject({ open: false, reason: "collection_daily_limit", limit: 3 });
  });

  it("ignores the answer's today_count on a later project day", () => {
    const atLimit = entry({ daily_interviewer_limit: 2, today_count: 2 });
    expect(evaluateGate(atLimit, "2026-11-06", 0, "2026-11-06")).toMatchObject({ open: false, reason: "collection_daily_limit" });
    expect(evaluateGate(atLimit, "2026-11-07", 0, "2026-11-06").open).toBe(true);
    expect(evaluateGate(atLimit, "2026-11-07", 2, "2026-11-06")).toMatchObject({ open: false, reason: "collection_daily_limit" });
  });
});

describe("gatesFromAccess", () => {
  const access = (project: Record<string, unknown>) => ({ projects: [{ project_id: "P1", ...project }] }) as unknown as AccessSummary;
  it("skips a project with no or a malformed gate, so it is allowed", () => {
    expect(gatesFromAccess(access({}))).toEqual([]);
    expect(gatesFromAccess(access({ project_today: "2026-11-06", server_time: "2026-11-06T09:00:00Z",
      collection_gate: { sites: [{ site_id: "S1", enabled: "yes" }], units: [] } }))).toEqual([]);
  });
  it("keeps a well-formed gate", () => {
    const [gate] = gatesFromAccess(access({ timezone: "Asia/Kolkata", project_today: "2026-11-06", server_time: "2026-11-06T09:00:00Z",
      collection_gate: { sites: [{ ...entry(), reason: null, open: true }], units: [] } }));
    expect(gate.sites).toEqual([entry()]);
  });
});

describe("projectToday", () => {
  it("follows the project timezone and never goes behind the answer's day", () => {
    expect(projectToday({ timezone: "Asia/Kolkata", project_today: "2026-11-06" }, new Date("2026-11-06T20:00:00Z"))).toBe("2026-11-07");
    expect(projectToday({ timezone: "Asia/Kolkata", project_today: "2026-11-06" }, new Date("2026-11-01T00:00:00Z"))).toBe("2026-11-06");
    expect(projectToday({ project_today: "2026-11-06" }, new Date("2026-11-09T00:00:00Z"))).toBe("2026-11-06");
  });
});

describe("checkCollectionGate applies the gate only online with a fresh answer", () => {
  const answerAt = (day: string, serverTime: string, gate: Partial<GateEntry>, timezone?: string) => ({ projects: [{
    project_id: "P1", project_today: day, server_time: serverTime, ...(timezone ? { timezone } : {}),
    collection_gate: { sites: [{ ...entry(gate), reason: null, open: true }], units: [] },
  }] }) as unknown as AccessSummary;
  const answer = (gate: Partial<GateEntry>) => answerAt("2026-11-06", "2026-11-06T09:00:00Z", gate);
  const setup = async (gate: Partial<GateEntry>) => {
    const sqlite = new DatabaseSync(":memory:");
    sqlite.exec("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)");
    const db = {
      runAsync: async (sql: string, params: never[]) => sqlite.prepare(sql).run(...params),
      getFirstAsync: async (sql: string, params: never[]) => sqlite.prepare(sql).get(...params) ?? null,
    } as unknown as Db;
    await rememberCollectionGate(db, answer(gate));
    return db;
  };
  const NOW = new Date("2026-11-06T10:00:00Z");
  beforeEach(() => { jest.useFakeTimers().setSystemTime(NOW); resetNetwork(); });
  afterEach(() => { jest.useRealTimers(); resetNetwork(); });

  it("refuses when online and fresh and closed", async () => {
    const db = await setup({ enabled: false });
    jest.setSystemTime(NOW.getTime() + 14 * 60 * 1000);
    expect(await checkCollectionGate(db, "P1", "S1")).toMatchObject({ open: false, reason: "collection_paused" });
  });
  it("allows when online and fresh and open", async () => {
    expect((await checkCollectionGate(await setup({}), "P1", "S1")).open).toBe(true);
  });
  it("applies the daily limit when fresh", async () => {
    expect(await checkCollectionGate(await setup({ daily_interviewer_limit: 1, today_count: 1 }), "P1", "S1")).toMatchObject({ open: false, reason: "collection_daily_limit", limit: 1 });
  });
  it("does not refuse at the limit once the project day has rolled over", async () => {
    const db = await setup({});
    const gate = { daily_interviewer_limit: 1, today_count: 1 };
    jest.setSystemTime(new Date("2026-11-06T23:55:00Z"));
    await rememberCollectionGate(db, answerAt("2026-11-06", "2026-11-06T23:55:00Z", gate, "UTC"));
    expect(await checkCollectionGate(db, "P1", "S1")).toMatchObject({ open: false, reason: "collection_daily_limit" });
    jest.setSystemTime(new Date("2026-11-07T00:05:00Z"));
    expect((await checkCollectionGate(db, "P1", "S1")).open).toBe(true);
  });
  it("counts an answer's age from when it arrived, not from a later unlock", async () => {
    const db = await setup({ enabled: false });
    jest.setSystemTime(NOW.getTime() + 20 * 60 * 1000);
    await rememberCollectionGate(db, answer({ enabled: false }), NOW.getTime());
    expect((await checkCollectionGate(db, "P1", "S1")).open).toBe(true);
    await rememberCollectionGate(db, answer({ enabled: false }));
    expect(await checkCollectionGate(db, "P1", "S1")).toMatchObject({ open: false, reason: "collection_paused" });
  });
  it("allows a closed gate when the answer is stale", async () => {
    const db = await setup({ enabled: false });
    jest.setSystemTime(NOW.getTime() + 16 * 60 * 1000);
    expect((await checkCollectionGate(db, "P1", "S1")).open).toBe(true);
  });
  it("allows a closed gate while offline", async () => {
    const db = await setup({ enabled: false });
    const net = jest.requireMock("expo-network") as { getNetworkStateAsync: jest.Mock };
    net.getNetworkStateAsync.mockResolvedValueOnce({ isConnected: false, isInternetReachable: false });
    const stop = startNetworkWatch();
    await Promise.resolve(); await Promise.resolve();
    stop();
    expect((await checkCollectionGate(db, "P1", "S1")).open).toBe(true);
  });
});
