import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = {
  user_id: "u1",
  name: "Interviewer",
  collection_access: true,
  registration_access: true,
  standalone: false,
  supervision_access: false as boolean,
};
const mockDb = { getFirstAsync: jest.fn(async () => null), getAllAsync: jest.fn(async () => []), runAsync: jest.fn(async () => ({ changes: 0 })), execAsync: jest.fn(async () => undefined) };
const mockDeathRegistrationAccess = {
  user: mockAccount,
  is_admin: false,
  roles: ["interviewer"],
  demo_coding: { available: false, project_ids: [] },
  projects: [{
    project_id: "P1",
    project_name: "Project P1",
    has_tree: false,
    grants: [{ role: "interviewer", scope: "project", active: true, source: "assigned" }],
    sites: [{ site_id: "S1", site_name: "Site 1", roles: ["interviewer"] }],
    actions: {
      interview: [{ site_id: "S1", site_name: "Site 1", web_intake_mode: "both", org_units: [] }],
      register_death: [{ site_id: "S1", site_name: "Site 1", web_intake_mode: "both", org_units: [] }],
    },
  }],
};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
const mockReload = jest.fn();
const mockChooseUiLocale = jest.fn(async () => undefined);
let mockParams: {
  userId: string;
  projectId?: string;
  siteId?: string;
  draftId?: string;
  clientDeathId?: string;
  deathId?: string;
  refresh?: string;
  view?: string;
  filter?: string;
} = { userId: "u1" };
let mockReference: unknown;
let mockCachedReference: unknown;
let mockCachedCases: unknown[] = [];
let mockSubmittedRevisions: unknown[] = [];
let mockLocalRevisions: unknown[] = [];
let mockFormProps: Record<string, unknown> = {};
let mockConsentProps: Record<string, unknown> | undefined;
let mockConfirmProps: Record<string, unknown> | undefined;
let mockLockVersion = 0;
let mockObservedLockVersion = 0;
let mockDefinitionResponse: { body: string; sha256: string } | undefined;
const mockDefinitionCache = {
  initialize: jest.fn(async () => undefined),
  get: jest.fn(async () => undefined),
  put: jest.fn(async () => undefined),
};
const realRuntime = jest.requireActual("../src/formDefinitionRuntime") as typeof import("../src/formDefinitionRuntime");
const realEngine = jest.requireActual("@drguptavivek/who-2022-va") as typeof import("@drguptavivek/who-2022-va");
const mockServedInstrument = { id: "WHO_2022_VA", version: "served-v2", sections: [{ name: "served" }], questions: [] };
const mockResolvedDefinition = {
  instrument: mockServedInstrument,
  provenance: "served",
  pin: { instrumentVersion: "served-v2", definitionSha256: "a".repeat(64), definitionExtensions: [] },
};

function pack(mode = "both", projectId = "P1") {
  const project = {
    project_id: projectId,
    project_name: `Project ${projectId}`,
    web_intake_mode: mode,
    sites: [
      {
        project_id: projectId,
        site_id: "S1",
        site_name: "Site 1",
        web_intake_mode: mode,
      },
    ],
    form_options: {
      default_locale: "en",
      available_locales: [{ code: "en", label: "English" }],
      narration_languages: [{ code: "en", label: "English" }],
      instrument_version: "served-v2",
      definition_sha256: "a".repeat(64),
      enabled_extensions: [],
    },
    prefill_policy: {
      direct: {},
      units: {},
      answer_fields: {},
      locked_fields: [],
    },
  };
  return {
    bootstrap: {
      user: mockAccount,
      instrument_version: "v1",
      projects: [project],
    },
    projects: [{ project, units: { scoped: false, levels: [], units: [] } }],
  };
}

mockReference = pack();

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    CryptoEncoding: { HEX: "hex" },
    randomUUID: () => "44444444-4444-4444-8444-444444444444",
    digestStringAsync: async (_algorithm: string, value: string) =>
      createHash("sha256").update(value, "utf8").digest("hex"),
  };
});

jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
const mockRemoveListeners: Array<(event: { data: { action: { type: string } }; preventDefault: () => void }) => void> = [];
const mockNavigation = {
  addListener: (_name: string, callback: (typeof mockRemoveListeners)[number]) => {
    mockRemoveListeners.push(callback);
    return () => { mockRemoveListeners.splice(mockRemoveListeners.indexOf(callback), 1); };
  },
  dispatch: jest.fn(),
};
const mockHardwareBack = (type = "GO_BACK") => {
  const event = { data: { action: { type } }, preventDefault: jest.fn() };
  mockRemoveListeners.forEach((listener) => listener(event));
  return event;
};
beforeEach(() => { mockRemoveListeners.length = 0; });
jest.mock("expo-router", () => ({
  useNavigation: () => mockNavigation,
  useIsFocused: () => true,
  Redirect: () => null,
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (callback: () => undefined | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(callback, [callback]);
  },
}));
let mockPlus = false;
let mockOfflineCoding = false;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus }));
jest.mock("../src/codingCapabilities", () => ({ canUseOfflineCoding: () => mockOfflineCoding }));
jest.mock("../src/AppState", () => ({
  useAppState: () => {
    mockObservedLockVersion = mockLockVersion;
    return {
      accounts: [mockAccount],
      reload: mockReload,
      lockNow: jest.fn(),
      activity: jest.fn(),
      onBeforeLock: jest.fn(() => jest.fn()),
      chooseUiLocale: mockChooseUiLocale,
      lockVersion: mockLockVersion,
      syncAccount: async (
        userId: string,
        db: unknown,
        callbacks: {
          onSuperseded?: (uniqueId: string) => void;
          onDraftConflict?: (draftId: string) => void;
          onServerKept?: (notice: { uniqueId: string; locked: boolean }) => void;
          onCanCodeNow?: (uniqueId: string) => void;
        } = {},
      ) => {
        const sync = await jest.requireMock("../src/sync").syncInterviewer(
          userId,
          db,
          callbacks.onSuperseded,
          callbacks.onDraftConflict,
          callbacks.onServerKept,
          callbacks.onCanCodeNow,
        );
        const reference = await jest
          .requireMock("../src/sync")
          .refreshReferenceData(userId, db, { force: true });
        return { sync, reference };
      },
    };
  },
}));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => true,
  unlockedDb: () => undefined,
  openInterviewerDb: jest.fn(async () => mockDb),
}));
jest.mock("../src/formDefinitionCache", () => ({
  createNativeDefinitionCache: jest.fn(() => mockDefinitionCache),
}));
jest.mock("../src/formDefinitionRuntime", () => ({
  PinnedDefinitionError: class PinnedDefinitionError extends Error { code?: string },
  readDefinitionPin: (envelope: unknown) => jest.requireActual("../src/formDefinitionRuntime").readDefinitionPin(envelope),
  resolveNewInterviewDefinition: jest.fn(async () => mockResolvedDefinition),
  resolveSavedEnvelopeDefinition: jest.fn(async () => mockResolvedDefinition),
}));
jest.mock("../src/formDefinitions", () => jest.requireActual("../src/formDefinitions"));
jest.mock("../src/auth", () => ({
  takePickedHomeProject: jest.fn(() => undefined),
  trainingProjectFor: jest.fn(() => undefined),
  refreshAccessSummaryForAction: jest.fn(async () => mockDeathRegistrationAccess),
  authedRawRequest: jest.fn(async () => ({
    status: 200,
    headers: { definitionSha256: mockDefinitionResponse?.sha256 },
    body: mockDefinitionResponse?.body ?? "{}",
  })),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
}));
jest.mock("../src/drafts", () => ({
  listDraftsNamed: jest.fn(async () => []),
  listActions: jest.fn(async () => []),
  listCases: jest.fn(async () => []),
  listRegistrations: jest.fn(async () => []),
  getDraftRow: jest.fn(async () => null),
  draftForCase: jest.fn(async () => null),
  getMeta: jest.fn(async () => undefined),
  setMeta: jest.fn(async () => undefined),
  createDraftStore: jest.fn(() => ({
    save: jest.fn(),
    load: jest.fn(),
    remove: jest.fn(),
  })),
  markCompleted: jest.fn(),
  stripDraftCovered: jest.fn(async () => undefined),
  clearRefusedDraft: jest.fn(async () => undefined),
  clearRefusedDraftInTransaction: jest.fn(async () => undefined),
  restoreResumedPrefill: jest.fn(async () => undefined),
  isNeverSentDraft: jest.fn(async () => false),
  deleteUnsentDraft: jest.fn(async () => true),
}));
jest.mock("../src/revisions", () => ({
  fetchSubmittedRevisions: jest.fn(async () => mockSubmittedRevisions),
  listLocalRevisions: jest.fn(async () => mockLocalRevisions),
}));
jest.mock("../src/cases", () => {
  const actual = jest.requireActual("../src/cases") as Record<string, unknown>;
  return {
    ...actual,
    getCase: jest.fn(async () => ({
      death_id: "d1",
      project_id: "P1",
      unique_id: "VA-1",
      site_id: "S1",
      org_unit_id: null,
      state: "in_progress",
      prefill: {},
    })),
    listCases: jest.fn(async () => mockCachedCases),
    listActions: jest.fn(async () => []),
    listRegistrations: jest.fn(async () => []),
    getRegistration: jest.fn(async () => undefined),
    saveRegistration: jest.fn(async () => undefined),
    resolveDraftHost: jest.fn(async () => ({
      projectId: "P1",
      siteId: "S1",
      binding: {},
      prefill: undefined,
    })),
  };
});
jest.mock("../src/sync", () => ({
  trainingProjectOnPhone: jest.fn(async () => undefined),
  fetchCaseDetail: jest.fn(async () => ({
    death_id: "d1",
    project_id: "P1",
    unique_id: "VA-1",
    state: "in_progress",
    site_id: "S1",
    org_unit_id: null,
    prefill: {},
  })),
  getCachedReferenceData: jest.fn(async () => mockCachedReference),
  listPausedProjects: jest.fn(async () => []),
  draftSyncDefaults: jest.fn(() => undefined),
  refreshReferenceData: jest.fn(async () => mockReference),
  refreshCases: jest.fn(async () => undefined),
  syncInterviewer: jest.fn(async () => ({
    sent: 0,
    failed: 0,
    remaining: 0,
    supersededUniqueIds: [],
  })),
  fetchCasePage: jest.fn(
    async (_user: string, projectId: string, options: { cursor?: string }) => ({
      cases: [
        {
          death_id: options.cursor ? "d2" : "d1",
          project_id: projectId,
          unique_id: "VA-1",
          state: "registered",
          deceased_name: "Online",
          deceased_sex: "female",
          age_years: 40,
          date_of_death: null,
          site_id: "S1",
          org_unit_id: null,
          unit_name: null,
          source: "reported",
          details_pending: false,
          pending_flag: false,
          registered_by_me: false,
          started_by_me: false,
          my_draft_id: null,
          va_sid: null,
          created_at: "",
          updated_at: "",
          next_visit_at: null,
          last_contact_at: null,
          has_informant_phone: false,
          has_informant_phone_2: false,
        },
      ],
      next_cursor: options.cursor ? null : "next",
    }),
  ),
  targetsFrom: (project: {
    sites: Array<{ site_id: string; site_name?: string; project_id: string }>;
  }) =>
    project.sites.map((site) => ({
      key: site.site_id,
      label: site.site_name ?? site.site_id,
      siteId: site.site_id,
      projectId: site.project_id,
    })),
  startsDirectly: (
    project: { sites: Array<{ site_id: string; web_intake_mode?: string }> },
    siteId: string,
  ) =>
    project.sites.some(
      (site) =>
        site.site_id === siteId &&
        ["direct", "both"].includes(site.web_intake_mode ?? ""),
    ),
  registersDeaths: (project: { web_intake_mode: string }) =>
    ["death_register", "both"].includes(project.web_intake_mode),
  translationsForDraft: jest.fn(async () => null),
  refreshAuthorizedProjectDefinitions: jest.fn(async () => []),
  canUseBundledFallbackForProject: jest.fn(async () => true),
  markProjectDefinitionServed: jest.fn(async () => undefined),
  isUploadable: () => true,
}));
jest.mock("../src/i18n", () => ({
  ...jest.requireActual("../src/i18n"),
  t: (key: string, values?: Record<string, string | number>) => {
    if (key === "draftConflictNotice") {
      return "This interview was also edited on another device; the newer version was kept.";
    }
    if (key === "draftHashInvalidAttention") {
      return "This interview could not be verified. Open it, review the answers, and try sending it again.";
    }
    if (key === "submissionHistoryNotice") {
      return "A newer completed version is already with the coder; yours was saved as history.";
    }
    if (key === "submissionLockedNotice") {
      return "Coding has finished; only a send-back or reopen can change the coder's version.";
    }
    if (key === "storedInterviewId") {
      return `Stored interview: ${values?.uniqueId ?? ""}`;
    }
    if (key === "supersededInterviewNotice") {
      return "Another interview of this case is with the coder; yours was saved as history.";
    }
    if (key === "otherCompleteInterviewNotice") {
      return "Another complete interview of this case is with the supervisor.";
    }
    if (key === "otherDraftCheck") {
      return `${key} ${values?.date ?? ""}`;
    }
    return key;
  },
  uiLocale: () => "en",
}));
jest.mock("../src/draftSync", () => ({
  reconcileCaseDraft: jest.fn(async (_user: string, _db: unknown, _detail: unknown, local: unknown) => ({
    draft: local,
    conflict: false,
    message: null,
    imported: false,
  })),
  recordDraftMilestones: jest.fn(async () => undefined),
  recordDraftTimeline: jest.fn(async () => true),
}));
const mockToast = jest.fn();
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return require("../test-support/uiMockExtras").withUiExtras({
    Button: ({
      label,
      onPress,
      disabled,
      loading,
    }: {
      label: string;
      onPress?: () => void;
      disabled?: boolean;
      loading?: boolean;
    }) =>
      ReactActual.createElement(
        "button",
        { "data-label": label, "data-loading": Boolean(loading), disabled, onClick: onPress },
        label,
      ),
    Row: ({ children }: { children: ReactNode }) =>
      ReactActual.createElement("div", null, children),
    Card: ({ children }: { children: ReactNode }) => ReactActual.createElement("div", null, children),
    Separator: () => null,
    ListRow: ({ label, value, onPress, accessibilityLabel }: { label: string; value?: string; onPress?: () => void; accessibilityLabel?: string }) =>
      ReactActual.createElement(onPress ? "button" : "div", { "data-label": accessibilityLabel ?? label, onClick: onPress }, label, value),
    Notice: ({ children, action }: { children: ReactNode; action?: ReactNode }) => ReactActual.createElement("aside", null, children, action),
    ChoiceRow: ({ label, onPress }: { label: string; onPress?: () => void }) =>
      ReactActual.createElement("button", { "data-label": label, onClick: onPress }, label),
    SegmentedControl: ({ options, onChange }: { options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) =>
      ReactActual.createElement("div", null, options.map((option) =>
        ReactActual.createElement("button", { key: option.value, "data-label": option.label, onClick: () => onChange(option.value) }, option.label))),
    Screen: ({ children, variant, footer }: { children: ReactNode; variant?: string; footer?: ReactNode }) =>
      ReactActual.createElement("main", { "data-variant": variant }, children, footer),
    errorText: () => "error",
    stateLabel: (state: string) => state,
    useUiStyles: () => ({
      text: {},
      muted: {},
      headline: {},
      error: {},
      card: {},
      input: {},
      fieldLabel: {},
    }),
  });
});
jest.mock("../src/ConfirmDialog", () => ({
  ConfirmDialog: (props: Record<string, unknown>) => {
    mockConfirmProps = props;
    return (jest.requireActual("react") as typeof React).createElement("section", { "data-confirm": true });
  },
}));
jest.mock("../src/web/StationConsentPanel", () => ({
  RespondentConsentPanel: (props: Record<string, unknown>) => {
    mockConsentProps = props;
    return (jest.requireActual("react") as typeof React).createElement("section", { "data-consent-panel": true });
  },
}));
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/attachmentServices", () => ({ useAttachmentServices: () => ({}) }));
jest.mock("../src/smartva/ensureLocal", () => ({ ensureLocalSmartVa: jest.fn(async () => undefined) }));
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: jest.fn(() => ({})) }));
let mockOfflineProfile: unknown = null;
jest.mock("../src/offlineProfile", () => ({
  ...jest.requireActual("../src/offlineProfile"),
  getOfflineProfile: jest.fn(async () => mockOfflineProfile),
}));
jest.mock(
  "@drguptavivek/who-2022-va/native",
  () => ({
    WhoVaForm: (props: Record<string, unknown>) => {
      mockFormProps = props;
      const ReactActual = jest.requireActual("react") as typeof React;
      return ReactActual.createElement("section", {
        "data-form-version": (props.instrument as { version?: string } | undefined)?.version,
      });
    },
    WhoVaQuestionControls: {
      Date: () => null,
      Integer: () => null,
      Text: () => null,
    },
  }),
  { virtual: true },
);
jest.mock(
  "@drguptavivek/who-2022-va",
  () => {
    const actual = jest.requireActual("@drguptavivek/who-2022-va") as Record<string, unknown>;
    return {
      ...actual,
      createWhoVa2022Instrument: jest.fn(() => ({
        id: "WHO_2022_VA",
        version: "v1",
        sections: [{ name: "start" }],
        questions: [],
      })),
      resolveUiMessages: () => ({}),
      WHO_VA_BUILT_IN_UI_TRANSLATIONS: {},
    };
  },
  { virtual: true },
);

import Register from "../src/nativeRoutes/register";
import Form from "../src/nativeRoutes/form";
import Worklist from "../src/nativeRoutes/worklist";
import { fetchCasePage } from "../src/sync";

/*
 * Pins the interview-supervisor paths of the worklist on its present behaviour (move-only refactor guard,
 * digitva-r8nh.26): the Supervision row on Home, and the online-cases list with Load more for a supervision-only account.
 */
const settle = async () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const dump = (tree: ReturnType<typeof create>) =>
  JSON.stringify(tree.toJSON(), (key, value) => ((key === "data" && Array.isArray(value)) || key === "refreshControl" || key === "ListHeaderComponent" ? undefined : value));
const pullRefresh = (tree: ReturnType<typeof create>) =>
  tree.root.findAll((n) => typeof n.props.refreshControl?.props?.onRefresh === "function")[0].props.refreshControl.props.onRefresh();
const supervisionRows = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props["data-label"] === "homeBlockSupervisor");

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = { userId: "u1" };
  mockAccount.collection_access = true;
  mockAccount.registration_access = true;
  mockAccount.supervision_access = false;
  mockPlus = false;
  mockOfflineCoding = false;
  mockReference = pack();
  mockCachedReference = mockReference;
  mockCachedCases = [];
  mockSubmittedRevisions = [];
  mockLocalRevisions = [];
  (jest.requireMock("../src/sync").getCachedReferenceData as jest.Mock).mockImplementation(async () => mockReference);
  (jest.requireMock("../src/sync").refreshReferenceData as jest.Mock).mockImplementation(async () => mockReference);
  (jest.requireMock("../src/drafts").getMeta as jest.Mock).mockImplementation(async () => undefined);
  (jest.requireMock("../src/revisions").fetchSubmittedRevisions as jest.Mock).mockImplementation(async () => mockSubmittedRevisions);
  (jest.requireMock("../src/revisions").listLocalRevisions as jest.Mock).mockImplementation(async () => mockLocalRevisions);
});

async function mount() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Worklist />); });
  await settle();
  await settle();
  return tree;
}

describe("worklist supervision entry", () => {
  it("shows the Supervision row on Home for an account with supervision access, and opens /supervision", async () => {
    mockAccount.supervision_access = true;
    const tree = await mount();
    expect(supervisionRows(tree).length).toBeGreaterThan(0);
    await act(async () => supervisionRows(tree).find((n) => typeof n.props.onClick === "function")!.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/supervision", params: { userId: "u1" } });
    await act(async () => tree.unmount());
  });

  it("never shows a Local cases row on Home, even on Plus with offline coding", async () => {
    mockPlus = true;
    mockOfflineCoding = true;
    const tree = await mount();
    expect(dump(tree)).toContain("registerDeath");
    expect(tree.root.findAll((n) => n.props["data-label"] === "localCases")).toHaveLength(0);
    expect(dump(tree)).not.toContain("localCases");
    await act(async () => tree.unmount());
  });

  it("hides the Supervision row without supervision access", async () => {
    const tree = await mount();
    expect(supervisionRows(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("hides the Supervision row in training mode even with supervision access", async () => {
    mockAccount.supervision_access = true;
    (jest.requireMock("../src/sync").trainingProjectOnPhone as jest.Mock).mockResolvedValue("P1");
    const tree = await mount();
    expect(dump(tree)).toContain("trainingMode");
    expect(supervisionRows(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("keeps the Supervision row off the Interviews tab: only Home carries it", async () => {
    mockAccount.supervision_access = true;
    mockParams = { userId: "u1", view: "interviews" };
    const tree = await mount();
    expect(supervisionRows(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
  });
});

describe("worklist online cases for a supervision-only account", () => {
  beforeEach(() => {
    mockAccount.collection_access = false;
    mockAccount.registration_access = false;
    mockAccount.supervision_access = true;
    mockParams = { userId: "u1", view: "interviews" };
  });

  it("lists the online page after a refresh and Load more appends the next page by cursor", async () => {
    const tree = await mount();
    await act(async () => pullRefresh(tree));
    await settle();
    expect(fetchCasePage).toHaveBeenCalledWith("u1", "P1", { limit: 50 });
    expect(dump(tree)).toContain("Online");
    const loadMore = () => tree.root.findAll((n) => n.props["data-label"] === "loadMore");
    expect(loadMore().length).toBeGreaterThan(0);
    await act(async () => loadMore()[0].props.onClick());
    await settle();
    expect(fetchCasePage).toHaveBeenLastCalledWith("u1", "P1", { limit: 50, cursor: "next" });
    // The last page carries no cursor: the button goes.
    expect(loadMore()).toHaveLength(0);
    await act(async () => tree.unmount());
  });
});
