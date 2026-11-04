import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** Statistics loads one summary per project: each lands on its own, at most four are out at once, Retry refetches failures only. */

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
}));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockParams,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: { csrf: "x", user: { user_id: "u" } } }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  browserErrorText: () => "error",
}));
jest.mock("../src/web/roleHome", () => ({ caseViewPath: jest.fn(), dataAccess: () => ({ allowed: false }), openServerPage: jest.fn() }));
jest.mock("../src/web/stats/FilterBar", () => ({ FilterBar: () => null }));
jest.mock("../src/web/stats/CaseTableTab", () => ({ CaseTableTab: () => null }));

import StatisticsScreen from "../src/web/StatisticsScreen";

let mockParams: Record<string, string> = {};
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const ids = ["P1", "P2", "P3", "P4", "P5", "P6"];
type Gate = { resolve: () => void; reject: () => void };
let gates: Record<string, Gate[]> = {};
let inFlight = 0;
let peak = 0;
const calls: string[] = [];

const summary = (id: string) => ({
  project_id: id, project_name: `Name ${id}`, mode: "organization", period: "all", project_wide: true, unit: null, breadcrumb: [], rows: [],
  card: { counts: { deaths_reported: 10, submitted: 5, final_cod: 2, overdue_interview: 0, overdue_coding: 0 }, medians: {}, causes: [], links: {} },
  thresholds: { interview_days: 7, coding_days: 7 }, freshness: null,
});
const mockRequest = (url: string): Promise<unknown> => {
  if (url.endsWith("/projects")) return Promise.resolve({ projects: ids.map((id) => ({ project_id: id, project_name: `Name ${id}`, mode: "organization" })) });
  const id = /project=(P\d)/.exec(url)![1];
  calls.push(id);
  inFlight += 1;
  peak = Math.max(peak, inFlight);
  return new Promise((resolve, reject) => {
    (gates[id] ??= []).push({
      resolve: () => { inFlight -= 1; resolve(summary(id)); },
      reject: () => { inFlight -= 1; reject(new Error("slow")); },
    });
  });
};

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const texts = (tree: ReactTestRenderer) => tree.root.findAll((node) => typeof node.props.children === "string").map((node) => node.props.children as string);
const retryButtons = (tree: ReactTestRenderer) => tree.root.findAll((node) => node.props["data-label"] === "statsRetry");
async function render() {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<StatisticsScreen />); });
  await flush();
  return tree;
}
const answer = async (id: string, how: "resolve" | "reject" = "resolve") => {
  await act(async () => { gates[id].shift()![how](); });
  await flush();
};

beforeEach(() => { gates = {}; inFlight = 0; peak = 0; calls.length = 0; mockParams = { tab: "projects" }; });

test("at most four summaries are requested at once; the next starts as one answers", async () => {
  const tree = await render();
  expect(calls).toEqual(["P1", "P2", "P3", "P4"]);
  await answer("P1");
  expect(calls).toEqual(["P1", "P2", "P3", "P4", "P5"]);
  await answer("P2");
  expect(calls.slice(-1)).toEqual(["P6"]);
  expect(peak).toBe(4);
  await act(async () => tree.unmount());
});

test("a slow project does not block another's card, and Retry refetches only the failed one", async () => {
  const tree = await render();
  await answer("P2");
  await answer("P3", "reject");
  const shown = texts(tree);
  // P2's card shows its counts while P1 still loads; P3's card has the error line.
  expect(shown).toContain("Name P2");
  expect(shown).toContain("5");
  expect(shown.filter((text) => text === "loading")).not.toHaveLength(0);
  expect(shown.some((text) => text.startsWith("statsLoadFailed"))).toBe(true);
  const before = calls.length;
  expect(retryButtons(tree)).toHaveLength(1);
  await act(async () => retryButtons(tree)[0].props.onClick());
  await flush();
  expect(calls.slice(before)).toEqual(["P3"]);
  await act(async () => tree.unmount());
});

test("the Overview shows the summed line once one summary is in, with a pending note and a failed note with Retry", async () => {
  mockParams = {};
  const tree = await render();
  expect(texts(tree)).toContain("loading");
  await answer("P1");
  await answer("P2", "reject");
  const shown = texts(tree);
  expect(shown).toContain("10");
  expect(shown).not.toContain("loading");
  expect(shown).toContain("statsLoadingMore:4");
  expect(shown).toContain("statsSomeFailedOne:1");
  const before = calls.length;
  await act(async () => retryButtons(tree)[0].props.onClick());
  await flush();
  expect(calls.slice(before)).toEqual(["P2"]);
  await act(async () => tree.unmount());
});
