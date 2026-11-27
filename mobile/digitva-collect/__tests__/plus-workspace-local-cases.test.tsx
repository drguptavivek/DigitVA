/**
 * The Code tab (Plus online coding queue) carries the Local cases row above the queue, on Plus with offline coding only.
 */
import React from "react";
import { act, create } from "react-test-renderer";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ userId: "coder-1", mode: "coding" }),
  useRouter: () => ({ push: mockPush, replace: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false }),
  useFocusEffect: () => undefined,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ accounts: [{ user_id: "coder-1", coding_access: true, server: "https://va.example" }] }),
}));
let mockPlus = false;
let mockOffline = false;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus }));
jest.mock("../src/codingCapabilities", () => ({ canUseOfflineCoding: () => mockOffline }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn() }));
jest.mock("../src/auth", () => ({ loadActiveSlot: jest.fn(), loadDevice: jest.fn(), accessSummaryForDisplay: jest.fn(async () => null) }));
jest.mock("../src/icd11DorisPreference", () => ({
  isIcd11DorisEnabled: async () => true,
  useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: true }),
}));
jest.mock("../src/codingHistoryCache.native", () => ({ createNativeCodingHistoryCache: jest.fn() }));
jest.mock("../src/workspace/media/AttachmentMedia.native", () => ({ AttachmentMedia: () => null }));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/QueueScreen", () => ({
  QueueScreen: ({ topSlot }: { topSlot?: React.ReactNode }) => <>{topSlot}</>,
}));
jest.mock("../src/workspace/transport.native", () => ({ createNativeWorkspaceTransport: () => jest.fn() }));
jest.mock("../src/workspace/CaseWorkspaceScreen", () => ({ CaseWorkspaceScreen: () => null }));

import { PlusCoding } from "../src/nativeRoutes/plusWorkspace";
import { t } from "../src/i18n";

async function mount() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<PlusCoding />); });
  return tree;
}
const localRows = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props.label === t("localCases") && typeof n.props.onPress === "function");

describe("Code tab Local cases row", () => {
  beforeEach(() => { mockPlus = false; mockOffline = false; mockPush.mockClear(); });

  it("shows on Plus with offline coding and routes to /offline-coding", async () => {
    mockPlus = true;
    mockOffline = true;
    const tree = await mount();
    expect(localRows(tree).length).toBeGreaterThan(0);
    await act(async () => localRows(tree)[0].props.onPress());
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/offline-coding", params: { userId: "coder-1" } });
    await act(async () => tree.unmount());
  });

  it("is absent on Plus without offline coding and on the plain build", async () => {
    mockPlus = true;
    let tree = await mount();
    expect(JSON.stringify(tree.toJSON())).toBe("null");
    expect(localRows(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
    mockPlus = false;
    mockOffline = true;
    tree = await mount();
    expect(localRows(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
  });
});
