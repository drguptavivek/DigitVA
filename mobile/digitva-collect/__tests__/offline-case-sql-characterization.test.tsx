/**
 * Characterization (digitva-r8nh.24): the statements the offline coding screen sends to the local store, with their
 * text, parameters and order, for opening a case, a Step 1 save, the coding store's save, a SmartVA run and the
 * SmartVA settings fill; and the methods the offline WorkspaceApi answers. The mocks are those of
 * offline-coding-route.test.tsx.
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
    useFocusEffect: () => undefined,
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
jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLanguageTag: () => "en" }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { View, TextInput } = jest.requireActual("react-native") as typeof import("react-native");
  const press = ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", {
    accessibilityRole: "button", accessibilityLabel: label, onPress,
  });
  return {
    Button: press,
    TextLink: press,
    ChoiceRow: press,
    Card: ({ children }: { children?: React.ReactNode }) => ReactActual.createElement(View, null, children),
    FieldLabel: () => null,
    Separator: () => null,
    TextField: (props: object) => ReactActual.createElement(TextInput, props),
    Screen: ({ children, sidebar }: { children: React.ReactNode; sidebar?: React.ReactNode }) => ReactActual.createElement(View, null, sidebar, children),
    errorText: () => "error",
    // The petrol notice as a plain text (an alert for error and warning, as the real one), so the message assertions keep reading its words.
    Notice: ({ children, testID, tone }: { children: React.ReactNode; testID?: string; tone?: string }) =>
      (jest.requireActual("react") as typeof import("react")).createElement((require("react-native") as typeof import("react-native")).Text, { accessibilityRole: tone === "error" || tone === "warning" ? "alert" : undefined, testID }, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {}, input: {} }),
  };
});

import OfflineCoding from "../src/nativeRoutes/offlineCoding.native";
import type { WorkspaceApi } from "../src/workspace/api";

async function render(element: React.ReactElement) {
  let root!: Awaited<ReturnType<typeof create>>;
  await act(async () => { root = create(element); });
  return root;
}

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

/** Every statement the screen sent to the store, in order: [method, sql, params]. */
const statements = () => ([
  ...mockDb.getFirstAsync.mock.calls.map((call, index) => ({ at: mockDb.getFirstAsync.mock.invocationCallOrder[index], call: ["getFirstAsync", ...call] })),
  ...mockDb.runAsync.mock.calls.map((call, index) => ({ at: mockDb.runAsync.mock.invocationCallOrder[index], call: ["runAsync", call[0]] })),
  ...mockDb.getAllAsync.mock.calls.map((call, index) => ({ at: mockDb.getAllAsync.mock.invocationCallOrder[index], call: ["getAllAsync", ...call] })),
  ...mockDb.execAsync.mock.calls.map((call, index) => ({ at: mockDb.execAsync.mock.invocationCallOrder[index], call: ["execAsync", ...call] })),
]).sort((left, right) => left.at - right.at).map((item) => item.call);

const clearStatements = () => {
  mockDb.getFirstAsync.mockClear();
  mockDb.runAsync.mockClear();
  mockDb.getAllAsync.mockClear();
  mockDb.execAsync.mockClear();
};

const ENVELOPE = ["getFirstAsync", "SELECT envelope FROM drafts WHERE id = ?", ["draft-7"]];
const PROJECT = ["getFirstAsync", "SELECT project_id FROM drafts WHERE id = ?", ["draft-7"]];
const PROJECT_SITE = ["getFirstAsync", "SELECT project_id, site_id FROM drafts WHERE id = ?", ["draft-7"]];
const REFUSAL = ["getFirstAsync", "SELECT envelope, death_id, client_death_id FROM drafts WHERE id = ?", ["draft-7"]];
const CONSENT_KEYS = ["getFirstAsync", "SELECT death_id, client_death_id FROM drafts WHERE id = ?", ["draft-7"]];

beforeEach(() => {
  Object.defineProperty(Platform, "OS", { configurable: true, value: "android" });
  mockPlus.mockReturnValue(true);
  mockSelectedSlot = "active";
  mockAccounts.splice(0, mockAccounts.length, { user_id: "coder-1", name: "Coder", coding_access: true, offline_coding_access: ["SELF"] });
  mockIcd11DorisEnabled = true;
  mockPanelProps = undefined;
  mockScreenProps = undefined;
  mockRealScreen = false;
  mockEngineInit.mockClear();
  mockEditorSave.mockReset().mockResolvedValue(undefined);
  mockAcquireEditor.mockReset().mockReturnValue(jest.fn());
  mockSmartvaProbe.mockReset().mockResolvedValue({ ok: true, version: "3.0.1" });
  mockEnsureSmartVa.mockReset().mockResolvedValue({ status: "config_needed" });
  mockEnvelope = JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} });
  mockDb.getFirstAsync.mockReset().mockImplementation(async (sql: string) =>
    sql.includes("project_id") ? { project_id: "SELF", site_id: "SITE-1" } : sql.includes("death_id") ? { envelope: mockEnvelope, death_id: null, client_death_id: null } : { envelope: mockEnvelope },
  );
  mockDb.runAsync.mockReset().mockImplementation(async (_sql: string, params: unknown[]) => {
    mockEnvelope = String(params[0]);
    return { changes: 1 };
  });
  mockDb.getAllAsync.mockReset().mockResolvedValue([]);
  mockDb.execAsync.mockReset().mockResolvedValue(undefined);
  const drafts = require("../src/drafts") as Record<string, jest.Mock>;
  drafts.getOfflineCoding.mockReset().mockResolvedValue(null);
  drafts.getOfflineCodingCase.mockReset().mockResolvedValue({
    client_draft_id: "draft-7", envelope: JSON.stringify({ instrumentId: "VA", instrumentVersion: "1", data: {} }),
    org_unit_id: "OU-42", started_at: null, completed_at: "2026-10-26T09:30:00.000+05:30",
  });
  drafts.getMeta.mockReset().mockResolvedValue(null);
  drafts.saveOfflineCoding.mockReset().mockResolvedValue(undefined);
  for (const key of Object.keys(mockParams)) delete mockParams[key];
  mockParams.caseId = "draft-7";
});

const OFFLINE_METHODS = [
  "allocateCoding", "allocateReviewer", "checkDorisSelection", "codeOwnSubmission", "getCategory",
  "getCodingAllocation", "getCodingAvailable", "getCodingHistory", "getCodingProjects", "getCodingStats", "getDorisCodeInfo",
  "getNote", "getReviewerAllocation", "getReviewerAvailable", "getReviewerHistory", "getReviewerProjects", "getReviewerStats",
  "getSmartvaStatus", "getVaDefinitionForIcd", "getWorkflowEvents", "getWorkspace", "processDoris",
  "recode", "releaseCoding", "releaseReviewer", "runSmartva", "saveFinal", "saveInitial", "saveNarrativeQuality",
  "saveNotCodeable", "saveNote", "saveSocialAutopsy", "searchDorisTerms", "searchIcd",
];

it("the offline api answers every required method and neither optional one", async () => {
  const root = await render(<OfflineCoding />);
  expect(mockScreenProps).toBeDefined();
  expect(Object.keys(mockScreenProps!.api as WorkspaceApi).sort()).toEqual(OFFLINE_METHODS);
  await act(async () => root.unmount());
});

it("opening a case sends the same statements in the same order", async () => {
  clearStatements();
  const root = await render(<OfflineCoding />);
  expect(mockPanelProps).toBeDefined();
  expect(statements()).toEqual(OPEN_STATEMENTS);
  await act(async () => root.unmount());
});

it("a Step 1 save sends the same statements in the same order", async () => {
  const root = await render(<OfflineCoding />);
  expect(mockPanelProps).toBeDefined();
  clearStatements();
  await (mockScreenProps!.api as WorkspaceApi).saveInitial("draft-7", {});
  expect(mockEditorSave).toHaveBeenCalledTimes(1);
  expect(statements()).toEqual(SAVE_STATEMENTS);
  await act(async () => root.unmount());
});

it("the coding store's save sends the same statements in the same order", async () => {
  const root = await render(<OfflineCoding />);
  const editorMock = require("../src/workspace/offlineDoris").createOfflineDorisEditor as jest.Mock;
  const store = editorMock.mock.calls[editorMock.mock.calls.length - 1][1] as { save: (row: Record<string, unknown>) => Promise<void> };
  clearStatements();
  await store.save({ client_draft_id: "draft-7", updated_at: "2026-10-27T11:00:00.000+05:30", provenance: JSON.stringify({}) });
  expect(statements()).toEqual(STORE_SAVE_STATEMENTS);
  await act(async () => root.unmount());
});

it("a manual SmartVA run sends the same statements in the same order", async () => {
  (require("../src/drafts").getMeta as jest.Mock).mockResolvedValue({ smartva: mockSmartVaOptions });
  const root = await render(<OfflineCoding />);
  const run = root.root.find((node) => node.props.accessibilityLabel === "localSmartVaRun");
  clearStatements();
  await act(async () => { await run.props.onPress(); });
  expect(mockPersistSmartVa).toHaveBeenCalled();
  expect(statements()).toEqual(RUN_STATEMENTS);
  await act(async () => root.unmount());
});

it("filling missing SmartVA settings sends the same statements in the same order", async () => {
  const root = await render(<OfflineCoding />);
  const repair = root.root.find((node) => node.props.accessibilityLabel === "localSmartVaUseCurrentSettings");
  clearStatements();
  await act(async () => { await repair.props.onPress(); });
  expect(statements()).toEqual(REPAIR_STATEMENTS);
  await act(async () => root.unmount());
});

const UPDATE_ENVELOPE = ["runAsync", "UPDATE drafts SET envelope = ? WHERE id = ? AND envelope = ?"];
const LOCAL_SMARTVA = ["getFirstAsync", expect.stringContaining("FROM local_smartva WHERE draft_id = ?"), ["draft-7"]];
/** assertAllowed: the refusal check, then the draft's project. */
const ALLOWED = [REFUSAL, PROJECT];

const OPEN_STATEMENTS = [
  PROJECT_SITE, REFUSAL,
  // the coding_opened milestone, then the persisted timeline, then the cached SmartVA result
  ENVELOPE, UPDATE_ENVELOPE, ENVELOPE, LOCAL_SMARTVA,
  // the engine start's assertAllowed, and the editor's
  REFUSAL, REFUSAL, PROJECT, PROJECT,
];
const SAVE_STATEMENTS = [...ALLOWED, ...ALLOWED, ENVELOPE];
const STORE_SAVE_STATEMENTS = [...ALLOWED, ["execAsync", "BEGIN IMMEDIATE"], ENVELOPE, UPDATE_ENVELOPE, ENVELOPE, ["execAsync", "COMMIT"]];
const RUN_STATEMENTS = [REFUSAL, CONSENT_KEYS, ...ALLOWED, ...ALLOWED];
const REPAIR_STATEMENTS = [...ALLOWED, PROJECT_SITE];
