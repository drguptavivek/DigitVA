/** Over 4 hours: entry routes are covered (children stay mounted), viewing routes are not. */
import React from "react";
import { act, create } from "react-test-renderer";

let mockPathname = "/form";
let mockLevel = "block";
const mockState = {
  ready: true,
  standaloneAvailable: true,
  accounts: [{ user_id: "w", name: "W", collection_access: true, registration_access: true, standalone: false }],
  reload: jest.fn(),
};

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useGlobalSearchParams: () => ({ userId: "w" }),
  usePathname: () => mockPathname,
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
}));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/auth", () => ({ refreshAccessSummary: jest.fn() }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn(), unsentWorkCount: jest.fn() }));
jest.mock("../src/sync", () => ({ uploadQueuedWork: jest.fn() }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({ Button: () => null, Screen: () => null, errorText: () => "", useUiStyles: () => ({}) }));
jest.mock("../src/phoneClock", () => ({ usePhoneClock: () => ({ level: mockLevel }) }));
jest.mock("../src/nativeShell/ClockNotice", () => {
  const R = jest.requireActual("react") as typeof React;
  return { ClockBlock: () => R.createElement("clock-block") };
});

import NativeCollectionGate from "../src/NativeCollectionGate.native";

function render() {
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(<NativeCollectionGate>{React.createElement("child-screen")}</NativeCollectionGate>);
  });
  return tree;
}

beforeEach(() => {
  mockLevel = "block";
  mockState.accounts[0].standalone = false;
});

it.each(["/form", "/revision", "/interview"])("does not block standalone %s with a retained server clock", (route) => {
  mockPathname = route;
  mockState.accounts[0].standalone = true;
  const tree = render();
  expect(tree.root.findAllByType("child-screen" as never)).toHaveLength(1);
  expect(tree.root.findAllByType("clock-block" as never)).toHaveLength(0);
});

it.each(["/form", "/revision", "/register", "/interview", "/death-registration"])("covers %s but keeps it mounted", (route) => {
  mockPathname = route;
  const tree = render();
  expect(tree.root.findAllByType("child-screen" as never)).toHaveLength(1);
  expect(tree.root.findAllByType("clock-block" as never)).toHaveLength(1);
});

it.each(["/case", "/worklist"])("lets %s through (viewing and sending still work)", (route) => {
  mockPathname = route;
  const tree = render();
  expect(tree.root.findAllByType("clock-block" as never)).toHaveLength(0);
  expect(tree.root.findAllByType("child-screen" as never)).toHaveLength(1);
});

it.each(["ok", "warn"])("does not cover entry at level %s", (level) => {
  mockLevel = level;
  mockPathname = "/form";
  expect(render().root.findAllByType("clock-block" as never)).toHaveLength(0);
});
