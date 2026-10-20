import React from "react";
import { Platform } from "react-native";
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
    Screen: ({ sidebar, children, lead }: { sidebar?: React.ReactNode; children?: React.ReactNode; lead?: React.ReactNode }) => ReactActual.createElement("screen", { lead }, sidebar, children),
    useUiStyles: () => ({ muted: {}, text: {} }),
  };
});

import { WebShell } from "../src/web/common";
import { ROLE_SCREENS } from "../src/web/roleHome";
import { leaveDialogOpen, leavePage, registerNavigationGuard, stayOnPage } from "../src/web/navigationGuard";

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

  test("passes a screen's lead (the interview's header bar) to Screen, and none otherwise", async () => {
    const plain = await render();
    expect(plain.root.findByType("screen" as never).props.lead).toBeUndefined();
    act(() => plain.unmount());
    const lead = <header />;
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<WebShell title="Title" lead={lead}><></></WebShell>); });
    expect(renderer.root.findByType("screen" as never).props.lead).toBe(lead);
    act(() => renderer.unmount());
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

  // Scoped to the menu landmark, so other press targets on the page (the KPI strip) never count.
  const navLabels = (renderer: ReactTestRenderer) =>
    renderer.root.findAll((node) => node.props["aria-label"] === "menuLabel" || node.props.accessibilityLabel === "menuLabel")[0].findAll((node) => typeof node.props.accessibilityLabel === "string" && typeof node.props.onPress === "function")
      .map((node) => node.props.accessibilityLabel as string)
      .filter((label) => label !== "openMenu" && label !== "closeMenu");
  const openMore = async (renderer: ReactTestRenderer) => { await act(async () => { navItem(renderer, "navMore")!.props.onPress(); }); };

  test("shows the owner's items in order for the user's roles and capabilities, the rest under More", async () => {
    mockBootstrap = bootstrap(["coder", "reviewer", "death_reporter", "data_manager"], { intake: true, registerDeath: true, registeredDeaths: true, supervision: true });
    const renderer = await render();
    expect(navLabels(renderer)).toEqual(["home", "navDeaths", "navVaInterview", "navVaCode", "navVaReview", "navStatistics", "navMore"]);
    await openMore(renderer);
    expect(navLabels(renderer)).toEqual([
      "home", "navDeaths", "navVaInterview", "navVaCode", "navVaReview", "navStatistics", "navMore",
      "navOrg", "navSettings", "navWebsite", "navDataManagement", "signOut",
    ]);
    await act(async () => { renderer.unmount(); });
  });

  test("a coder sees no Deaths, Interview, Statistics or Data management", async () => {
    const renderer = await render();
    await openMore(renderer);
    expect(navLabels(renderer)).toEqual(["home", "navVaCode", "navMore", "navOrg", "navSettings", "navWebsite", "signOut"]);
    await act(async () => { renderer.unmount(); });
  });

  test("Deaths opens my registrations; Home goes to /; Website opens the public site in a new tab", async () => {
    mockBootstrap = bootstrap(["death_reporter"], { registerDeath: true, registeredDeaths: true });
    const open = jest.fn();
    Object.defineProperty(window, "open", { configurable: true, value: open });
    const renderer = await render();
    await act(async () => { navItem(renderer, "navDeaths")!.props.onPress(); });
    expect(mockRouter.push).toHaveBeenLastCalledWith({ pathname: "/death-registration", params: { view: "mine" } });
    await act(async () => { navItem(renderer, "home")!.props.onPress(); });
    expect(mockRouter.push).toHaveBeenLastCalledWith("/");
    await openMore(renderer);
    await act(async () => { navItem(renderer, "navWebsite")!.props.onPress(); });
    expect(open).toHaveBeenCalledWith("/vaindex", "_blank", "noopener");
    await act(async () => { renderer.unmount(); });
  });

  test("Deaths is active on the death-registration screen; More opens itself on a page it holds", async () => {
    mockBootstrap = bootstrap(["death_reporter"], { registerDeath: true, registeredDeaths: true });
    mockPathname = "/death-registration";
    let renderer = await render();
    expect(navItem(renderer, "navDeaths")!.props.accessibilityState.selected).toBe(true);
    expect(navItem(renderer, "home")!.props.accessibilityState.selected).toBe(false);
    await act(async () => { renderer.unmount(); });
    mockPathname = "/organization";
    renderer = await render();
    expect(navItem(renderer, "navMore")!.props.accessibilityState.expanded).toBe(true);
    expect(navItem(renderer, "navOrg")!.props.accessibilityState.selected).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  test("below 768px on the web the left menu never renders, on /interview as on every other route", async () => {
    const platform = jest.replaceProperty(Platform, "OS", "web");
    const dims = jest.spyOn(require("react-native"), "useWindowDimensions").mockReturnValue({ width: 375, height: 812, scale: 2, fontScale: 1 });
    mockPathname = "/interview";
    let renderer = await render();
    expect(renderer.root.findAll((node) => node.props.accessibilityLabel === "menuLabel" || node.props["aria-label"] === "menuLabel")).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
    dims.mockReturnValue({ width: 1200, height: 800, scale: 1, fontScale: 1 });
    renderer = await render();
    expect(navItem(renderer, "navVaCode")).toBeDefined();
    expect(navItem(renderer, "navVaInterview")).toBeUndefined(); // coder: no interview item, but the sidebar is there
    await act(async () => { renderer.unmount(); });
    dims.mockRestore();
    platform.restore();
  });

  test("Statistics remembers the page before opening it", async () => {
    mockBootstrap = bootstrap(["data_manager"]);
    const renderer = await render();
    await act(async () => { navItem(renderer, "navStatistics")!.props.onPress(); });
    expect(local.getItem(LOCAL_KEY)).toBe("/area/");
    expect(assign).toHaveBeenCalledWith("/area/");
    await act(async () => { renderer.unmount(); });
  });

  test("with a dirty navigation guard the left menu asks first: Stay keeps the user, Leave navigates; a new tab is never held", async () => {
    mockBootstrap = bootstrap(["data_manager"], { intake: true });
    const open = jest.fn();
    Object.defineProperty(window, "open", { configurable: true, value: open });
    const unregister = registerNavigationGuard({ isDirty: () => true, save: async () => true });
    const renderer = await render();
    await act(async () => { navItem(renderer, "home")!.props.onPress(); });
    expect(leaveDialogOpen()).toBe(true);
    expect(mockRouter.push).not.toHaveBeenCalled();
    await act(async () => { stayOnPage(); });
    await act(async () => { navItem(renderer, "navStatistics")!.props.onPress(); });
    expect(assign).not.toHaveBeenCalled();
    await act(async () => { leavePage(); });
    expect(assign).toHaveBeenCalledWith("/area/");
    unregister();
    const again = registerNavigationGuard({ isDirty: () => true, save: async () => true });
    await openMore(renderer);
    await act(async () => { navItem(renderer, "navWebsite")!.props.onPress(); });
    expect(open).toHaveBeenCalledWith("/vaindex", "_blank", "noopener");
    expect(leaveDialogOpen()).toBe(false);
    again();
    await act(async () => { renderer.unmount(); });
  });

  test("sign-out sits under More and goes through the shared logout, which clears the first-load flag", async () => {
    const renderer = await render();
    expect(navItem(renderer, "signOut")).toBeUndefined();
    await openMore(renderer);
    await act(async () => { navItem(renderer, "signOut")!.props.onPress(); });
    expect(mockLogout).toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });
});
