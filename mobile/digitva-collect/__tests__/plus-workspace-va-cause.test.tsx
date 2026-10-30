/**
 * Online native coding (Collect Plus workspace): the VA cause bucket comes from the pack bundled in the app, so
 * the workspace api answers it without a network call, while every other call still goes to the server.
 */
import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ vaSid: "VA-1", mode: "coding" }),
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
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
jest.mock("../src/workspace/media/AttachmentMedia.native", () => ({ AttachmentMedia: () => null }));
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: () => null }));
jest.mock("../src/workspace/QueueScreen", () => ({ QueueScreen: () => null }));
const mockRequest = jest.fn(async (_path: string): Promise<unknown> => ({}));
jest.mock("../src/workspace/transport.native", () => ({ createNativeWorkspaceTransport: () => mockRequest }));
const mockBundled = jest.fn(async (_value: string) => ({ icd_code: "5A00", classification: "icd11", va_code: "VAs-98", title: "Other", definition_html: "", bucket_code: "vas_98", bucket_label: "Other", bucket_section: null, has_definition: false }));
jest.mock("../src/coding/bundledVaDefinitions", () => ({ getBundledVaDefinition: (value: string) => mockBundled(value) }));
let mockApi: import("../src/workspace/api").WorkspaceApi | undefined;
jest.mock("../src/workspace/CaseWorkspaceScreen", () => ({
  CaseWorkspaceScreen: (props: { api: import("../src/workspace/api").WorkspaceApi }) => { mockApi = props.api; return null; },
}));

import { PlusWorkspace } from "../src/nativeRoutes/plusWorkspace";

describe("online native VA cause lookup", () => {
  it("answers from the bundled pack without calling the server", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<PlusWorkspace />); });
    expect(mockApi).toBeDefined();
    const found = await mockApi!.getVaDefinitionForIcd("5A00");
    expect(found).toMatchObject({ bucket_code: "vas_98", has_definition: false });
    expect(mockBundled).toHaveBeenCalledWith("5A00");
    expect(mockRequest).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("asks the server for a / cluster's causing condition and falls back to the pack's first stem", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<PlusWorkspace />); });
    mockBundled.mockClear();
    mockRequest.mockResolvedValueOnce({ icd_code: "2F9Z", classification: "icd11", va_code: "VAs-02.99", title: "Neoplasm", definition_html: "", bucket_code: "vas_02_99", bucket_label: "Neoplasm", bucket_section: "Neoplasms", has_definition: true });
    await expect(mockApi!.getVaDefinitionForIcd("FB80.B/2F9Z")).resolves.toMatchObject({ bucket_code: "vas_02_99" });
    expect(mockRequest).toHaveBeenCalledTimes(1);
    expect(mockBundled).not.toHaveBeenCalled();

    mockRequest.mockRejectedValueOnce(new Error("offline"));
    await expect(mockApi!.getVaDefinitionForIcd("FB80.B/2F9Z")).resolves.toMatchObject({ bucket_code: "vas_98" });
    expect(mockBundled).toHaveBeenCalledWith("FB80.B/2F9Z");
    await act(async () => tree.unmount());
  });
});
