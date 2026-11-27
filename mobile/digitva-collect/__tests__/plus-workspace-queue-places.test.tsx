/**
 * The phone's Code queue hands the account's held access summary (accessSummaryForDisplay: never a publishing refresh)
 * to the shared QueueScreen for its "Site and unit" filter; offline (no answer) the queue simply has no filter.
 */
import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({}),
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false }),
  useFocusEffect: () => undefined,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ accounts: [{ user_id: "coder-1", coding_access: true, server: "https://va.example" }] }),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn() }));
const mockAccess = jest.fn();
const mockRefresh = jest.fn();
jest.mock("../src/auth", () => ({
  loadActiveSlot: jest.fn(), loadDevice: jest.fn(),
  accessSummaryForDisplay: (userId: string) => mockAccess(userId),
  refreshAccessSummaryForAction: (userId: string) => mockRefresh(userId),
}));
jest.mock("../src/icd11DorisPreference", () => ({
  isIcd11DorisEnabled: async () => true,
  useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: true }),
}));
jest.mock("../src/codingHistoryCache.native", () => ({ createNativeCodingHistoryCache: jest.fn() }));
jest.mock("../src/workspace/media/AttachmentMedia.native", () => ({ AttachmentMedia: () => null }));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/transport.native", () => ({ createNativeWorkspaceTransport: () => jest.fn() }));
let mockQueueProps: Record<string, unknown> | undefined;
jest.mock("../src/workspace/QueueScreen", () => ({
  QueueScreen: (props: Record<string, unknown>) => { mockQueueProps = props; return null; },
}));

import { PlusCoding } from "../src/nativeRoutes/plusWorkspace";

describe("phone queue Site and unit wiring", () => {
  beforeEach(() => { mockQueueProps = undefined; mockAccess.mockReset(); });

  it("hands the account's access projects to the queue", async () => {
    const projects = [{ project_id: "P1" }];
    mockAccess.mockResolvedValue({ projects });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<PlusCoding />); });
    expect(mockAccess).toHaveBeenCalledWith("coder-1");
    expect(mockQueueProps?.accessProjects).toBe(projects);
    // A queue mount never refreshes (and so never publishes) the account's access.
    expect(mockRefresh).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("offline the queue gets no access projects", async () => {
    mockAccess.mockResolvedValue(undefined);
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<PlusCoding />); });
    expect(mockQueueProps).toBeDefined();
    expect(mockQueueProps?.accessProjects).toBeUndefined();
    await act(async () => tree.unmount());
  });
});
