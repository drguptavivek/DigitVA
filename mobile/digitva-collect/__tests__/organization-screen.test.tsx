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
  Button: () => null,
  useUiStyles: () => ({ card: {}, text: {}, muted: {}, headline: {}, error: {} }),
}));

import OrganizationScreen from "../src/web/OrganizationScreen";

const ROOT_UNIT = { org_unit_id: "U0", unit_name: "District", level_name: "District", parent_org_unit_id: null, people: [{ name: "Dr Root", cadre: "CS" }] };
const MID_UNIT = { org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC", parent_org_unit_id: "U0", people: [{ name: "Asha Mid", cadre: "MO" }] };

function project(overrides: Record<string, unknown> = {}) {
  return {
    project_id: "P1",
    project_name: "Project One",
    my_units: [{ org_unit_id: "U2", unit_name: "Sub-centre B", level_name: "Sub-centre", cadres: ["ANM", "MPW"] }],
    above: [ROOT_UNIT, MID_UNIT],
    my_level: [{ org_unit_id: "U2", unit_name: "Sub-centre B", parent_org_unit_id: "U1", people: [{ name: "Meena", cadre: "ANM" }] }],
    below: [{ org_unit_id: "U3", unit_name: "Village X", level_name: "Village", parent_org_unit_id: "U2", people_count: 2, has_children: true }],
    ...overrides,
  };
}

const VILLAGE_PEOPLE = {
  unit: { org_unit_id: "U3", unit_name: "Village X", level_name: "Village" },
  people: [{ name: "Ravi", cadre: "CHO" }],
  children: [{ org_unit_id: "U4", unit_name: "Hamlet Y", level_name: "Hamlet", people_count: 1, has_children: true }],
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

/** The header Pressable carrying this accessibilityLabel (the node that carries onPress). */
function findButton(tree: ReactTestRenderer, label: string) {
  return tree.root.findAll(
    (n) => typeof n.props.onPress === "function" && n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label,
  )[0];
}

const expandedOf = (tree: ReactTestRenderer, label: string) => findButton(tree, label).props.accessibilityState.expanded;

async function press(tree: ReactTestRenderer, label: string) {
  const target = findButton(tree, label);
  if (!target) throw new Error(`no button labelled ${label}`);
  await act(async () => {
    target.props.onPress();
  });
  await settle();
}

/** The people badge of a unit, found by its show-members label. */
const badge = (name: string) => `Show members of ${name}`;
const dialogs = (tree: ReactTestRenderer) => tree.root.findAll((n) => host(n) && n.props.role === "dialog");

/** Press by label prefix (the badge label carries the count after the unit name). */
async function pressBadge(tree: ReactTestRenderer, name: string) {
  const target = tree.root.findAll(
    (n) => typeof n.props.onPress === "function" && String(n.props.accessibilityLabel ?? "").startsWith(badge(name)),
  )[0];
  if (!target) throw new Error(`no badge for ${name}`);
  await act(async () => {
    target.props.onPress();
  });
  await settle();
}

async function closeFlyout(tree: ReactTestRenderer) {
  const close = tree.root.findAll((n) => n.props.nativeID === "org-people-close" && typeof n.props.onPress === "function")[0];
  await act(async () => {
    close.props.onPress();
  });
}

const CADRES = ["ANM", "MPW", "CS", "MO", "CHO", "ASHA", "Cadres"];

describe("OrganizationScreen", () => {
  beforeEach(() => {
    mockRequest.mockReset();
    mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: ["coder"] } };
  });

  it("folds a branch on its own arrow", async () => {
    mockRequest.mockResolvedValue({ projects: [project()] });
    const tree = await render();
    const fold = "Fold units under District · District";
    expect(text(tree)).toContain("Village X");
    expect(expandedOf(tree, fold)).toBe(true);
    await press(tree, fold);
    expect(text(tree)).not.toContain("Village X");
    expect(text(tree)).not.toContain("Sub-centre B");
    expect(text(tree)).not.toContain("Dr Root");
    expect(expandedOf(tree, "Unfold units under District · District")).toBe(false);
    await press(tree, "Unfold units under District · District");
    expect(text(tree)).toContain("Village X");
  });

  it("renders one tree: ancestors nested root-first, then my level, then the units below", async () => {
    mockRequest.mockResolvedValue({ projects: [project()] });
    const tree = await render();

    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/me");
    const shown = text(tree);
    for (const heading of [en.orgWhereIAm, en.orgAbove, en.orgMyLevel, en.orgBelow]) {
      expect(shown).not.toContain(heading);
    }
    // People appear only in the flyout opened from a badge.
    for (const name of ["Dr Root", "Asha Mid", "Meena"]) expect(shown).not.toContain(name);
    expect(shown).not.toContain('"1 people"');
    expect(shown).not.toContain("Project One");
    expect(findButton(tree, "District · District")).toBeUndefined();

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

  it("opens one flyout of names only from the badge, and Close hides it", async () => {
    const leaky = { name: "Dr Root", cadre: "CS", roles: ["Coder", "Interview Supervisor"], email: "root@example.com", phone: "9000000001" };
    mockRequest.mockResolvedValue({ projects: [project({ above: [{ ...ROOT_UNIT, people: [leaky] }, MID_UNIT] })] });
    const tree = await render();

    expect(dialogs(tree)).toHaveLength(0);
    expect(text(tree)).not.toContain("Dr Root");
    await pressBadge(tree, "District");
    const [dialog] = dialogs(tree);
    expect(dialog.props["aria-modal"]).toBe(true);
    const shown = textOf(dialog);
    expect(shown).toContain("District · District");
    expect(shown).toContain("Dr Root");
    expect(shown).toContain("Coder · Interview Supervisor");
    expect(shown).not.toContain("Asha Mid");
    for (const hidden of [...CADRES, "root@example.com", "9000000001"]) expect(shown).not.toContain(hidden);

    await closeFlyout(tree);
    expect(dialogs(tree)).toHaveLength(0);
    expect(text(tree)).not.toContain("Dr Root");
  });

  it("closes on Escape and on the scrim, and a zero count still opens", async () => {
    const listeners: Record<string, (e: { key: string; preventDefault: () => void }) => void> = {};
    const g = globalThis as any;
    g.window = { addEventListener: (k: string, f: any) => { listeners[k] = f; }, removeEventListener: () => { delete listeners.keydown; } };
    g.document = { getElementById: () => null };
    try {
      mockRequest.mockResolvedValue({ projects: [project({ my_level: [{ org_unit_id: "U2", unit_name: "Sub-centre B", parent_org_unit_id: "U1", people: [] }] })] });
      const tree = await render();

      await pressBadge(tree, "Sub-centre B");
      expect(textOf(dialogs(tree)[0])).toContain(en.orgNoPeople);
      await act(async () => listeners.keydown({ key: "Escape", preventDefault() {} }));
      expect(dialogs(tree)).toHaveLength(0);

      await pressBadge(tree, "District");
      const scrim = tree.root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === "Close")[0];
      await act(async () => scrim.props.onPress());
      expect(dialogs(tree)).toHaveLength(0);
    } finally {
      delete g.window;
      delete g.document;
    }
  });

  it("a below unit's badge loads it, shows names, and a failed load shows the error", async () => {
    let calls = 0;
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") {
        calls += 1;
        if (calls === 1) throw new ClientApiError(500, "server_error");
        return VILLAGE_PEOPLE;
      }
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await pressBadge(tree, "Village X");
    expect(textOf(dialogs(tree)[0])).toContain("server error");
    expect(dialogs(tree)[0].findAll((n) => host(n) && n.props.accessibilityRole === "alert")).not.toHaveLength(0);
    await closeFlyout(tree);

    await pressBadge(tree, "Village X");
    expect(calls).toBe(2);
    expect(textOf(dialogs(tree)[0])).toContain("Ravi");
    expect(textOf(dialogs(tree)[0])).not.toContain("CHO");

    // Already loaded: opening the flyout again must not toggle the branch shut.
    await closeFlyout(tree);
    await pressBadge(tree, "Village X");
    expect(calls).toBe(2);
    expect(textOf(dialogs(tree)[0])).toContain("Ravi");
    expect(expandedOf(tree, "Close Village X")).toBe(true);
  });

  it("tints cards by unit type: same level shares colours, different levels differ", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({
        below: [
          { org_unit_id: "U3", unit_name: "Village X", level_name: "Village", parent_org_unit_id: "U2", people_count: 2, has_children: false },
          { org_unit_id: "U5", unit_name: "Village Z", level_name: "Village", parent_org_unit_id: "U2", people_count: 1, has_children: false },
        ],
      })],
    });
    const tree = await render();
    const flat = (style: unknown): Record<string, any> => Object.assign({}, ...[style].flat(Infinity).filter(Boolean));
    const card = (name: string) => {
      const item = tree.root.findAll((n) => host(n) && n.props.role === "treeitem" && textOf(n).startsWith(name))[0];
      return flat(item.findAll((n) => host(n) && n.props.style && flat(n.props.style).borderLeftWidth === 3)[0].props.style);
    };
    const [x, z, phc, district] = [card("Village X"), card("Village Z"), card("PHC A"), card("District")];
    expect(x.backgroundColor).toBeTruthy();
    expect(x.backgroundColor).toBe(z.backgroundColor);
    expect(x.borderLeftColor).toBe(z.borderLeftColor);
    expect(x.backgroundColor).not.toBe(phc.backgroundColor);
    expect(phc.borderLeftColor).not.toBe(district.borderLeftColor);
  });

  it("highlights the user's own unit with a You badge and no cadres line, and no other node", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({ my_level: [
        { org_unit_id: "U2", unit_name: "Sub-centre B", people: [] },
        { org_unit_id: "U9", unit_name: "Sub-centre C", parent_org_unit_id: "U1", people: [] },
      ] })],
    });
    const tree = await render();

    const selected = tree.root.findAll((n) => host(n) && n.props["aria-selected"] === true);
    expect(selected).toHaveLength(1);
    const shown = textOf(selected[0]);
    expect(shown).toContain("Sub-centre B · Sub-centre");
    expect(shown).toContain(en.orgYou);
    expect(text(tree)).toContain("Sub-centre C");
    for (const cadre of ["Cadres", "ANM", "MPW"]) expect(text(tree)).not.toContain(cadre);
  });

  it("nests two own units on one branch and their below siblings by real parentage", async () => {
    mockRequest.mockResolvedValue({
      projects: [project({
        my_units: [
          { org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC", cadres: ["MO"] },
          { org_unit_id: "U2", unit_name: "SC 1", level_name: "Sub-centre", cadres: ["ANM"] },
        ],
        above: [ROOT_UNIT],
        my_level: [
          { org_unit_id: "U1", unit_name: "PHC A", parent_org_unit_id: "U0", people: [] },
          { org_unit_id: "U2", unit_name: "SC 1", parent_org_unit_id: "U1", people: [] },
        ],
        below: [
          { org_unit_id: "U5", unit_name: "SC 2", level_name: "Sub-centre", parent_org_unit_id: "U1", people_count: 1, has_children: false },
          { org_unit_id: "U6", unit_name: "SC 3", level_name: "Sub-centre", parent_org_unit_id: "U1", people_count: 1, has_children: false },
        ],
      })],
    });
    const tree = await render();

    const items = (node: { findAll: (p: (n: any) => boolean) => any[] }) => node.findAll((n) => host(n) && n.props.role === "treeitem");
    const [root] = tree.root.findAll((n) => host(n) && n.props.role === "tree");
    const [district, phc] = items(root);
    expect(items(district)).toContain(phc);
    const inner = items(phc).filter((n) => n !== phc);
    expect(inner.map((n) => /SC \d/.exec(textOf(n))?.[0])).toEqual(["SC 1", "SC 2", "SC 3"]);
    // Siblings: none of the three contains another.
    for (const sc of inner) expect(items(sc).filter((n) => n !== sc)).toHaveLength(0);
    expect(root.findAll((n) => host(n) && n.props["aria-selected"] === true)).toHaveLength(2);
  });

  it("falls back to the flat layout when the server sends no parent ids", async () => {
    const strip = ({ parent_org_unit_id: _p, ...rest }: Record<string, unknown>) => rest;
    const base = project();
    mockRequest.mockResolvedValue({
      projects: [{ ...base, above: base.above.map(strip), my_level: base.my_level.map(strip), below: base.below.map(strip) }],
    });
    const tree = await render();

    const items = (node: { findAll: (p: (n: any) => boolean) => any[] }) => node.findAll((n) => host(n) && n.props.role === "treeitem");
    const [root] = tree.root.findAll((n) => host(n) && n.props.role === "tree");
    const [district, phc, subcentre, village] = items(root);
    expect(items(district)).toContain(phc);
    expect(items(phc)).toContain(subcentre);
    expect(items(subcentre)).toContain(village);
  });

  it("opening a below unit fetches its people and children, and closing it hides them", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await press(tree, "Open Village X");
    expect(mockRequest).toHaveBeenCalledWith("/api/v1/organization/units/U3/people");
    expect(text(tree)).not.toContain("Ravi");
    expect(text(tree)).toContain("Hamlet Y");
    await pressBadge(tree, "Village X");
    expect(textOf(dialogs(tree)[0])).toContain("Ravi");
    expect(textOf(dialogs(tree)[0])).not.toContain("CHO");
    await closeFlyout(tree);

    await press(tree, "Close Village X");
    expect(text(tree)).not.toContain("Hamlet Y");
  });

  it("closing a unit collapses its children, so reopening it shows them closed", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      if (path === "/api/v1/organization/units/U4/people") return HAMLET_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    await press(tree, "Open Village X");
    await press(tree, "Open Hamlet Y");
    expect(expandedOf(tree, "Close Hamlet Y")).toBe(true);

    await press(tree, "Close Village X");
    await press(tree, "Open Village X");
    expect(text(tree)).toContain("Hamlet Y");
    expect(expandedOf(tree, "Open Hamlet Y")).toBe(false);
  });

  it("names each open button after its unit and exposes whether it is expanded", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      if (path === "/api/v1/organization/units/U3/people") return VILLAGE_PEOPLE;
      throw new Error(`unexpected ${path}`);
    });
    const tree = await render();

    expect(expandedOf(tree, "Open Village X")).toBe(false);
    await press(tree, "Open Village X");
    expect(expandedOf(tree, "Close Village X")).toBe(true);
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

    await press(tree, "Open Village X");
    expect(text(tree)).toContain("server error");
    expect(expandedOf(tree, "Open Village X")).toBe(false);

    await press(tree, "Open Village X");
    expect(villageCalls).toBe(2);
    expect(text(tree)).toContain("Hamlet Y");
    expect(expandedOf(tree, "Close Village X")).toBe(true);
  });

  it("a unit the user may not open shows an error and the page still renders", async () => {
    mockRequest.mockImplementation(async (path: string) => {
      if (path === "/api/v1/organization/me") return { projects: [project()] };
      throw new ClientApiError(404, "not_found");
    });
    const tree = await render();

    await press(tree, "Open Village X");
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
    "orgPeopleCount", "orgShowMembers", "orgOpen", "orgClose", "orgOpenUnit", "orgCloseUnit", "orgUnitNotAllowed", "kpiLine",
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
