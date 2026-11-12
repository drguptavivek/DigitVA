import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ vaSid: "VA-1", mode: "coding" }),
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false }),
  useFocusEffect: () => undefined,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ accounts: [{ user_id: "coder-1", coding_access: true, server: "https://va.example" }] }),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn() }));
jest.mock("../src/auth", () => ({ loadActiveSlot: jest.fn(), loadDevice: jest.fn() }));
jest.mock("../src/icd11DorisPreference", () => ({
  isIcd11DorisEnabled: async () => true,
  useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: true }),
}));
jest.mock("../src/codingHistoryCache.native", () => ({ createNativeCodingHistoryCache: jest.fn() }));
jest.mock("../src/workspace/transport.native", () => ({ createNativeWorkspaceTransport: () => jest.fn(async () => ({})) }));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/QueueScreen", () => ({ QueueScreen: () => null }));
jest.mock("../src/workspace/media/AttachmentMedia.native", () => ({ AttachmentMedia: () => null }));
let mockRenderMedia: ((attachmentPath: string) => React.ReactElement) | undefined;
jest.mock("../src/workspace/CaseWorkspaceScreen", () => ({
  CaseWorkspaceScreen: (props: { renderMedia: (attachmentPath: string) => React.ReactElement }) => {
    mockRenderMedia = props.renderMedia;
    return null;
  },
}));

import { PlusWorkspace } from "../src/nativeRoutes/plusWorkspace";
import { AttachmentMedia } from "../src/workspace/media/AttachmentMedia.native";

describe("Collect Plus workspace attachments", () => {
  it("passes the workspace account's userId to native AttachmentMedia so attachments can load", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<PlusWorkspace />); });
    const attachmentPath = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
    const element = mockRenderMedia!(attachmentPath);

    expect(element.type).toBe(AttachmentMedia);
    expect(element.props).toMatchObject({ userId: "coder-1", attachmentPath });
    await act(async () => tree.unmount());
  });
});
