/**
 * The standalone Interviews tab (`/standalone?view=interviews`, navAdapter nativeTabs) shows only the record tabs and
 * the list; Home keeps its next-step, backup, Settings and Lock blocks.
 */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockParams: { value: Record<string, string> } = { value: { userId: "standalone-1" } };
jest.mock("expo-router", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Redirect: () => null,
    useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
    useLocalSearchParams: () => mockParams.value,
    // Focus once on mount, as the screen does when first shown.
    useFocusEffect: (callback: () => void | (() => void)) => R.useEffect(callback, [callback]),
  };
});
jest.mock("expo-crypto", () => ({ randomUUID: () => "44444444-4444-4444-8444-444444444444" }));
// One stable object: a fresh accounts array each render would reload the home in a loop.
const mockAppState = {
  accounts: [{ user_id: "standalone-1", name: "Asha", standalone: true }],
  lockVersion: 0,
  lockNow: jest.fn(),
  uiLocale: "en",
};
jest.mock("../src/AppState", () => ({ useAppState: () => mockAppState }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn(async () => ({})) }));
jest.mock("../src/drafts", () => ({ retryHeldDraft: jest.fn() }));
jest.mock("../src/offlineProfile", () => ({ getOfflineProfile: jest.fn(async () => null), standaloneProfileMissing: () => [] }));
jest.mock("../src/offlineEngine", () => ({ scheduleEngineWarmUp: () => undefined }));
jest.mock("../src/standalone/shareFile", () => ({ sweepExportLeftovers: () => undefined }));
const baseRecord = {
  completed: false, started_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z", completed_at: null,
  coding_status: null, upload_issue: null, refusal_code: null, name: "", age_years: null, sex: null,
};
jest.mock("../src/standalone/records", () => ({
  listStandaloneRecords: jest.fn(async () => [
    { ...baseRecord, id: "draft-1", name: "Ravi Kumar", age_years: 30, sex: "male" },
    { ...baseRecord, id: "p-1", completed: true, name: "Sita Devi", age_years: 41, sex: "female" },
    { ...baseRecord, id: "0ef144e3-eb3f-48fb-839f-84187165790a", completed: true },
  ]),
  lastBackupAt: jest.fn(async () => new Date().toISOString()),
}));
const WORDS: Record<string, string> = { sexMale: "Male", sexFemale: "Female" };
jest.mock("../src/i18n", () => ({
  t: (key: string, values?: Record<string, string | number>) => WORDS[key]
    ?? (key === "standaloneTabCount" ? `${values!.label} (${values!.count})` : key === "metaAgeYears" ? `${values!.value} y` : key),
}));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label }: { label: string }) => R.createElement("button", { "data-label": label }, label),
    Screen: ({ title, children }: { title: string; children: ReactNode }) => R.createElement("main", { "data-title": title }, children),
    errorText: () => "error",
    Notice: ({ children }: { children: ReactNode }) => R.createElement("p", null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

import StandaloneHome from "../src/nativeRoutes/standalone";

async function render(view?: string): Promise<ReactTestRenderer> {
  mockParams.value = view ? { userId: "standalone-1", view } : { userId: "standalone-1" };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<StandaloneHome />); });
  await act(async () => { await Promise.resolve(); });
  return tree;
}

function labels(tree: ReactTestRenderer): string[] {
  return tree.root.findAll((node) => typeof node.props.children === "string").map((node) => node.props.children as string);
}

afterEach(() => { mockParams.value = { userId: "standalone-1" }; });

describe("standalone Interviews view", () => {
  it("renders the record list and the tabs, not the Home blocks", async () => {
    const tree = await render("interviews");
    const out = labels(tree);
    expect(tree.root.findByType("main").props["data-title"]).toBe("tabInterviews");
    expect(out).toContain("Sita Devi · 41 y · Female");
    expect(out).toContain("standaloneCoded (0)");
    // A record with no name read is "Untitled interview", never its UUID as the title (digitva-egr0).
    expect(out).toContain("untitledInterview");
    expect(out).toContain("0ef144e3-eb3f-48fb-839f-84187165790a");
    expect(out).not.toContain("standaloneNewInterview");
    expect(out).not.toContain("standaloneClockNotice");
    expect(out).not.toContain("settings");
    expect(out).not.toContain("lockNow");
    await act(async () => tree.unmount());
  });

  it("keeps the Home blocks on Home", async () => {
    const tree = await render();
    const out = labels(tree);
    expect(tree.root.findByType("main").props["data-title"]).toBe("standaloneHomeTitle");
    expect(out).toContain("Sita Devi · 41 y · Female");
    expect(out).toContain("standaloneNewInterview");
    expect(out).toContain("settings");
    expect(out).toContain("lockNow");
    await act(async () => tree.unmount());
  });
});
