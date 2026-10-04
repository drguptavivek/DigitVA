import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockBootstrap = {
  user: { user_id: "u1", name: "Interviewer" },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, coding: false, reviewing: false },
  links: { intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
};
const mockBootstrapB = {
  ...mockBootstrap,
  csrf: { header: "X-CSRFToken", token: "csrf-b" },
  links: { intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
};
let mockCurrentBootstrap = mockBootstrap;
let mockParams: { superseded?: string } = {};
const mockRouterPush = jest.fn();

jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockRouterPush }), useLocalSearchParams: () => mockParams }));
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
jest.mock("../src/i18n", () => ({ t: (key: string, values: Record<string, string> = {}) => key + (values.date ? `:${values.date}` : "") }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ error: {}, muted: {}, headline: {}, card: {}, text: {} })
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));

import CollectionScreen from "../src/web/CollectionScreen";
import { getCases, getDrafts, getIntakeContext } from "../src/client/api";
import { getSubmittedRevisions } from "../src/client/revisions";

const mockGetIntakeContext = getIntakeContext as jest.Mock;
const mockGetCases = getCases as jest.Mock;
const mockGetDrafts = getDrafts as jest.Mock;
const mockGetSubmittedRevisions = getSubmittedRevisions as jest.Mock;

const mockIntake = {
  context: [{ project_id: "P1", site_id: "S1", web_intake_mode: "both" }]
};

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

    const refresh = tree!.root.findAll((node) => node.props["data-label"] === "refresh")[0];
    await act(async () => {
      refresh?.props.onClick();
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
    expect(tree!.root.findAll((node) => node.props["data-label"] === "newDeath")).toHaveLength(canRegister ? 1 : 0);
    expect(tree!.root.findAll((node) => node.props["data-label"] === "newInterview")).toHaveLength(canStart ? 1 : 0);
    await act(async () => tree!.unmount());
  });

  it("shows active other-draft warnings with the start time and a superseded notice", async () => {
    const startedAt = "2026-10-04T10:30:00Z";
    mockParams = { superseded: "1" };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "timed", unique_id: "A-001", other_draft_active: true, other_draft_started_at: startedAt },
      { death_id: "unknown", unique_id: "A-002", other_draft_active: true, other_draft_started_at: "invalid" },
      { death_id: "inactive", unique_id: "A-003", other_draft_active: false, other_draft_started_at: startedAt }
    ], next_cursor: null });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(`otherDraftActiveAt:${new Date(startedAt).toLocaleString()}`);
    expect(rendered).toContain('"otherDraftActive"');
    expect(rendered).toContain("supersededInterviewNotice");
    expect(rendered.match(/otherDraftActiveAt/g)).toHaveLength(1);
    await act(async () => tree!.unmount());
  });

  it("shows submitted interviews from metadata and opens revision only on request", async () => {
    mockGetSubmittedRevisions.mockResolvedValue([{
      draft_id: "d1", project_id: "p1", site_id: "s1", va_sid: "va1", status: "submitted",
      unique_id: "case-1", created_at: "2026-10-04T10:00:00Z", updated_at: "2026-10-04T11:00:00Z"
    }]);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CollectionScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("submittedInterviewsTitle");
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
});
