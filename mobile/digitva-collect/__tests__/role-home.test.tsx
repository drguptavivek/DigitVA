import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import type { ClientBootstrap } from "../src/client/api";

let mockRouteParams: Record<string, string> = {};
let mockAppBootstrap: ClientBootstrap;
let mockLoadedSession: { authenticated: boolean; bootstrap?: ClientBootstrap };
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn(async () => undefined);

function bootstrap(roles: string[], capabilities: Partial<ClientBootstrap["capabilities"]> = {}): ClientBootstrap {
  return {
    user: { user_id: "u1", name: "Worker" },
    csrf: { header: "X-CSRFToken", token: "csrf" },
    access: { user: { user_id: "u1", name: "Worker" }, roles, is_admin: false,
      demo_coding: { available: false, project_ids: [] }, projects: [] },
    capabilities: { intake: false, registerDeath: false, registeredDeaths: false, coding: false, reviewing: false, supervision: false, ...capabilities },
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
  return { QueueScreen: ({ mode }: { mode: string }) => ReactActual.createElement("queue-screen", { mode }) };
});
jest.mock("../src/workspace/CaseWorkspaceScreen", () => ({ CaseWorkspaceScreen: () => null }));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/media/AttachmentMedia.web", () => ({ AttachmentMedia: () => null }));

import WorkspaceScreen, { CodingScreen } from "../src/web/WorkspaceScreen";

const LOCAL_KEY = "digitva.lastVisit.u1";
const SESSION_KEY = "digitva.homeLanded.u1";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, String(value)); },
    removeItem: (key: string) => { data.delete(key); },
    clear: () => data.clear(),
    key: () => null,
    length: 0,
  };
}

async function render(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
  return renderer;
}

function buttonLabels(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType("button" as never).map((node) => node.props.label as string);
}

describe("role home landing", () => {
  let local: ReturnType<typeof memoryStorage>;
  let session: ReturnType<typeof memoryStorage>;
  let assign: jest.Mock;
  const originalLocation = window.location;

  beforeEach(() => {
    jest.clearAllMocks();
    local = memoryStorage();
    session = memoryStorage();
    Object.defineProperty(window, "localStorage", { configurable: true, value: local });
    Object.defineProperty(window, "sessionStorage", { configurable: true, value: session });
    assign = jest.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...originalLocation, assign } });
    mockRouteParams = {};
    mockAppBootstrap = bootstrap(["coder"], {});
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  test("the first home load goes to the remembered screen once, then shows the home list", async () => {
    mockAppBootstrap = bootstrap(["coder", "interview_supervisor"], { supervision: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    local.setItem(LOCAL_KEY, "/supervision");

    const first = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith("/supervision");
    await act(async () => { first.unmount(); });

    const second = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(second.toJSON())).toContain("loginSuccess");
    expect(buttonLabels(second)).toContain("navCoding");
    // The home has no Supervision button; that entry lives in the shell menu.
    expect(buttonLabels(second)).not.toContain("supervisionTitle");
    await act(async () => { second.unmount(); });
  });

  test("without a remembered screen the first load goes to the first role screen", async () => {
    mockAppBootstrap = bootstrap(["coder", "reviewer"], { reviewing: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledWith("/coding");
    await act(async () => { renderer.unmount(); });
  });

  it.each([
    ["reviewer lands on /reviewing", ["reviewer"], { intake: true }, "/reviewing"],
    ["interviewer lands on /collection", ["interviewer"], { intake: true }, "/collection"],
    ["death reporter lands on /death-registration", ["death_reporter"], { registerDeath: true, registeredDeaths: true }, "/death-registration"],
    ["supervisor lands on /supervision", ["interview_supervisor"], { supervision: true }, "/supervision"],
  ])("%s", async (_name, roles, capabilities, expected) => {
    mockAppBootstrap = bootstrap(roles, capabilities);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledWith(expected);
    await act(async () => { renderer.unmount(); });
  });

  test("a data manager with no role screen goes to Area with a full page load", async () => {
    mockAppBootstrap = bootstrap(["data_manager"], { supervision: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<WorkspaceScreen />);
    expect(assign).toHaveBeenCalledWith("/area/");
    expect(mockRouter.replace).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  test("a remembered server page is only resumed for a data manager", async () => {
    mockAppBootstrap = bootstrap(["coder"]);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    local.setItem(LOCAL_KEY, "/area/");
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledWith("/coding");
    expect(assign).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  test("storage that throws falls back to the first role screen", async () => {
    const denied = () => { throw new Error("storage denied"); };
    Object.defineProperty(window, "localStorage", { configurable: true, get: denied });
    Object.defineProperty(window, "sessionStorage", { configurable: true, get: denied });
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).toHaveBeenCalledWith("/coding");
    await act(async () => { renderer.unmount(); });
  });

  test("the coding and reviewing screens never redirect", async () => {
    const renderer = await render(<CodingScreen />);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });

  test("a data manager's home list offers Area and Data management after the first load", async () => {
    mockAppBootstrap = bootstrap(["data_manager", "interview_supervisor"], { supervision: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    session.setItem(SESSION_KEY, "1");
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(buttonLabels(renderer)).toEqual(expect.arrayContaining(["navArea", "navDataManagement"]));
    await act(async () => { renderer.unmount(); });
  });
});
