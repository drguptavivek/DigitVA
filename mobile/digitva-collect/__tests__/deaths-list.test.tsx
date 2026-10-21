import React, { type ReactNode } from "react";
import { StyleSheet } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The shared reported-deaths list (docs/policy/case-list-views.md) and the two screens that show it. */

const projectAccess = (projectId: string, name: string) => ({
  project_id: projectId, project_name: name, has_tree: false, grants: [], sites: [], units: [],
  actions: {
    interview: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
    register_death: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
  },
});

const makeBootstrap = (roles: string[], capabilities: Record<string, boolean>, projects = [projectAccess("P1", "Project One")]) => ({
  user: { user_id: "u1", name: "User" },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: false, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false, ...capabilities },
  access: { user: { user_id: "u1", name: "User" }, is_admin: false, roles, demo_coding: { available: false, project_ids: [] }, projects },
  links: { login: "/l", logout: "/o", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" },
});

let mockBootstrap = makeBootstrap(["interviewer"], { intake: true });
let mockParams: Record<string, string> = {};
const mockPush = jest.fn();
const mockSetParams = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), setParams: mockSetParams, back: jest.fn() }),
  useLocalSearchParams: () => mockParams,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap, reload: jest.fn() }) }));
jest.mock("../src/client/api", () => ({
  INTAKE_API: "/api/v1/intake",
  getCases: jest.fn(),
  getDrafts: jest.fn(),
  getIntakeContext: jest.fn(),
  registerDeath: jest.fn(),
  startDraft: jest.fn(),
}));
jest.mock("../src/client/revisions", () => ({ getSubmittedRevisions: jest.fn() }));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string> = {}) => key + (values.label ? `:${values.label}` : "") + (values.value ? `:${values.value}` : ""),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, kind }: { label: string; onPress: () => void; kind?: string }) =>
    <button data-label={label} data-kind={kind ?? "primary"} onClick={onPress} />,
  stateLabel: (state: string) => `state:${state}`,
  useUiStyles: () => ({ error: {}, muted: {}, card: {}, text: {}, row: {}, fieldLabel: {} }),
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));
jest.mock("../src/web/SupervisionPanel", () => ({ SupervisionPanel: () => <div data-supervision-panel="true" /> }));
jest.mock("../src/web/ContextualHelp", () => ({ ContextualHelpBanner: () => null }));
jest.mock("../src/web/registrationControls", () => ({ RegistrationFieldControl: () => null }));
jest.mock("../src/PhoneInput", () => ({ PhoneNumbers: () => null }));
jest.mock("../src/web/LocationCapture", () => ({
  LocationCapture: () => null,
  MapsLink: () => null,
  MapsPinButton: ({ latitude, longitude }: { latitude?: number | null; longitude?: number | null }) =>
    typeof latitude === "number" && typeof longitude === "number" ? <a data-maps-pin={`${latitude},${longitude}`} /> : null,
}));

import CollectionScreen from "../src/web/CollectionScreen";
import DeathRegistrationScreen from "../src/web/DeathRegistrationScreen";
import { DeathsList, DeathsListPanel } from "../src/web/DeathsList";
import { withinLastDays } from "../src/web/caseFilters";
import * as identifiersApi from "../src/identifiers";
import { getCases, getDrafts, getIntakeContext } from "../src/client/api";
import { getSubmittedRevisions } from "../src/client/revisions";

const mockGetCases = getCases as jest.Mock;

const today = new Date();
const daysAgo = (days: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate() - days, 12).toISOString();
const rows = [
  { death_id: "d1", unique_id: "UID-1", deceased_name: "Asha Devi", state: "registered", registered_by_me: true, created_at: daysAgo(2), project_id: "P1", site_id: "S1" },
  { death_id: "d2", unique_id: "UID-2", state: "in_progress", my_draft_id: "dr2", registered_by_me: false, created_at: daysAgo(3), project_id: "P1", site_id: "S1" },
  { death_id: "d3", unique_id: "UID-3", deceased_name: "Old Case", state: "submitted", registered_by_me: true, created_at: daysAgo(60), project_id: "P1", site_id: "S1" },
];

async function settle(): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(element); });
  await settle();
  return tree;
}

const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());
const pressable = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
const press = async (tree: ReactTestRenderer, label: string) => {
  const node = pressable(tree, label);
  expect(node).toBeDefined();
  await act(async () => node.props.onPress());
};
const selected = (tree: ReactTestRenderer, label: string) => pressable(tree, label)?.props.accessibilityState?.selected;
const titles = (tree: ReactTestRenderer) => tree.root.findByType(DeathsList)
  .findAll((node) => typeof node.type === "string" && node.props.testID === "death-card-title")
  .map((node) => node.props.children);

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = {};
  mockBootstrap = makeBootstrap(["interviewer"], { intake: true });
  mockGetCases.mockResolvedValue({ cases: rows, counts: { registered: 1, in_progress: 1, submitted: 1 }, next_cursor: null });
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [{ project_id: "P1", site_id: "S1", web_intake_mode: "both" }] });
  (getDrafts as jest.Mock).mockResolvedValue({ drafts: [] });
  (getSubmittedRevisions as jest.Mock).mockResolvedValue([]);
});

describe("DeathsList filter bar", () => {
  it("puts status chips left and the Mine and Last 30 days toggles right, with no project or area chips in the bar", async () => {
    mockBootstrap = makeBootstrap(["interviewer"], { intake: true }, [projectAccess("P1", "Project One"), projectAccess("P2", "Project Two")]);
    const tree = await render(<DeathsListPanel />);
    const left = tree.root.findAll((n) => n.props.testID === "case-filter-status-left")[0];
    const right = tree.root.findAll((n) => n.props.testID === "case-filter-status-right")[0];
    const labels = (node: ReactTestRenderer["root"]) => node.findAll((n) => typeof n.props.onPress === "function").map((n) => n.props.accessibilityLabel);
    expect(labels(left)).toEqual(["filterStatusLabel:filterAll", "filterStatusLabel:filterToVisit", "filterStatusLabel:filterInProgress", "filterStatusLabel:filterSubmitted"]);
    expect(labels(right)).toEqual(["filterWhoseLabel:filterMine", "filterWhoseLabel:filterAll", "filterPeriodLabel:filterLast30Days", "filterPeriodLabel:filterAll"]);
    expect(tree.root.findAll((n) => /^filter(Project|Area)Label/.test(String(n.props.accessibilityLabel)))).toHaveLength(0);

    // Project and Area are the first sections of the sheet.
    await press(tree, "advancedFilters");
    const sections = tree.root.findAll((n) => typeof n.type === "string" && ["filterProject", "filterArea", "filterDates", "filterSex"].includes(n.props.children)).map((n) => n.props.children);
    expect(sections[0]).toBe("filterProject");
    expect(sections.indexOf("filterProject")).toBeLessThan(sections.indexOf("filterDates"));
    await act(async () => tree.unmount());
  });

  it("applies a project from the sheet on the server, counts it in the badge and removes it as a chip", async () => {
    mockBootstrap = makeBootstrap(["interviewer"], { intake: true }, [projectAccess("P1", "Project One"), projectAccess("P2", "Project Two")]);
    const tree = await render(<DeathsListPanel />);
    mockGetCases.mockClear();
    await press(tree, "advancedFilters");
    await press(tree, "filterProjectLabel:Project Two");
    expect(mockGetCases).not.toHaveBeenCalled(); // nothing applies before Apply
    await act(async () => tree.root.findAll((n) => n.props["data-label"] === "applyFilters")[0].props.onClick());
    await settle();
    expect(mockGetCases).toHaveBeenCalledWith("/api/v1/intake/cases", mockBootstrap.csrf, null, "P2");
    expect(pressable(tree, "advancedFiltersActive")).toBeDefined();
    await press(tree, "removeFilter:filterProject: Project Two");
    await settle();
    expect(mockGetCases).toHaveBeenLastCalledWith("/api/v1/intake/cases", mockBootstrap.csrf, null, undefined);
    expect(pressable(tree, "advancedFilters")).toBeDefined();
    await act(async () => tree.unmount());
  });

  it("defaults to All for an interviewer and narrows to own registrations with Mine", async () => {
    const tree = await render(<DeathsListPanel />);
    expect(selected(tree, "filterWhoseLabel:filterAll")).toBe(true);
    expect(text(tree)).toContain("UID-2");
    await press(tree, "filterWhoseLabel:filterMine");
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).toContain("Old Case");
    expect(text(tree)).not.toContain("UID-2");
    await act(async () => tree.unmount());
  });

  it("defaults to Mine for a user whose only death role is death_reporter, and Clear all keeps that default", async () => {
    mockBootstrap = makeBootstrap(["death_reporter"], { registeredDeaths: true });
    const tree = await render(<DeathsListPanel />);
    expect(selected(tree, "filterWhoseLabel:filterMine")).toBe(true);
    expect(text(tree)).not.toContain("UID-2");
    await press(tree, "filterWhoseLabel:filterAll");
    expect(text(tree)).toContain("UID-2");
    await press(tree, "filterStatusLabel:filterSubmitted");
    await press(tree, "clearAll");
    expect(selected(tree, "filterWhoseLabel:filterMine")).toBe(true);
    await act(async () => tree.unmount());
  });

  it("keeps deaths reported in the last 30 days with Last 30 days, combined with the status chips", async () => {
    const tree = await render(<DeathsListPanel />);
    expect(selected(tree, "filterPeriodLabel:filterAll")).toBe(true);
    await press(tree, "filterPeriodLabel:filterLast30Days");
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).not.toContain("Old Case");
    await press(tree, "filterStatusLabel:filterInProgress");
    expect(text(tree)).toContain("UID-2");
    expect(text(tree)).not.toContain("Asha Devi");
    await act(async () => tree.unmount());
  });

  it("counts today and the 29 days before it, by local date", () => {
    const now = new Date(2026, 9, 20, 9);
    expect(withinLastDays(new Date(2026, 9, 20, 23).toISOString(), 30, now)).toBe(true);
    expect(withinLastDays(new Date(2026, 8, 21, 0, 5).toISOString(), 30, now)).toBe(true);
    expect(withinLastDays(new Date(2026, 8, 20, 23, 55).toISOString(), 30, now)).toBe(false);
    expect(withinLastDays(null, 30, now)).toBe(false);
    expect(withinLastDays("garbage", 30, now)).toBe(false);
  });
});

describe("DeathsList cards", () => {
  it("shows registration numbers on a card and the Add action only when the row says the caller may write", async () => {
    mockGetCases.mockResolvedValue({ cases: [
      { ...rows[0], identifiers: [{ code: "mccd", label: "MCCD number", value: "MCCD123" }], can_edit_identifiers: true },
      { ...rows[1], identifiers: [{ code: "mccd", label: "MCCD number", present: false }] },
    ], counts: {}, next_cursor: null });
    jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue([
      { code: "mccd", label: "MCCD number", min_length: 5, max_length: 12, char_type: null, pattern: null, example: null, required_at_report: false, sort_order: 1 },
    ]);
    const tree = await render(<DeathsListPanel />);
    expect(text(tree)).toContain("MCCD123");
    expect(text(tree)).toContain("idBadgeMissing:");
    expect(tree.root.findAll((n) => n.props["data-label"] === "idAddAction")).toHaveLength(1);
    await act(async () => tree.unmount());
  });

  it("shows the ID once, a status badge on every card and exactly one primary action", async () => {
    const tree = await render(<DeathsListPanel />);
    const rendered = text(tree);
    // Shown once each (the a11y "Case ID" label is the accessible name of that one copy).
    for (const id of ["UID-1", "UID-2", "UID-3"]) {
      expect(rendered.replace(new RegExp(`metaCaseIdA11y:${id}`, "g"), "").match(new RegExp(id, "g"))).toHaveLength(1);
    }
    expect(titles(tree)).toEqual(["Asha Devi", "UID-2", "Old Case"]);
    for (const state of ["state:registered", "state:in_progress", "state:submitted"]) expect(rendered).toContain(state);
    const cards = ["d1", "d2", "d3"].map((id) => tree.root.findAll((n) => n.props.testID === `death-card-${id}`)[0]);
    expect(cards.every(Boolean)).toBe(true);
    const primaries = cards.map((card) => card.findAll((n) => n.type === "button" && n.props["data-kind"] === "primary").map((n) => n.props["data-label"]));
    expect(primaries).toEqual([["startInterview"], ["resumeInterview"], ["editRegistration"]]);
    await act(async () => tree.unmount());
  });

  it("lays facts out as named list items in plain >= 14px high-contrast text, not chips", async () => {
    mockGetCases.mockResolvedValue({ cases: [{
      ...rows[0], age_years: 51, deceased_sex: "male", date_of_death: "2026-09-22", unit_name: "Taluka Hospital",
      has_informant_phone: true, last_contact_at: "2026-10-01", next_visit_at: "2026-10-25",
    }], next_cursor: null });
    const tree = await render(<DeathsListPanel />);
    const items = tree.root.findAll((n) => typeof n.type === "string" && n.props.role === "listitem");
    const named = Object.fromEntries(items.map((n) => [n.props.testID, n.props.accessibilityLabel]));
    expect(named).toEqual({
      "case-fact-age": "metaAgeA11y:51",
      "case-fact-sex": "metaSexA11y:male",
      "case-fact-died": "metaDiedA11y:2026-09-22",
      "case-fact-area": undefined,
      "case-fact-lastContact": undefined,
      "case-fact-nextVisit": undefined,
      "case-fact-caseId": "metaCaseIdA11y:UID-1",
    });
    // The card carries no phone fact at all, not even partial digits.
    expect(items.some((n) => String(n.props.testID).includes("phone"))).toBe(false);
    const { ui } = jest.requireActual("../src/theme") as typeof import("../src/theme");
    for (const item of items) {
      const style = StyleSheet.flatten(item.props.style);
      expect(style.fontSize).toBeGreaterThanOrEqual(14);
      expect(style.color).toBe(ui.light.foreground);
      // Plain text: no chip fill or border around a fact.
      expect(style.backgroundColor).toBeUndefined();
      expect(style.borderWidth).toBeUndefined();
      // Every fact sits in a list, so it is announced as one item of the card's facts.
      let list = item.parent;
      while (list && typeof list.type !== "string") list = list.parent;
      expect(list?.props.role).toBe("list");
      expect(StyleSheet.flatten(list?.props.style).backgroundColor).toBeUndefined();
    }
    // Order is kept: identity, then death, then contact, then the case ID.
    expect(items.map((n) => n.props.testID)).toEqual([
      "case-fact-age", "case-fact-sex", "case-fact-died", "case-fact-area",
      "case-fact-lastContact", "case-fact-nextVisit", "case-fact-caseId",
    ]);
    // Card buttons keep a 44px target.
    const buttons = tree.root.findAll((n) => typeof n.type === "function" && typeof n.props.label === "string" && typeof n.props.onPress === "function");
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(StyleSheet.flatten(button.props.style).minHeight).toBe(44);
    await act(async () => tree.unmount());
  });

  it("omits empty facts and shows the map pin only for a row that carries a GPS fix", async () => {
    mockGetCases.mockResolvedValue({ cases: [
      { ...rows[0], latitude: 12.97, longitude: 77.59 },
      { ...rows[2], latitude: null, longitude: null },
    ], next_cursor: null });
    const tree = await render(<DeathsListPanel />);
    const card = (id: string) => tree.root.findAll((n) => n.props.testID === `death-card-${id}`)[0];
    expect(card("d1").findAll((n) => n.type === "a" && n.props["data-maps-pin"] === "12.97,77.59")).toHaveLength(1);
    expect(card("d3")).toBeDefined();
    expect(card("d3").findAll((n) => n.type === "a")).toHaveLength(0);
    // No age, sex, date, phone or contact on these rows: no empty items.
    const facts = card("d1").findAll((n) => typeof n.type === "string" && n.props.role === "listitem").map((n) => n.props.testID);
    expect(facts).toEqual(["case-fact-caseId"]);
    await act(async () => tree.unmount());
  });

  it("offers a death reached only as its reporter for correction only, through the reporter's own list", async () => {
    mockGetCases.mockResolvedValue({ cases: [{ ...rows[0], can_interview: false }], next_cursor: null });
    const tree = await render(<DeathsListPanel />);
    expect(tree.root.findAll((n) => n.props["data-label"] === "startInterview")).toHaveLength(0);
    expect(tree.root.findAll((n) => n.props["data-label"] === "viewDetails")).toHaveLength(0);
    const edit = tree.root.findAll((n) => n.props["data-label"] === "editRegistration")[0];
    expect(edit.props["data-kind"]).toBe("primary");
    await act(async () => edit.props.onClick());
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/death-registration", params: { deathId: "d1", registered: "mine" } });
    await act(async () => tree.unmount());
  });
});

describe("both screens", () => {
  it("render the same list: VA Interview's Reported deaths tab and the Deaths screen", async () => {
    mockBootstrap = makeBootstrap(["interviewer", "death_reporter"], { intake: true, registeredDeaths: true });
    mockParams = { tab: "deaths" };
    const collection = await render(<CollectionScreen />);
    expect(collection.root.findAllByType(DeathsList)).toHaveLength(1);
    const fromCollection = titles(collection);
    await act(async () => collection.unmount());

    mockParams = { view: "mine" };
    const deaths = await render(<DeathRegistrationScreen />);
    expect(deaths.root.findAllByType(DeathsList)).toHaveLength(1);
    expect(fromCollection).toEqual(["Asha Devi", "UID-2", "Old Case"]);
    expect(titles(deaths)).toEqual(fromCollection);
    // Only the Deaths screen carries the "Register a death" primary button above the list.
    expect(deaths.root.findAll((n) => n.props["data-label"] === "registerDeath" && n.props["data-kind"] === "primary")).toHaveLength(1);
    expect(mockGetCases).toHaveBeenCalledTimes(2);
    await act(async () => deaths.unmount());
  });
});
