import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockParams: Record<string, string> = { userId: "coder-user" };
let mockAccounts: Array<Record<string, unknown>> = [];
let mockUnlocked = new Set<string>();
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockRefreshAccess = jest.fn();
const mockTransportUsers: string[] = [];
const mockApiCreations = jest.fn();

function access(userId: string, roles: string[]) {
  return { user: { user_id: userId, name: userId }, roles };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Alert: jest.requireActual("react-native").Alert,
    useFocusEffect: (callback: () => (() => void) | void) => ReactActual.useEffect(callback, [callback]),
    useLocalSearchParams: () => mockParams,
    useRouter: () => mockRouter,
  };
});
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: mockAccounts, reload: mockReload, lockNow: jest.fn() }) }));
jest.mock("../src/auth", () => ({ refreshAccessSummaryForAction: (userId: string) => mockRefreshAccess(userId), signOut: jest.fn() }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: (userId: string) => mockUnlocked.has(userId) }));
jest.mock("../src/workspace/transport.native", () => ({
  createNativeWorkspaceTransport: (userId: string) => { mockTransportUsers.push(userId); return jest.fn(); },
}));
jest.mock("../src/workspace/api", () => ({ createWorkspaceApi: (...args: unknown[]) => { mockApiCreations(...args); return {}; } }));
jest.mock("../src/workspace/QueueScreen", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { QueueScreen: ({ mode }: { mode: string }) => ReactActual.createElement("queue-screen", { mode }) };
});
jest.mock("../src/workspace/CaseWorkspaceScreen", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { CaseWorkspaceScreen: () => ReactActual.createElement("case-workspace") };
});
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/media/AttachmentMedia.native", () => ({ AttachmentMedia: () => null }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", { label, onPress }),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ error: {}, muted: {}, text: {} }),
  };
});

import { CodingScreen, WorkspaceScreen } from "../src/nativeRoutes/workspaceScreens";

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function render(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(element); });
  await settle();
  return renderer;
}

describe("native workspace route binding", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = { userId: "coder-user" };
    mockAccounts = [{ user_id: "coder-user", name: "Coder", coding_access: true }];
    mockUnlocked = new Set(["coder-user"]);
    mockTransportUsers.length = 0;
    mockRefreshAccess.mockImplementation(async (userId: string) => access(userId, ["coder"]));
  });

  test("loads current access before mounting the unlocked coder queue", async () => {
    const renderer = await render(<CodingScreen />);
    expect(mockRefreshAccess).toHaveBeenCalledWith("coder-user");
    expect(mockTransportUsers).toEqual(["coder-user"]);
    expect(renderer.root.findByType("queue-screen" as never).props.mode).toBe("coding");
    await act(async () => { renderer.unmount(); });
  });

  test("locked and wrong-user workspace params make no access request or API binding", async () => {
    mockUnlocked = new Set();
    let renderer = await render(<CodingScreen />);
    expect(mockRefreshAccess).not.toHaveBeenCalled();
    expect(mockTransportUsers).toHaveLength(0);
    expect(mockApiCreations).not.toHaveBeenCalled();
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });

    mockUnlocked = new Set(["coder-user"]);
    mockParams = { userId: "other-user", mode: "coding" };
    renderer = await render(<WorkspaceScreen />);
    expect(mockRefreshAccess).not.toHaveBeenCalled();
    expect(mockTransportUsers).toHaveLength(0);
    expect(mockApiCreations).not.toHaveBeenCalled();
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });

  test("discards late access after switching to a different account", async () => {
    const oldAccess = deferred<ReturnType<typeof access>>();
    mockAccounts = [
      { user_id: "coder-user", name: "Coder", coding_access: true },
      { user_id: "reviewer-user", name: "Reviewer", coding_access: false },
    ];
    mockUnlocked = new Set(["coder-user", "reviewer-user"]);
    mockRefreshAccess.mockImplementation((userId: string) => userId === "coder-user"
      ? oldAccess.promise
      : Promise.resolve(access(userId, ["reviewer"])));
    let renderer = await render(<CodingScreen />);
    await act(async () => {
      mockParams = { userId: "reviewer-user" };
      renderer.update(<CodingScreen />);
    });
    await settle();
    expect(JSON.stringify(renderer.toJSON())).toContain("serverForbidden");
    await act(async () => { oldAccess.resolve(access("coder-user", ["coder"])); await oldAccess.promise; });
    await settle();
    expect(JSON.stringify(renderer.toJSON())).toContain("serverForbidden");
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });
});
