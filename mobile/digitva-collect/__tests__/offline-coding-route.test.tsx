/**
 * The offline coding and profile routes (Collect Plus): route wrappers gate on
 * platform + variant, the .web twins always redirect home without touching
 * native-only modules, and the .native coding screen gates on Plus, resolves
 * the interviewer's store and lists the completed-but-unsent cases from it.
 */
import React from "react";
import { AppState, Platform, TextInput } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";
import type { OfflineEngine } from "../src/offlineEngine";

const mockPlus = jest.fn(() => false);
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus() }));

const mockParams: Record<string, string> = {};
const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Redirect: ({ href }: { href: string }) => ReactActual.createElement("redirect", { href }),
    useLocalSearchParams: () => mockParams,
    useRouter: () => mockRouter,
  };
});

const mockAccounts: Array<Record<string, unknown>> = [{ user_id: "coder-1", name: "Coder", coding_access: true, offline_coding_access: ["SELF"] }];
const mockReload = jest.fn(async () => undefined);
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: mockAccounts, reload: mockReload }) }));
let mockSelectedSlot: "active" | "demo" = "active";
const mockLoadActiveSlot = jest.fn(async () => mockSelectedSlot);
const mockLoadAccounts = jest.fn(async (_slot?: "active" | "demo") => mockAccounts as never);
jest.mock("../src/auth", () => ({
  ...jest.requireActual("../src/auth"),
  loadActiveSlot: () => mockLoadActiveSlot(),
  loadAccounts: (slot?: "active" | "demo") => mockLoadAccounts(slot),
}));
const mockIdentitySelected = jest.fn(async (_userId: string) => true);
jest.mock("../src/accountStoreIdentity", () => ({
  ...jest.requireActual("../src/accountStoreIdentity"),
  accountStoreIdentityIsInSelectedMode: (userId: string) => mockIdentitySelected(userId),
}));

const mockDb = { runAsync: jest.fn(), getAllAsync: jest.fn(), getFirstAsync: jest.fn(), execAsync: jest.fn(), closeAsync: jest.fn() };
let mockEnvelope = JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} });
jest.mock("../src/interviewerDb", () => ({
  StoreLockedError: class extends Error {},
  isUnlocked: () => true,
  openInterviewerDb: jest.fn(async () => mockDb),
}));

const mockCases: Array<Record<string, unknown>> = [{
  client_draft_id: "draft-7",
  org_unit_id: "OU-42",
  completed_at: "2026-10-26T09:30:00.000+05:30",
  updated_at: "2026-10-26T10:00:00.000+05:30",
  offline_status: "coded",
}];
jest.mock("../src/drafts", () => ({
  listDrafts: jest.fn(async () => [{ id: "draft-7", project_id: "SELF" }]),
  listOfflineCodingCases: jest.fn(async () => mockCases),
  getOfflineCoding: jest.fn(async () => null),
  getOfflineCodingCase: jest.fn(async () => null),
  getMeta: jest.fn(async () => null),
  setMeta: jest.fn(async () => undefined),
  saveOfflineCoding: jest.fn(),
}));
const mockEnsureSmartVa = jest.fn(async (_input?: unknown): Promise<{ status: string; row?: unknown; reason?: string }> => ({ status: "config_needed" }));
jest.mock("../src/smartva/ensureLocal", () => ({ ensureLocalSmartVa: (input: unknown) => mockEnsureSmartVa(input) }));
const mockSmartVaOptions = {
  schemaVersion: 1,
  formId: "VA",
  formUpdatedAt: "1",
  options: { country: "India", hiv: false, malaria: false, hce: true, freetext: true },
  optionsDigest: `sha256:${"a".repeat(64)}`,
};
const mockPersistSmartVa = jest.fn(async () => undefined);
const mockBeforeManualPersist = jest.fn(async () => undefined);
const mockRunLocalSmartVa = jest.fn(async (input: { assertAllowed: () => Promise<void> }) => {
  await input.assertAllowed();
  await mockBeforeManualPersist();
  await input.assertAllowed();
  await mockPersistSmartVa();
  return {
    draft_id: "draft-7", status: "ready" as const, result_json: "{}", error_code: null,
    answers_sha256: "a".repeat(64), options_digest: mockSmartVaOptions.optionsDigest,
    engine_version: "3.0.1", created_at: "2026-10-28T00:00:00.000Z", updated_at: "2026-10-28T00:00:00.000Z",
  };
});
jest.mock("../src/smartva/localApi", () => ({
  ...jest.requireActual("../src/smartva/localApi"),
  runLocalSmartVa: (input: { assertAllowed: () => Promise<void> }) => mockRunLocalSmartVa(input),
}));
const mockSmartvaProbe = jest.fn(async () => ({ ok: true, version: "3.0.1" }));
jest.mock("../src/smartva/nativeEngine", () => ({
  offlineSmartvaEngine: () => ({ init: () => mockSmartvaProbe() }),
}));
jest.mock("../src/consentStore", () => ({
  DEFAULT_COVERED_FIELDS: [], consentForDraft: jest.fn(async () => undefined),
}));
jest.mock("../src/sync", () => ({
  ...jest.requireActual("../src/sync"),
  draftAnswersSha256: jest.fn(async () => "a".repeat(64)),
  getCachedReferenceData: jest.fn(async () => undefined),
}));
const mockEditorSave = jest.fn(async () => undefined);
const mockOnGuidance = jest.fn(async (_endpoint: string, body: unknown) => ({ answered: body }));
const mockPrimaryStem = jest.fn(async (_expression: string) => "GB00");
const mockBundledDefinition = jest.fn(async (_value: string, _stem?: string) => null);
jest.mock("../src/coding/bundledVaDefinitions", () => ({ getBundledVaDefinition: (value: string, stem?: string) => mockBundledDefinition(value, stem) }));
let mockIcd11DorisEnabled = true;
jest.mock("../src/icd11DorisPreference", () => ({
  isIcd11DorisEnabled: async () => mockIcd11DorisEnabled,
  useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: mockIcd11DorisEnabled }),
}));
jest.mock("../src/offlineIdentity", () => ({ getOrCreatePlusDeviceIdentity: jest.fn(async () => ({ uuid: "plus-install" })) }));
const mockGetProfile = jest.fn(async (): Promise<Record<string, unknown> | null> => null);
const mockSaveProfile = jest.fn(async (_profile?: unknown) => undefined);
jest.mock("../src/offlineProfile", () => ({
  getOfflineProfile: () => mockGetProfile(),
  saveOfflineProfile: (profile: unknown) => mockSaveProfile(profile),
  standaloneProfileMissing: jest.requireActual("../src/offlineProfile").standaloneProfileMissing,
}));
const mockSetUpStandaloneAccount = jest.fn(async (_profile?: unknown) => ({ user_id: "standalone-1" }));
jest.mock("../src/standalone/account", () => ({ setUpStandaloneAccount: (profile: unknown) => mockSetUpStandaloneAccount(profile) }));
const mockEngineInit = jest.fn<ReturnType<OfflineEngine["init"]>, Parameters<OfflineEngine["init"]>>(
  async () => ({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true }),
);
let mockProgress: ((progress: { phase: string; percent?: number }) => void) | undefined;
const mockEngine = {
  init: mockEngineInit,
  onProgress: (listener: (progress: { phase: string; percent?: number }) => void) => { mockProgress = listener; return () => { mockProgress = undefined; }; },
};
jest.mock("../src/offlineEngine", () => ({ offlineEngine: () => mockEngine }));
type AcquireEditor = () => (() => void) | null;
const mockAcquireEditor = jest.fn<ReturnType<AcquireEditor>, Parameters<AcquireEditor>>(() => jest.fn());
jest.mock("../src/localCodingLeases", () => ({ acquireLocalCodingEditor: () => mockAcquireEditor() }));
let mockPanelProps: Record<string, any> | undefined;
jest.mock("../src/workspace/offlineDoris", () => {
  const { OfflineAllowabilityError, createGuidanceRequester } = jest.requireActual<typeof import("../src/workspace/offlineDoris")>("../src/workspace/offlineDoris");
  return {
    OfflineAllowabilityError,
    createGuidanceRequester,
    createOfflineDorisEditor: jest.fn(() => ({ onProcess: jest.fn(), primaryStem: mockPrimaryStem, save: mockEditorSave, onGuidance: mockOnGuidance })),
    certificateSeedFromInterview: jest.fn(() => ({ certificate: {}, provenance: {} })),
  };
});
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: (props: Record<string, any>) => { mockPanelProps = props; return null; } }));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
}));
let mockMediaProps: Record<string, any> | undefined;
jest.mock("../src/workspace/media/LocalAttachmentMedia.native", () => ({
  LocalAttachmentMedia: (props: Record<string, any>) => { mockMediaProps = props; return null; },
}));
// The shared workspace screen has its own suites; here it loads the local workspace and shows the COD section's
// DORIS slot at once, so the route's guards and its local API can be driven directly. `mockRealScreen` puts the
// real screen back for the tests of how the two work together.
let mockScreenProps: Record<string, any> | undefined;
let mockRealScreen = false;
jest.mock("../src/workspace/CaseWorkspaceScreen", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const Real = jest.requireActual("../src/workspace/CaseWorkspaceScreen").CaseWorkspaceScreen;
  return {
    CaseWorkspaceScreen: (props: Record<string, any>) => {
      mockScreenProps = props;
      return ReactActual.createElement(mockRealScreen ? Real : Fake, props);
    },
  };
  function Fake(props: Record<string, any>) {
    const [workspace, setWorkspace] = ReactActual.useState<unknown>(null);
    ReactActual.useEffect(() => {
      let live = true;
      props.api.getWorkspace(props.identity.vaSid, "coding").then((value: unknown) => { if (live) setWorkspace(value); }, () => undefined);
      return () => { live = false; };
    }, [props.api, props.identity.vaSid]);
    return workspace ? props.renderDoris(workspace, async () => undefined, props.onDone, props.api) : null;
  }
});
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { View } = jest.requireActual("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", {
      accessibilityRole: "button", accessibilityLabel: label, onPress,
    }),
    Screen: ({ children, sidebar }: { children: React.ReactNode; sidebar?: React.ReactNode }) => ReactActual.createElement(View, null, sidebar, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {}, input: {} }),
  };
});

import OfflineCodingRoute from "../app/offline-coding";
import OfflineProfileRoute from "../app/offline-profile";
import OfflineCoding from "../src/nativeRoutes/offlineCoding.native";
import OfflineCodingWeb from "../src/nativeRoutes/offlineCoding.web";
import OfflineProfileScreen from "../src/nativeRoutes/offlineProfile.native";
import OfflineProfileWeb from "../src/nativeRoutes/offlineProfile.web";
import StandaloneSetup from "../src/nativeRoutes/standaloneSetup";

async function render(element: React.ReactElement) {
  let root!: Awaited<ReturnType<typeof create>>;
  await act(async () => { root = create(element); });
  return root;
}

const labels = (root: Awaited<ReturnType<typeof create>>) =>
  root.root.findAll((node: ReactTestInstance) => node.props.accessibilityRole === "button")
    .map((node: ReactTestInstance) => node.props.accessibilityLabel as string);

const alerts = (root: Awaited<ReturnType<typeof create>>) =>
  root.root.findAll((node) => typeof node.type === "string" && String(node.type) === "Text" && node.props.accessibilityRole === "alert")
    .map((node) => node.children.join(""));

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

beforeEach(() => {
  setOs("ios");
  mockPlus.mockReturnValue(false);
  mockSelectedSlot = "active";
  mockLoadActiveSlot.mockClear();
  mockLoadAccounts.mockClear();
  mockIdentitySelected.mockReset().mockResolvedValue(true);
  mockAccounts.splice(0, mockAccounts.length, { user_id: "coder-1", name: "Coder", coding_access: true, offline_coding_access: ["SELF"] });
  mockGetProfile.mockReset();
  mockGetProfile.mockResolvedValue(null);
  mockSaveProfile.mockReset();
  mockSaveProfile.mockResolvedValue(undefined);
  mockSetUpStandaloneAccount.mockReset();
  mockSetUpStandaloneAccount.mockResolvedValue({ user_id: "standalone-1" });
  mockRouter.replace.mockClear();
  mockRouter.back.mockClear();
  mockReload.mockClear();
  mockEngineInit.mockClear();
  mockEditorSave.mockClear();
  mockOnGuidance.mockClear();
  mockIcd11DorisEnabled = true;
  mockPanelProps = undefined;
  mockScreenProps = undefined;
  mockRealScreen = false;
  mockSmartvaProbe.mockReset().mockResolvedValue({ ok: true, version: "3.0.1" });
  mockEnsureSmartVa.mockReset().mockResolvedValue({ status: "config_needed" });
  mockRunLocalSmartVa.mockClear();
  mockPersistSmartVa.mockReset().mockResolvedValue(undefined);
  mockBeforeManualPersist.mockReset().mockResolvedValue(undefined);
  mockAcquireEditor.mockReset();
  mockAcquireEditor.mockReturnValue(jest.fn());
  mockDb.getFirstAsync.mockReset();
  mockEnvelope = JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} });
  mockDb.getFirstAsync.mockImplementation(async (sql: string) =>
    sql.includes("project_id") ? { project_id: "SELF" } : { envelope: mockEnvelope },
  );
  mockDb.runAsync.mockReset();
  mockDb.runAsync.mockImplementation(async (_sql: string, params: unknown[]) => {
    mockEnvelope = String(params[0]);
    return { changes: 1 };
  });
  const draftMocks = require("../src/drafts") as { getOfflineCodingCase: jest.Mock; getOfflineCoding: jest.Mock };
  draftMocks.getOfflineCoding.mockReset().mockResolvedValue(null);
  draftMocks.getOfflineCodingCase.mockReset().mockResolvedValue({
    client_draft_id: "draft-7", envelope: JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} }),
    org_unit_id: "OU-42", started_at: null, completed_at: "2026-10-26T09:30:00.000+05:30",
  });
  (require("../src/drafts").getMeta as jest.Mock).mockReset().mockResolvedValue(null);
  for (const key of Object.keys(mockParams)) delete mockParams[key];
  mockCases.length = 0;
  mockCases.push({
    client_draft_id: "draft-7",
    org_unit_id: "OU-42",
    completed_at: "2026-10-26T09:30:00.000+05:30",
    updated_at: "2026-10-26T10:00:00.000+05:30",
    offline_status: "coded",
  });
});

describe("route wrappers and web twins", () => {
  it("non-Plus builds and the web redirect home from both offline routes", async () => {
    const coding = await render(<OfflineCodingRoute />);
    expect(coding.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    const profile = await render(<OfflineProfileRoute />);
    expect(profile.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });

  // Under the web bundle the platform-agnostic route paths resolve to the
  // .web twins, so a web build renders redirect-home even with Plus flags set;
  // the native screen behind the same path is covered by the explicit
  // .native imports below.
  it("the web twins redirect home unconditionally, even with Plus flags set", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    const coding = await render(<OfflineCodingWeb />);
    expect(coding.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    const profile = await render(<OfflineProfileWeb />);
    expect(profile.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });
});

describe("the offline coding screen", () => {
  it("non-Plus redirects home before touching the store", async () => {
    const { openInterviewerDb } = require("../src/interviewerDb") as { openInterviewerDb: jest.Mock };
    openInterviewerDb.mockClear();
    const root = await render(<OfflineCoding />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    expect(openInterviewerDb).not.toHaveBeenCalled();
  });

  it("on Plus it lists the completed-but-unsent cases with their coding status", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    const root = await render(<OfflineCoding />);
    expect(labels(root)).toEqual([
      "draft-7 · 2026-10-26 · OU-42 · Coded",
    ]);
  });

  it("does not open the local store or show its case list while ICD-11/DORIS is off", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockIcd11DorisEnabled = false;
    const { openInterviewerDb } = require("../src/interviewerDb") as { openInterviewerDb: jest.Mock };
    openInterviewerDb.mockClear();

    const root = await render(<OfflineCoding />);

    expect(alerts(root)).toContain("icd11DorisDisabledBody");
    expect(labels(root)).not.toContain("draft-7 · 2026-10-26 · OU-42 · Coded");
    expect(openInterviewerDb).not.toHaveBeenCalled();
  });

  it.each([
    ["enrolled", { user_id: "coder-1", name: "Coder", coding_access: true, offline_coding_access: ["SELF"] }],
    ["standalone", { user_id: "coder-1", name: "Coder", standalone: true }],
    ["demo", { user_id: "coder-1", name: "Coder", coding_access: true, offline_coding_access: ["SELF"], server: "https://demo.example" }],
  ])("blocks a direct local ICD-11 case for %s when the device preference is off", async (_mode, account) => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockAccounts.splice(0, mockAccounts.length, account);
    mockIcd11DorisEnabled = false;
    mockParams.caseId = "draft-7";
    const { openInterviewerDb } = require("../src/interviewerDb") as { openInterviewerDb: jest.Mock };
    openInterviewerDb.mockClear();

    const root = await render(<OfflineCoding />);

    expect(alerts(root)).toContain("icd11DorisDisabledBody");
    expect(labels(root)).toContain("icd11DorisOpenSettings");
    expect(openInterviewerDb).not.toHaveBeenCalled();
    expect(mockEngineInit).not.toHaveBeenCalled();
  });

  it("returns to the local case list after enabling without starting the engine", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockIcd11DorisEnabled = false;
    mockParams.caseId = "draft-7";
    const root = await render(<OfflineCoding />);
    expect(mockEngineInit).not.toHaveBeenCalled();

    mockIcd11DorisEnabled = true;
    await act(async () => { root.update(<OfflineCoding />); });
    expect(labels(root)).toContain("draft-7 · 2026-10-26 · OU-42 · Coded");
    expect(mockEngineInit).not.toHaveBeenCalled();

    const row = root.root.find((node) => node.props.accessibilityLabel?.startsWith("draft-7 ·"));
    await act(async () => { row.props.onPress(); });
    expect(mockEngineInit).toHaveBeenCalledTimes(1);
  });

  it("without a signed-in account it redirects home", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockAccounts.length = 0;
    const root = await render(<OfflineCoding />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });

  it("denies a direct case from a project outside the refreshed offline capability", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    mockDb.getFirstAsync.mockResolvedValueOnce({ project_id: "OTHER" });
    const root = await render(<OfflineCoding />);
    expect(alerts(root)).toContain("offline_case_access_revoked");
    expect(mockEngineInit).not.toHaveBeenCalled();
    expect(mockEditorSave).not.toHaveBeenCalled();
  });

  it("rechecks a list-selected project's access and blocks processing and saving while retaining another project", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    const root = await render(<OfflineCoding />);
    const row = root.root.find((node) => node.props.accessibilityLabel?.startsWith("draft-7 ·"));
    await act(async () => { row.props.onPress(); });
    expect(mockPanelProps).toBeDefined();
    mockAccounts[0] = { ...mockAccounts[0], offline_coding_access: ["OTHER"] };
    await act(async () => { root.update(<OfflineCoding />); });
    await expect(mockPanelProps!.api.processDoris("draft-7", "coder", 1, {})).rejects.toThrow("offline_case_access_revoked");
    await expect(mockPanelProps!.api.saveInitial("draft-7", {})).rejects.toThrow("offline_case_access_revoked");
    expect(mockEditorSave).not.toHaveBeenCalled();
    expect(alerts(root)).toContain("Offline coding access for this project is unavailable.");
  });

  it("resolves a '/' cluster's VA cause from the editor's primary stem, and a single code from the code itself", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    await render(<OfflineCoding />);
    const api = mockPanelProps!.api;
    await api.getVaDefinitionForIcd("1A00/GB00");
    expect(mockPrimaryStem).toHaveBeenCalledWith("1A00/GB00");
    expect(mockBundledDefinition).toHaveBeenLastCalledWith("1A00/GB00", "GB00");
    mockPrimaryStem.mockClear();
    await api.getVaDefinitionForIcd("1A00");
    expect(mockBundledDefinition).toHaveBeenLastCalledWith("1A00", undefined);
    await api.getVaDefinitionForIcd("not a code");
    expect(mockPrimaryStem).not.toHaveBeenCalled();
  });

  it("stops an already-open local editor from processing or saving after ICD-11 coding is turned off", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    const root = await render(<OfflineCoding />);
    expect(mockPanelProps).toBeDefined();
    mockIcd11DorisEnabled = false;
    await act(async () => { root.update(<OfflineCoding />); });

    await expect(mockPanelProps!.api.processDoris("draft-7", "coder", 1, {})).rejects.toThrow("icd11_doris_disabled");
    await expect(mockPanelProps!.api.saveInitial("draft-7", {})).rejects.toThrow("icd11_doris_disabled");
    expect(mockEditorSave).not.toHaveBeenCalled();
    expect(mockEngineInit).toHaveBeenCalledTimes(1);
    expect(alerts(root)).toContain("icd11DorisDisabledBody");
  });

  it("keeps its requester and engine across an unrelated account refresh", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    const root = await render(<OfflineCoding />);
    const request = mockPanelProps!.request;
    mockAccounts[0] = { ...mockAccounts[0], name: "Coder renamed" };
    await act(async () => { root.update(<OfflineCoding />); });
    expect(mockPanelProps!.request).toBe(request);
    expect(mockEngineInit).toHaveBeenCalledTimes(1);
    expect(mockEnsureSmartVa).toHaveBeenCalledTimes(1);
  });

  it("answers the picker's guidance routes for the open case from the editor, and nothing else", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    const root = await render(<OfflineCoding />);
    const request = mockPanelProps!.request;
    await expect(request("/api/v1/doris-clinical/hierarchy/draft-7", { method: "POST", json: { schema_version: 1, code: "1A00" } }))
      .resolves.toEqual({ answered: { schema_version: 1, code: "1A00" } });
    expect(mockOnGuidance).toHaveBeenCalledWith("hierarchy", { schema_version: 1, code: "1A00" });
    await expect(request("/api/v1/doris-clinical/hierarchy/draft-8", { method: "POST", json: {} })).rejects.toThrow("offline_server_unavailable");
    await expect(request("/api/v1/doris-clinical/process/draft-7", { method: "POST", json: {} })).rejects.toThrow("offline_server_unavailable");
    expect(mockOnGuidance).toHaveBeenCalledTimes(1);
    mockIcd11DorisEnabled = false;
    await act(async () => { root.update(<OfflineCoding />); });
    expect(mockPanelProps!.request).toBe(request);
    await expect(mockPanelProps!.request("/api/v1/doris-clinical/details/draft-7", { method: "POST", json: {} })).rejects.toThrow("icd11_doris_disabled");
    expect(mockOnGuidance).toHaveBeenCalledTimes(1);
  });

  it("ensures SmartVA on local coding entry before taking the editor lease", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    await render(<OfflineCoding />);

    expect(mockEnsureSmartVa).toHaveBeenCalledWith({ db: mockDb, userId: "coder-1", draftId: "draft-7" });
    expect(mockEnsureSmartVa.mock.invocationCallOrder[0]).toBeLessThan(mockAcquireEditor.mock.invocationCallOrder[0]);
    expect(mockPanelProps).toBeDefined();
  });

  it("opens coding with a current SmartVA result", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    mockEnsureSmartVa.mockResolvedValueOnce({ status: "current" });
    const root = await render(<OfflineCoding />);
    expect(mockEnsureSmartVa).toHaveBeenCalledTimes(1);
    expect(mockPanelProps).toBeDefined();
  });

  it("tries automatic generation only once per entry and retains manual Run after failure", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    (require("../src/drafts").getMeta as jest.Mock).mockResolvedValue({ smartva: mockSmartVaOptions });
    mockEnsureSmartVa.mockResolvedValueOnce({ status: "failed" });
    const root = await render(<OfflineCoding />);
    expect(labels(root)).toContain("localSmartVaRun");
    expect(alerts(root)).toContain("localSmartVaFailed");

    mockAccounts[0] = { ...mockAccounts[0], name: "Coder refreshed" };
    await act(async () => { root.update(<OfflineCoding />); });
    expect(mockEnsureSmartVa).toHaveBeenCalledTimes(1);
    expect(labels(root)).toContain("localSmartVaRun");
  });

  it("keeps manual SmartVA available for the current selected server account", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    (require("../src/drafts").getMeta as jest.Mock).mockResolvedValue({ smartva: mockSmartVaOptions });
    const root = await render(<OfflineCoding />);
    const run = root.root.find((node) => node.props.accessibilityLabel === "localSmartVaRun");
    await act(async () => { await run.props.onPress(); });

    expect(mockLoadAccounts).toHaveBeenCalledWith("active");
    expect(mockIdentitySelected).toHaveBeenCalledWith("coder-1");
    expect(mockPersistSmartVa).toHaveBeenCalledTimes(1);
  });

  it("fills missing standalone SmartVA settings from the interview's own HIV and malaria answers", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    mockAccounts.splice(0, mockAccounts.length, { user_id: "coder-1", name: "Coder", standalone: true });
    mockGetProfile.mockResolvedValue({ name: "Coder", country: "India", hiv_mortality: null, malaria_mortality: null });
    (require("../src/drafts").getOfflineCodingCase as jest.Mock).mockResolvedValue({
      client_draft_id: "draft-7", org_unit_id: null, started_at: null, completed_at: "2026-10-26T09:30:00.000+05:30",
      envelope: JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: { Id10002: "veryl", Id10003: "high" } }),
    });
    (require("../src/drafts").getMeta as jest.Mock).mockResolvedValue({ projectId: "SELF", smartva: null });
    const root = await render(<OfflineCoding />);
    const repair = root.root.find((node) => node.props.accessibilityLabel === "localSmartVaUseCurrentSettings");
    await act(async () => { await repair.props.onPress(); });

    expect(require("../src/drafts").setMeta).toHaveBeenCalledWith(mockDb, "draft-config:draft-7", {
      projectId: "SELF",
      smartva: expect.objectContaining({ source: "interview", options: expect.objectContaining({ country: "India", hiv: false, malaria: true }) }),
    });
    expect(labels(root)).toContain("localSmartVaRun");
  });

  it.each<[string, () => void]>([
    ["logout", () => { mockAccounts.length = 0; }],
    ["selected-mode switch", () => { mockSelectedSlot = "demo"; mockIdentitySelected.mockResolvedValue(false); }],
    ["project-access revocation", () => { mockAccounts[0] = { ...mockAccounts[0], offline_coding_access: ["OTHER"] }; }],
  ])("refuses a manual SmartVA result after %s and before persistence", async (_change, revoke) => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    (require("../src/drafts").getMeta as jest.Mock).mockResolvedValue({ smartva: mockSmartVaOptions });
    mockBeforeManualPersist.mockImplementationOnce(async () => { revoke(); });
    const root = await render(<OfflineCoding />);
    const run = root.root.find((node) => node.props.accessibilityLabel === "localSmartVaRun");
    await act(async () => { await run.props.onPress(); });

    expect(mockRunLocalSmartVa).toHaveBeenCalledTimes(1);
    expect(mockPersistSmartVa).not.toHaveBeenCalled();
    expect(alerts(root)).toContain("localSmartVaFailed");
  });

  it("does not cancel an async case load when the account object refreshes", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    let resolveCase!: (value: Record<string, unknown>) => void;
    const pendingCase = new Promise<Record<string, unknown>>((resolve) => { resolveCase = resolve; });
    (require("../src/drafts").getOfflineCodingCase as jest.Mock).mockReturnValueOnce(pendingCase);
    const root = await render(<OfflineCoding />);
    const row = root.root.find((node) => node.props.accessibilityLabel?.startsWith("draft-7 ·"));
    await act(async () => { row.props.onPress(); await Promise.resolve(); });
    mockAccounts[0] = { ...mockAccounts[0], name: "Coder refreshed" };
    await act(async () => { root.update(<OfflineCoding />); });
    await act(async () => {
      resolveCase({ client_draft_id: "draft-7", envelope: JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} }),
        org_unit_id: "OU-42", started_at: null, completed_at: null });
      await pendingCase;
    });
    expect(mockEngineInit).toHaveBeenCalledTimes(1);
  });

  it("restores coding milestones from provenance after reopening a completed interview", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    const codingOpened = { event: "coding_opened", at: "2026-10-26T10:01:00+05:30" };
    const processed = { event: "doris_processed", at: "2026-10-26T10:02:00+05:30", elapsed_ms: 850 };
    (require("../src/drafts").getOfflineCoding as jest.Mock).mockResolvedValueOnce({
      provenance: JSON.stringify({ codingTimelineV1: [codingOpened, processed] }),
    });

    await render(<OfflineCoding />);

    expect(mockPanelProps).toBeDefined();
    expect(JSON.parse(mockEnvelope)).toMatchObject({ codingTimelineV1: [codingOpened, processed] });
  });

  it("shows a retryable error when engine init returns a failure result", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    mockEngineInit.mockResolvedValueOnce({ ok: false, error: "init_failed", ms: 1 });
    const root = await render(<OfflineCoding />);
    expect(alerts(root)).toContain("error");
    const retry = root.root.find((node) => node.props.accessibilityLabel === "Retry");
    await act(async () => { retry.props.onPress(); });
    expect(mockEngineInit).toHaveBeenCalledTimes(2);
    expect(alerts(root)).toEqual([]);
  });

  it("shows a spinner with the engine's progress until DORIS is ready", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    let finish!: (value: Awaited<ReturnType<OfflineEngine["init"]>>) => void;
    mockEngineInit.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const root = await render(<OfflineCoding />);
    const text = () => JSON.stringify(root.toJSON());
    expect(text()).toContain("offlineDorisStarting");
    await act(async () => { mockProgress?.({ phase: "engine", percent: 40 }); });
    expect(text()).toContain("40%");
    await act(async () => { finish({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: false }); });
    expect(text()).not.toContain("offlineDorisStarting");
  });

  it("shows a retry while upload owns the case lease and releases the editor lease on unmount", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockEnsureSmartVa.mockResolvedValueOnce({ status: "skipped", reason: "busy" });
    mockAcquireEditor.mockReturnValueOnce(null);
    const root = await render(<OfflineCoding />);
    const row = root.root.find((node) => node.props.accessibilityLabel?.startsWith("draft-7 ·"));
    await act(async () => { row.props.onPress(); });
    expect(labels(root)).toContain("Retry");
    const release = jest.fn();
    mockAcquireEditor.mockReturnValue(release);
    const retryButton = root.root.find((node) => node.props.accessibilityLabel === "Retry");
    await act(async () => { retryButton.props.onPress(); });
    expect(mockPanelProps).toBeDefined();
    expect(mockEnsureSmartVa).toHaveBeenCalledTimes(2);
    expect(mockEnsureSmartVa.mock.invocationCallOrder[1]).toBeLessThan(mockAcquireEditor.mock.invocationCallOrder[1]);
    await act(async () => { root.unmount(); });
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("keeps retained local work unavailable after cached access is revoked", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockAccounts[0].access_removed = true;
    (require("../src/interviewerDb").openInterviewerDb as jest.Mock).mockClear();
    const root = await render(<OfflineCoding />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    expect(require("../src/interviewerDb").openInterviewerDb).not.toHaveBeenCalled();
  });
});

describe("the offline coding workspace's local API", () => {
  // Synthetic answers whose attachments survive the relevance strip (the golden case adult_attachments_and_narrative).
  const answers = {
    Id10013: "yes", Id10020: "no", Id10022: "no", Id10024: "2026-07-19", age_group: "adult", isNeonatal: "0", isChild: "0",
    isAdult: "1", Id10019: "male", ageInYears: 61, Id10476: "Narrated by the brother.",
    Id10476_audio: "who-va-attachment:00000000-0000-4000-8000-000000000001",
  };
  const metaStore = new Map<string, unknown>();
  const originalFetch = global.fetch;
  const fetchSpy = jest.fn();

  beforeEach(() => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockParams.caseId = "draft-7";
    metaStore.clear();
    fetchSpy.mockReset();
    global.fetch = fetchSpy as unknown as typeof fetch;
    const drafts = require("../src/drafts") as { getMeta: jest.Mock; setMeta: jest.Mock; getOfflineCodingCase: jest.Mock };
    drafts.getMeta.mockReset().mockImplementation(async (_db: unknown, key: string) => metaStore.get(key));
    drafts.setMeta.mockReset().mockImplementation(async (_db: unknown, key: string, value: unknown) => { metaStore.set(key, value); });
    drafts.getOfflineCodingCase.mockResolvedValue({
      client_draft_id: "draft-7", org_unit_id: "OU-42", started_at: null, completed_at: "2026-10-26T09:30:00.000+05:30",
      envelope: JSON.stringify({ instrumentId: "va_who_2022", instrumentVersion: "1", data: answers }),
    });
  });
  afterEach(() => { global.fetch = originalFetch; });

  const openCase = async () => {
    const root = await render(<OfflineCoding />);
    expect(mockScreenProps).toBeDefined();
    return { root, api: mockScreenProps!.api as import("../src/workspace/api").WorkspaceApi };
  };

  it("serves the workspace and every category from the phone, in shapes the client contract accepts", async () => {
    const { parseCategory, parseWorkspace } = jest.requireActual<typeof import("../src/workspace/contracts")>("../src/workspace/contracts");
    const { api } = await openCase();
    const workspace = await api.getWorkspace("draft-7", "coding");
    expect(parseWorkspace(JSON.parse(JSON.stringify(workspace)), "coding")).toEqual(workspace);
    expect(workspace.case).toMatchObject({
      va_sid: "draft-7", form_type_code: "WHO_2022_VA", age: 61, gender: "male", project_mode: "unmasked_doris",
      icd_classification: "icd11", narrative_qa_enabled: false, social_autopsy_enabled: false,
    });
    expect(workspace).toMatchObject({ step: "initial", blocked_by: [], smartva: null, smartva_can_run: false, narrative_qa: null, social_autopsy: null });
    expect(workspace.categories.map((item) => item.code)).toEqual(expect.arrayContaining(["vademographicdetails", "vanarrationanddocuments", "vacodassessment"]));
    expect(workspace.default_category).toBe("vademographicdetails");
    for (const { code } of workspace.categories) {
      const category = await api.getCategory("draft-7", code, "coding");
      expect(parseCategory(JSON.parse(JSON.stringify(category)), "coding")).toEqual(category);
    }
    const narration = await api.getCategory("draft-7", "vanarrationanddocuments", "coding");
    expect(narration.subcategories.flatMap((sub) => sub.items.map((item) => item.value))).toContain("digitva-local-attachment:Id10476_audio");
    await expect(api.getCategory("draft-7", "vamaternalsymptoms", "coding")).rejects.toMatchObject({ status: 404 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("resolves a local attachment value from the draft's own reference, and nothing else", async () => {
    await openCase();
    const media = await render(mockScreenProps!.renderMedia("digitva-local-attachment:Id10476_audio"));
    expect(media.toJSON()).toBeNull();
    expect(mockMediaProps).toMatchObject({ db: mockDb, draftId: "draft-7", reference: answers.Id10476_audio });
    expect(mockScreenProps!.renderMedia("/api/v1/attachments/abc.mp3")).toBeNull();
  });

  it("answers SmartVA status from the phone and never lets the shared lifecycle start a run", async () => {
    const { useSmartvaLifecycle } = jest.requireActual<typeof import("../src/workspace/useSmartvaLifecycle")>("../src/workspace/useSmartvaLifecycle");
    const { api } = await openCase();
    await expect(api.getSmartvaStatus("draft-7")).resolves.toEqual({ va_sid: "draft-7", status: "not_requested", can_run: false });
    expect(() => api.runSmartva("draft-7")).toThrow("offline_server_unavailable");
    const runSpy = jest.spyOn(api, "runSmartva");
    const statusSpy = jest.spyOn(api, "getSmartvaStatus");
    function Probe() {
      useSmartvaLifecycle({ api, identity: { vaSid: "draft-7", mode: "coding" }, status: "not_requested", canRun: false, active: true });
      return null;
    }
    await render(<Probe />);
    expect(statusSpy).toHaveBeenCalled();
    expect(runSpy).not.toHaveBeenCalled();
  });

  it("keeps the private note in the account store for this draft", async () => {
    const { api } = await openCase();
    await expect(api.getNote("draft-7", "coding")).resolves.toEqual({ va_sid: "draft-7", content: null, updated_at: null });
    const saved = await api.saveNote("draft-7", "coding", "Fever for a week.");
    expect(saved).toMatchObject({ va_sid: "draft-7", content: "Fever for a week." });
    expect(saved.updated_at).toEqual(expect.any(String));
    expect(metaStore.get("offlineNote:draft-7")).toEqual({ content: "Fever for a week.", updated_at: saved.updated_at });
    await expect(api.getNote("draft-7", "coding")).resolves.toEqual(saved);
    await expect(api.saveNote("draft-7", "coding", "x".repeat(20_001))).rejects.toThrow("offline_note_invalid");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("refuses every server-only call", async () => {
    const { api } = await openCase();
    const calls: Array<() => Promise<unknown>> = [
      () => api.getCodingStats(), () => api.getCodingAvailable(), () => api.allocateCoding(), () => api.releaseCoding(),
      () => api.searchIcd("draft-7", "icd11", "fever"), () => api.saveFinal("draft-7", {}), () => api.saveNotCodeable("draft-7", {}),
      () => api.saveNarrativeQuality("draft-7", {}), () => api.saveSocialAutopsy("draft-7", {}), () => api.getWorkflowEvents("draft-7"),
      () => api.runSmartva("draft-7"),
    ];
    for (const call of calls) await expect(Promise.resolve().then(call)).rejects.toThrow("offline_server_unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("shows a SmartVA result the capability probe confirms after the workspace first loaded, in the COD section", async () => {
    const appState = Object.getOwnPropertyDescriptor(AppState, "currentState");
    Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
    try {
      mockRealScreen = true;
      let settleProbe!: (value: { ok: boolean; version: string }) => void;
      mockSmartvaProbe.mockReturnValue(new Promise((resolve) => { settleProbe = resolve; }));
      metaStore.set("draft-config:draft-7", { smartva: mockSmartVaOptions });
      const cause = (rank: number, name: string | null) => ({ rank, cause: name, icd10: name ? "I64" : null, likelihood: name ? "Most likely" : null });
      const result = { age: "61", gender: "male", key_symptoms: [], causes: [cause(1, "Stroke"), cause(2, null), cause(3, null)], symptoms: [], module: "adult", cause34: "Stroke", icd10: "I64" };
      mockDb.getFirstAsync.mockImplementation(async (sql: string) => sql.includes("FROM local_smartva") ? {
        draft_id: "draft-7", status: "ready", result_json: JSON.stringify(result), error_code: null, answers_sha256: "a".repeat(64),
        options_digest: mockSmartVaOptions.optionsDigest, engine_version: "3.0.1",
        created_at: "2026-10-28T00:00:00.000Z", updated_at: "2026-10-28T00:00:00.000Z",
      } : sql.includes("project_id") ? { project_id: "SELF" } : { envelope: mockEnvelope });
      const root = await render(<OfflineCoding />);
      const api = mockScreenProps!.api;
      // Before the probe settles, the workspace has no SmartVA yet.
      const first = await api.getWorkspace("draft-7", "coding");
      expect(first).toMatchObject({ smartva: null });
      const codLabel = first.categories.find((item: { code: string }) => item.code === "vacodassessment")?.nav_label;
      expect(codLabel).toBeTruthy();
      const text = () => JSON.stringify(root.toJSON());
      expect(text()).toContain("Demographic");
      expect(text()).not.toContain("Stroke");
      // The probe settles while the coder is on another section.
      await act(async () => { settleProbe({ ok: true, version: "3.0.1" }); });
      await act(async () => { await Promise.resolve(); });
      // The section list's entry: the nearest pressable around the COD Assessment label.
      let cod: ReactTestInstance | null = root.root.findAll((node) => node.props.children === codLabel)[0] ?? null;
      while (cod && typeof cod.props.onPress !== "function") cod = cod.parent;
      expect(cod).toBeDefined();
      await act(async () => { cod!.props.onPress(); });
      await act(async () => { await Promise.resolve(); });
      expect(text()).toContain("SmartVA Analysis");
      expect(text()).toContain("Stroke");
    } finally {
      if (appState) Object.defineProperty(AppState, "currentState", appState);
    }
  });

  it.each<[string, string, () => void]>([
    ["project access is revoked", "offline_case_access_revoked", () => { mockAccounts[0] = { ...mockAccounts[0], offline_coding_access: ["OTHER"] }; }],
    ["the server refused the consent", "consent_refused", () => { metaStore.set("consent:server-refused:draft-7", true); }],
    ["ICD-11 coding is turned off", "icd11_doris_disabled", () => { mockIcd11DorisEnabled = false; }],
  ])("stops reading and writing the case when %s", async (_change, error, revoke) => {
    const { api } = await openCase();
    await expect(api.getWorkspace("draft-7", "coding")).resolves.toBeDefined();
    revoke();
    await expect(api.getWorkspace("draft-7", "coding")).rejects.toThrow(error);
    await expect(api.getCategory("draft-7", "vademographicdetails", "coding")).rejects.toThrow(error);
    await expect(api.getSmartvaStatus("draft-7")).rejects.toThrow(error);
    await expect(api.getNote("draft-7", "coding")).rejects.toThrow(error);
    await expect(api.saveNote("draft-7", "coding", "note")).rejects.toThrow(error);
    expect(metaStore.has("offlineNote:draft-7")).toBe(false);
  });
});

describe("the offline profile screen", () => {
  it("non-Plus redirects home", async () => {
    const root = await render(<OfflineProfileScreen />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });

  it("renders the complete profile and reloads saved values", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockGetProfile.mockResolvedValue({
      name: "Saved Coder", age_years: 41, sex: "female", designation: "Coder", facility_name: "PHC 1",
      country: "India", state: "Bihar", org_code: "UNIT7", hiv_mortality: "low", malaria_mortality: "none",
      updated_at: "2026-10-28T00:00:00.000Z",
    });
    const root = await render(<OfflineProfileScreen />);
    const showOptional = root.root.findAll((node) => node.props.accessibilityLabel === "offlineProfileShowOptional");
    if (showOptional.length) await act(async () => { showOptional[0].props.onPress(); });
    const inputs = root.root.findAllByType(TextInput);
    expect(inputs.find((node) => node.props.accessibilityLabel === "offlineProfileName")?.props.value).toBe("Saved Coder");
    expect(inputs.find((node) => node.props.accessibilityLabel === "offlineProfileAge")?.props.value).toBe("41");
    expect(inputs.map((node) => node.props.accessibilityLabel)).toEqual([
      "offlineProfileName", "offlineProfileCountry", "offlineProfileAge", "offlineProfileDesignation",
      "offlineProfileFacility", "offlineProfileState", "offlineProfileOrgCode",
    ]);
    const name = inputs.find((node) => node.props.accessibilityLabel === "offlineProfileName")!;
    await act(async () => { name.props.onChangeText("Edited Coder"); });
    const save = root.root.find((node) => node.props.accessibilityLabel === "offlineProfileSave");
    await act(async () => { save.props.onPress(); });
    expect(mockSaveProfile).toHaveBeenCalledWith(expect.objectContaining({ name: "Edited Coder", country: "India", org_code: "UNIT7" }));
  });

  it("asks every interview field up front and names what a standalone account still needs", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockSetUpStandaloneAccount.mockRejectedValue(new Error("standalone_profile_incomplete"));
    const root = await render(<StandaloneSetup />);
    expect(labels(root)).not.toContain("offlineProfileShowOptional");
    expect(root.root.findAllByType(TextInput).map((node) => node.props.accessibilityLabel)).toContain("offlineProfileAge");
    expect(labels(root)).toEqual(expect.arrayContaining(["offlineProfileFemale", "offlineProfileLevelHigh"]));
    const create = root.root.find((node) => node.props.accessibilityLabel === "standaloneCreate");
    await act(async () => { create.props.onPress(); });
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(root.root.find((node) => node.props.accessibilityRole === "alert").props.children).toBe("standaloneProfileIncomplete");
  });

  it("does not navigate when standalone profile/account setup fails", async () => {
    setOs("android");
    mockPlus.mockReturnValue(true);
    mockSetUpStandaloneAccount.mockRejectedValue(new Error("profile_write_failed"));
    const root = await render(<StandaloneSetup />);
    const create = root.root.find((node) => node.props.accessibilityLabel === "standaloneCreate");
    await act(async () => { create.props.onPress(); });
    expect(mockSetUpStandaloneAccount).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(root.root.find((node) => node.props.accessibilityRole === "alert").props.children).toBe("standaloneSetupFailed");
  });
});
