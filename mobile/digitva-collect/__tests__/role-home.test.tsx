import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import Svg from "react-native-svg";

import type { HomeSummary } from "../src/api";
import type { AccessProject, ClientBootstrap } from "../src/client/api";

let mockRouteParams: Record<string, string> = {};
let mockAppBootstrap: ClientBootstrap;
let mockLoadedSession: { authenticated: boolean; bootstrap?: ClientBootstrap };
let mockHome: HomeSummary | Error;
const mockRequest = jest.fn(async (path: string) => {
  if (path !== "/api/v1/me/home") throw new Error(`unexpected ${path}`);
  if (mockHome instanceof Error) throw mockHome;
  return mockHome;
});
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn(async () => undefined);

function bootstrap(
  roles: string[],
  capabilities: Partial<ClientBootstrap["capabilities"]> = {},
  projects: AccessProject[] = [],
  demoAvailable = false,
): ClientBootstrap {
  return {
    user: { user_id: "u1", name: "Worker" },
    csrf: { header: "X-CSRFToken", token: "csrf" },
    access: {
      user: { user_id: "u1", name: "Worker" },
      roles,
      is_admin: roles.includes("admin"),
      demo_coding: { available: demoAvailable, project_ids: demoAvailable ? ["DEMO01"] : [] },
      projects,
    },
    capabilities: {
      intake: false,
      registerDeath: false,
      registeredDeaths: false,
      coding: false,
      reviewing: false,
      supervision: false,
      ...capabilities,
    },
    links: {
      login: "/login",
      logout: "/logout",
      intakeCases: "/api/v1/intake/cases",
      intakeDrafts: "/api/v1/intake/drafts",
    },
  } as ClientBootstrap;
}

jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockRouteParams,
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockAppBootstrap, reload: mockReload }) }));
jest.mock("../src/client/session", () => ({ loadBrowserSession: () => Promise.resolve(mockLoadedSession) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/KpiStrip", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { KpiStrip: () => ReactActual.createElement("kpi-strip") };
});
jest.mock("../src/i18n", () => ({
  t: (key: string, params?: Record<string, string | number>) =>
    params ? `${key}:${JSON.stringify(params)}` : key,
}));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) =>
      ReactActual.createElement("button", { label, onPress }),
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

import WorkspaceScreen, { CodingScreen, MANY_PROJECTS, projectSubline, roleBlocks } from "../src/web/WorkspaceScreen";
import {
  claimFirstHomeLoad,
  describeProjectGrant,
  describeProjectGrants,
  homeLanding,
  projectActionItems,
  readLastVisit,
  rememberVisit,
  resetFirstHomeLoad,
  roleScreens,
} from "../src/web/roleHome";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, String(value));
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
    clear: () => data.clear(),
    key: (index: number) => [...data.keys()][index] ?? null,
    get length() {
      return data.size;
    },
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

describe("role home dashboard", () => {
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
    mockHome = { roles: ["coder"], blocks: { coder: { ready: 3, practice: false, completed: 5, recodeable: 1 } } };
    mockAppBootstrap = bootstrap(["coder"], {});
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  test("a new user with no roles sees the Welcome Home screen without redirecting", async () => {
    mockAppBootstrap = bootstrap([], {}, [], true);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };

    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    const json = JSON.stringify(renderer.toJSON());
    expect(json).toContain("homeNoRolesTitle");
    expect(json).toContain("homeNoRolesDescription");
    expect(buttonLabels(renderer)).toEqual(
      expect.arrayContaining(["navSettings", "homeOpenHelp", "homePracticeDemoCoding"]),
    );
    await act(async () => {
      renderer.unmount();
    });
  });

  test("one block per role, most actionable backlog first, numbers and one action each, no role chips or project cards", async () => {
    const project: AccessProject = {
      project_id: "TST001",
      project_name: "Test Project",
      has_tree: true,
      grants: [
        { role: "interviewer", scope: "org_unit", org_unit_id: "u-sc1", unit_name: "Subcentre A", active: true, source: "assigned" },
        { role: "coder", scope: "org_unit", org_unit_id: "u-ph1", unit_name: "PHC 1", codes: true, active: true, source: "assigned" },
        { role: "reviewer", scope: "project_site", site_id: "S01", codes: true, active: true, source: "assigned" },
      ],
      sites: [{ site_id: "S01", site_name: "Sites_in_project_TST001", roles: ["reviewer"] }],
      actions: { interview: [], register_death: [] },
      units: [],
      levels: [],
    };
    mockAppBootstrap = bootstrap(["interviewer", "coder", "reviewer"], { intake: true, coding: true, reviewing: true }, [project]);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    mockHome = {
      roles: ["coder", "interviewer", "reviewer"],
      blocks: {
        interviewer: { drafts_in_progress: 0, needing_visit: 2 },
        coder: { ready: 9, practice: false, completed: 4, recodeable: 1 },
        reviewer: { available: 5, completed: 0 },
      },
    };

    const renderer = await render(<WorkspaceScreen />);
    expect(mockRequest).toHaveBeenCalledWith("/api/v1/me/home");
    const json = JSON.stringify(renderer.toJSON());
    // Coder (9) before reviewer (5) before interviewer (2).
    expect(json).toContain("homeBlockCoder");
    expect(json.indexOf("homeBlockCoder")).toBeLessThan(json.indexOf("homeBlockReviewer"));
    expect(json.indexOf("homeBlockReviewer")).toBeLessThan(json.indexOf("homeBlockInterviewer"));
    // The project is a subline, not a card with role chips or per-project actions.
    expect(json).toContain("Test Project");
    expect(json).not.toContain("role_coder");
    expect(json).not.toContain("Sites_in_project_TST001");
    const labels = buttonLabels(renderer);
    expect(labels).toContain("homeCtaCodeNext");
    expect(labels).not.toContain("navCoding");
    expect(labels).not.toContain("navOrganization");
    // No progress role: no progress block.
    expect(json).not.toContain("homeBlockProgress");
    await act(async () => {
      renderer.unmount();
    });
  });

  test("the first block takes the action, an interviewer with drafts resumes, and a practice tester is never ranked by backlog", async () => {
    mockAppBootstrap = bootstrap(["interviewer", "coding_tester"], { intake: true, coding: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    mockHome = {
      roles: ["coding_tester", "interviewer"],
      blocks: {
        coder: { ready: 50, practice: true },
        interviewer: { drafts_in_progress: 1, needing_visit: 0 },
      },
    };

    const renderer = await render(<WorkspaceScreen />);
    const json = JSON.stringify(renderer.toJSON());
    expect(json).toContain("homeBlockInterviewer");
    expect(json.indexOf("homeBlockInterviewer")).toBeLessThan(json.indexOf("homeBlockPracticeCoding"));
    const labels = buttonLabels(renderer);
    expect(labels).toContain("homeCtaResumeDraft");
    renderer.root.findAllByType("button" as never).find((node) => node.props.label === "homeCtaResumeDraft")?.props.onPress();
    expect(mockRouter.push).toHaveBeenCalledWith("/collection");
    await act(async () => {
      renderer.unmount();
    });
  });

  test("a progress role gets a folded block that loads project progress only when opened", async () => {
    mockAppBootstrap = bootstrap(["project_pi"]);
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    mockHome = { roles: ["project_pi"], blocks: { progress: { roles: ["project_pi"] } } };

    const renderer = await render(<WorkspaceScreen />);
    expect(JSON.stringify(renderer.toJSON())).toContain("homeBlockProgress");
    expect(renderer.root.findAllByType("kpi-strip" as never)).toHaveLength(0);
    const toggle = renderer.root.findAll(
      (node) => node.props.accessibilityLabel === "homeShowProgress" && typeof node.props.onPress === "function",
    )[0];
    expect(toggle).toBeDefined();
    expect(toggle.props.accessibilityState).toEqual({ expanded: false });
    expect(JSON.stringify(renderer.toJSON())).not.toMatch(/[▾▸]/);
    expect(renderer.root.findAllByType(Svg).length).toBeGreaterThanOrEqual(1);
    await act(async () => {
      toggle.props.onPress();
    });
    expect(renderer.root.findAllByType("kpi-strip" as never)).toHaveLength(1);
    renderer.root.findAllByType("button" as never).find((node) => node.props.label === "navStatistics")?.props.onPress();
    expect(assign).toHaveBeenCalledWith("/area/");
    await act(async () => {
      renderer.unmount();
    });
  });

  test("a failed home call says so and still offers the links", async () => {
    mockAppBootstrap = bootstrap(["coder"], { coding: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    mockHome = new Error("down");

    const renderer = await render(<WorkspaceScreen />);
    expect(JSON.stringify(renderer.toJSON())).toContain("homeCountsUnavailable");
    expect(buttonLabels(renderer)).toContain("homeOpenCaseById");
    await act(async () => {
      renderer.unmount();
    });
  });

  test("quick actions keep only what the sidebar lacks: no Area, Data management or Supervision for a data manager", async () => {
    mockAppBootstrap = bootstrap(["data_manager", "interview_supervisor", "site_pi"], { supervision: true });
    mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
    const renderer = await render(<WorkspaceScreen />);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    const labels = buttonLabels(renderer);
    expect(labels).toContain("homeSitePiDashboard");
    renderer.root.findAllByType("button" as never).find((node) => node.props.label === "homeSitePiDashboard")?.props.onPress();
    expect(assign).toHaveBeenCalledWith("/sitepi/");
    expect(labels).not.toContain("navArea");
    expect(labels).not.toContain("navDataManagement");
    expect(labels).not.toContain("supervisionTitle");
    await act(async () => {
      renderer.unmount();
    });
  });

  test("admin, collaborator and viewer homes carry their Flask-page entries", async () => {
    for (const [roles, label, path] of [
      [["admin"], "homeAdminConsole", "/admin/"],
      [["collaborator"], "navDataManagement", "/data-management/"],
      [["collaborator_pii"], "navDataManagement", "/data-management/"],
      [["project_pi"], "navDataManagement", "/data-management/"],
    ] as const) {
      assign.mockClear();
      mockAppBootstrap = bootstrap([...roles], {});
      mockLoadedSession = { authenticated: true, bootstrap: mockAppBootstrap };
      const renderer = await render(<WorkspaceScreen />);
      expect(buttonLabels(renderer)).toContain(label);
      renderer.root.findAllByType("button" as never).find((node) => node.props.label === label)?.props.onPress();
      expect(assign).toHaveBeenCalledWith(path);
      await act(async () => {
        renderer.unmount();
      });
    }
  });

  test("a role's projects are named up to MANY_PROJECTS, then counted", () => {
    const grants: AccessProject["grants"] = [{ role: "coder", scope: "project", codes: true, active: true, source: "assigned" }];
    const make = (id: string): AccessProject => ({ project_id: id, project_name: `Name ${id}`, has_tree: false, grants, sites: [], units: [], levels: [], actions: { interview: [], register_death: [] } });
    const three = ["A", "B", "C"].map(make);
    expect(projectSubline(three, ["coder"])).toBe("Name A · Name B · Name C");
    expect(projectSubline(three, ["reviewer"])).toBe("");
    expect(projectSubline([...three, make("D")], ["coder"])).toBe('homeProjectsCount:{"count":4}');
    expect(MANY_PROJECTS).toBe(3);
  });

  test("the coding and reviewing screens never redirect", async () => {
    const renderer = await render(<CodingScreen />);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(renderer.root.findAllByType("queue-screen" as never)).toHaveLength(1);
    await act(async () => {
      renderer.unmount();
    });
  });

  test("the supervisor block counts and leads with what needs the supervisor's decision", () => {
    const go = jest.fn();
    const [block] = roleBlocks({ interview_supervisor: { flagged: 1, needs_decision: 5, open: 7, submitted: 2 } } as never, go);
    expect(block.cta).toBe("homeCtaNeedsDecision");
    expect(block.backlog).toBe(5);
    expect(block.metrics).toContainEqual({ label: "homeMetricNeedsDecision", value: 5 });
    block.onPress();
    expect(go).toHaveBeenCalledWith("interview_supervisor");
  });

  test("roleHome helpers resolve primary landing, lastVisit, Within Area / All grant labels, and Death Reporter actions", () => {
    expect(homeLanding(bootstrap(["coder", "reviewer"], { reviewing: true }), undefined)).toBe("/coding");
    expect(homeLanding(bootstrap(["coder", "reviewer"], { reviewing: true }), "/reviewing")).toBe("/reviewing");
    // A data manager supervises too, and supervisors work in the Deaths tab: it is their first role screen.
    expect(homeLanding(bootstrap(["data_manager"], { supervision: true }), undefined)).toBe("/death-registration");
    expect(roleScreens(bootstrap(["data_manager"], { supervision: true }))).toEqual(["/death-registration"]);
    expect(roleScreens(bootstrap(["interview_supervisor"], { supervision: true }))).toEqual(["/death-registration"]);
    expect(roleScreens(bootstrap(["coder"]))).not.toContain("/death-registration");
    expect(roleScreens(bootstrap(["data_manager"], { supervision: true }))).not.toContain("/supervision");

    rememberVisit("u1", "/supervision");
    expect(readLastVisit("u1")).toBe("/supervision");

    expect(claimFirstHomeLoad("u1")).toBe(true);
    expect(claimFirstHomeLoad("u1")).toBe(false);
    resetFirstHomeLoad();
    expect(claimFirstHomeLoad("u1")).toBe(true);

    const fmt = (k: string, p?: Record<string, string | number>) => (p ? `${k}:${JSON.stringify(p)}` : k);
    const unitLabel = describeProjectGrant(
      { role: "coder", scope: "org_unit", org_unit_id: "u1", unit_name: "PHC 1", codes: true, active: true, source: "assigned" },
      [],
      fmt,
    );
    expect(unitLabel).toContain("role_coder");
    expect(unitLabel).toContain("PHC 1");

    const containerSiteLabel = describeProjectGrant(
      { role: "reviewer", scope: "project_site", site_id: "S01", codes: true, active: true, source: "assigned" },
      [{ site_id: "S01", site_name: "Sites_in_project_TST001", roles: ["reviewer"] }],
      fmt,
    );
    expect(containerSiteLabel).toContain("homeScopeProject");
    expect(containerSiteLabel).not.toContain("Sites_in_project_TST001");

    const grouped = describeProjectGrants(
      [
        { role: "interviewer", scope: "org_unit", org_unit_id: "u1", unit_name: "PHC-AAM 1", active: true, source: "assigned" },
        { role: "interviewer", scope: "org_unit", org_unit_id: "u2", unit_name: "SC-AAM 1", active: true, source: "assigned" },
      ],
      [],
      fmt,
    );
    expect(grouped).toHaveLength(1);
    expect(grouped[0]).toContain("PHC-AAM 1, SC-AAM 1");

    const deathReporterActions = projectActionItems(
      {
        project_id: "TST001",
        project_name: "Test Project",
        has_tree: false,
        grants: [{ role: "death_reporter", scope: "org_unit", org_unit_id: "u1", unit_name: "SC 1", active: true, source: "assigned" }],
        sites: [],
        actions: {
          interview: [],
          register_death: [{ site_id: "S01", site_name: "S01", web_intake_mode: "death_register", org_units: [] }],
        },
      },
      ["death_reporter"],
    );
    expect(deathReporterActions.map((a) => a.key)).toEqual(["registerDeath", "myRegisteredDeaths"]);
  });
});
