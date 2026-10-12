import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { ClientBootstrap } from "../src/client/api";

let mockPathname = "/coding";
let mockBootstrap: ClientBootstrap;
const mockLogout = jest.fn(async () => undefined);
const mockRouter = { push: jest.fn(), replace: jest.fn() };

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
  usePathname: () => mockPathname,
  useRouter: () => mockRouter,
  useGlobalSearchParams: () => ({}),
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: mockBootstrap, ready: true, logout: mockLogout, uiLocale: "en", chooseUiLocale: jest.fn() }),
}));
jest.mock("../src/theme", () => ({
  radius: { sm: 4, md: 6, lg: 8, full: 9999 }, 
  useTheme: () => ({ colors: { surface: "#fff", border: "#ccc", text: "#000", textMuted: "#666", accent: "#00f", accentSoft: "#eef", focus: "#00f" } }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, UI_LOCALES: [{ code: "en", label: "English" }] }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: () => null,
    Screen: ({ sidebar, children }: { sidebar?: React.ReactNode; children?: React.ReactNode }) => ReactActual.createElement("screen", null, sidebar, children),
    useUiStyles: () => ({ muted: {}, text: {} }),
  };
});

import { WebShell } from "../src/web/common";
import { ROLE_SCREENS } from "../src/web/roleHome";

const LOCAL_KEY = "digitva.lastVisit.u1";

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

async function render(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WebShell title="Title"><></></WebShell>);
  });
  return renderer;
}

function navItem(renderer: ReactTestRenderer, label: string): ReactTestInstance | undefined {
  return renderer.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
}

describe("web shell navigation and last visit", () => {
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
    mockPathname = "/coding";
    mockBootstrap = bootstrap(["coder"]);
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  test.each(ROLE_SCREENS)("remembers the role screen %s on mount", async (route) => {
    mockPathname = route;
    const renderer = await render();
    expect(local.getItem(LOCAL_KEY)).toBe(route);
    await act(async () => { renderer.unmount(); });
  });

  test("does not remember the home or a case page", async () => {
    mockPathname = "/workspace";
    const renderer = await render();
    expect(local.getItem(LOCAL_KEY)).toBeNull();
    await act(async () => { renderer.unmount(); });
  });

  test("shows the role entries for the user's roles and capabilities", async () => {
    mockBootstrap = bootstrap(["coder", "reviewer", "death_reporter"], { intake: true, registerDeath: true, registeredDeaths: true });
    const renderer = await render();
    for (const label of ["navCoding", "navReview", "reportedDeaths", "registerDeath", "myRegisteredDeaths"]) {
      expect(navItem(renderer, label)).toBeDefined();
    }
    expect(navItem(renderer, "navArea")).toBeUndefined();
    expect(navItem(renderer, "navDataManagement")).toBeUndefined();
    await act(async () => { renderer.unmount(); });
  });

  test("shows Area and Data management only for a data manager", async () => {
    mockBootstrap = bootstrap(["data_manager"], { supervision: true });
    const renderer = await render();
    expect(navItem(renderer, "navArea")).toBeDefined();
    expect(navItem(renderer, "navDataManagement")).toBeDefined();
    await act(async () => { renderer.unmount(); });
  });

  test("Area remembers the page before opening it", async () => {
    mockBootstrap = bootstrap(["data_manager"]);
    const renderer = await render();
    await act(async () => { navItem(renderer, "navArea")!.props.onPress(); });
    expect(local.getItem(LOCAL_KEY)).toBe("/area/");
    expect(assign).toHaveBeenCalledWith("/area/");
    await act(async () => { renderer.unmount(); });
  });

  test("sign-out goes through the shared logout, which clears the first-load flag", async () => {
    const renderer = await render();
    await act(async () => { navItem(renderer, "signOut")!.props.onPress(); });
    expect(mockLogout).toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });
});
