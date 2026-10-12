import React, { type ReactNode } from "react";
import { Text } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ClientApiError } from "../src/client/api";
import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

const mockRequest = jest.fn();
let mockBootstrap: { csrf: { header: string; token: string }; access: { roles: string[] } } | undefined;

jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "server error",
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, loading, accessibilityLabel, expanded }: { label: string; onPress: () => void; loading?: boolean; accessibilityLabel?: string; expanded?: boolean }) => (
    <button
      data-label={label}
      data-a11y-label={accessibilityLabel}
      data-expanded={expanded ? "yes" : "no"}
      data-loading={loading ? "yes" : "no"}
      onClick={onPress}
    />
  ),
  useUiStyles: () => ({ card: {}, text: {}, muted: {}, headline: {}, error: {} }),
}));

import OrganizationScreen from "../src/web/OrganizationScreen";

const ROOT_UNIT = { org_unit_id: "U0", unit_name: "District", level_name: "District", people: [{ name: "Dr Root", cadre: "CS" }] };
const MID_UNIT = { org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC", people: [{ name: "Asha Mid", cadre: "MO" }] };

function project(overrides: Record<string, unknown> = {}) {
  return {
    project_id: "P1",
    project_name: "Project One",
    my_units: [{ org_unit_id: "U2", unit_name: "Sub-centre B", level_name: "Sub-centre", cadres: ["ANM", "MPW"] }],
    above: [ROOT_UNIT, MID_UNIT],
    my_level: [{ org_unit_id: "U2", unit_name: "Sub-centre B", people: [{ name: "Meena", cadre: "ANM" }] }],
    below: [{ org_unit_id: "U3", unit_name: "Village X", level_name: "Village", people_count: 2, has_children: true }],
    ...overrides,
  };
}

const VILLAGE_PEOPLE = {
  unit: { org_unit_id: "U3", unit_name: "Village X", level_name: "Village" },
  people: [{ name: "Ravi", cadre: "CHO" }],
  children: [{ org_unit_id: "U4", unit_name: "Hamlet Y", level_name: "Hamlet", people_count: 1, has_children: false }],
};

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<OrganizationScreen />);
  });
  await settle();
  return tree;
}

function text(tree: ReactTestRenderer): string {
  return JSON.stringify(tree.toJSON());
}

/** Host elements only: a composite View and the host node beneath it would otherwise both match. */
const host = (n: { type: unknown }) => typeof n.type === "string";
const textOf = (node: ReactTestInstance) =>
  node.findAllByType(Text).map((n) => [n.props.children].flat().join("")).join("|");

const HAMLET_PEOPLE = {
  unit: { org_unit_id: "U4", unit_name: "Hamlet Y", level_name: "Hamlet" },
  people: [{ name: "Kofi", cadre: "ASHA" }],
  children: [],
};

function findButton(tree: ReactTestRenderer, accessibilityLabel: string) {
  return tree.root.findAll((node) => node.type === "button" && node.props["data-a11y-label"] === accessibilityLabel)[0];
}

async function pressOpen(tree: ReactTestRenderer, index = 0) {
  const buttons = tree.root.findAll((node) => node.type === "button" && node.props["data-label"] !== undefined);
  const target = buttons.filter((node) => node.props["data-label"] === en.orgOpen || node.props["data-label"] === en.orgClose)[index];
  if (!target) throw new Error(`no open button at ${index}`);
  await act(async () => {
    target.props.onClick();
  });
  await settle();
}

describe("OrganizationScreen", () => {
  beforeEach(() => {
    mockRequest.mockReset();
    mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: ["coder"] } };
  });

  it("renders one tree: ancestors nested root-first, then my level, then the units below", async () => {
    mockRequest.mockResolvedValue({ projects: [project()] });
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/me");
    const shown = text(tree);
    for (const heading of [en.orgWhereIAm, en.orgAbove, en.orgMyLevel, en.orgBelow]) {
      expect(shown).not.toContain(heading);
    }
    expect(shown).toContain("Dr Root · CS");
    expect(shown).toContain("Asha Mid · MO");
    expect(shown).toContain("Meena · ANM");
    expect(shown).toContain("2 people");
    expect(shown).not.toContain("Project One");

    const items = (node: { findAll: (p: (n: any) => boolean) => any[] }) => node.findAll((n) => host(n) && n.props.role === "treeitem");
    const [root] = tree.root.findAll((n) => host(n) && n.props.role === "tree");
    const [district, phc, subcentre, village] = items(root);
    expect(textOf(district)).toContain("District · District");
    // Each treeitem contains the next one: ancestors are nested root-first, not listed side by side.
    expect(items(district)).toContain(phc);
    expect(items(phc)).toContain(subcentre);
    expect(items(subcentre)).toContain(village);
    expect(textOf(village)).toContain("Village X · Village");
    expect(textOf(district).indexOf("District")).toBeLessThan(textOf(district).indexOf("PHC A"));
  });

  it("highlights the user's own unit with a You badge and cadres, and no other node", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({ my_level: [
        { org_unit_id: "U2", unit_name: "Sub-centre B", people: [] },
        { org_unit_id: "U9", unit_name: "Sub-centre C", people: [] },
      ] })],
    });
    const tree = await render();

    const selected = tree.root.findAll((n) => host(n) && n.props["aria-selected"] === true);
    expect(selected).toHaveLength(1);
    const shown = textOf(selected[0]);
    expect(shown).toContain("Sub-centre B · Sub-centre");
    expect(shown).toContain(en.orgYou);
    expect(shown).toContain("Cadres: ANM, MPW");
    expect(text(tree)).toContain("Sub-centre C");
    expect(text(tree).split(en.orgCadres.split("{")[0]).length - 1).toBe(1);
  });

  it("opening a below unit fetches its people and children, and closing it hides them", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await pressOpen(tree);
    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/units/U3/people");
    expect(text(tree)).toContain("Ravi · CHO");
    expect(text(tree)).toContain("Hamlet Y");

    await pressOpen(tree);
    expect(text(tree)).not.toContain("Ravi · CHO");
  });

  it("closing a unit collapses its children, so reopening it shows them closed", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      if (path === "/api/v1/organization/units/U4/people") return HAMLET_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await pressOpen(tree, 0);
    await pressOpen(tree, 1);
    expect(text(tree)).toContain("Kofi · ASHA");

    await pressOpen(tree, 0);
    await pressOpen(tree, 0);
    expect(text(tree)).toContain("Hamlet Y");
    expect(text(tree)).not.toContain("Kofi · ASHA");
    expect(findButton(tree, "Open Hamlet Y").props["data-expanded"]).toBe("no");
  });

  it("names each open button after its unit and exposes whether it is expanded", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    expect(findButton(tree, "Open Village X").props["data-expanded"]).toBe("no");
    await pressOpen(tree);
    expect(findButton(tree, "Close Village X").props["data-expanded"]).toBe("yes");
    expect(findButton(tree, "Open Village X")).toBeUndefined();
  });

  it("a unit whose load failed offers Open again, and Open retries the load", async () => {
    let villageCalls = 0;
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") {
        villageCalls += 1;
        if (villageCalls === 1) throw new ClientApiError(500, "server_error");
        return VILLAGE_PEOPLE;
      }
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await pressOpen(tree);
    expect(text(tree)).toContain("server error");
    expect(findButton(tree, "Open Village X").props["data-expanded"]).toBe("no");

    await pressOpen(tree);
    expect(villageCalls).toBe(2);
    expect(text(tree)).toContain("Ravi · CHO");
    expect(findButton(tree, "Close Village X").props["data-expanded"]).toBe("yes");
  });

  it("shows only name and cadre for each person, even when the API sends contact fields", async () => {
    const leaky = { name: "Dr Root", cadre: "CS", email: "root@example.com", phone: "9000000001", worker_code: "WC-77", user_id: "uid-9" };
    mockRequest.mockResolvedValue({ projects: [project({ above: [{ ...ROOT_UNIT, people: [leaky] }] })] });
    const tree = await render();

    const shown = text(tree);
    expect(shown).toContain("Dr Root · CS");
    for (const hidden of ["root@example.com", "9000000001", "WC-77", "uid-9"]) {
      expect(shown).not.toContain(hidden);
    }
  });

  it("a unit the user may not open shows an error and the page still renders", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      throw new ClientApiError(404, "not_found");
    });
    const tree = await render();

    await pressOpen(tree);
    const shown = text(tree);
    expect(shown).toContain(en.orgUnitNotAllowed);
    expect(shown).toContain("Sub-centre B");
    expect(shown).toContain("Village X");
  });

  it("keeps the no-placement message when the user holds no unit", async () => {
    mockRequest.mockResolvedValue({ projects: [project({ my_units: [], my_level: [] })] });
    const tree = await render();

    expect(text(tree)).toContain(en.orgNoPlacement);
    expect(tree.root.findAll((n) => host(n) && n.props["aria-selected"] === true)).toHaveLength(0);
  });

  it("shows the project name only when there are two projects", async () => {
    mockRequest.mockResolvedValue({ projects: [project(), project({ project_id: "P2", project_name: "Project Two" })] });
    const tree = await render();

    expect(text(tree)).toContain("Project One");
    expect(text(tree)).toContain("Project Two");
  });

  it("says so when the user is in no organization tree", async () => {
    mockRequest.mockResolvedValue({ projects: [] });
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/me");
    expect(text(tree)).toContain(en.orgNotInTree);
    expect(text(tree)).not.toContain("Sub-centre B");
  });

  it("shows the error and no sections when the list call fails", async () => {
    mockRequest.mockRejectedValue(new TypeError("network down"));
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/me");
    expect(text(tree)).toContain("server error");
    expect(text(tree)).not.toContain("Sub-centre B");
  });
});

describe("My organization strings", () => {
  const keys = [
    "navOrganization", "organizationTitle", "orgNotInTree", "orgWhereIAm", "orgNoPlacement", "orgUnitLine",
    "orgCadres", "orgAbove", "orgMyLevel", "orgBelow", "orgNone", "orgNoPeople", "orgPersonLine",
    "orgPeopleCount", "orgOpen", "orgClose", "orgOpenUnit", "orgCloseUnit", "orgUnitNotAllowed", "kpiLine",
  ] as const;

  it("has the tree strings in English (other locales fall back to it)", () => {
    expect(en.orgYouAreHere).toBeTruthy();
    expect(en.orgYou).toBeTruthy();
  });

  it.each(keys)("has %s in English and Hindi", (key) => {
    expect(en[key]).toBeTruthy();
    expect(hi[key]).toBeTruthy();
  });
});
