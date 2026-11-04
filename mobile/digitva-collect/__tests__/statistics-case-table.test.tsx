import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The Statistics case tables (src/web/stats/CaseTableTab.tsx) over a mocked GET /api/v1/cases. */

let mockWidth = 1024;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: mockWidth, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  useUiStyles: () => ({ card: {}, muted: {}, error: {} }),
}));
jest.mock("../src/web/common", () => ({ browserErrorText: () => "error" }));
jest.mock("../src/web/LocationCapture", () => ({ MapsPinButton: () => null }));

import { ui } from "../src/theme";
import { clearStatsCache } from "../src/web/stats/cache";
import { CaseTableTab } from "../src/web/stats/CaseTableTab";
import type { StatsView } from "../src/web/stats/view";

const row = (id: string, extra: Record<string, unknown> = {}) => ({
  death_id: id, unique_id: `UID-${id}`, project_id: "P1", site_id: "S1", status: "reported", source: "register",
  age_years: 40, deceased_sex: "female", date_of_death: "2026-08-01", created_at: "2026-08-02T00:00:00Z", ...extra,
});

// Each test starts with an empty Statistics cache (it lives for the page, not the component).
beforeEach(() => clearStatsCache());

const view: StatsView & { tab: "deaths" } = { tab: "deaths", projects: [], period: "all", unit: null, site: null, status: null, overdue: false, source: null };

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(element); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return tree;
}
const texts = (tree: ReactTestRenderer) => tree.root.findAll((node) => typeof node.props.children === "string").map((node) => node.props.children as string);
const flat = (style: unknown): Record<string, unknown> => (Array.isArray(style) ? Object.assign({}, ...style.map(flat)) : (style as Record<string, unknown>) ?? {});

test("a desktop table: counts on the chips, gated columns only when sent, overdue rows filled and said in words", async () => {
  mockWidth = 1024;
  const request = jest.fn(async () => ({
    cases: [row("a", { overdue: "interview", days_waiting: 74 }), row("b", { status: "coded" })],
    counts: { reported: 1, interview_pending: 2, coded: 1 },
    next_cursor: null,
  }));
  const tree = await render(<CaseTableTab view={view} projectIds={["P1", "P2"]} request={request} onStatus={jest.fn()} />);
  expect(request).toHaveBeenCalledWith("/api/v1/cases?preset=deaths&project_id=P1%2CP2&unregistered=1&limit=50");
  const shown = texts(tree);
  expect(shown).toContain("statsColId");
  expect(shown).toContain("statsColStatus");
  // No row carries a name or a reporter: those columns are absent, not blank.
  expect(shown).not.toContain("statsColName");
  expect(shown).not.toContain("statsColReporter");
  expect(tree.root.findAll((node) => node.props.accessibilityLabel === "statsChipCount:statsChipPending:3")).not.toHaveLength(0);
  const rows = tree.root.findAll((node) => typeof node.type === "string" && node.props.role === "row");
  expect(rows).toHaveLength(3);
  const overdue = rows.find((node) => node.findAll((one) => one.props.children === "UID-a").length > 0)!;
  expect(overdue.findAll((one) => one.props.children === "statsOverdueDays:74")).not.toHaveLength(0);
  expect(flat(overdue.props.style).backgroundColor).toBe(ui.light.warning);
  const plain = rows.find((node) => node.findAll((one) => one.props.children === "UID-b").length > 0)!;
  expect(flat(plain.props.style).backgroundColor).toBeUndefined();
  await act(async () => tree.unmount());
});

test("a narrow window shows cards; Load more keeps counts and Source is left to the server", async () => {
  mockWidth = 375;
  const request = jest.fn()
    .mockResolvedValueOnce({ cases: [row("a", { deceased_name: "Asha" }), row("b", { source: "direct" })], counts: { reported: 2 }, next_cursor: "c1" })
    .mockResolvedValueOnce({ cases: [row("c")], next_cursor: null });
  const tree = await render(<CaseTableTab view={{ ...view, source: "reported" }} projectIds={["P1"]} request={request} onStatus={jest.fn()} />);
  expect(tree.root.findAll((node) => typeof node.type === "string" && node.props.role === "table")).toHaveLength(0);
  let shown = texts(tree);
  expect(shown).toContain("Asha");
  expect(request).toHaveBeenCalledWith("/api/v1/cases?preset=deaths&project_id=P1&source=register&unregistered=1&limit=50");
  expect(shown.join()).not.toContain("filteringLoadedCases");
  await act(async () => tree.root.findAll((node) => node.props["data-label"] === "loadMore")[0].props.onClick());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(request).toHaveBeenLastCalledWith("/api/v1/cases?preset=deaths&project_id=P1&source=register&unregistered=1&limit=50&cursor=c1");
  shown = texts(tree);
  expect(shown).toContain("UID-c");
  expect(tree.root.findAll((node) => node.props.accessibilityLabel === "statsChipCount:statsChipPending:2")).not.toHaveLength(0);
  await act(async () => tree.unmount());
});

test("a submission with no register row (null death_id) is a row of its own, keyed by its sid, and opens", async () => {
  for (const width of [1024, 375]) {
    mockWidth = width;
    const unregistered = (sid: string) => row("x", { death_id: null, va_sid: sid, unique_id: `UID-${sid}`, source: "odk", status: "coded", can_open: true });
    const request = jest.fn(async () => ({ cases: [row("a"), unregistered("SID-1"), unregistered("SID-2")], next_cursor: null }));
    const onOpen = jest.fn();
    const errors = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const tree = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} onOpen={onOpen} />);
    const shown = texts(tree);
    expect(shown).toContain("UID-a");
    expect(shown).toContain("UID-SID-1");
    expect(shown).toContain("UID-SID-2");
    // Null death ids are no React key; keyed by the sid, nothing warns.
    expect(errors.mock.calls.some((call) => String(call[0]).includes("key"))).toBe(false);
    errors.mockRestore();
    const views = tree.root.findAll((node) => node.props["data-label"] === "dataActionView");
    expect(views).toHaveLength(2);
    views[1].props.onClick();
    expect(onOpen).toHaveBeenCalledWith("SID-2");
    await act(async () => tree.unmount());
  }
});

test("View shows only when the server allows it and the user holds a role; it opens the sid", async () => {
  for (const width of [1024, 375]) {
    mockWidth = width;
    const request = jest.fn(async () => ({
      cases: [row("a", { can_open: true, va_sid: "SID-A" }), row("b", { can_open: false, va_sid: "SID-B" }), row("c", { can_open: true })],
      next_cursor: null,
    }));
    const onOpen = jest.fn();
    const views = (tree: ReactTestRenderer) => tree.root.findAll((node) => node.props["data-label"] === "dataActionView");
    const tree = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} onOpen={onOpen} />);
    expect(views(tree)).toHaveLength(1);
    views(tree)[0].props.onClick();
    expect(onOpen).toHaveBeenCalledWith("SID-A");
    await act(async () => tree.unmount());
    const none = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} />);
    expect(views(none)).toHaveLength(0);
    await act(async () => none.unmount());
  }
});

test("Not recorded only where the server says so; a hidden name stays blank and adds no column", async () => {
  mockWidth = 1024;
  let request = jest.fn(async () => ({
    cases: [row("a", { deceased_name: "Asha" }), row("b", { deceased_name: null, name_recorded: false }), row("c")],
    next_cursor: null,
  }));
  let tree = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} />);
  let shown = texts(tree);
  expect(shown).toContain("statsColName");
  expect(shown).toContain("Asha");
  const rows = tree.root.findAll((node) => typeof node.type === "string" && node.props.role === "row");
  const said = (id: string) => rows.find((node) => node.findAll((one) => one.props.children === `UID-${id}`).length > 0)!
    .findAll((one) => one.props.children === "statsNameNotRecorded").length > 0;
  expect([said("a"), said("b"), said("c")]).toEqual([false, true, false]);
  await act(async () => tree.unmount());
  // A viewer who sees no name: no column, nothing said (another user: the screen's scope change empties the cache).
  clearStatsCache();
  request = jest.fn(async () => ({ cases: [row("c")], next_cursor: null }));
  tree = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} />);
  shown = texts(tree);
  expect(shown).toContain("UID-c");
  expect(shown).not.toContain("statsColName");
  expect(shown).not.toContain("statsNameNotRecorded");
  await act(async () => tree.unmount());
  // Cards say it as a fact.
  mockWidth = 375;
  clearStatsCache();
  request = jest.fn(async () => ({ cases: [row("d", { death_id: null, va_sid: "SID-D", name_recorded: false })], next_cursor: null }));
  tree = await render(<CaseTableTab view={view} projectIds={["P1"]} request={request} onStatus={jest.fn()} />);
  expect(JSON.stringify(tree.toJSON())).toContain("statsFactName:statsNameNotRecorded");
  await act(async () => tree.unmount());
});
