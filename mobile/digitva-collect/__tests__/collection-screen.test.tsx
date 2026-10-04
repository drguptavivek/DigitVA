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

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
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
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ error: {}, muted: {}, headline: {}, card: {}, text: {} })
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));

import CollectionScreen from "../src/web/CollectionScreen";
import { getCases, getDrafts, getIntakeContext } from "../src/client/api";

const mockGetIntakeContext = getIntakeContext as jest.Mock;
const mockGetCases = getCases as jest.Mock;
const mockGetDrafts = getDrafts as jest.Mock;

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
    mockGetIntakeContext.mockResolvedValue(mockIntake);
    mockGetCases.mockResolvedValue({ cases: [], next_cursor: null });
    mockGetDrafts.mockResolvedValue({ drafts: [] });
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
});
