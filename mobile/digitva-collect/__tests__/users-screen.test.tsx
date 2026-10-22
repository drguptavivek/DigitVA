import React, { type ReactNode } from "react";
import { Image, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { usersQuery } from "../src/users/api";

let mockWidth = 1280;
const mockRequest = jest.fn();
const mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: ["data_manager"] } };

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: () => ({ width: mockWidth, height: 900, scale: 1, fontScale: 1 }), configurable: true });
  return actual;
});
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "server error",
}));
jest.mock("../src/web/DeathsList", () => ({ formatDisplayTimestamp: (value: string) => value }));

import UsersScreen from "../src/web/UsersScreen";

const ASHA = {
  user_id: "u1",
  name: "Asha Devi",
  email: "asha@example.org",
  phone: "9876500001",
  active: true,
  last_signed_in_at: null,
  grants: [{ role: "interviewer", scope: "org_unit", project_id: "P1", project_name: "Project One", site_id: null, site_name: null, org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC" }],
  enrolment: { status: "enrolled", devices: 1, revoked_devices: 0, last_seen_at: "2026-10-21T10:00:00Z" },
};
const PAGE = {
  users: [ASHA],
  total: 1,
  limit: 50,
  offset: 0,
  options: { projects: [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }], units: [] },
};
const ACTIVITY = {
  user_id: "u1", name: "Asha Devi",
  totals: { deaths_reported: 4, interviews_submitted: 7, drafts_in_progress: 1, coded: 0, not_codeable: 0, reviewed: 0 },
  by_project: {}, last_signed_in_at: null, last_device_seen_at: "2026-10-21T10:00:00Z", last_active_at: "2026-10-21T10:00:00Z",
};

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const mounted: ReactTestRenderer[] = [];

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<UsersScreen />);
  });
  await settle();
  mounted.push(tree);
  return tree;
}

// Unmount every screen, so its search-debounce timer never fires after the test.
afterEach(() => {
  act(() => { mounted.splice(0).forEach((tree) => tree.unmount()); });
});

/** Host nodes only: a composite View and its host node would otherwise both match. */
const byTestId = (tree: ReactTestRenderer, id: string) => tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === id);
const text = (tree: ReactTestRenderer) => tree.root.findAllByType(Text).map((n) => [n.props.children].flat().join("")).join("|");

async function press(tree: ReactTestRenderer, label: string) {
  const [target] = tree.root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === label);
  if (!target) throw new Error(`no button labelled ${label}`);
  await act(async () => {
    target.props.onPress();
  });
  await settle();
}

function route(path: string) {
  if (path.endsWith("/activity")) return Promise.resolve(ACTIVITY);
  if (path.endsWith("/enrolment-code")) return Promise.resolve({ code: "SECRET-CODE", qr_payload: "{}", qr_png: "iVBOR", project_id: "P1", expires_at: "2026-10-22T11:00:00Z", max_uses: 1 });
  return Promise.resolve(PAGE);
}

describe("UsersScreen", () => {
  beforeEach(() => {
    mockWidth = 1280;
    mockRequest.mockReset();
    mockRequest.mockImplementation(route);
  });

  it("renders a table on a wide screen and cards on a phone", async () => {
    const wide = await render();
    expect(byTestId(wide, "users-table")).toHaveLength(1);
    expect(text(wide)).toContain("asha@example.org");
    expect(text(wide)).toContain("9876500001");
    expect(text(wide)).toContain("Interviewer · PHC A");
    expect(byTestId(wide, "users-card")).toHaveLength(0);

    mockWidth = 375;
    const narrow = await render();
    expect(byTestId(narrow, "users-card").length).toBeGreaterThan(0);
    expect(byTestId(narrow, "users-table")).toHaveLength(0);
  });

  it("starts on active accounts and re-queries the server when a filter changes", async () => {
    const tree = await render();
    expect(mockRequest.mock.calls[0][0]).toBe("/api/v1/users?status=active&limit=50");
    await press(tree, "Filter: Not enrolled");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/users?status=active&enrolment=none&limit=50");
    await press(tree, "Filter: Project Two");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toContain("project=P2");
  });

  it("builds the query from set filters only", () => {
    expect(usersQuery({ q: " asha ", status: "all", role: "", unit: "U 1" }, 50)).toBe("/api/v1/users?q=asha&unit=U+1&limit=50&offset=50");
  });

  it("loads activity when it is opened", async () => {
    const tree = await render();
    expect(mockRequest.mock.calls.some(([path]) => String(path).endsWith("/activity"))).toBe(false);
    await press(tree, "Activity");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/users/u1/activity");
    expect(text(tree)).toContain("Interviews submitted");
    expect(text(tree)).toContain("7");
    expect(text(tree)).toContain("Last active: 2026-10-21T10:00:00Z");
  });

  it("issues an enrolment code and shows it once in a dialog", async () => {
    const tree = await render();
    await press(tree, "Issue an app enrolment code for Asha Devi");
    expect(text(tree)).toContain("App enrolment for Asha Devi");
    await press(tree, "Show code");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/enrolment-code", { method: "POST", json: { project_id: "P1", delivery: "show" } });
    expect(text(tree)).toContain("SECRET-CODE");
    expect(tree.root.findAllByType(Image)[0].props.source.uri).toBe("data:image/png;base64,iVBOR");
    await press(tree, "Close");
    expect(text(tree)).not.toContain("SECRET-CODE");
  });
});
