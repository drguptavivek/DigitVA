/**
 * Characterization of the phone interview screen (src/nativeRoutes/form.tsx) before digitva-r8nh.22 moves its
 * consent/refusal handlers, its draft SQL and its load effect out of the component. Pinned at the boundaries
 * that do not move: the SQLite handle (SQL text and parameters, in order), the drafts store functions, the router
 * and the form props. The mock preamble is native-reference-routes.test.tsx's, except that errorText returns the
 * error's own message.
 */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = {
  user_id: "u1",
  name: "Interviewer",
  collection_access: true,
  registration_access: true,
  standalone: false,
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
    // The real message, so draft_conflict / invalid_draft_envelope / a raw JSON SyntaxError stay distinguishable.
    errorText: (error: unknown) => (error instanceof Error ? error.message : String(error)),
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


import Form from "../src/nativeRoutes/form";
import { RefusalPanel } from "../src/RefusalPanel";
import { refusalAnswers } from "../src/refusalBoundary";
import { computeUtf8Sha256HexSync } from "../src/consent";
import { WHO_VA_FORM_VERSION } from "@drguptavivek/who-2022-va";

const FORM_ID = "44444444-4444-4444-8444-444444444444";
const SELECT_ENVELOPE = "SELECT envelope FROM drafts WHERE id = ?";
const SELECT_ENVELOPE_PREFILL = "SELECT envelope, prefill FROM drafts WHERE id = ?";
const RESUME_UPDATE = "UPDATE drafts SET envelope = ?, completed = 0, completion = NULL, upload_issue = NULL, draft_sync_dirty = 1 WHERE id = ? AND envelope = ?";
const SAVED_CONFIG = { projectId: "P1", locale: "en", enabledExtensions: [], instrumentCode: "WHO_2022_VA", smartva: null };
const NOTICE = "Notice";
const drafts = () => jest.requireMock("../src/drafts") as Record<string, jest.Mock>;
const consentConfig = (required = true) => ({
  project_id: "P1", consent_required: required, refusal_behaviour: "interview_without_informant_data",
  notice_versions: [{
    notice_version_id: "n1", version: 1, language: "en", text: NOTICE, text_sha256: computeUtf8Sha256HexSync(NOTICE),
    purposes: [{ code: "a", label: "A", required: true }], covered_fields: ["Id10007"], allowed_modes: ["spoken"], witness_allowed: false,
  }],
});
const storedDecision = (decision: "granted" | "refused") => ({
  envelope: { client_id: "c1", decision, client_draft_id: null }, project_id: "P1", covered_fields: ["Id10007"], recorded_by: "u1",
});

const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

/** Calls on the SQLite handle that read or write the drafts table, in order. */
const draftSql = () => [
  ...mockDb.getFirstAsync.mock.calls.map((call, index) => ({ call, order: mockDb.getFirstAsync.mock.invocationCallOrder[index] })),
  ...mockDb.runAsync.mock.calls.map((call, index) => ({ call, order: mockDb.runAsync.mock.invocationCallOrder[index] })),
]
  .filter(({ call }) => /\bdrafts\b/.test(String((call as unknown[])[0])))
  .sort((a, b) => a.order - b.order)
  .map(({ call }) => call);

let store: { save: jest.Mock; load: jest.Mock; remove: jest.Mock };
let storedEnvelope: string | null;

/**
 * An existing phone draft (row, saved config) whose stored envelope is `envelope`; `config` is the cached project
 * consent settings and `rows` the consent records on file (meta rows read by prefix).
 */
function seed(envelope: unknown, config: unknown, rows: Array<{ key: string; value: unknown }> = [], row: Record<string, unknown> = {}) {
  storedEnvelope = typeof envelope === "string" ? envelope : JSON.stringify(envelope);
  drafts().getDraftRow.mockResolvedValue({ id: FORM_ID, project_id: "P1", completed: 0, upload_issue: null, death_id: null, client_death_id: null, ...row });
  drafts().getMeta.mockImplementation(async (_db: unknown, key: string) =>
    key === "consentConfig" ? config : key === `draft-config:${FORM_ID}` ? SAVED_CONFIG : undefined);
  mockDb.getFirstAsync.mockImplementation((async (sql: string) => {
    if (sql === SELECT_ENVELOPE_PREFILL) return storedEnvelope === null ? null : { envelope: storedEnvelope, prefill: null };
    if (sql === SELECT_ENVELOPE) return storedEnvelope === null ? null : { envelope: storedEnvelope };
    return null;
  }) as never);
  mockDb.getAllAsync.mockImplementation((async (_sql: string, params: string[]) =>
    rows.filter((entry) => entry.key.startsWith(String(params[0]).replace("%", "")))
      .map((entry) => ({ key: entry.key, value: JSON.stringify(entry.value) }))) as never);
}

const open = async (userId = "u1") => {
  mockParams = { userId, projectId: "P1", siteId: "S1", draftId: FORM_ID };
  mockConsentProps = undefined;
  mockConfirmProps = undefined;
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Form />); });
  await settle();
  await settle();
  return tree;
};
const panel = (tree: ReturnType<typeof create>) => tree.root.findByType(RefusalPanel);
const shown = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());
const confirmOpen = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props["data-confirm"] === true).length > 0;
const press = (tree: ReturnType<typeof create>, label: string) =>
  act(async () => {
    tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0].props.onPress();
  });
/** Whether the invocation orders are strictly increasing. */
const inOrder = (order: number[]) => order.every((value, index) => index === 0 || (value > order[index - 1]! && value > 0));

// native-reference-routes.test.tsx's own reset, for the mocks this file uses.
beforeEach(() => {
  jest.clearAllMocks();
  mockAccount.user_id = "u1";
  mockAccount.standalone = false;
  mockOfflineProfile = null;
  mockDb.getFirstAsync.mockReset().mockResolvedValue(null);
  drafts().getDraftRow.mockReset().mockResolvedValue(null);
  mockReference = pack();
  mockCachedReference = mockReference;
  mockLockVersion = 0;
  mockObservedLockVersion = 0;
  mockFormProps = {};
  mockDefinitionResponse = undefined;
  (jest.requireMock("../src/formDefinitionRuntime").resolveNewInterviewDefinition as jest.Mock)
    .mockImplementation(async () => mockResolvedDefinition);
  (jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition as jest.Mock)
    .mockImplementation(async () => mockResolvedDefinition);
  (jest.requireMock("../src/sync").getCachedReferenceData as jest.Mock).mockImplementation(async () => mockCachedReference);
});

beforeEach(() => {
  store = { save: jest.fn(async () => undefined), load: jest.fn(async () => undefined), remove: jest.fn() };
  drafts().createDraftStore.mockImplementation(() => store);
  drafts().markCompleted.mockReset().mockResolvedValue(undefined);
  drafts().setMeta.mockReset().mockResolvedValue(undefined);
  drafts().clearRefusedDraft.mockReset().mockResolvedValue(undefined);
  drafts().restoreResumedPrefill.mockReset().mockResolvedValue(undefined);
  mockDb.runAsync.mockReset().mockResolvedValue({ changes: 0 } as never);
  mockDb.execAsync.mockReset().mockResolvedValue(undefined as never);
  mockRouter.back.mockReset();
  mockToast.mockReset();
});
afterEach(() => {
  drafts().getMeta.mockReset().mockResolvedValue(undefined);
  mockDb.getAllAsync.mockReset().mockResolvedValue([] as never);
});

describe("draft SQL on open", () => {
  it("reads an existing draft's envelope once to load it and once more to decide consent", async () => {
    seed({ locale: "en", data: {} }, consentConfig(false));
    const tree = await open();
    expect(mockFormProps.instrument).toBeTruthy();
    expect(draftSql()).toEqual([
      [SELECT_ENVELOPE, [FORM_ID]],
      [SELECT_ENVELOPE, [FORM_ID]],
    ]);
    await act(async () => tree.unmount());
  });

  it("reads a server-based draft's envelope through the same SELECT", async () => {
    seed({ locale: "en", data: {} }, consentConfig(false), [], { server_draft_id: "srv-1", base_updated_at: "2026-11-01T00:00:00Z" });
    const tree = await open();
    expect(mockFormProps.instrument).toBeTruthy();
    expect(draftSql()).toEqual([
      [SELECT_ENVELOPE, [FORM_ID]],
      [SELECT_ENVELOPE, [FORM_ID]],
    ]);
    await act(async () => tree.unmount());
  });

  it("names a missing draft row draft_missing", async () => {
    seed({ locale: "en", data: {} }, consentConfig(false));
    storedEnvelope = null;
    const tree = await open();
    expect(mockFormProps.instrument).toBeUndefined();
    expect(shown(tree)).toContain("draft_missing");
    await act(async () => tree.unmount());
  });

  it("reports unreadable JSON raw on a local draft but as invalid_draft_envelope on a server-based one", async () => {
    let syntax = "";
    try { JSON.parse("{bad"); } catch (error) { syntax = (error as Error).message; }
    seed("{bad", consentConfig(false));
    let tree = await open();
    expect(shown(tree)).toContain(syntax);
    expect(shown(tree)).not.toContain("invalid_draft_envelope");
    await act(async () => tree.unmount());

    seed("{bad", consentConfig(false), [], { server_draft_id: "srv-1", base_updated_at: "2026-11-01T00:00:00Z" });
    tree = await open();
    expect(shown(tree)).toContain("invalid_draft_envelope");
    await act(async () => tree.unmount());

    seed("[]", consentConfig(false));
    tree = await open();
    expect(shown(tree)).toContain("invalid_draft_envelope");
    await act(async () => tree.unmount());
  });

  it("reads a standalone draft's envelope and prefill, then its envelope for consent", async () => {
    const userId = "standalone-device";
    mockAccount.user_id = userId;
    mockAccount.standalone = true;
    seed({ locale: "hi", translation_version: 6 }, undefined);
    drafts().getDraftRow.mockResolvedValue({ completed: false });
    drafts().getMeta.mockResolvedValue(undefined);
    const tree = await open(userId);
    expect(draftSql()).toEqual([
      [SELECT_ENVELOPE_PREFILL, [FORM_ID]],
      [SELECT_ENVELOPE, [FORM_ID]],
    ]);
    expect(drafts().setMeta).toHaveBeenCalledWith(mockDb, `draft-config:${FORM_ID}`, expect.objectContaining({ locale: "hi", translationVersion: 6 }));
    expect(mockConsentProps).toMatchObject({ language: "hi" });
    await act(async () => tree.unmount());
  });
});

describe("refusal after the WHO consent question was answered No", () => {
  const ENVELOPE = { locale: "en", data: { Id10013: "no", Id10007: "Name", refusal_age_group: "child", refusal_sex: "male" } };

  it("restores the refusal profile from the stored draft", async () => {
    seed(ENVELOPE, consentConfig(false));
    const tree = await open();
    expect(mockFormProps.instrument).toBeUndefined();
    expect(panel(tree).props).toMatchObject({ locale: "en", age: "child", sex: "male" });
    await act(async () => tree.unmount());
  });

  it("Save refusal stores only the refusal answers over the stored draft, marks it complete and leaves", async () => {
    seed(ENVELOPE, consentConfig(false));
    const existing = { id: FORM_ID, schemaVersion: 1, updatedAt: "old", data: { Id10013: "no", Id10007: "Name" } };
    store.load.mockResolvedValue(existing);
    const tree = await open();
    await act(async () => { panel(tree).props.onAge("15_49y"); });
    await act(async () => { panel(tree).props.onSex("female"); });
    await act(async () => { panel(tree).props.onSave(); });
    await settle();
    expect(store.load).toHaveBeenCalledWith(FORM_ID);
    expect(store.save).toHaveBeenCalledTimes(1);
    const saved = store.save.mock.calls[0][0];
    expect(saved).toEqual({ ...existing, updatedAt: expect.any(String), data: { Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female" } });
    expect(saved.data).toEqual(refusalAnswers({ ...existing.data, Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female" }));
    expect(drafts().markCompleted).toHaveBeenCalledWith(mockDb, FORM_ID, { valid: true, issues: [] });
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    expect(inOrder([
      store.load.mock.invocationCallOrder[0]!,
      store.save.mock.invocationCallOrder[0]!,
      drafts().markCompleted.mock.invocationCallOrder[0]!,
      mockRouter.back.mock.invocationCallOrder[0]!,
    ])).toBe(true);
    await act(async () => tree.unmount());
  });

  it("Save refusal with no stored copy writes a new envelope on the open questionnaire", async () => {
    seed(ENVELOPE, consentConfig(false));
    const tree = await open();
    await act(async () => { panel(tree).props.onSave(); });
    await settle();
    const saved = store.save.mock.calls[0][0];
    expect(saved).toEqual({
      schemaVersion: 1, formVersion: WHO_VA_FORM_VERSION, id: FORM_ID, instrumentId: "WHO_2022_VA", instrumentVersion: "served-v2",
      currentSection: "served", createdAt: expect.any(String), updatedAt: expect.any(String),
      data: { Id10013: "no", refusal_age_group: "child", refusal_sex: "male" },
    });
    expect(saved.createdAt).toBe(saved.updatedAt);
    expect(drafts().markCompleted).toHaveBeenCalledWith(mockDb, FORM_ID, { valid: true, issues: [] });
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("a failed Save refusal stays on the panel with the error and completes nothing", async () => {
    seed(ENVELOPE, consentConfig(false));
    store.save.mockRejectedValue(new Error("disk_full"));
    const tree = await open();
    await act(async () => { panel(tree).props.onSave(); });
    await settle();
    expect(drafts().markCompleted).not.toHaveBeenCalled();
    expect(mockRouter.back).not.toHaveBeenCalled();
    // With the questionnaire loaded a message is a toast, the refusal screen included.
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "disk_full" });
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => tree.unmount());
  });

  it("Change consent asks to confirm in the interview language; Cancel closes the dialog", async () => {
    seed(ENVELOPE, consentConfig(false));
    const tree = await open();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConfirmProps).toMatchObject({
      title: "Confirm consent",
      message: "Has the respondent now agreed to the interview? Removed answers will not be restored.",
      confirmLabel: "Yes, consent granted",
      cancelLabel: "cancel",
    });
    expect(mockConsentProps).toBeUndefined();
    await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
    expect(confirmOpen(tree)).toBe(false);
    await act(async () => tree.unmount());
  });

  it("confirming resets the stored draft to Id10013 yes in one transaction and reopens the questionnaire", async () => {
    seed(ENVELOPE, consentConfig(false));
    mockDb.runAsync.mockResolvedValue({ changes: 1 } as never);
    const tree = await open();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    mockDb.getFirstAsync.mockClear();
    mockDb.runAsync.mockClear();
    drafts().setMeta.mockClear();
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    await settle();
    expect(drafts().clearRefusedDraft).toHaveBeenCalledWith(mockDb, FORM_ID);
    expect(mockDb.execAsync.mock.calls).toEqual([["BEGIN IMMEDIATE"], ["COMMIT"]]);
    expect(draftSql()).toEqual([
      [SELECT_ENVELOPE, [FORM_ID]],
      [RESUME_UPDATE, [JSON.stringify({ ...ENVELOPE, data: { Id10013: "yes" } }), FORM_ID, storedEnvelope]],
    ]);
    const resumeIndex = drafts().setMeta.mock.calls.findIndex(([, key]) => key === `consent:resume-who:${FORM_ID}`);
    expect(drafts().setMeta.mock.calls[resumeIndex]).toEqual([mockDb, `consent:resume-who:${FORM_ID}`, true]);
    // The prefill a new draft on this host gets now (the project's direct preset), never the pre-refusal one.
    expect(drafts().restoreResumedPrefill).toHaveBeenCalledWith(mockDb, FORM_ID, { answers: {}, lockedQuestionNames: [] }, expect.any(Object));
    expect(inOrder([
      drafts().clearRefusedDraft.mock.invocationCallOrder[0]!,
      mockDb.execAsync.mock.invocationCallOrder[0]!,
      mockDb.getFirstAsync.mock.invocationCallOrder[0]!,
      mockDb.runAsync.mock.invocationCallOrder[0]!,
      drafts().setMeta.mock.invocationCallOrder[resumeIndex]!,
      drafts().restoreResumedPrefill.mock.invocationCallOrder[0]!,
      mockDb.execAsync.mock.invocationCallOrder[1]!,
    ])).toBe(true);
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(0);
    expect(confirmOpen(tree)).toBe(false);
    expect(mockFormProps.instrument).toBeTruthy();
    await act(async () => tree.unmount());
  });

  it("a draft changed meanwhile rolls back, keeps the refusal and the open dialog, and says draft_conflict", async () => {
    seed(ENVELOPE, consentConfig(false));
    const tree = await open();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    await settle();
    expect(mockDb.execAsync.mock.calls).toEqual([["BEGIN IMMEDIATE"], ["ROLLBACK"]]);
    expect(drafts().setMeta).not.toHaveBeenCalledWith(mockDb, `consent:resume-who:${FORM_ID}`, true);
    expect(drafts().restoreResumedPrefill).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "draft_conflict" });
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    expect(confirmOpen(tree)).toBe(true);
    await act(async () => tree.unmount());
  });
});

describe("refusal of the consent notice on file", () => {
  it("Change consent reopens the consent screen when the settings are cached", async () => {
    seed({ locale: "en", data: {} }, consentConfig(), [{ key: `consent:draft:${FORM_ID}`, value: storedDecision("refused") }]);
    const tree = await open();
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    expect(mockConsentProps).toBeUndefined();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConsentProps).toMatchObject({ clientDraftId: FORM_ID, language: "en" });
    expect(mockConfirmProps).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("a server-refused draft regranted on the consent screen stores the resume flag and falls back to the WHO confirm", async () => {
    seed({ locale: "en", data: {} }, consentConfig(), [{ key: `consent:draft:${FORM_ID}`, value: storedDecision("granted") }], { upload_issue: "consent_refused" });
    const tree = await open();
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConsentProps).toMatchObject({ clientDraftId: FORM_ID });
    expect(mockConfirmProps).toBeUndefined();
    await act(async () => {
      (mockConsentProps!.onDecision as (e: unknown) => void)({ client_id: "c9", client_draft_id: FORM_ID, notice_version_id: "n1", decision: "granted" });
    });
    await settle();
    expect(drafts().setMeta).toHaveBeenCalledWith(mockDb, `consent:resume-who:${FORM_ID}`, true);
    expect(drafts().restoreResumedPrefill).toHaveBeenCalledWith(mockDb, FORM_ID, { answers: {}, lockedQuestionNames: [] }, expect.any(Object));
    // The server refusal is answered; what is left is the WHO question's own No, confirmed from the refusal panel.
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConfirmProps).toMatchObject({ title: "Confirm consent" });
    await act(async () => tree.unmount());
  });

  it("Change consent says the settings are unavailable when none are cached", async () => {
    seed({ locale: "en", data: {} }, undefined, [{ key: `consent:draft:${FORM_ID}`, value: storedDecision("refused") }]);
    const tree = await open();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConsentProps).toBeUndefined();
    expect(mockConfirmProps).toBeUndefined();
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "consentUnavailableInterview" });
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => tree.unmount());
  });
});

describe("questionnaire language switch", () => {
  const twoLanguages = (instrumentVersion = "served-v2") => {
    const reference = pack();
    Object.assign(reference.projects[0]!.project.form_options, {
      instrument_version: instrumentVersion,
      available_locales: [{ code: "en", label: "English" }, { code: "hi", label: "Hindi" }],
      translation_versions: { hi: 5 },
    });
    mockReference = reference;
    mockCachedReference = reference;
  };
  const chooseHindi = async (tree: ReturnType<typeof create>) => {
    await press(tree, "moreActions");
    await press(tree, "questionnaireLanguage");
    await press(tree, "Hindi");
    await settle();
  };

  it("saves the open answers first, then reloads the questionnaire in the chosen language with its version", async () => {
    twoLanguages();
    seed({ locale: "en", data: {} }, consentConfig(false));
    const tree = await open();
    const saveDraft = jest.fn(async () => undefined);
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft }); });
    const translations = jest.requireMock("../src/sync").translationsForDraft as jest.Mock;
    translations.mockClear();
    mockChooseUiLocale.mockClear();
    await chooseHindi(tree);
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(mockFormProps.locale).toBe("hi");
    expect(translations).toHaveBeenLastCalledWith("u1", mockDb, "P1", "WHO_2022_VA", "hi", 5, 5);
    expect(saveDraft.mock.invocationCallOrder[0]).toBeLessThan(translations.mock.invocationCallOrder[0]!);
    expect(mockChooseUiLocale).toHaveBeenLastCalledWith("hi");
    expect(drafts().createDraftStore).toHaveBeenLastCalledWith(mockDb, expect.objectContaining({ locale: "hi", translationVersion: 5 }));
    await act(async () => tree.unmount());
  });

  it("drops the translation version when the draft is pinned to another form version", async () => {
    twoLanguages("served-v3");
    seed({ locale: "en", data: {} }, consentConfig(false));
    const tree = await open();
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft: jest.fn(async () => undefined) }); });
    await chooseHindi(tree);
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenLastCalledWith("u1", mockDb, "P1", "WHO_2022_VA", "hi", undefined, 5);
    expect(drafts().createDraftStore).toHaveBeenLastCalledWith(mockDb, expect.objectContaining({ locale: "hi", translationVersion: undefined }));
    await act(async () => tree.unmount());
  });

  it("stays in the current language when the open answers cannot be saved", async () => {
    twoLanguages();
    seed({ locale: "en", data: {} }, consentConfig(false));
    const tree = await open();
    await act(async () => {
      (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft: jest.fn(async () => { throw new Error("save_failed"); }) });
    });
    await chooseHindi(tree);
    expect(mockFormProps.locale).toBe("en");
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "save_failed" });
    await act(async () => tree.unmount());
  });
});
