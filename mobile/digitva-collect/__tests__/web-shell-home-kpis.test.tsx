import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

import type { ClientBootstrap } from "../src/client/api";

const mockRequest = jest.fn();
const mockRouter = { push: jest.fn(), replace: jest.fn() };
let mockBootstrap: ClientBootstrap;

function bootstrap(): ClientBootstrap {
  return {
    user: { user_id: "u1", name: "Worker" },
    csrf: { header: "X-CSRFToken", token: "csrf" },
    access: { user: { user_id: "u1", name: "Worker" }, roles: ["coder"], is_admin: false,
      demo_coding: { available: false, project_ids: [] }, projects: [] },
    capabilities: { intake: false, registerDeath: false, registeredDeaths: false, coding: false, reviewing: false, supervision: false },
    links: { login: "/login", logout: "/logout", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" },
  } as ClientBootstrap;
}

let mockPathname = "/coding";

jest.mock("expo-router", () => ({
  usePathname: () => mockPathname,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: mockBootstrap, ready: true, logout: jest.fn(), uiLocale: "en", chooseUiLocale: jest.fn() }),
}));
jest.mock("../src/theme", () => ({
  useTheme: () => ({ colors: { surface: "#fff", border: "#ccc", text: "#000", textMuted: "#666", accent: "#00f", accentSoft: "#eef", focus: "#00f" } }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, UI_LOCALES: [{ code: "en", label: "English" }] }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: () => null,
    Screen: ({ sidebar, children }: { sidebar?: React.ReactNode; children?: React.ReactNode }) => ReactActual.createElement("screen", null, sidebar, children),
    useUiStyles: () => ({ card: {}, text: {}, muted: {} }),
    stateLabel: (state: string) => state,
  };
});

import { WebShell } from "../src/web/common";

async function render(children: React.ReactNode = <Text>PAGE_BODY</Text>): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WebShell title="Title">{children}</WebShell>);
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return renderer;
}

function navItem(renderer: ReactTestRenderer, label: string): ReactTestInstance | undefined {
  return renderer.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
}

describe("WebShell home KPI strip and My organization entry", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = bootstrap();
    mockPathname = "/coding";
  });

  it("shows the strip above the page content", async () => {
    mockRequest.mockResolvedValue({ projects: [{ project_id: "P1", project_name: "P", deaths_reported: 1, interviews_done: 0, coded: 0, interviews_pct: 0, coded_pct: 0 }] });
    const renderer = await render();

    expect(mockRequest).toHaveBeenCalledWith("/api/v1/me/kpis");
    const text = JSON.stringify(renderer.toJSON());
    expect(text).toContain("kpiLine");
    expect(text).toContain("PAGE_BODY");
    expect(text.indexOf("kpiLine")).toBeLessThan(text.indexOf("PAGE_BODY"));
    await act(async () => { renderer.unmount(); });
  });

  it("fetches the KPIs once per mount, not again when the page re-renders", async () => {
    mockRequest.mockResolvedValue({ projects: [] });
    const renderer = await render();
    await act(async () => {
      renderer.update(<WebShell title="Title"><Text>PAGE_BODY_2</Text></WebShell>);
    });

    expect(mockRequest.mock.calls.filter(([path]) => path === "/api/v1/me/kpis")).toHaveLength(1);
    await act(async () => { renderer.unmount(); });
  });

  it("shows the strip on /coding and not on a case page or settings", async () => {
    mockRequest.mockResolvedValue({ projects: [{ project_id: "P1", project_name: "P", deaths_reported: 1, interviews_done: 0, coded: 0, interviews_pct: 0, coded_pct: 0 }] });
    mockPathname = "/coding";
    const onCoding = await render();
    expect(JSON.stringify(onCoding.toJSON())).toContain("kpiLine");
    await act(async () => { onCoding.unmount(); });

    for (const path of ["/case", "/coding/case-1", "/settings"]) {
      jest.clearAllMocks();
      mockPathname = path;
      const renderer = await render();
      expect(JSON.stringify(renderer.toJSON())).toContain("PAGE_BODY");
      expect(JSON.stringify(renderer.toJSON())).not.toContain("kpiLine");
      expect(mockRequest).not.toHaveBeenCalled();
      await act(async () => { renderer.unmount(); });
    }
  });

  it("still renders the page when the KPI call fails", async () => {
    mockRequest.mockRejectedValue(new TypeError("network down"));
    const renderer = await render();

    const text = JSON.stringify(renderer.toJSON());
    expect(text).toContain("PAGE_BODY");
    expect(text).not.toContain("kpiLine");
    await act(async () => { renderer.unmount(); });
  });

  it("offers My organization in the user menu, which opens the page", async () => {
    mockRequest.mockResolvedValue({ projects: [] });
    const renderer = await render();

    const entry = navItem(renderer, "navOrganization");
    expect(entry).toBeDefined();
    await act(async () => { entry!.props.onPress(); });
    expect(mockRouter.push).toHaveBeenCalledWith("/organization");
    await act(async () => { renderer.unmount(); });
  });
});
