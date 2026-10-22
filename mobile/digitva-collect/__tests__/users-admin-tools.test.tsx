import React, { type ReactNode } from "react";
import { Text, TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { gridQuery, primaryUnit, rolesAt, type GridUser } from "../src/users/api";

let mockWidth = 1280;
let mockRoles = ["admin"];
const mockRequest = jest.fn();

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: () => ({ width: mockWidth, height: 900, scale: 1, fontScale: 1 }), configurable: true });
  return actual;
});
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: mockRoles } } }),
}));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: (error: Error) => error.message,
}));
jest.mock("../src/web/DeathsList", () => ({ formatDisplayTimestamp: (value: string) => value }));
jest.mock("../src/web/caseFilters", () => {
  const actual = jest.requireActual("../src/web/caseFilters");
  const { TextInput: Input } = jest.requireActual("react-native");
  return { ...actual, DateField: ({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) => (
    <Input accessibilityLabel={label} value={value} onChangeText={onChange} />
  ) };
});

import UsersScreen from "../src/web/UsersScreen";
import { AccountUpload } from "../src/web/UsersAdminTools";

const P1 = "unit:U1";
const ASHA: GridUser = {
  user_id: "u1", name: "Asha Devi", email: "asha@example.org", phone: "9876500001", active: true,
  created_at: "2026-10-20T10:00:00+00:00",
  grants: [
    { role: "interviewer", scope: "org_unit", project_id: "P1", project_name: "Project One", site_id: null, site_name: null, org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC", unit: P1 },
    { role: "coder", scope: "org_unit", project_id: "P1", project_name: "Project One", site_id: null, site_name: null, org_unit_id: "U2", unit_name: "PHC B", level_name: "PHC", unit: "unit:U2" },
  ],
  enrolment: { status: "none", devices: 0, revoked_devices: 0, last_seen_at: null },
};
const LIST = { users: [], total: 0, limit: 50, offset: 0, options: { projects: [{ project_id: "P1", project_name: "Project One" }], units: [] } };
const GRID = {
  users: [ASHA], total: 1, limit: 50, offset: 0,
  options: { mode: "organization", units: [{ key: P1, label: "PHC A (PHC)", depth: 2 }, { key: "unit:U2", label: "PHC B (PHC)", depth: 2 }],
    cadres: [{ cadre_id: "c1", cadre_code: "MO", cadre_name: "Medical officer" }] },
};

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const mounted: ReactTestRenderer[] = [];
async function render(node: React.ReactElement = <UsersScreen />): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(node);
  });
  await settle();
  mounted.push(tree);
  return tree;
}
afterEach(() => {
  act(() => { mounted.splice(0).forEach((tree) => tree.unmount()); });
});

const byTestId = (tree: ReactTestRenderer, id: string) => tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === id);
const text = (tree: ReactTestRenderer) => tree.root.findAllByType(Text).map((n) => [n.props.children].flat().join("")).join("|");
const lastCall = () => mockRequest.mock.calls.at(-1) ?? [];

async function press(tree: ReactTestRenderer, label: string) {
  const [target] = tree.root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === label);
  if (!target) throw new Error(`no control labelled ${label}`);
  await act(async () => { target.props.onPress(); });
  await settle();
}
async function type(tree: ReactTestRenderer, label: string, value: string) {
  const [input] = tree.root.findAll((n) => n.type === TextInput && n.props.accessibilityLabel === label);
  if (!input) throw new Error(`no input labelled ${label}`);
  await act(async () => { input.props.onChangeText(value); });
  await settle();
}
const checked = (tree: ReactTestRenderer, role: string) =>
  tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === `grid-role-${role}`)[0].props.accessibilityState.checked;

function route(path: string, init?: { method?: string; json?: unknown }) {
  if (path.startsWith("/api/v1/users/grid")) return Promise.resolve(GRID);
  if (path.endsWith("/grants")) {
    return Promise.resolve({ user: { ...ASHA, grants: [{ ...ASHA.grants[0], role: "reviewer" }] }, changes: 2, invited: true, enrolment_email: null, warnings: ["mail note"] });
  }
  if (path.endsWith("/import/preview") || path.endsWith("/import/apply")) {
    const applied = path.endsWith("/apply");
    return Promise.resolve({
      rows: [
        { row: 2, name: "New", email: "new@example.org", phone: "******1111", status: "new", reason: null, phone_clash: false },
        { row: 3, name: "Bad", email: "bad", phone: null, status: "invalid", reason: "invalid email", phone_clash: false },
      ],
      counts: { new: 1, exists: 0, invalid: 1 },
      ...(applied ? { created: 1 } : {}),
      init,
    });
  }
  return Promise.resolve(LIST);
}

describe("Users admin tools", () => {
  beforeEach(() => {
    mockWidth = 1280;
    mockRoles = ["admin"];
    mockRequest.mockReset();
    mockRequest.mockImplementation(route);
  });

  it("offers the grid and upload views to an admin only", async () => {
    const admin = await render();
    expect(text(admin)).toContain("Grant access");
    mockRoles = ["data_manager"];
    const dm = await render();
    expect(dm.root.findAll((n) => n.props.accessibilityLabel === "View: Grant access")).toHaveLength(0);
  });

  it("builds the grid query from set filters only", () => {
    expect(gridQuery({ project: "P1", from: "2026-01-01", to: "", q: " asha ", role: "", status: "all" }, 50))
      .toBe("/api/v1/users/grid?project=P1&from=2026-01-01&q=asha&limit=50&offset=50");
  });

  it("picks the row's unit where the user holds the most grid roles", () => {
    expect(primaryUnit(ASHA, "project")).toBe(P1);
    expect(rolesAt(ASHA, "unit:U2")).toEqual(["coder"]);
    expect(primaryUnit({ ...ASHA, grants: [] }, "project")).toBe("project");
  });

  it("asks for a project, then queries the grid with the filters", async () => {
    const tree = await render();
    await press(tree, "View: Grant access");
    expect(text(tree)).toContain("Choose a project to grant access in.");
    expect(mockRequest.mock.calls.some(([path]) => String(path).startsWith("/api/v1/users/grid"))).toBe(false);
    await press(tree, "Filter: Project One");
    expect(lastCall()[0]).toBe("/api/v1/users/grid?project=P1&limit=50");
    await type(tree, "Created from", "2026-10-01");
    expect(lastCall()[0]).toBe("/api/v1/users/grid?project=P1&from=2026-10-01&limit=50");
    await press(tree, "Filter: Interviewer");
    expect(lastCall()[0]).toContain("role=interviewer");
    expect(byTestId(tree, "grid-table")).toHaveLength(1);
    expect(text(tree)).toContain("Created 2026-10-20T10:00:00+00:00");
    expect(text(tree)).toContain("Coder · PHC B");  // the other unit, read only
    expect(checked(tree, "interviewer")).toBe(true);
    expect(checked(tree, "coder")).toBe(false);
  });

  it("shows cards on a phone", async () => {
    mockWidth = 375;
    const tree = await render();
    await press(tree, "View: Grant access");
    await press(tree, "Filter: Project One");
    expect(byTestId(tree, "grid-card")).toHaveLength(1);
    expect(byTestId(tree, "grid-table")).toHaveLength(0);
  });

  it("edits a row and saves one diff for the project and unit", async () => {
    const tree = await render();
    await press(tree, "View: Grant access");
    await press(tree, "Filter: Project One");
    await press(tree, "Edit access for Asha Devi");
    await press(tree, "Interview for Asha Devi");
    await press(tree, "Review for Asha Devi");
    await type(tree, "Name", "Asha D");
    await press(tree, "Filter: Medical officer");
    await press(tree, "Inactive for Asha Devi");
    await press(tree, "Save changes for Asha Devi");
    expect(lastCall()).toEqual(["/api/v1/users/u1/grants", {
      method: "POST",
      json: { project_id: "P1", unit: P1, roles: ["reviewer"], name: "Asha D", active: false, cadre_id: "c1" },
    }]);
    expect(text(tree)).toContain("Invitation email sent.");
    expect(text(tree)).toContain("mail note");
    expect(checked(tree, "reviewer")).toBe(true);
  });

  it("switching the unit in edit mode shows the roles held there", async () => {
    const tree = await render();
    await press(tree, "View: Grant access");
    await press(tree, "Filter: Project One");
    await press(tree, "Edit access for Asha Devi");
    await press(tree, "Filter: PHC B (PHC)");
    expect(checked(tree, "coder")).toBe(true);
    expect(checked(tree, "interviewer")).toBe(false);
    await press(tree, "Save changes for Asha Devi");
    expect(lastCall()[1]).toEqual({ method: "POST", json: { project_id: "P1", unit: "unit:U2", roles: ["coder"] } });
  });

  it("previews an upload, then applies the same file", async () => {
    const file = { filename: "a.csv", content: "bmFtZQ==" };
    const tree = await render(<AccountUpload request={mockRequest} pickFile={() => Promise.resolve(file)} />);
    await press(tree, "Choose file");
    expect(lastCall()).toEqual(["/api/v1/users/import/preview", { method: "POST", json: file }]);
    expect(text(tree)).toContain("1 new, 0 already exist, 1 invalid");
    expect(text(tree)).toContain("Invalid · invalid email");
    expect(byTestId(tree, "upload-row")).toHaveLength(2);
    await press(tree, "Create 1 account(s)");
    expect(lastCall()).toEqual(["/api/v1/users/import/apply", { method: "POST", json: file }]);
    expect(text(tree)).toContain("1 account(s) created.");
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Create 1 account(s)")).toHaveLength(0);
  });

  it("does nothing when the file picker is cancelled", async () => {
    const tree = await render(<AccountUpload request={mockRequest} pickFile={() => Promise.resolve(undefined)} />);
    await press(tree, "Choose file");
    expect(mockRequest).not.toHaveBeenCalled();
  });
});
