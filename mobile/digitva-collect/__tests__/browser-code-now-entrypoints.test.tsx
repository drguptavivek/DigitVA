import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

let mockParams: Record<string, string> = {};
let mockBootstrap: Record<string, unknown>;
let mockCases: unknown[] = [];
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockWorkspaceApi = {
  codeOwnSubmission: jest.fn().mockResolvedValue({ va_sid: "sid" }),
  releaseCoding: jest.fn().mockResolvedValue({ va_sid: "other", workflow_state: "ready_for_coding" }),
};

jest.mock("expo-router", () => ({ useLocalSearchParams: () => mockParams, useRouter: () => mockRouter }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap, reload: mockReload }) }));
jest.mock("../src/client/api", () => ({
  getCaseDetail: async () => ({ case: {
    death_id: "death-id", unique_id: "unique-id", state: "submitted", code_now: true, va_sid: "sid",
  } }),
  getCases: async () => ({ cases: mockCases, next_cursor: null }),
  getDrafts: async () => ({ drafts: [] }),
  getIntakeContext: async () => ({ context: [] }),
}));
jest.mock("../src/client/revisions", () => ({ getSubmittedRevisions: async () => [] }));
jest.mock("../src/workspace/api", () => ({ createWorkspaceApi: () => mockWorkspaceApi }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => jest.fn() }));
jest.mock("../src/workspace/CodeNowButton", () => jest.requireActual("../src/workspace/CodeNowButton"));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) => ReactActual.createElement("button", {
      accessibilityRole: "button", accessibilityLabel: label, disabled, onPress,
    }),
    stateLabel: (value: string) => value,
    useUiStyles: () => ({ error: {}, muted: {}, text: {}, headline: {}, card: {}, row: {} }),
  };
});
jest.mock("../src/web/common", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return { WebShell: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("web-shell", null, children) };
});
jest.mock("../src/web/newCasePreview", () => ({ rememberCasePreviews: jest.fn() }));
jest.mock("../src/web/registrationControls", () => ({ RegistrationFieldControl: () => null }));

import CollectionScreen from "../src/web/CollectionScreen";
import NewCaseDetailScreen from "../src/web/newCaseDetailScreen";

function bootstrap(roles: string[]) {
  return {
    user: { user_id: "coder-user", name: "Coder" },
    csrf: { header: "X-CSRFToken", token: "csrf" },
    access: { user: { user_id: "coder-user", name: "Coder" }, roles, is_admin: false, demo_coding: { available: false, project_ids: [] }, projects: [] },
    capabilities: { intake: true, registerDeath: false, registeredDeaths: false, coding: roles.includes("coder"), reviewing: false },
    links: { login: "/login", logout: "/logout", intakeCases: "/cases", intakeDrafts: "/drafts" },
  };
}

function button(root: ReactTestInstance, label: string) {
  return root.findAll((node) => node.props.accessibilityRole === "button" && node.props.accessibilityLabel === label)[0];
}

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

describe("browser Code now entry points", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = {};
    mockCases = [];
    mockBootstrap = bootstrap(["coder"]);
  });

  test("post-submit readiness hint lets a coder explicitly allocate and open the returned SID", async () => {
    mockParams = { canCodeNow: "1", readyUniqueId: "unique-id", readyVaSid: "sid" };
    const renderer = await render(<CollectionScreen />);
    expect(button(renderer.root, "codeNow")).toBeDefined();
    expect(mockWorkspaceApi.codeOwnSubmission).not.toHaveBeenCalled();
    await act(async () => { button(renderer.root, "codeNow")?.props.onPress(); });
    await settle();
    expect(mockWorkspaceApi.codeOwnSubmission).toHaveBeenCalledWith("sid");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/workspace", params: { vaSid: "sid", mode: "coding" } });
    await act(async () => { renderer.unmount(); });
  });

  test("case detail readiness opens the same real workspace after an explicit action", async () => {
    mockParams = { deathId: "death-id" };
    const renderer = await render(<NewCaseDetailScreen />);
    expect(button(renderer.root, "codeNow")).toBeDefined();
    await act(async () => { button(renderer.root, "codeNow")?.props.onPress(); });
    await settle();
    expect(mockWorkspaceApi.codeOwnSubmission).toHaveBeenCalledWith("sid");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/workspace", params: { vaSid: "sid", mode: "coding" } });
    await act(async () => { renderer.unmount(); });
  });

  test("case detail does not offer Code now to an admin without a coder grant", async () => {
    mockBootstrap = bootstrap(["admin"]);
    mockParams = { deathId: "death-id" };
    const renderer = await render(<NewCaseDetailScreen />);
    expect(button(renderer.root, "codeNow")).toBeUndefined();
    expect(JSON.stringify(renderer.toJSON())).toContain("readyForCodeOnWeb");
    expect(mockWorkspaceApi.codeOwnSubmission).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });
});
