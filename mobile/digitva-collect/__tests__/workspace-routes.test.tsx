import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import type { ClientBootstrap } from "../src/client/api";

let mockRouteParams: Record<string, string> = {};
let mockAppBootstrap: ClientBootstrap;
let mockLoadedSession: { authenticated: boolean; bootstrap?: ClientBootstrap };
const mockRouter = { push: jest.fn(), replace: jest.fn(), setParams: jest.fn() };
const mockReload = jest.fn(async () => undefined);

function bootstrap(userId: string, roles: string[], isAdmin = false): ClientBootstrap {
  return {
    user: { user_id: userId, name: "Worker" },
    csrf: { header: "X-CSRFToken", token: "csrf" },
    access: { user: { user_id: userId, name: "Worker" }, roles, is_admin: isAdmin,
      demo_coding: { available: isAdmin, project_ids: ["P1"] }, projects: [] },
    capabilities: { intake: false, registerDeath: false, registeredDeaths: false, coding: roles.includes("coder"), reviewing: roles.includes("reviewer"), supervision: roles.includes("interview_supervisor") || roles.includes("data_manager") },
    links: { login: "/login", logout: "/logout", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" },
  } as ClientBootstrap;
}

jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockRouteParams,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockAppBootstrap, reload: mockReload }) }));
jest.mock("../src/client/session", () => ({ loadBrowserSession: () => Promise.resolve(mockLoadedSession) }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", { label, onPress }),
    useUiStyles: () => ({ error: {}, muted: {}, text: {}, headline: {}, card: {} }),
  };
});
jest.mock("../src/web/common", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    LoginLanding: () => ReactActual.createElement("login-landing"),
    WebShell: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("web-shell", null, children),
    browserErrorText: () => "session-error",
  };
});
jest.mock("../src/workspace/QueueScreen", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { QueueScreen: ({ mode, onViewChange }: { mode: string; onViewChange: unknown }) => ReactActual.createElement("queue-screen", { mode, onViewChange }) };
});
jest.mock("../src/workspace/CaseWorkspaceScreen", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { CaseWorkspaceScreen: ({ identity }: { identity: { vaSid: string; mode: string } }) => ReactActual.createElement("case-workspace", identity) };
});
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));

import WorkspaceScreen, { CodingScreen } from "../src/web/WorkspaceScreen";

async function render(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
    await Promise.resolve();
    await Promise.resolve();
  });
  return renderer;
}

describe("browser workspace routes", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouteParams = {};
    mockAppBootstrap = bootstrap("current-user", []);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
  });

  test("allows server-authorized read-only viewing for a reporter without coder roles", async () => {
    mockRouteParams = { mode: "view", vaSid: "authorized-sid" };
    const renderer = await render(<WorkspaceScreen />);
    const view = renderer.root.findByType("case-workspace" as never);
    expect(view.props).toMatchObject({ mode: "view", vaSid: "authorized-sid" });
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });

  test("drops queue params that a case URL inherited", async () => {
    mockAppBootstrap = bootstrap("current-user", ["coder"]);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    mockRouteParams = { vaSid: "sid-1", mode: "coding", project: "SADEMO", tab: "history", offset: "50" };
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/workspace", params: { vaSid: "sid-1", mode: "coding" } });
    await act(async () => { renderer.unmount(); });
  });

  test("writes queue params only while the URL names a queue, never onto a case URL", async () => {
    mockAppBootstrap = bootstrap("current-user", ["coder"]);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<CodingScreen />);
    const report = renderer.root.findByType("queue-screen" as never).props.onViewChange;
    const view = { projectId: "SADEMO", showHistory: true, offset: 0 };
    Object.defineProperty(window, "location", { configurable: true, value: { search: "" } });
    report(view);
    expect(mockRouter.setParams).toHaveBeenCalledWith({ project: "SADEMO", tab: "history", offset: undefined });
    mockRouter.setParams.mockClear();
    Object.defineProperty(window, "location", { configurable: true, value: { search: "?vaSid=sid-1&mode=coding" } });
    report(view); // a late report from the queue that was just left
    expect(mockRouter.setParams).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  test("does not infer coding access from admin or demo-coding availability", async () => {
    mockAppBootstrap = bootstrap("current-user", ["admin"], true);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<CodingScreen />);
    expect(JSON.stringify(renderer.toJSON())).toContain("serverForbidden");
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });

  test("does not open a route when the fresh browser session belongs to another user", async () => {
    mockRouteParams = { mode: "view", vaSid: "sensitive-sid" };
    mockLoadedSession = { authenticated: true, bootstrap: bootstrap("different-user", []) };
    const renderer = await render(<WorkspaceScreen />);
    expect(JSON.stringify(renderer.toJSON())).toContain("serverUnauthorized");
    expect(renderer.root.findAllByType("case-workspace" as never)).toHaveLength(0);
    expect(mockReload).toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });
});
