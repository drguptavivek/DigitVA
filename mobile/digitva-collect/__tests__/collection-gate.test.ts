import { evaluateGate, gatesFromAccess, projectToday, type GateEntry } from "../src/collectionGate";
import type { AccessSummary } from "../src/api";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

const entry = (over: Partial<GateEntry> = {}): GateEntry => ({
  site_id: "S1", enabled: true, start_date: null, end_date: null,
  daily_interviewer_limit: null, today_count: 0, display_name: "Site 1", ...over,
});

describe("evaluateGate", () => {
  it("allows with no gate (older server) and an open default gate", () => {
    expect(evaluateGate(undefined, "2026-11-06", "2026-11-06", 99)).toEqual({ open: true });
    expect(evaluateGate(entry(), "2026-11-06", "2026-11-06", 99)).toEqual({ open: true });
  });

  it("refuses when switched off", () => {
    expect(evaluateGate(entry({ enabled: false }), "2026-11-06", "2026-11-06", 0)).toMatchObject({ open: false, reason: "collection_paused", date: null, displayName: "Site 1" });
  });

  it("does not keep refusing on a pause from an earlier project day", () => {
    expect(evaluateGate(entry({ enabled: false }), "2026-11-06", "2026-11-07", 0)).toEqual({ open: true });
  });

  it("treats start and end dates as inclusive", () => {
    const window = entry({ start_date: "2026-11-06", end_date: "2026-11-30" });
    expect(evaluateGate(window, "2026-11-05", "2026-11-05", 0)).toMatchObject({ open: false, reason: "collection_not_started", date: "2026-11-06" });
    expect(evaluateGate(window, "2026-11-06", "2026-11-06", 0).open).toBe(true);
    expect(evaluateGate(window, "2026-11-30", "2026-11-30", 0).open).toBe(true);
    expect(evaluateGate(window, "2026-12-01", "2026-12-01", 0)).toMatchObject({ open: false, reason: "collection_ended", date: "2026-11-30" });
  });

  it("adds local starts to the server count and resets on a new project day", () => {
    const limited = entry({ daily_interviewer_limit: 3, today_count: 2 });
    expect(evaluateGate(limited, "2026-11-06", "2026-11-06", 0).open).toBe(true);
    expect(evaluateGate(limited, "2026-11-06", "2026-11-06", 1)).toMatchObject({ open: false, reason: "collection_daily_limit", limit: 3 });
    // The answer's count is yesterday's.
    expect(evaluateGate(limited, "2026-11-06", "2026-11-07", 2).open).toBe(true);
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
