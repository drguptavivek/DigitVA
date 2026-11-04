import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/**
 * The Statistics response cache (src/web/stats/cache.ts): fresh hits send nothing, stale hits show at once and refresh,
 * concurrent reads share one request, errors are not kept, a user change empties it, and the other tabs are prefetched.
 */

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  useUiStyles: () => ({ card: {}, muted: {}, error: {} }),
}));
jest.mock("../src/ui/CaseCard", () => ({ CaseCard: () => null, formatDisplayTimestamp: (value: string | null) => value ?? "", sexLabel: (value: string | null) => value ?? "" }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockParams,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
// A new transport per bootstrap, as in the app: another user gets another requester.
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => (url: string) => mockRequest(url) }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  browserErrorText: () => "error",
}));
jest.mock("../src/web/roleHome", () => ({ caseViewPath: jest.fn(), dataAccess: () => ({ allowed: false }), openServerPage: jest.fn() }));
jest.mock("../src/web/stats/FilterBar", () => ({ FilterBar: () => null }));

import StatisticsScreen from "../src/web/StatisticsScreen";
import { casesEntry, clearStatsCache, followStats, PREFETCH_DELAY_MS, prefetchStats, readStats, setStatsScope, TTL_MS } from "../src/web/stats/cache";
import { CaseTableTab } from "../src/web/stats/CaseTableTab";
import type { StatsView } from "../src/web/stats/view";

let mockParams: Record<string, string> = {};
const mockRouter = { push: jest.fn(), replace: jest.fn() };
let mockBootstrap: { csrf: string; user: { user_id: string }; access: object } | undefined;
/** Case pages held open by the test, by request URL; everything else answers at once. */
let held: Record<string, () => void> = {};
let holdCases = false;
const calls: string[] = [];

const caseRow = (id: string) => ({
  death_id: id, unique_id: `UID-${id}`, project_id: "P1", site_id: "S1", status: "reported", source: "register",
  age_years: 40, deceased_sex: "female", date_of_death: "2026-08-01", created_at: "2026-08-02T00:00:00Z",
});
const stage = { reported: 10, interviewed: 5, coded: 2, overdue_interview: 0, overdue_coding: 0 };
const summary = { project_id: "P1", project_name: "Name P1", mode: "organization", period: "all", project_wide: true, unit: null, breadcrumb: [], rows: [],
  card: { counts: {}, medians: {}, causes: { coded: 0, hidden: true, rows: [] }, links: {} }, thresholds: { interview_days: 7, coding_days: 7 }, freshness: null };
const mockRequest = jest.fn((url: string): Promise<unknown> => {
  calls.push(url);
  if (url.endsWith("/projects")) return Promise.resolve({ projects: [{ project_id: "P1", project_name: "Name P1", mode: "organization", roots: [] }] });
  if (url.includes("/stage-counts")) return Promise.resolve({ projects: { P1: stage }, total: stage, thresholds: { interview_days: 7, coding_days: 7 } });
  if (url.includes("/summary")) return Promise.resolve(summary);
  const page = { cases: [caseRow(url)], next_cursor: null };
  if (!holdCases) return Promise.resolve(page);
  return new Promise((resolve) => { held[url] = () => resolve(page); });
});

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const waitPrefetch = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, PREFETCH_DELAY_MS + 50)); });
const texts = (tree: ReactTestRenderer) => tree.root.findAll((node) => typeof node.props.children === "string").map((node) => node.props.children as string);
const caseCalls = (preset: string) => calls.filter((url) => url.startsWith(`/api/v1/cases?preset=${preset}&`));

beforeEach(() => {
  clearStatsCache();
  calls.length = 0;
  held = {};
  holdCases = false;
  mockParams = {};
  mockBootstrap = { csrf: "x", user: { user_id: "u1" }, access: { projects: [] } };
  mockRequest.mockClear();
});
afterEach(() => jest.restoreAllMocks());

describe("the cache module", () => {
  const entry = (key: string, fetch: () => Promise<unknown>) => ({ key, fetch });

  test("two concurrent reads of one key send one request; a fresh hit sends none", async () => {
    const fetch = jest.fn(async () => "value");
    const first = readStats(entry("k", fetch));
    const second = readStats(entry("k", fetch));
    expect(first.next).toBe(second.next);
    await first.next;
    expect(readStats(entry("k", fetch))).toEqual({ cached: "value" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  test("a stale entry is handed over at once and refreshed behind it", async () => {
    let answer = "old";
    const fetch = jest.fn(async () => answer);
    await readStats(entry("k", fetch)).next;
    const now = Date.now();
    jest.spyOn(Date, "now").mockReturnValue(now + TTL_MS + 1);
    answer = "new";
    const seen: string[] = [];
    followStats(entry("k", fetch), (value) => seen.push(value as string), () => seen.push("error"));
    expect(seen).toEqual(["old"]);
    await flush();
    expect(seen).toEqual(["old", "new"]);
    expect(readStats(entry("k", fetch)).cached).toBe("new");
  });

  test("errors are not cached: the next read asks again", async () => {
    const fetch = jest.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce("value");
    await expect(readStats(entry("k", fetch)).next).rejects.toThrow("down");
    expect(readStats(entry("k", fetch)).cached).toBeUndefined();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test("a scope change (another user or access) empties the cache and drops a reply still in flight", async () => {
    setStatsScope("u1");
    let finish!: (value: string) => void;
    const slow = readStats(entry("slow", () => new Promise((resolve) => { finish = resolve; })));
    await readStats(entry("k", async () => "value")).next;
    setStatsScope("u2");
    finish("late");
    await slow.next;
    const fetch = jest.fn(async () => "again");
    expect(readStats(entry("k", fetch)).cached).toBeUndefined();
    expect(readStats(entry("slow", fetch)).cached).toBeUndefined();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  test("a cancelled prefetch starts nothing more; what it had under way is stored under its own key only", async () => {
    let finish!: (value: string) => void;
    const first = jest.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
    const second = jest.fn(async () => "b");
    const cancel = prefetchStats([entry("old-a", first), entry("old-b", second)]);
    await waitPrefetch();
    expect(first).toHaveBeenCalledTimes(1);
    cancel();
    finish("a");
    await flush();
    expect(second).not.toHaveBeenCalled();
    expect(readStats(entry("old-a", jest.fn())).cached).toBe("a");
    const fresh = jest.fn(async () => "new");
    expect(readStats(entry("new-a", fresh)).cached).toBeUndefined();
    expect(fresh).toHaveBeenCalledTimes(1);
  });
});

describe("the case table", () => {
  const view = (tab: "deaths" | "interviews", extra: Partial<StatsView> = {}): StatsView & { tab: typeof tab } =>
    ({ projects: [], period: "all", unit: null, site: null, status: null, overdue: false, source: null, ...extra, tab });
  async function render(element: React.ReactElement) {
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(element); });
    await flush();
    return tree;
  }
  const ids = ["P1"];

  test("tabs A -> B -> A within the TTL: A is not asked for again and shows with no loading line", async () => {
    const request = jest.fn(async (url: string) => ({ cases: [caseRow(url)], next_cursor: null }));
    const deaths = view("deaths");
    const interviews = view("interviews");
    const tree = await render(<CaseTableTab view={deaths} projectIds={ids} request={request} onStatus={jest.fn()} />);
    await act(async () => tree.update(<CaseTableTab view={interviews} projectIds={ids} request={request} onStatus={jest.fn()} />));
    await flush();
    act(() => tree.update(<CaseTableTab view={deaths} projectIds={ids} request={request} onStatus={jest.fn()} />));
    // Synchronously, before any effect or request: the cached rows are already on screen.
    expect(texts(tree)).not.toContain("loading");
    expect(texts(tree).some((text) => text.includes("preset=deaths"))).toBe(true);
    await flush();
    expect(request).toHaveBeenCalledTimes(2);
  });

  test("a changed filter misses the cache and asks the server", async () => {
    const request = jest.fn(async (url: string) => ({ cases: [caseRow(url)], next_cursor: null }));
    const tree = await render(<CaseTableTab view={view("deaths")} projectIds={ids} request={request} onStatus={jest.fn()} />);
    await act(async () => tree.update(<CaseTableTab view={view("deaths", { period: "30d" })} projectIds={ids} request={request} onStatus={jest.fn()} />));
    await flush();
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[1][0]).toContain("reported_from=");
  });

  test("a stale page shows at once with no loading line; the refresh replaces it", async () => {
    let label = "old";
    const request = jest.fn(async () => ({ cases: [caseRow(label)], next_cursor: null }));
    let tree = await render(<CaseTableTab view={view("deaths")} projectIds={ids} request={request} onStatus={jest.fn()} />);
    await act(async () => tree.unmount());
    jest.spyOn(Date, "now").mockReturnValue(Date.now() + TTL_MS + 1);
    label = "new";
    let finish!: () => void;
    request.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ cases: [caseRow("new")], next_cursor: null }); }));
    tree = await render(<CaseTableTab view={view("deaths")} projectIds={ids} request={request} onStatus={jest.fn()} />);
    expect(texts(tree)).toContain("UID-old");
    expect(texts(tree)).not.toContain("loading");
    await act(async () => finish());
    await flush();
    expect(texts(tree)).toContain("UID-new");
    expect(texts(tree)).not.toContain("UID-old");
    expect(request).toHaveBeenCalledTimes(2);
  });
});

describe("the screen", () => {
  async function render() {
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<StatisticsScreen />); });
    await flush();
    return tree;
  }
  const rerender = async (tree: ReactTestRenderer) => {
    await act(async () => tree.update(<StatisticsScreen />));
    await flush();
  };

  test("after the Deaths tab loads, the other tabs' first pages are prefetched; opening Interviews asks for nothing", async () => {
    mockParams = { tab: "deaths" };
    const tree = await render();
    expect(caseCalls("deaths")).toHaveLength(1);
    expect(caseCalls("interview")).toHaveLength(0);
    await waitPrefetch();
    expect(caseCalls("interview")).toHaveLength(1);
    expect(caseCalls("coding")).toHaveLength(1);
    // The Overview's numbers came along too.
    expect(calls.filter((url) => url.includes("/stage-counts"))).toHaveLength(1);
    const before = calls.length;
    mockParams = { tab: "interviews" };
    await rerender(tree);
    expect(texts(tree)).not.toContain("loading");
    mockParams = { tab: "overview" };
    await rerender(tree);
    expect(texts(tree)).not.toContain("loading");
    expect(calls.slice(before).filter((url) => !url.endsWith("/projects"))).toEqual([]);
    await act(async () => tree.unmount());
  });

  test("a filter change during a prefetch: the old filters' reply is not used for the new filters", async () => {
    mockParams = { tab: "deaths" };
    const tree = await render();
    holdCases = true;
    await waitPrefetch();
    const oldInterviews = caseCalls("interview");
    expect(oldInterviews).toHaveLength(1);
    expect(oldInterviews[0]).not.toContain("submitted_from");
    mockParams = { tab: "deaths", period: "30d" };
    await rerender(tree);
    // The old filters' reply lands after the change.
    await act(async () => held[oldInterviews[0]]());
    await flush();
    holdCases = false;
    Object.values(held).forEach((release) => release());
    await flush();
    mockParams = { tab: "interviews", period: "30d" };
    await rerender(tree);
    const asked = caseCalls("interview").filter((url) => url.includes("submitted_from"));
    expect(asked.length).toBeGreaterThanOrEqual(1);
    expect(texts(tree).some((text) => text.includes("submitted_from"))).toBe(true);
    expect(texts(tree)).not.toContain(`UID-${oldInterviews[0]}`);
    await act(async () => tree.unmount());
  });

  test("another user (or sign-out) empties the cache: the same view is asked for again", async () => {
    mockParams = { tab: "deaths" };
    const tree = await render();
    expect(caseCalls("deaths")).toHaveLength(1);
    mockBootstrap = undefined;
    await rerender(tree);
    mockBootstrap = { csrf: "x", user: { user_id: "u1" }, access: { projects: [] } };
    await rerender(tree);
    expect(caseCalls("deaths")).toHaveLength(2);
    mockBootstrap = { csrf: "x", user: { user_id: "u2" }, access: { projects: [] } };
    await rerender(tree);
    expect(caseCalls("deaths")).toHaveLength(3);
    await act(async () => tree.unmount());
  });
});
