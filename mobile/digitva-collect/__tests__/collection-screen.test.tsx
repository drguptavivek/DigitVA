import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockBootstrap = {
  user: { user_id: "u1", name: "Interviewer" },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false },
  access: {
    user: { user_id: "u1", name: "Interviewer" },
    is_admin: false,
    roles: ["interviewer"],
    demo_coding: { available: false, project_ids: [] },
    projects: [{
      project_id: "P1",
      project_name: "Project",
      has_tree: false,
      grants: [{ role: "interviewer", scope: "project", active: true, source: "assigned" }],
      sites: [{ site_id: "S1", site_name: "Site", roles: ["interviewer"] }],
      actions: {
        interview: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
        register_death: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
      },
    }],
  },
  links: { login: "/vaauth/valogin", logout: "/vaauth/valogout", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
};
const mockBootstrapB = {
  ...mockBootstrap,
  user: { user_id: "u2", name: "Next interviewer" },
  access: { ...mockBootstrap.access, user: { user_id: "u2", name: "Next interviewer" } },
  csrf: { header: "X-CSRFToken", token: "csrf-b" },
  links: { login: "/vaauth/valogin", logout: "/vaauth/valogout", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
};
let mockCurrentBootstrap = mockBootstrap;
let mockParams: { superseded?: string; submissionHistory?: string; submissionLocked?: string; canCodeNow?: string; readyUniqueId?: string; readyVaSid?: string; saved?: string; tab?: string } = {};
const mockRouterPush = jest.fn();
const mockSetParams = jest.fn();

jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockRouterPush, setParams: mockSetParams }), useLocalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    bootstrap: mockCurrentBootstrap
  })
}));
jest.mock("../src/client/api", () => ({
  getIntakeContext: jest.fn(),
  getCases: jest.fn(),
  getDrafts: jest.fn()
}));
jest.mock("../src/client/revisions", () => ({ getSubmittedRevisions: jest.fn() }));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string> = {}) => key + (values.date ? `:${values.date}` : "") + (values.label ? `:${values.label}` : "") + (values.value ? `:${values.value}` : ""),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => <button data-label={label} disabled={disabled} onClick={onPress} />,
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ error: {}, muted: {}, headline: {}, card: {}, text: {} })
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));

import CollectionScreen from "../src/web/CollectionScreen";
import { EMPTY_ADVANCED, matchesAdvanced } from "../src/web/caseFilters";
import { getCases, getDrafts, getIntakeContext } from "../src/client/api";
import { getSubmittedRevisions } from "../src/client/revisions";

const mockGetIntakeContext = getIntakeContext as jest.Mock;
const mockGetCases = getCases as jest.Mock;
const mockGetDrafts = getDrafts as jest.Mock;
const mockGetSubmittedRevisions = getSubmittedRevisions as jest.Mock;

const mockIntake = {
  context: [{ project_id: "P1", site_id: "S1", web_intake_mode: "both" }]
};

/** Project and Area live in the Advanced filters sheet: open it, choose, Apply. */
async function chooseInSheet(tree: ReturnType<typeof create>, label: string): Promise<void> {
  const open = tree.root.findAll((node) => String(node.props.accessibilityLabel).startsWith("advancedFilters") && typeof node.props.onPress === "function")[0];
  await act(async () => open.props.onPress());
  await act(async () => tree.root.findByProps({ accessibilityLabel: label }).props.onPress());
  await act(async () => tree.root.findAll((node) => node.props["data-label"] === "applyFilters")[0].props.onClick());
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("CollectionScreen refresh", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCurrentBootstrap = mockBootstrap;
    mockParams = {};
    mockGetIntakeContext.mockResolvedValue(mockIntake);
    mockGetCases.mockResolvedValue({ cases: [], next_cursor: null });
    mockGetDrafts.mockResolvedValue({ drafts: [] });
    mockGetSubmittedRevisions.mockResolvedValue([]);
    mockRouterPush.mockClear();
  });

  it("loads once on mount and refreshes only when explicitly requested", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CollectionScreen />);
    });
    await settle();
    expect(mockGetIntakeContext).toHaveBeenCalledTimes(1);
    expect(mockGetCases).toHaveBeenCalledTimes(1);
    expect(mockGetDrafts).toHaveBeenCalledTimes(1);

    const refresh = tree!.root.findAll((node) => node.props.accessibilityLabel === "refresh" && typeof node.props.onPress === "function")[0];
    expect(refresh).toBeDefined();
    await act(async () => {
      refresh.props.onPress();
    });
    await settle();
    expect(mockGetIntakeContext).toHaveBeenCalledTimes(2);
    expect(mockGetCases).toHaveBeenCalledTimes(2);
    expect(mockGetDrafts).toHaveBeenCalledTimes(2);
    await act(async () => tree!.unmount());
  });

  it("does not let a previous user's pending response populate the new session", async () => {
    let resolveUserA!: (value: typeof mockIntake) => void;
    const userAPending = new Promise<typeof mockIntake>((resolve) => {
      resolveUserA = resolve;
    });
    const intakeB = { context: [{ project_id: "PB", site_id: "SB", web_intake_mode: "both" }] };
    const casesB = [{ death_id: "death-b", unique_id: "B-001", deceased_name: "User B case", state: "registered" }];
    const draftsB = [{ draft_id: "draft-b", project_id: "PB", site_id: "SB", unique_id: "B-002", current_section: "one" }];
    mockParams = { tab: "deaths" };
    mockGetIntakeContext.mockImplementation((csrf: {token: string}) => csrf.token === mockBootstrap.csrf.token ? userAPending : Promise.resolve(intakeB));
    mockGetCases.mockImplementation((_link: string, csrf: {token: string}) => Promise.resolve({ cases: csrf.token === "csrf-b" ? casesB : [], next_cursor: null }));
    mockGetDrafts.mockImplementation((_link: string, csrf: {token: string}) => Promise.resolve({ drafts: csrf.token === "csrf-b" ? draftsB : [] }));

    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CollectionScreen />);
      await Promise.resolve();
    });
    mockCurrentBootstrap = mockBootstrapB;
    await act(async () => {
      tree!.update(<CollectionScreen />);
      await Promise.resolve();
    });
    await settle();
    resolveUserA({ context: [{ project_id: "PA", site_id: "SA", web_intake_mode: "both" }] });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("User B case");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("User A case");
    await act(async () => tree!.unmount());
  });

  it.each([
    ["death_register", true, false],
    ["direct", false, true],
    ["both", true, true],
    ["off", false, false],
    [undefined, false, false]
  ] as const)("shows only the allowed new-entry controls for %s", async (mode, canRegister, canStart) => {
    mockGetIntakeContext.mockResolvedValue({ context: [{ project_id: "P1", site_id: "S1", web_intake_mode: mode }] });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CollectionScreen />);
    });
    await settle();
    expect(tree!.root.findAll((node) => node.props["data-label"] === "recordDeath")).toHaveLength(canRegister ? 1 : 0);
    expect(tree!.root.findAll((node) => node.props["data-label"] === "directVaInterview")).toHaveLength(canStart ? 1 : 0);
    await act(async () => tree!.unmount());
  });

  describe("direct VA interview panel", () => {
    const byLabel = (tree: ReturnType<typeof create>, label: string) =>
      tree.root.findAll((node) => node.props["data-label"] === label);
    const pressable = (tree: ReturnType<typeof create>, label: string) =>
      tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];

    async function openPanel(context: unknown[]) {
      mockGetIntakeContext.mockResolvedValue({ context });
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<CollectionScreen />); });
      await settle();
      expect(byLabel(tree!, "startInterview")).toHaveLength(0);
      await act(async () => byLabel(tree!, "directVaInterview")[0].props.onClick());
      return tree!;
    }

    it("replaces the per-unit buttons with one entry point and auto-selects a single project and site", async () => {
      const tree = await openPanel([
        { project_id: "P1", project_name: "Alpha", site_id: "S1", site_name: "Site One", web_intake_mode: "direct", org_units: [] },
      ]);
      expect(tree.root.findAll((node) => typeof node.props["data-label"] === "string" && node.props["data-label"].startsWith("newInterview"))).toHaveLength(0);
      expect(pressable(tree, "interviewProject: Alpha")).toBeDefined();
      expect(pressable(tree, "interviewPlace: Site One")).toBeDefined();
      const start = byLabel(tree, "startInterview")[0];
      expect(start.props.disabled).toBe(false);
      await act(async () => start.props.onClick());
      expect(mockRouterPush).toHaveBeenCalledWith({ pathname: "/interview", params: { projectId: "P1", siteId: "S1" } });
      await act(async () => tree.unmount());
    });

    it("requires a project then a unit, lists only that project's eligible units, and starts with the unit", async () => {
      const tree = await openPanel([
        { project_id: "P1", project_name: "Alpha", site_id: "S1", site_name: "Site One", web_intake_mode: "both", org_units: [
          { org_unit_id: "U1", unit_name: "CHC 01" },
          { org_unit_id: "U2", unit_name: "PHC 1" },
          { org_unit_id: "U3", unit_name: "Closed unit", selectable: false },
        ] },
        { project_id: "P2", project_name: "Beta", site_id: "S2", site_name: "Beta Site", web_intake_mode: "direct", org_units: [] },
        { project_id: "P3", project_name: "Gamma", site_id: "S3", site_name: "Register only", web_intake_mode: "death_register", org_units: [] },
      ]);
      expect(byLabel(tree, "startInterview")[0].props.disabled).toBe(true);
      expect(pressable(tree, "interviewPlace: choosePlace")).toBeUndefined();

      await act(async () => pressable(tree, "interviewProject: chooseProject").props.onPress());
      expect(pressable(tree, "Alpha")).toBeDefined();
      expect(pressable(tree, "Beta")).toBeDefined();
      expect(pressable(tree, "Gamma")).toBeUndefined();
      await act(async () => pressable(tree, "Alpha").props.onPress());
      expect(byLabel(tree, "startInterview")[0].props.disabled).toBe(true);

      await act(async () => pressable(tree, "interviewPlace: choosePlace").props.onPress());
      expect(pressable(tree, "CHC 01")).toBeDefined();
      expect(pressable(tree, "PHC 1")).toBeDefined();
      expect(pressable(tree, "Closed unit")).toBeUndefined();
      expect(pressable(tree, "Beta Site")).toBeUndefined();
      await act(async () => pressable(tree, "PHC 1").props.onPress());
      const start = byLabel(tree, "startInterview")[0];
      expect(start.props.disabled).toBe(false);
      await act(async () => start.props.onClick());
      expect(mockRouterPush).toHaveBeenCalledWith({ pathname: "/interview", params: { projectId: "P1", siteId: "S1", orgUnitId: "U2" } });

      await act(async () => pressable(tree, "interviewProject: Alpha").props.onPress());
      await act(async () => pressable(tree, "Beta").props.onPress());
      expect(pressable(tree, "interviewPlace: Beta Site")).toBeDefined();
      await act(async () => tree.unmount());
    });
  });

  it("shows active other-draft warnings with the start time and a superseded notice", async () => {
    const startedAt = "2026-10-04T10:30:00Z";
    mockParams = { superseded: "1" };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "timed", unique_id: "A-001", other_draft_active: true, other_draft_started_at: startedAt, other_complete_interview: true },
      { death_id: "unknown", unique_id: "A-002", other_draft_active: true, other_draft_started_at: "invalid" },
      { death_id: "inactive", unique_id: "A-003", other_draft_active: false, other_draft_started_at: startedAt, other_complete_interview: false }
    ], next_cursor: null });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(`otherDraftActiveAt:${new Date(startedAt).toLocaleString()}`);
    expect(rendered).toContain('"otherDraftActive"');
    expect(rendered).toContain("supersededInterviewNotice");
    expect(rendered.match(/otherCompleteInterviewNotice/g)).toHaveLength(1);
    expect(rendered.match(/otherDraftActiveAt/g)).toHaveLength(1);
    await act(async () => tree!.unmount());
  });

  it("shows server-kept history and locked notices, with superseded taking precedence", async () => {
    mockParams = { submissionHistory: "1", submissionLocked: "1" };
    mockGetIntakeContext.mockRejectedValueOnce(new Error("later refresh failed"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    let rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("submissionHistoryNotice");
    expect(rendered).toContain("submissionLockedNotice");
    expect(rendered).toContain("error");
    expect(rendered).not.toContain("supersededInterviewNotice");
    await act(async () => tree!.unmount());

    mockParams = { superseded: "1", submissionHistory: "1", submissionLocked: "1" };
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("supersededInterviewNotice");
    expect(rendered).not.toContain("submissionHistoryNotice");
    expect(rendered).not.toContain("submissionLockedNotice");
    await act(async () => tree!.unmount());
  });

  it("uses matching case readiness as authoritative and preserves its coding action", async () => {
    mockCurrentBootstrap = { ...mockBootstrap, access: { ...mockBootstrap.access, roles: ["coder"] } };
    mockParams = { canCodeNow: "1", readyUniqueId: "VA-READY", readyVaSid: "sid-ready" };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "d1", unique_id: "VA-READY", va_sid: "sid-ready", state: "submitted", code_now: true },
      { death_id: "d2", unique_id: "VA-MALFORMED", state: "submitted", code_now: "true" },
    ], next_cursor: null });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    let rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("readyForCode");
    expect(rendered).not.toContain("readyForCodeOnWeb");
    expect(tree!.root.findAll((node) => node.props["data-label"] === "codeNow")).toHaveLength(1);
    await act(async () => tree!.unmount());

    mockParams = { canCodeNow: "1", readyUniqueId: "VA-READY", readyVaSid: "sid-ready" };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "d1", unique_id: "VA-READY", va_sid: "sid-ready", state: "submitted", code_now: false },
    ], next_cursor: null });
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).not.toContain("readyForCodeOnWeb");
    expect(tree!.root.findAll((node) => node.props["data-label"] === "codeNow")).toHaveLength(0);
    await act(async () => tree!.unmount());

    mockParams = { submissionHistory: "1", submissionLocked: "1", canCodeNow: "1" };
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("submissionHistoryNotice");
    expect(rendered).toContain("readyForCodeOnWeb");
    await act(async () => tree!.unmount());

    mockParams = { superseded: "1", canCodeNow: "1" };
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("supersededInterviewNotice");
    const supersededNotice = tree!.root.findAllByProps({ accessibilityRole: "alert" })
      .find((node) => node.props.children === "supersededInterviewNotice");
    expect(supersededNotice?.props.children).toBe("supersededInterviewNotice");
    expect(rendered).toContain("readyForCodeOnWeb");
    await act(async () => tree!.unmount());
  });

  it("keeps the acknowledgement hint when its case is missing and refresh fails", async () => {
    mockParams = { canCodeNow: "1", readyUniqueId: "VA-MISSING" };
    mockGetIntakeContext.mockRejectedValueOnce(new Error("refresh failed"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();

    expect(JSON.stringify(tree!.toJSON())).toContain("readyForCodeOnWeb");
    await act(async () => tree!.unmount());
  });

  it("shows submitted interviews from metadata and opens revision only on request", async () => {
    mockGetSubmittedRevisions.mockResolvedValue([{
      draft_id: "d1", project_id: "p1", site_id: "s1", va_sid: "va1", status: "submitted",
      unique_id: "case-1", created_at: "2026-10-04T10:00:00Z", updated_at: "2026-10-04T11:00:00Z"
    }]);
    let tree: ReturnType<typeof create>;
    mockParams = { tab: "interviews" };
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("filterSubmitted");
    expect(rendered).toContain("case-1");
    expect(mockGetSubmittedRevisions).toHaveBeenCalledTimes(1);
    expect(mockRouterPush).not.toHaveBeenCalled();
    const revise = tree!.root.findAll((node) => node.props["data-label"] === "reviseInterview")[0];
    await act(async () => revise?.props.onClick());
    expect(mockRouterPush).toHaveBeenCalledWith({ pathname: "/interview", params: {
      revisionDraftId: "d1", revisionProjectId: "p1", revisionSiteId: "s1", revisionVaSid: "va1"
    } });
    await act(async () => tree!.unmount());
  });

  it("renders structured death card metadata and filters reported deaths by search, status, and unit", async () => {
    mockGetCases.mockResolvedValue({
      cases: [
        {
          death_id: 101,
          unique_id: "UID-101",
          deceased_name: "Asha Devi",
          deceased_sex: "female",
          age_years: 62,
          date_of_death: "2026-10-01",
          status: "registered",
          state: "registered",
          unit_name: "Ward North",
          informant_phone_masked: "***4321",
          next_visit_at: "2026-10-20",
        },
        {
          death_id: 102,
          unique_id: "UID-102",
          deceased_name: "Ramesh Kumar",
          deceased_sex: "male",
          age_years: 48,
          date_of_death: "2026-10-02",
          status: "in_progress",
          state: "in_progress",
          unit_name: "Ward South",
          my_draft_id: "draft-102",
        },
        {
          death_id: 103,
          unique_id: "UID-103",
          deceased_name: "Meena Sharma",
          deceased_sex: "female",
          age_years: 75,
          date_of_death: "2026-10-03",
          status: "submitted",
          state: "submitted",
          unit_name: "Ward North",
          code_now: true,
        },
      ],
      next_cursor: null,
    });

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();

    let rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Asha Devi");
    expect(rendered).toContain("Ramesh Kumar");
    expect(rendered).toContain("Meena Sharma");
    expect(rendered).toContain("metaAgeYears:62");
    expect(rendered).toContain("metaAgeA11y:62");
    expect(rendered).toContain('"female"');
    expect(rendered).toContain("metaDied:2026-10-01");
    expect(rendered).toContain("metaPhone:***4321");
    expect(rendered).toContain("actionVisit:2026-10-20");
    expect(rendered).toContain("metaArea:Ward North");
    expect(rendered).not.toContain("Age:");
    expect(rendered).not.toContain("Sex:");
    expect(rendered).not.toContain("ID: UID-101");
    // Shown once; its accessible name is the "Case ID" label, not a second visible copy.
    expect(rendered).toContain("metaCaseIdA11y:UID-101");
    expect(rendered.replace(/metaCaseIdA11y:UID-101/g, "").match(/UID-101/g)).toHaveLength(1);
    expect(rendered).not.toContain("draftInProgress");

    // Filter by status: In progress
    const inProgressChip = tree!.root.findByProps({ accessibilityLabel: "filterStatusLabel:filterInProgress" });
    await act(async () => { inProgressChip.props.onPress(); });
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Ramesh Kumar");
    expect(rendered).not.toContain("Asha Devi");
    expect(rendered).not.toContain("Meena Sharma");

    // Filter by status: Ready to code
    const readyChip = tree!.root.findByProps({ accessibilityLabel: "filterStatusLabel:filterReadyToCode" });
    await act(async () => { readyChip.props.onPress(); });
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Meena Sharma");
    expect(rendered).not.toContain("Ramesh Kumar");

    // Clear filters
    const clearBtn = tree!.root.findAll((node) => node.props.accessibilityLabel === "clearAll" && typeof node.props.onPress === "function")[0];
    await act(async () => { clearBtn.props.onPress(); });
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Asha Devi");
    expect(rendered).toContain("Ramesh Kumar");
    expect(rendered).toContain("Meena Sharma");

    // Filter by area (in the sheet): Ward South, then a removable applied chip
    await chooseInSheet(tree!, "filterAreaLabel:Ward South");
    expect(tree!.root.findAll((node) => node.props.accessibilityLabel === "removeFilter:filterArea: Ward South")).not.toHaveLength(0);
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Ramesh Kumar");
    expect(rendered).not.toContain("Asha Devi");

    // Filter by search input
    const searchInput = tree!.root.findByProps({ accessibilityLabel: "searchCases" });
    await act(async () => { searchInput.props.onChangeText("nonexistent"); });
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("noMatchingCases");

    await act(async () => tree!.unmount());
  });

  it("lists every own draft, case-linked too, and starts a case's interview directly", async () => {
    mockParams = { saved: "1" };
    mockGetCases.mockResolvedValue({
      cases: [
        { death_id: "d1", unique_id: "UID-1", deceased_name: "Asha Devi", state: "registered" },
        { death_id: "d2", unique_id: "UID-2", deceased_name: "Ramesh Kumar", state: "in_progress", my_draft_id: "draft-2" },
        { death_id: "d3", unique_id: "UID-3", deceased_name: "Meena Sharma", state: "registered", other_draft_active: true },
      ],
      next_cursor: null,
    });
    mockGetDrafts.mockResolvedValue({
      drafts: [{ draft_id: "draft-2", project_id: "P1", site_id: "S1", death_id: "d2", unique_id: "UID-2", deceased_name: "Ramesh Kumar", sections_saved: 3 }],
    });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();

    const has = (key: string) => tree!.root.findAll((node) => node.props.children === key).length > 0;
    expect(has("registrationSaved")).toBe(true);
    // Drafts in progress: My interviews is the default tab.
    expect(tree!.root.findByProps({ accessibilityRole: "tab", accessibilityLabel: "myInterviews (1)" }).props.accessibilityState).toEqual({ selected: true });
    expect(has("sectionsSaved")).toBe(true);
    expect(has("Ramesh Kumar")).toBe(true);
    expect(tree!.root.findAll((node) => node.props["data-label"] === "startInterview")).toHaveLength(0);

    await act(async () => tree!.root.findByProps({ accessibilityRole: "tab", accessibilityLabel: "reportedDeaths (3)" }).props.onPress());
    expect(mockSetParams).toHaveBeenCalledWith({ tab: "deaths" });
    expect(has("sectionsSaved")).toBe(false);
    expect(has("Ramesh Kumar")).toBe(true);

    const starts = tree!.root.findAll((node) => node.props["data-label"] === "startInterview");
    expect(starts).toHaveLength(1);
    await act(async () => starts[0].props.onClick());
    expect(mockRouterPush).toHaveBeenCalledWith({ pathname: "/interview", params: { deathId: "d1" } });
    await act(async () => tree!.unmount());
  });

  it("filters by Within Area, parent area subtree, and hides internal placeholder unit names", async () => {
    mockCurrentBootstrap = {
      ...mockBootstrap,
      access: {
        ...mockBootstrap.access,
        projects: [{
          project_id: "TST001",
          project_name: "Organization Test Project",
          has_tree: true,
          grants: [
            { role: "interviewer", scope: "unit", org_unit_id: "u-phc1", unit_code: "PHC01", unit_name: "PHC-AAM 1", active: true, source: "assigned" },
            { role: "coder", scope: "unit", org_unit_id: "u-phc2", unit_code: "PHC02", unit_name: "PHC-AAM 2", active: true, source: "assigned" },
          ],
          sites: [],
          units: [
            { org_unit_id: "u-dh1", unit_code: "DH01", unit_name: "District Hospital", level: "district", parent_id: null, path: "DH01", depth: 0, selectable: false, can_register_death: false, can_interview: false, can_code: false, roles: [] },
            { org_unit_id: "u-chc1", unit_code: "CHC01", unit_name: "Community Health Centre", level: "chc", parent_id: "u-dh1", path: "DH01.CHC01", depth: 1, selectable: false, can_register_death: false, can_interview: false, can_code: false, roles: [] },
            { org_unit_id: "u-phc1", unit_code: "PHC01", unit_name: "PHC-AAM 1", level: "phc", parent_id: "u-chc1", path: "DH01.CHC01.PHC01", depth: 2, selectable: true, can_register_death: true, can_interview: true, can_code: false, roles: ["interviewer"] },
            { org_unit_id: "u-sc1", unit_code: "SC01", unit_name: "SC-AAM 1", level: "subcentre", parent_id: "u-phc1", path: "DH01.CHC01.PHC01.SC01", depth: 3, selectable: true, can_register_death: true, can_interview: true, can_code: false, roles: ["interviewer"] },
            { org_unit_id: "u-sc4", unit_code: "SC04", unit_name: "SC-AAM 4", level: "subcentre", parent_id: "u-phc2", path: "DH01.CHC01.PHC02.SC04", depth: 3, selectable: true, can_register_death: false, can_interview: true, can_code: true, roles: ["interviewer", "coder"] },
          ],
          actions: {
            interview: [{ site_id: "DH01", site_name: "District Hospital", web_intake_mode: "both", org_units: [] }],
            register_death: [{ site_id: "DH01", site_name: "District Hospital", web_intake_mode: "both", org_units: [] }],
          },
        }],
      },
    } as unknown as typeof mockBootstrap;

    mockGetCases.mockResolvedValue({
      cases: [
        {
          death_id: 201,
          unique_id: "TST-SC01-01",
          deceased_name: "Kamla Bai",
          org_unit_id: "u-sc1",
          unit_name: "SC-AAM 1",
          site_name: "Sites_in_project_TST001",
          state: "registered",
          next_visit_at: "2026-10-03T12:11:15.304271+00:00",
        },
        {
          death_id: 202,
          unique_id: "TST-SC04-01",
          deceased_name: "Mohan Lal",
          org_unit_id: "u-sc4",
          unit_name: "SC-AAM 4",
          state: "submitted",
          code_now: true,
        },
      ],
      next_cursor: null,
    });

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();

    let rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("metaArea:SC-AAM 1");
    expect(rendered).not.toContain("Tree:");
    expect(rendered).not.toContain("Sites_in_project_TST001");
    expect(rendered).not.toContain("12:11:15.304271");

    // Filtering by Within Area matches the user's home grant subtree (PHC-AAM 1 -> SC-AAM 1)
    await chooseInSheet(tree!, "filterAreaLabel:filterWithinArea");
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Kamla Bai");
    expect(rendered).not.toContain("Mohan Lal");

    // Filtering by All shows both
    await chooseInSheet(tree!, "filterAreaLabel:filterAll");
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Kamla Bai");
    expect(rendered).toContain("Mohan Lal");

    // Filtering by parent unit PHC-AAM 1 matches its descendant SC-AAM 1
    await chooseInSheet(tree!, "filterAreaLabel:PHC-AAM 1");
    rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("Kamla Bai");
    expect(rendered).not.toContain("Mohan Lal");

    await act(async () => tree!.unmount());
  });
});

describe("CollectionScreen tabs and filters", () => {
  const intakeTwoProjects = {
    context: [
      { project_id: "P1", project_name: "Project One", site_id: "S1", web_intake_mode: "both" },
      { project_id: "P2", project_name: "Project Two", site_id: "S2", web_intake_mode: "both" },
    ],
  };
  const deathCases = [
    { death_id: "c1", unique_id: "UID-1", deceased_name: "Asha Devi", deceased_sex: "female", age_years: 72, date_of_death: "2026-09-01", created_at: "2026-09-02T10:00:00", state: "registered", project_id: "P1" },
    { death_id: "c2", unique_id: "UID-2", deceased_name: "Ravi Lal", deceased_sex: "male", age_years: 30, date_of_death: "2026-10-05", created_at: "2026-10-06T10:00:00", state: "registered", project_id: "P1" },
    { death_id: "c3", unique_id: "UID-3", deceased_name: "Baby Kumari", deceased_sex: "unknown", age_years: 0, date_of_death: "2026-10-10", created_at: "2026-10-11T10:00:00", state: "registered", project_id: "P1" },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockCurrentBootstrap = mockBootstrap;
    mockParams = {};
    mockGetIntakeContext.mockResolvedValue(mockIntake);
    mockGetCases.mockResolvedValue({ cases: [], next_cursor: null });
    mockGetDrafts.mockResolvedValue({ drafts: [] });
    mockGetSubmittedRevisions.mockResolvedValue([]);
  });

  async function render() {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    return tree;
  }
  const text = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());
  const press = async (tree: ReturnType<typeof create>, label: string) => {
    const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
    expect(node).toBeDefined();
    await act(async () => node.props.onPress());
  };
  const tabSelected = (tree: ReturnType<typeof create>, prefix: string) =>
    tree.root.findAll((n) => n.props.accessibilityRole === "tab" && String(n.props.accessibilityLabel).startsWith(prefix) && typeof n.props.onPress === "function")[0]?.props.accessibilityState?.selected;

  it("defaults to Reported deaths without drafts, to My interviews with drafts, and honours ?tab", async () => {
    let tree = await render();
    expect(tabSelected(tree, "reportedDeaths")).toBe(true);
    expect(tabSelected(tree, "myInterviews")).toBe(false);
    await act(async () => tree.unmount());

    mockGetDrafts.mockResolvedValue({ drafts: [{ draft_id: "dr1", project_id: "P1", site_id: "S1", unique_id: "UID-9", sections_saved: 1 }] });
    tree = await render();
    expect(tabSelected(tree, "myInterviews")).toBe(true);
    await act(async () => tree.unmount());

    mockParams = { tab: "deaths" };
    tree = await render();
    expect(tabSelected(tree, "reportedDeaths")).toBe(true);
    await act(async () => tree.unmount());
  });

  it("shows tab counts from the server's per-state counts and the interview lists", async () => {
    mockGetCases.mockResolvedValue({ cases: deathCases, counts: { registered: 40, submitted: 2 }, next_cursor: "next" });
    mockGetDrafts.mockResolvedValue({ drafts: [{ draft_id: "dr1", project_id: "P1", site_id: "S1", unique_id: "UID-9" }] });
    mockGetSubmittedRevisions.mockResolvedValue([{ draft_id: "sb1", project_id: "P1", site_id: "S1", va_sid: "va1", status: "submitted", created_at: "x", updated_at: "y" }]);
    const tree = await render();
    expect(tabSelected(tree, "reportedDeaths (42)")).toBe(false);
    expect(tabSelected(tree, "myInterviews (2)")).toBe(true);
    await act(async () => tree.unmount());
  });

  it("filters My interviews by search, status chips and project (from the sheet), on the loaded lists", async () => {
    mockGetIntakeContext.mockResolvedValue(intakeTwoProjects);
    mockGetDrafts.mockResolvedValue({ drafts: [
      { draft_id: "dr1", project_id: "P1", site_id: "S1", unique_id: "UID-1", deceased_name: "Asha Devi", sections_saved: 2, updated_at: "2026-10-01T10:00:00" },
    ] });
    mockGetSubmittedRevisions.mockResolvedValue([
      { draft_id: "sb1", project_id: "P2", site_id: "S2", va_sid: "va1", status: "submitted", unique_id: "UID-2", deceased_name: "Ravi Lal", created_at: "2026-10-02T10:00:00", updated_at: "2026-10-03T10:00:00" },
    ]);
    const tree = await render();
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).toContain("Ravi Lal");
    expect(text(tree)).toContain("metaProject:Project Two");
    expect(tree.root.findAll((n) => n.props["data-label"] === "resumeInterview")).toHaveLength(1);
    expect(tree.root.findAll((n) => n.props["data-label"] === "reviseInterview")).toHaveLength(1);

    await press(tree, "filterStatusLabel:filterSubmitted");
    expect(text(tree)).toContain("Ravi Lal");
    expect(text(tree)).not.toContain("Asha Devi");
    await press(tree, "filterStatusLabel:filterInProgress");
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).not.toContain("Ravi Lal");
    await press(tree, "filterStatusLabel:filterAll");

    const search = tree.root.findByProps({ accessibilityLabel: "searchCases" });
    await act(async () => search.props.onChangeText("uid-2"));
    expect(text(tree)).toContain("Ravi Lal");
    expect(text(tree)).not.toContain("Asha Devi");
    await act(async () => search.props.onChangeText(""));

    mockGetCases.mockClear();
    await chooseInSheet(tree, "filterProjectLabel:Project One");
    await settle();
    // My interviews are whole lists: the project narrows them here, the deaths list is not re-fetched.
    expect(mockGetCases).not.toHaveBeenCalled();
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).not.toContain("Ravi Lal");
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "advancedFiltersActive")).not.toHaveLength(0);

    await press(tree, "clearAll");
    await settle();
    expect(text(tree)).toContain("Ravi Lal");
    await act(async () => tree.unmount());
  });

  it("hides the project chips when the user has one project", async () => {
    mockGetCases.mockResolvedValue({ cases: deathCases, next_cursor: null });
    const tree = await render();
    expect(tree.root.findAll((n) => String(n.props.accessibilityLabel).startsWith("filterProjectLabel"))).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("applies advanced filters from the sheet, shows a badge and removable chips, and clears them", async () => {
    mockGetCases.mockResolvedValue({ cases: deathCases, next_cursor: "more" });
    const tree = await render();
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).not.toContain("filteringLoadedCases");

    await press(tree, "advancedFilters");
    await press(tree, "filterSexLabel:sexMale");
    // Nothing applies until Apply.
    expect(text(tree)).toContain("Asha Devi");
    const apply = tree.root.findAll((n) => n.props["data-label"] === "applyFilters")[0];
    await act(async () => apply.props.onClick());
    expect(text(tree)).toContain("Ravi Lal");
    expect(text(tree)).not.toContain("Asha Devi");
    expect(text(tree)).not.toContain("Baby Kumari");
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "advancedFiltersActive")).not.toHaveLength(0);
    // More pages exist, so the list says it filters only what is loaded.
    expect(text(tree)).toContain("filteringLoadedCases");

    await press(tree, "removeFilter:filterSex: sexMale");
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).toContain("Baby Kumari");

    await press(tree, "advancedFilters");
    await press(tree, "filterAgeLabel:ageUnder1");
    const dodFrom = tree.root.findByProps({ "aria-label": "filterDateOfDeath filterFrom" });
    await act(async () => dodFrom.props.onChange({ currentTarget: { value: "2026-10-01" } }));
    await act(async () => tree.root.findAll((n) => n.props["data-label"] === "applyFilters")[0].props.onClick());
    expect(text(tree)).toContain("Baby Kumari");
    expect(text(tree)).not.toContain("Ravi Lal");
    expect(text(tree)).not.toContain("Asha Devi");
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "removeFilter:filterDateOfDeath: 2026-10-01 – …" && typeof n.props.onPress === "function")).toHaveLength(1);

    await press(tree, "clearAll");
    expect(text(tree)).toContain("Asha Devi");
    expect(text(tree)).toContain("Ravi Lal");
    expect(text(tree)).toContain("Baby Kumari");
    expect(tree.root.findAll((n) => String(n.props.accessibilityLabel).startsWith("removeFilter"))).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("matches advanced filters on dates, sex buckets and age bounds", () => {
    const row = { deceased_sex: "undetermined", age_years: 15, date_of_death: "2026-10-05", created_at: "2026-10-06T10:00:00" };
    expect(matchesAdvanced(row, EMPTY_ADVANCED)).toBe(true);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, sex: "other" })).toBe(true);
    expect(matchesAdvanced({ ...row, deceased_sex: null }, { ...EMPTY_ADVANCED, sex: "other" })).toBe(true);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, sex: "female" })).toBe(false);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, ageBand: "15-49" })).toBe(true);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, ageBand: "1-14" })).toBe(false);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, ageBand: "15-49", ageMin: "20" })).toBe(false);
    expect(matchesAdvanced({ ...row, age_years: null }, { ...EMPTY_ADVANCED, ageMax: "90" })).toBe(false);
    // Range ends are inclusive; a half-open range works; a malformed date is ignored.
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, dodFrom: "2026-10-05", dodTo: "2026-10-05" })).toBe(true);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, dodTo: "2026-10-04" })).toBe(false);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, dodFrom: "garbage" })).toBe(true);
    expect(matchesAdvanced(row, { ...EMPTY_ADVANCED, reportedFrom: "2026-10-06", reportedTo: "2026-10-06" })).toBe(true);
    expect(matchesAdvanced({ ...row, date_of_death: null }, { ...EMPTY_ADVANCED, dodFrom: "2026-01-01" })).toBe(false);
  });
});

describe("reported death card strings", () => {
  it.each(["metaAgeYears", "metaAgeA11y", "metaDied", "metaPhone", "metaLastContact"])("has en and hi key %s", (key) => {
    expect(require("../src/strings/en.json")[key]).toContain("{value}");
    expect(require("../src/strings/hi.json")[key]).toContain("{value}");
  });
});
