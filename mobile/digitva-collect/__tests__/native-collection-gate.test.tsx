import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockPathname = "/case";
let mockParams: Record<string, string> = { userId: "worker" };
const mockRouter = { replace: jest.fn(), push: jest.fn() };
const mockUnsentCount = jest.fn<Promise<number | undefined>, [string]>(async () => 0);
let mockUnlocked = true;
let mockCodingEnabled = true;
jest.mock("../src/icd11DorisPreference", () => ({ useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: mockCodingEnabled }) }));
const mockUpload = jest.fn(async () => ({ sent: 2, failed: 0, supersededUniqueIds: [], serverKeptUploads: [], canCodeNowUniqueIds: [] }));
const mockRefreshAccess = jest.fn<Promise<unknown>, [string]>(async () => undefined);
const mockReload = jest.fn(async () => undefined);
const mockSignOut = jest.fn<Promise<void>, [string]>(async () => undefined);
const mockState = {
  ready: true,
  standaloneAvailable: true,
  authenticated: true,
  bootstrap: { user: { user_id: "worker", name: "Worker" }, csrf: "csrf", access: { roles: [] }, capabilities: { intake: false, registerDeath: false, registeredDeaths: false } },
  accounts: [{ user_id: "worker", name: "Worker", collection_access: false as boolean | undefined, registration_access: false as boolean | undefined } as Record<string, unknown>],
  reload: mockReload,
  lockNow: jest.fn(async () => undefined),
  offline: false,
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
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => mockUnlocked,
  openInterviewerDb: async () => ({}),
  unsentWorkCount: (userId: string) => mockUnsentCount(userId),
}));
jest.mock("../src/sync", () => ({ uploadQueuedWork: (...args: unknown[]) => mockUpload(...(args as [])) }));
let mockPlus = false;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus }));
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
  mockPlus = false;
  mockUnlocked = true;
  mockState.ready = true;
  mockState.standaloneAvailable = true;
  mockPathname = "/case";
  mockParams = { userId: "worker" };
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false }];
  mockState.bootstrap = { user: { user_id: "worker", name: "Worker" }, csrf: "csrf", access: { roles: [] }, capabilities: { intake: false, registerDeath: false, registeredDeaths: false } };
  mockState.offline = false;
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

it("redirects standalone worklist visits locally before rendering children or refreshing access", async () => {
  mockPathname = "/worklist";
  mockParams = { userId: "worker", view: "interviews" };
  mockState.accounts = [{ user_id: "worker", name: "Worker", standalone: true }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>enrolled worklist</NativeCollectionGate>); });
  expect(tree.toJSON()).toMatchObject({
    type: "redirect",
    props: { href: { pathname: "/standalone", params: { userId: "worker", view: "interviews" } } },
  });
  expect(JSON.stringify(tree.toJSON())).not.toContain("enrolled worklist");
  expect(mockRefreshAccess).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("blocks standalone setup before it can render without an account id while a server session is active", async () => {
  mockState.standaloneAvailable = false;
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate routeName="standalone-setup">standalone setup</NativeCollectionGate>); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("standaloneLogoutRequired");
  expect(output).not.toContain("standalone setup");
  expect(tree.root.findByProps({ label: "accounts" })).toBeTruthy();
  await act(async () => tree.unmount());
});

it.each(["/standalone", "/form", "/unlock", "/pin-setup", "/settings", "/offline-coding"])(
  "blocks a standalone account route %s before rendering children and preserves its user id", async (pathname) => {
    mockPathname = pathname;
    mockState.standaloneAvailable = false;
    mockState.accounts = [{ user_id: "worker", name: "Worker", standalone: true }];
    let tree!: ReturnType<typeof create>;
    await act(async () => {
      tree = create(
        <NativeCollectionGate routeName={pathname.slice(1)} routeParams={{ userId: "worker" }}>
          {`standalone ${pathname}`}
        </NativeCollectionGate>,
      );
    });
    const output = JSON.stringify(tree.toJSON());
    expect(output).toContain("standaloneLogoutRequired");
    expect(output).not.toContain(`standalone ${pathname}`);
    expect(mockRefreshAccess).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  },
);

it("allows a standalone account after every server account is explicitly signed out", async () => {
  mockPathname = "/standalone";
  mockState.standaloneAvailable = true;
  mockState.accounts = [{ user_id: "worker", name: "Worker", standalone: true }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>standalone home</NativeCollectionGate>); });
  expect(JSON.stringify(tree.toJSON())).toContain("standalone home");
  await act(async () => tree.unmount());
});

it("allows direct online coding for a plain enrolled account with coding access", async () => {
  mockPathname = "/coding";
  mockState.accounts = [{ user_id: "worker", name: "Worker", coding_access: true }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>coding workspace</NativeCollectionGate>); });
  expect(JSON.stringify(tree.toJSON())).toContain("coding workspace");
  await act(async () => tree.unmount());
});

it("blocks direct online coding when coding access is absent", async () => {
  mockPathname = "/coding";
  mockState.accounts = [{ user_id: "worker", name: "Worker", coding_access: false }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>coding workspace</NativeCollectionGate>); });
  expect(tree.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  await act(async () => tree.unmount());
});

it("waits for accounts before deciding a direct offline route", async () => {
  mockPathname = "/offline-coding";
  mockPlus = true;
  mockState.ready = false;
  mockState.accounts = [];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>offline coding</NativeCollectionGate>); });
  expect(JSON.stringify(tree.toJSON())).toContain("ActivityIndicator");
  await act(async () => tree.unmount());
});

it("sends a locked offline route to unlock without starting the engine", async () => {
  mockPathname = "/offline-coding";
  mockPlus = true;
  mockUnlocked = false;
  mockState.accounts = [{ user_id: "worker", name: "Worker", offline_coding_access: ["SELF"] }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>offline coding</NativeCollectionGate>); });
  expect(tree.toJSON()).toMatchObject({ type: "redirect", props: { href: { pathname: "/unlock", params: { userId: "worker" } } } });
  await act(async () => tree.unmount());
});

it("shows both local and online case sources for a coder-only account", async () => {
  mockPathname = "/worklist";
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false, coding_access: true, reviewing_access: true, offline_coding_access: ["SELF"] }];
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<NativeCollectionGate>worklist</NativeCollectionGate>); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("localCases");
  expect(output).toContain("onlineCases");
  expect(output).not.toContain("worklist");
  expect(tree.root.findAllByType("button").filter((node) => node.props.label === "localCases")).toHaveLength(1);
  expect(tree.root.findAllByType("button").filter((node) => node.props.label === "onlineCases")).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("sends a QR-signed-in coder on Collect Plus to the coding screens, not the interviewer worklist", async () => {
  mockPlus = true;
  mockPathname = "/worklist";
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false, coding_access: true, reviewing_access: false, offline_coding_access: ["SELF"] }];
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<NativeCollectionGate>worklist</NativeCollectionGate>); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).not.toContain("codingOnWeb");
  expect(output).not.toContain("worklist");
  await act(async () => tree.root.findByProps({ label: "onlineCases" }).props.onPress());
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/coding", params: { userId: "worker" } });
  await act(async () => tree.root.findByProps({ label: "localCases" }).props.onPress());
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/offline-coding", params: { userId: "worker" } });
  await act(async () => tree.unmount());
});

it("disables online cases while offline but leaves local cases available", async () => {
  mockPlus = true;
  mockPathname = "/worklist";
  mockState.offline = true;
  mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false, coding_access: true, offline_coding_access: ["SELF"] }];
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<NativeCollectionGate>worklist</NativeCollectionGate>); });
  expect(tree.root.findByProps({ label: "onlineCases" }).props.disabled).toBe(true);
  expect(tree.root.findByProps({ label: "localCases" }).props.disabled).toBe(false);
  await act(async () => tree.unmount());
});

it("keeps local coding disabled after the user chooses Not now", async () => {
  mockCodingEnabled = false;
  mockPathname = "/worklist";
  mockState.accounts = [{ user_id: "worker", name: "Worker", coding_access: true, offline_coding_access: ["SELF"] }];
  let tree!: ReactTestRenderer;
  try {
    await act(async () => { tree = create(<NativeCollectionGate>worklist</NativeCollectionGate>); });
    expect(tree.root.findByProps({ label: "localCases" }).props.disabled).toBe(true);
  } finally {
    mockCodingEnabled = true;
    if (tree) await act(async () => tree.unmount());
  }
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

describe("an account with unsent work and no collection session", () => {
  it("offers Sign in again (keeping the store) instead of only sign-out", async () => {
    mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: true, needs_sign_in: true, access_removed: true }];
    mockUnsentCount.mockResolvedValue(3);
    mockPathname = "/worklist";
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<NativeCollectionGate>worklist</NativeCollectionGate>); });

    expect(JSON.stringify(tree.toJSON())).toContain("accessRemovedUnsent");
    const signInAgain = tree.root.findByProps({ label: "signInAgainAction" });
    await act(async () => signInAgain.props.onPress());
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/sign-in", params: { userId: "worker" } });
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(tree.root.findAllByProps({ label: "sendUnsent" })).toHaveLength(0);
  });

  it("still sends unsent work when the session lasts but collection access is gone", async () => {
    mockState.accounts = [{ user_id: "worker", name: "Worker", collection_access: false, registration_access: false, coding_access: true }];
    mockUnsentCount.mockResolvedValue(2);
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<NativeCollectionGate>stale case data</NativeCollectionGate>); });

    expect(JSON.stringify(tree.toJSON())).toContain("unsentWaiting");
    expect(tree.root.findAllByProps({ label: "signInAgainAction" })).toHaveLength(0);
    await act(async () => tree.root.findByProps({ label: "sendUnsent" }).props.onPress());
    expect(mockUpload).toHaveBeenCalledWith("worker", {});
  });
});
