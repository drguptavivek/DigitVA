/**
 * The offline coding and profile routes (Collect Plus): route wrappers gate on
 * platform + variant, the .web twins always redirect home without touching
 * native-only modules, and the .native coding screen gates on Plus, resolves
 * the interviewer's store and lists the completed-but-unsent cases from it.
 */
import React from "react";
import { Platform } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

const mockPlus = jest.fn(() => false);
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus() }));

const mockParams: Record<string, string> = {};
const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Redirect: ({ href }: { href: string }) => ReactActual.createElement("redirect", { href }),
    useLocalSearchParams: () => mockParams,
    useRouter: () => mockRouter,
  };
});

const mockAccounts: Array<Record<string, unknown>> = [{ user_id: "coder-1", name: "Coder" }];
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: mockAccounts }) }));

const mockDb = { runAsync: jest.fn(), getAllAsync: jest.fn(), getFirstAsync: jest.fn(), execAsync: jest.fn(), closeAsync: jest.fn() };
jest.mock("../src/interviewerDb", () => ({
  StoreLockedError: class extends Error {},
  isUnlocked: () => true,
  openInterviewerDb: jest.fn(async () => mockDb),
}));

const mockCases: Array<Record<string, unknown>> = [{
  client_draft_id: "draft-7",
  org_unit_id: "OU-42",
  completed_at: "2026-10-26T09:30:00.000+05:30",
  updated_at: "2026-10-26T10:00:00.000+05:30",
  offline_status: "coded",
}];
jest.mock("../src/drafts", () => ({
  listOfflineCodingCases: jest.fn(async () => mockCases),
  getOfflineCoding: jest.fn(async () => null),
  getOfflineCodingCase: jest.fn(async () => null),
  saveOfflineCoding: jest.fn(),
}));
jest.mock("../src/offlineIdentity", () => ({ getOrCreatePlusDeviceIdentity: jest.fn(async () => null) }));
jest.mock("../src/offlineProfile", () => ({ getOfflineProfile: jest.fn(async () => null) }));
jest.mock("../src/offlineEngine", () => ({ offlineEngine: () => ({ init: jest.fn(async () => ({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true })) }) }));
jest.mock("../src/workspace/offlineDoris", () => ({
  createOfflineDorisEditor: jest.fn(() => ({})),
  certificateSeedFromInterview: jest.fn(() => ({ certificate: {}, provenance: {} })),
}));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { View } = jest.requireActual("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", {
      accessibilityRole: "button", accessibilityLabel: label, onPress,
    }),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement(View, null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {}, input: {} }),
  };
});

import OfflineCodingRoute from "../app/offline-coding";
import OfflineProfileRoute from "../app/offline-profile";
import OfflineCoding from "../src/nativeRoutes/offlineCoding.native";
import OfflineCodingWeb from "../src/nativeRoutes/offlineCoding.web";
import OfflineProfileScreen from "../src/nativeRoutes/offlineProfile.native";
import OfflineProfileWeb from "../src/nativeRoutes/offlineProfile.web";

async function render(element: React.ReactElement) {
  let root!: Awaited<ReturnType<typeof create>>;
  await act(async () => { root = create(element); });
  return root;
}

const labels = (root: Awaited<ReturnType<typeof create>>) =>
  root.root.findAll((node: ReactTestInstance) => node.props.accessibilityRole === "button")
    .map((node: ReactTestInstance) => node.props.accessibilityLabel as string);

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

beforeEach(() => {
  setOs("ios");
  mockPlus.mockReturnValue(false);
  for (const key of Object.keys(mockParams)) delete mockParams[key];
  mockCases.length = 0;
  mockCases.push({
    client_draft_id: "draft-7",
    org_unit_id: "OU-42",
    completed_at: "2026-10-26T09:30:00.000+05:30",
    updated_at: "2026-10-26T10:00:00.000+05:30",
    offline_status: "coded",
  });
});

describe("route wrappers and web twins", () => {
  it("non-Plus builds and the web redirect home from both offline routes", async () => {
    const coding = await render(<OfflineCodingRoute />);
    expect(coding.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    const profile = await render(<OfflineProfileRoute />);
    expect(profile.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });

  // Under the web bundle the platform-agnostic route paths resolve to the
  // .web twins, so a web build renders redirect-home even with Plus flags set;
  // the native screen behind the same path is covered by the explicit
  // .native imports below.
  it("the web twins redirect home unconditionally, even with Plus flags set", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    const coding = await render(<OfflineCodingWeb />);
    expect(coding.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    const profile = await render(<OfflineProfileWeb />);
    expect(profile.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });
});

describe("the offline coding screen", () => {
  it("non-Plus redirects home before touching the store", async () => {
    const { openInterviewerDb } = require("../src/interviewerDb") as { openInterviewerDb: jest.Mock };
    openInterviewerDb.mockClear();
    const root = await render(<OfflineCoding />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    expect(openInterviewerDb).not.toHaveBeenCalled();
  });

  it("on Plus it lists the completed-but-unsent cases with their coding status", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    const root = await render(<OfflineCoding />);
    expect(labels(root)).toEqual([
      "draft-7 · 2026-10-26 · OU-42 · Coded",
    ]);
  });

  it("without a signed-in account it redirects home", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockAccounts.length = 0;
    const root = await render(<OfflineCoding />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });
});

describe("the offline profile screen", () => {
  it("non-Plus redirects home", async () => {
    const root = await render(<OfflineProfileScreen />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });
});
