import React from "react";
import { act, create } from "react-test-renderer";

let mockPathname = "/case";
let mockParams: Record<string, string> = { userId: "worker" };
const mockRouter = { replace: jest.fn() };
const mockRefreshAccess = jest.fn<Promise<unknown>, [string]>(async () => undefined);
const mockReload = jest.fn(async () => undefined);
const mockSignOut = jest.fn<Promise<void>, [string]>(async () => undefined);
const mockState = {
  ready: true,
  authenticated: true,
  bootstrap: { user: { user_id: "worker", name: "Worker" }, csrf: "csrf", access: { roles: [] }, capabilities: { intake: false, registerDeath: false, registeredDeaths: false } },
  accounts: [{ user_id: "worker", name: "Worker", collection_access: false as boolean | undefined, registration_access: false as boolean | undefined }],
  reload: mockReload,
  lockNow: jest.fn(async () => undefined),
};

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    return ReactActual.createElement("redirect", { href });
  },
  useGlobalSearchParams: () => mockParams,
  useLocalSearchParams: () => mockParams,
  usePathname: () => mockPathname,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/auth", () => ({
  refreshAccessSummary: (userId: string) => mockRefreshAccess(userId),
  signOut: (userId: string) => mockSignOut(userId),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) =>
      ReactActual.createElement("button", { label, onPress }),
    Screen: ({ children }: { children: React.ReactNode }) =>
      ReactActual.createElement("screen", null, children),
    errorText: () => "accessError",
    useUiStyles: () => ({ text: {}, error: {} }),
  };
});
// The gate assertions never render questionnaire controls; keep this test
// isolated from the vendor package's ESM native entry point.
jest.mock("@drguptavivek/who-2022-va/native", () => ({
  WhoVaQuestionControls: { SingleChoice: () => null, MultipleChoice: () => null },
}));
jest.mock("../src/web/common", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    WebShell: ({ children }: { children: React.ReactNode }) =>
      ReactActual.createElement("web-shell", null, children),
  };
});
jest.mock("../src/client/session", () => ({
  loadBrowserSession: async () => ({
    authenticated: true,
    bootstrap: {
      user: { user_id: "worker", name: "Worker" },
      csrf: "csrf",
      access: { roles: [] },
      capabilities: { intake: false, registerDeath: false, registeredDeaths: false },
    },
  }),
}));

import NativeCollectionGate from "../src/NativeCollectionGate.native";
import BrowserCollectionGate from "../src/NativeCollectionGate";
import WorkspaceScreen from "../src/web/WorkspaceScreen";

beforeEach(() => {
  mockPathname = "/case";
  mockParams = { userId: "worker" };
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false }];
  mockState.bootstrap = { user: { user_id: "worker", name: "Worker" }, csrf: "csrf", access: { roles: [] }, capabilities: { intake: false, registerDeath: false, registeredDeaths: false } };
  jest.clearAllMocks();
});

it("blocks a direct native collection route for a confirmed role-only account", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>stale case data</NativeCollectionGate>); });

  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("codingReviewPending");
  expect(output).not.toContain("stale case data");
  expect(mockRefreshAccess).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("keeps mixed-role native collection routes available", async () => {
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: true, registration_access: true }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>collection screen</NativeCollectionGate>); });
  expect(JSON.stringify(tree.toJSON())).toContain("collection screen");
  await act(async () => tree.unmount());
});

it("does not let a workspace route select another device account", async () => {
  mockPathname = "/workspace";
  mockParams = { userId: "other-user", mode: "view" };
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>private case data</NativeCollectionGate>); });
  expect(JSON.stringify(tree.toJSON())).toContain("redirect");
  expect(JSON.stringify(tree.toJSON())).not.toContain("private case data");
  await act(async () => tree.unmount());
});

it("blocks registration routes for interviewers without registration access", async () => {
  mockPathname = "/register";
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: true, registration_access: false }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>registration form</NativeCollectionGate>); });

  expect(JSON.stringify(tree.toJSON())).not.toContain("registration form");
  expect(mockRefreshAccess).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("keeps an unknown native access state behind the gate until refresh succeeds", async () => {
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: undefined, registration_access: undefined }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>collection screen</NativeCollectionGate>); });

  expect(JSON.stringify(tree.toJSON())).not.toContain("collection screen");
  expect(mockRefreshAccess).toHaveBeenCalledWith("worker");
  expect(tree.root.findAllByProps({ label: "retryAccess" })).toHaveLength(2);
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: undefined, registration_access: undefined }];
  await act(async () => { tree.update(<NativeCollectionGate>collection screen</NativeCollectionGate>); });
  expect(mockRefreshAccess).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("blocks a direct browser collection route when the access summary has no interviewer capability", async () => {
  mockPathname = "/death-registration";
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<BrowserCollectionGate>browser intake screen</BrowserCollectionGate>); });

  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("codingReviewPending");
  expect(output).not.toContain("browser intake screen");
  await act(async () => tree.unmount());
});

it("shows pending copy without a collection link on the role-only browser workspace", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<WorkspaceScreen />); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("codingReviewPending");
  expect(output).not.toContain("navCollection");
  await act(async () => tree.unmount());
});
