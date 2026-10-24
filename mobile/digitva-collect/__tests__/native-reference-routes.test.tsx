import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";
import { AppState, Text } from "react-native";
import * as Crypto from "expo-crypto";

const mockAccount = {
  user_id: "u1",
  name: "Interviewer",
  collection_access: true,
  registration_access: true,
};
const mockDb = { getFirstAsync: jest.fn(async () => null), getAllAsync: jest.fn(async () => []), runAsync: jest.fn(async () => ({ changes: 0 })) };
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
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
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
  openInterviewerDb: jest.fn(async () => mockDb),
}));
jest.mock("../src/formDefinitionCache", () => ({
  createNativeDefinitionCache: jest.fn(() => mockDefinitionCache),
}));
jest.mock("../src/formDefinitionRuntime", () => ({
  PinnedDefinitionError: class PinnedDefinitionError extends Error { code?: string },
  resolveNewInterviewDefinition: jest.fn(async () => mockResolvedDefinition),
  resolveSavedEnvelopeDefinition: jest.fn(async () => mockResolvedDefinition),
}));
jest.mock("../src/formDefinitions", () => jest.requireActual("../src/formDefinitions"));
jest.mock("../src/auth", () => ({
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
  listDrafts: jest.fn(async () => []),
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
    if (key === "otherDraftActiveAt") {
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
}));
const mockToast = jest.fn();
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
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
    Screen: ({ children, variant }: { children: ReactNode; variant?: string }) =>
      ReactActual.createElement("main", { "data-variant": variant }, children),
    errorText: () => "error",
    stateLabel: (state: string) => state,
    useUiStyles: () => ({
      text: {},
      muted: {},
      headline: {},
      error: {},
      card: {},
      input: {},
    }),
  };
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
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: () => ({}) }));
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
import Case from "../src/nativeRoutes/case";
import Worklist from "../src/nativeRoutes/worklist";
import {
  fetchCaseDetail,
  fetchCasePage,
  getCachedReferenceData,
  refreshReferenceData,
  refreshCases,
  syncInterviewer,
} from "../src/sync";
import { saveRegistration } from "../src/cases";
import { getMeta, setMeta } from "../src/drafts";
import { computeUtf8Sha256HexSync } from "../src/consent";

/** The rendered tree as JSON without the FlatList's own `data` prop, which repeats every row's fields. */
const dump = (tree: ReturnType<typeof create>) =>
  JSON.stringify(tree.toJSON(), (key, value) => (key === "data" && Array.isArray(value) ? undefined : value));
const press = (tree: ReturnType<typeof create>, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0].props.onPress();
const pressStarting = (tree: ReturnType<typeof create>, prefix: string) =>
  tree.root.findAll((n) => String(n.props.accessibilityLabel ?? "").startsWith(prefix) && typeof n.props.onPress === "function")[0].props.onPress();

const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = { userId: "u1", view: "interviews" };
  mockReference = pack();
  mockCachedReference = mockReference;
  mockCachedCases = [];
  mockSubmittedRevisions = [];
  mockLocalRevisions = [];
  mockLockVersion = 0;
  mockObservedLockVersion = 0;
  mockFormProps = {};
  mockDefinitionResponse = undefined;
  mockDefinitionCache.get.mockReset().mockResolvedValue(undefined);
  mockDefinitionCache.put.mockReset().mockResolvedValue(undefined);
  (jest.requireMock("../src/formDefinitionRuntime").resolveNewInterviewDefinition as jest.Mock)
    .mockImplementation(async (...args: unknown[]) => mockResolvedDefinition);
  (jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition as jest.Mock)
    .mockImplementation(async (...args: unknown[]) => mockResolvedDefinition);
  (jest.requireMock("../src/drafts").listDrafts as jest.Mock).mockImplementation(
    async () => [],
  );
  (jest.requireMock("../src/revisions").fetchSubmittedRevisions as jest.Mock).mockImplementation(
    async () => mockSubmittedRevisions,
  );
  (jest.requireMock("../src/revisions").listLocalRevisions as jest.Mock).mockImplementation(
    async () => mockLocalRevisions,
  );
  (getCachedReferenceData as jest.Mock).mockImplementation(
    async () => mockReference,
  );
  (refreshReferenceData as jest.Mock).mockImplementation(
    async () => mockReference,
  );
});

describe("native project-aware routes", () => {
  it("loads only authorized submitted metadata and opens its revise route on tap", async () => {
    const summary = {
      draft_id: "server-draft-1",
      project_id: "P1",
      site_id: "S1",
      death_id: null,
      va_sid: "va-1",
      unique_id: "VA-SUBMITTED",
      status: "submitted",
      updated_at: "2026-10-05T00:00:00Z",
    };
    mockSubmittedRevisions = [summary, { ...summary, draft_id: "other", project_id: "P2" }];
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await settle();

    expect(jest.requireMock("../src/revisions").fetchSubmittedRevisions).toHaveBeenCalledWith("u1");
    const rendered = dump(tree!);
    expect(rendered).toContain("VA-SUBMITTED");
    expect(rendered).not.toContain('"other"');
    expect(mockRouter.push).not.toHaveBeenCalled();
    const revise = tree!.root.findByProps({ "data-label": "reviseInterview" });
    await act(async () => revise.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: "/revision",
      params: { userId: "u1", draftId: "server-draft-1", projectId: "P1", siteId: "S1", vaSid: "va-1" },
    });
    await act(async () => tree!.unmount());
  });

  it("titles a submitted row with the deceased's name and the ID below, and the ID alone without a name", async () => {
    const base = {
      project_id: "P1", site_id: "S1", death_id: null, va_sid: "va-1", status: "submitted",
      updated_at: "2026-10-05T00:00:00Z",
    };
    mockSubmittedRevisions = [
      { ...base, draft_id: "d1", unique_id: "VA-NAMED", deceased_name: "Asha Rao" },
      { ...base, draft_id: "d2", unique_id: "VA-NONAME" },
    ];
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await settle();
    const rendered = dump(tree!);
    expect(rendered).toContain("Asha Rao");
    expect(rendered.split("VA-NAMED").length - 1).toBe(1);
    expect(rendered).toContain("VA-NONAME");
    expect(rendered.split("Asha Rao").length - 1).toBe(1);
    await act(async () => tree!.unmount());
  });

  it("keeps the offline worklist when submitted metadata cannot be fetched", async () => {
    const { fetchSubmittedRevisions } = jest.requireMock("../src/revisions") as {
      fetchSubmittedRevisions: jest.Mock;
    };
    fetchSubmittedRevisions.mockRejectedValue(new Error("offline"));
    mockLocalRevisions = [{
      draft_id: "local-revision-1",
      project_id: "P1",
      unique_id: "VA-LOCAL",
      state: "editing",
      updated_at: "2026-10-05T00:00:00Z",
      refusal_code: null,
    }];
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await settle();

    const rendered = dump(tree!);
    expect(rendered).toContain("revisionRetry");
    expect(rendered).toContain("VA-LOCAL");
    await act(async () => tree!.unmount());
  });

  it("refreshes authorized project definitions after loading the unlocked reference pack", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();

    expect(jest.requireMock("../src/sync").refreshAuthorizedProjectDefinitions)
      .toHaveBeenCalledWith("u1", mockDb, mockReference);
    await act(async () => tree!.unmount());
  });

  it("shows a spinner on Refresh while it runs, then the refreshed content", async () => {
    mockCachedReference = pack("both", "P1");
    mockReference = pack("both", "P1");
    let release!: () => void;
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    (refreshReferenceData as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => { release = () => resolve(mockReference); }),
    );
    const button = () => tree!.root.findAllByProps({ "data-label": "refresh" }).at(-1)!;
    expect(button().props["data-loading"]).toBe(false);
    let pending!: Promise<unknown>;
    await act(async () => { pending = Promise.resolve(button().props.onClick()); });
    expect(button().props["data-loading"]).toBe(true);
    await act(async () => { release(); await pending; });
    await settle();
    expect(button().props["data-loading"]).toBe(false);
    await act(async () => tree!.unmount());
  });

  it("drops a submitted metadata response after foreground refresh revokes its project", async () => {
    mockCachedReference = pack("both", "P1");
    mockReference = pack("both", "P1");
    mockSubmittedRevisions = [{
      draft_id: "current-draft",
      project_id: "P2",
      site_id: "S1",
      death_id: null,
      va_sid: "va-current",
      unique_id: "VA-CURRENT",
      status: "submitted",
    }];
    let resolveOldList!: (rows: unknown[]) => void;
    const { fetchSubmittedRevisions } = jest.requireMock("../src/revisions") as {
      fetchSubmittedRevisions: jest.Mock;
    };
    fetchSubmittedRevisions
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveOldList = resolve; }),
      )
      .mockImplementationOnce(async () => mockSubmittedRevisions);

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await settle();

    expect(fetchSubmittedRevisions).toHaveBeenCalledTimes(2);
    expect(dump(tree!)).not.toContain("VA-REVOKED");
    mockReference = pack("both", "P2");
    const refreshButtons = tree!.root.findAllByProps({ "data-label": "refresh" });
    await act(async () => refreshButtons[refreshButtons.length - 1].props.onClick());
    await settle();
    await settle();

    expect(fetchSubmittedRevisions).toHaveBeenCalledTimes(3);
    expect(dump(tree!)).toContain("VA-CURRENT");
    expect(dump(tree!)).not.toContain("VA-REVOKED");
    await act(async () => {
      resolveOldList([{
        draft_id: "revoked-draft",
        project_id: "P1",
        site_id: "S1",
        death_id: null,
        va_sid: "va-revoked",
        unique_id: "VA-REVOKED",
        status: "submitted",
      }]);
    });
    await settle();

    const rendered = dump(tree!);
    expect(rendered).toContain("VA-CURRENT");
    expect(rendered).not.toContain("VA-REVOKED");
    expect(tree!.root.findAllByProps({ "data-label": "reviseInterview" })).toHaveLength(1);
    expect(mockRouter.push).not.toHaveBeenCalledWith(
      expect.objectContaining({ pathname: "/revision" }),
    );
    await act(async () => tree!.unmount());
  });

  it("opens an imported server draft with its locale and current project config", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const row = {
      id,
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      death_id: "d1",
      unique_id: "VA-1",
      client_death_id: null,
      server_draft_id: "22222222-2222-4222-8222-222222222222",
      base_updated_at: "2026-10-03T00:00:00Z",
      draft_sync_dirty: 0,
      draft_sync_blocked: 0,
    };
    mockParams = { userId: "u1", projectId: "P1", draftId: id, deathId: "d1" };
    (jest.requireMock("../src/drafts").getDraftRow as jest.Mock).mockResolvedValueOnce(row);
    (jest.requireMock("../src/draftSync").reconcileCaseDraft as jest.Mock).mockResolvedValueOnce({
      draft: row,
      conflict: false,
      message: null,
      imported: true,
    });
    mockDb.getFirstAsync.mockImplementationOnce(async () => ({
      envelope: JSON.stringify({ locale: "hi", translation_version: 17 }),
    }) as never);

    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Form />);
    });
    await settle();
    await settle();

    expect(dump(tree!)).not.toContain("referenceDataUnavailable");
    expect(jest.requireMock("../src/drafts").setMeta).toHaveBeenCalledWith(
      mockDb,
      `draft-config:${id}`,
      expect.objectContaining({ projectId: "P1", locale: "hi", translationVersion: 17 }),
    );
    expect(jest.requireMock("../src/drafts").createDraftStore).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({ locale: "hi", translationVersion: 17 }),
    );
    await act(async () => tree!.unmount());
  });

  it("opens a new interview with the resolved served definition and pins draft storage", async () => {
    const id = "44444444-4444-4444-8444-444444444444";
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: id };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();

    expect(jest.requireMock("../src/formDefinitionRuntime").resolveNewInterviewDefinition)
      .toHaveBeenCalledWith(expect.objectContaining({
        accountId: "u1",
        projectId: "P1",
        options: expect.objectContaining({ instrumentVersion: "served-v2", definitionSha256: "a".repeat(64) }),
        narrationLanguageCodes: ["en"],
      }));
    expect(mockFormProps.instrument).toEqual(mockServedInstrument);
    expect(jest.requireMock("../src/drafts").createDraftStore).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({ definitionPin: mockResolvedDefinition.pin }),
    );
    await act(async () => tree!.unmount());
  });

  it("downloads and verifies the current served definition through the native route", async () => {
    const id = "44444444-4444-4444-8444-444444444444";
    const definition = {
      ...realEngine.createWhoVa2022Instrument([]),
      version: "20261005-a1b2c3d4e5",
      engineVersion: realEngine.ENGINE_VERSION,
      extensions: [],
    };
    const body = JSON.stringify(definition);
    const sha256 = await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      body,
      { encoding: Crypto.CryptoEncoding.HEX },
    );
    mockDefinitionResponse = { body, sha256 };
    const packData = pack() as ReturnType<typeof pack>;
    const project = packData.projects[0].project;
    project.form_options.definition_sha256 = sha256;
    project.form_options.instrument_version = definition.version;
    mockReference = packData;
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: id };
    const resolveNew = jest.requireMock("../src/formDefinitionRuntime").resolveNewInterviewDefinition as jest.Mock;
    resolveNew.mockImplementation((input) => realRuntime.resolveNewInterviewDefinition(input));

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();

    expect(jest.requireMock("../src/auth").authedRawRequest).toHaveBeenCalledWith(
      "u1",
      "/api/v1/instruments/WHO_2022_VA/definition?project_id=P1",
      expect.objectContaining({ acceptGzip: true }),
    );
    expect(mockFormProps.instrument).toMatchObject({ version: definition.version });
    expect(jest.requireMock("../src/drafts").createDraftStore).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({
        definitionPin: {
          instrumentVersion: definition.version,
          definitionSha256: sha256,
          definitionExtensions: [],
        },
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("downloads the exact historical slice before reopening an encrypted draft", async () => {
    const id = "55555555-5555-4555-8555-555555555555";
    const definition = {
      ...realEngine.createWhoVa2022Instrument([]),
      version: "historic-v1",
      engineVersion: realEngine.ENGINE_VERSION,
      extensions: [],
    };
    const body = JSON.stringify(definition);
    const sha256 = await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      body,
      { encoding: Crypto.CryptoEncoding.HEX },
    );
    mockDefinitionResponse = { body, sha256 };
    const projectPack = pack();
    const project = projectPack.projects[0].project;
    project.form_options.instrument_version = "historic-v1";
    project.form_options.definition_sha256 = "c".repeat(64);
    mockReference = projectPack;
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: id };
    const row = {
      id,
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      death_id: null,
      unique_id: "VA-OLD",
      client_death_id: null,
      server_draft_id: null,
      base_updated_at: null,
      draft_sync_dirty: 0,
      draft_sync_blocked: 0,
    };
    (jest.requireMock("../src/drafts").getDraftRow as jest.Mock).mockResolvedValueOnce(row);
    (jest.requireMock("../src/drafts").getMeta as jest.Mock).mockImplementationOnce(async () => ({
      projectId: "P1",
      locale: "en",
      enabledExtensions: [],
      instrumentCode: "WHO_2022_VA",
    }));
    mockDb.getFirstAsync.mockImplementationOnce(async () => ({
      envelope: JSON.stringify({
        instrumentId: "WHO_2022_VA",
        instrumentVersion: definition.version,
        definitionSha256: sha256,
        definitionExtensions: [],
        data: { answer: "keep-this-answer" },
        locale: "en",
      }),
    }) as never);
    const resolveSaved = jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition as jest.Mock;
    resolveSaved.mockImplementation((input) => realRuntime.resolveSavedEnvelopeDefinition(input));

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();

    const requestCalls = (jest.requireMock("../src/auth").authedRawRequest as jest.Mock).mock.calls;
    expect(requestCalls[0][1]).toContain("version=historic-v1&extensions=");
    expect(mockFormProps.instrument).toMatchObject({ version: definition.version });
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenCalled();
    expect((jest.requireMock("../src/drafts").getMeta as jest.Mock).mock.calls)
      .not.toContainEqual(expect.arrayContaining([expect.stringContaining("translations:")]));
    expect(jest.requireMock("../src/drafts").createDraftStore).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({
        definitionPin: {
          instrumentVersion: definition.version,
          definitionSha256: sha256,
          definitionExtensions: [],
        },
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("applies translations by name to an unpinned legacy bundle", async () => {
    const id = "77777777-7777-4777-8777-777777777777";
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: id };
    (jest.requireMock("../src/drafts").getDraftRow as jest.Mock).mockResolvedValueOnce({
      id,
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      death_id: null,
      unique_id: "VA-LEGACY",
      client_death_id: null,
      server_draft_id: null,
      base_updated_at: null,
      draft_sync_dirty: 0,
      draft_sync_blocked: 0,
    });
    (jest.requireMock("../src/drafts").getMeta as jest.Mock).mockImplementationOnce(async () => ({
      projectId: "P1",
      locale: "en",
      translationVersion: 9,
      enabledExtensions: [],
      instrumentCode: "WHO_2022_VA",
    }));
    mockDb.getFirstAsync.mockImplementationOnce(async () => ({
      envelope: JSON.stringify({
        instrumentId: "WHO_2022_VA",
        instrumentVersion: "v1",
        data: { answer: "legacy-answer" },
        locale: "en",
      }),
    }) as never);
    const projectPack = pack();
    const formOptions = projectPack.projects[0].project.form_options as unknown as {
      translation_versions?: Record<string, number>;
    };
    formOptions.translation_versions = { en: 10 };
    mockReference = projectPack;
    const legacyDefinition = { instrument: mockServedInstrument, provenance: "bundled-original", pin: null };
    (jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition as jest.Mock)
      .mockResolvedValueOnce(legacyDefinition);

    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();

    expect(mockFormProps.instrument).toEqual(mockServedInstrument);
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("clears a mounted form after access changes and blocks its stale draft store", async () => {
    const id = "66666666-6666-4666-8666-666666666666";
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: id };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();

    expect(tree!.root.findAllByProps({ "data-form-version": "served-v2" })).toHaveLength(1);
    const staleStore = mockFormProps.draftStore as { save(draft: unknown): Promise<unknown> };
    const stores = jest.requireMock("../src/drafts").createDraftStore as jest.Mock;
    const underlyingSave = stores.mock.results[stores.mock.results.length - 1].value.save as jest.Mock;
    let releaseReference!: (value: unknown) => void;
    (getCachedReferenceData as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => { releaseReference = resolve; }),
    );

    mockLockVersion += 1;
    await act(async () => { tree!.update(<Form />); });

    expect(mockObservedLockVersion).toBe(mockLockVersion);
    expect(tree!.root.findAllByProps({ "data-form-version": "served-v2" })).toHaveLength(0);
    await expect(staleStore.save({ data: { answer: "must-not-write" } })).rejects.toThrow("interview_access_changed");
    expect(underlyingSave).not.toHaveBeenCalled();
    await act(async () => { releaseReference(mockReference); });
    await settle();
    await settle();
    expect(tree!.root.findAllByProps({ "data-form-version": "served-v2" })).toHaveLength(1);
    await act(async () => tree!.unmount());
  });

  it("refuses an incompatible server draft without creating a blank questionnaire", async () => {
    const id = "33333333-3333-4333-8333-333333333333";
    mockParams = { userId: "u1", projectId: "P1", draftId: id, deathId: "d1" };
    (jest.requireMock("../src/draftSync").reconcileCaseDraft as jest.Mock).mockRejectedValueOnce(
      new Error("server_draft_instrument_mismatch"),
    );

    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Form />);
    });
    await settle();

    expect(dump(tree!)).toContain("error");
    expect(jest.requireMock("../src/drafts").createDraftStore).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("shows the cached other-draft warning without blocking case details", async () => {
    const startedAt = "2026-01-02T03:04:05.000Z";
    mockCachedCases = [
      {
        death_id: "d1",
        project_id: "P1",
        unique_id: "VA-CACHED",
        state: "registered",
        site_id: "S1",
        deceased: {
          name: "Cached case",
          age_years: null,
          sex: null,
          date_of_death: null,
        },
        other_draft_active: true,
        other_draft_started_at: startedAt,
        other_complete_interview: true,
        code_now: true,
      },
      {
        death_id: "d2",
        project_id: "P1",
        unique_id: "VA-CACHED-UNCHOSEN",
        state: "registered",
        site_id: "S1",
        deceased: { name: "Another case", age_years: null, sex: null, date_of_death: null },
        other_complete_interview: false,
      },
    ];
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    const rendered = dump(tree!);
    expect(rendered).toContain(
      `otherDraftActiveAt ${new Date(startedAt).toLocaleString()}`,
    );
    expect(rendered).toContain("otherDraftSyncNotice");
    expect(rendered).toContain("readyForCode");
    expect(rendered).toContain("Another complete interview of this case is with the supervisor.");
    expect(rendered.match(/Another complete interview of this case is with the supervisor\./g)).toHaveLength(1);
    const viewDetails = tree!.root.findAllByProps({
      "data-label": "actionStart",
    })[0];
    expect(Boolean(viewDetails.props.disabled)).toBe(false);
    await act(async () => viewDetails.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({ pathname: "/case" }),
    );
    await act(async () => tree!.unmount());
  });

  it("shows the neutral complete-interview notice on native case details", async () => {
    mockParams = { userId: "u1", projectId: "P1", deathId: "d1" };
    const detail = {
      death_id: "d1",
      unique_id: "VA-CASE",
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      unit_name: "Clinic",
      state: "registered",
      source: "registration",
      details_pending: false,
      pending_flag: false,
      deceased: {
        name: "Case subject",
        sex: "female",
        age_years: 56,
        date_of_birth: null,
        date_of_birth_partial: null,
        date_of_death: null,
        place_of_death: null,
      },
      household_address: { address: null, house_street: null, village_ward: null, landmark: null },
      informant: { name: "Contact", phone: null, phone_2: null },
      remarks: null,
      registered_by_me: true,
      started_by_me: false,
      my_draft_id: null,
      other_complete_interview: false,
      va_sid: null,
      created_at: "",
      updated_at: "",
      next_visit_at: null,
      last_contact_at: null,
      has_informant_phone: false,
      has_informant_phone_2: false,
    };
    (fetchCaseDetail as jest.Mock).mockResolvedValueOnce(detail);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Case />); });
    await settle();
    expect(dump(tree!)).not.toContain("Another complete interview of this case is with the supervisor.");
    await act(async () => tree!.unmount());

    (fetchCaseDetail as jest.Mock).mockResolvedValueOnce({ ...detail, other_complete_interview: true, code_now: true });
    await act(async () => { tree = create(<Case />); });
    await settle();

    const rendered = dump(tree!);
    expect(rendered).toContain("Another complete interview of this case is with the supervisor.");
    expect(rendered).toContain("readyForCode");
    expect(rendered).toContain("logAttempt");
    await act(async () => tree!.unmount());
  });

  it("shows a generic warning for an invalid online other-draft timestamp", async () => {
    (fetchCasePage as jest.Mock).mockResolvedValueOnce({
      cases: [
        {
          death_id: "d1",
          project_id: "P1",
          unique_id: "VA-ONLINE",
          state: "registered",
          deceased_name: "Online case",
          other_draft_active: true,
          other_draft_started_at: "invalid-date",
          other_complete_interview: true,
          code_now: true,
        },
        {
          death_id: "d2",
          project_id: "P1",
          unique_id: "VA-ONLINE-UNCHOSEN",
          state: "registered",
          deceased_name: "Another case",
          other_complete_interview: false,
        },
      ],
      next_cursor: null,
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findAllByProps({ "data-label": "refresh" })[0].props.onClick(),
    );
    await settle();
    const rendered = dump(tree!);
    expect(rendered).toContain("otherDraftActive");
    expect(rendered).toContain("readyForCode");
    expect(rendered).toContain("otherDraftSyncNotice");
    expect(rendered).toContain("Another complete interview of this case is with the supervisor.");
    expect(rendered.match(/Another complete interview of this case is with the supervisor\./g)).toHaveLength(1);
    expect(rendered).not.toContain("otherDraftActiveAt");
    await act(async () => tree!.unmount());
  });

  it("keeps project settings separate and passes the selected project to direct starts", async () => {
    const p2 = pack("direct", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...p2.bootstrap.projects],
      },
      projects: [...first.projects, ...p2.projects],
    };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () => pressStarting(tree!, "Project P1 · Interviewer"));
    await act(async () => press(tree!, "Project P2"));
    mockParams = { userId: "u1" };
    await act(async () => tree!.update(<Worklist />));
    await act(async () =>
      tree!.root.findByProps({ "data-label": "homeStartInterview" }).props.onClick(),
    );
    await act(async () => press(tree!, "Site 1"));
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ projectId: "P2" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("builds Home from local data: resumes the latest draft, counts unsent, and opens Interviews filtered to to-do", async () => {
    mockParams = { userId: "u1" };
    mockCachedCases = [{ death_id: "C1", unique_id: "VA-C1", project_id: "P1", site_id: "S1", state: "registered", unit_name: null, my_draft_id: null, deceased: { name: "Asha Rao" }, updated_at: "2026-10-01T00:00:00Z" }];
    (jest.requireMock("../src/drafts").listDrafts as jest.Mock).mockResolvedValue([
      { id: "draft-1", project_id: "P1", completed: 0, updated_at: "2026-10-04T00:00:00.000Z", unique_id: "VA-X", death_id: null },
    ]);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    const out = dump(tree!);
    expect(out).toContain("homeDraftsOne");
    expect(out).toContain('"1"'); // one unsent (the draft); one case needs a visit
    await act(async () => tree!.root.findByProps({ "data-label": "homeResumeDraft" }).props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/form", params: { userId: "u1", draftId: "draft-1", projectId: "P1" } });
    await act(async () => tree!.root.findByProps({ "data-label": "homeView" }).props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", view: "interviews", filter: "todo" } });
    await act(async () => tree!.unmount());
  });

  it("starts an interview from the site picker with the same route params, and remembers the choice", async () => {
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "homeStartInterview" }).props.onClick());
    await act(async () => press(tree!, "Site 1"));
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: "/form",
      params: { userId: "u1", draftId: "44444444-4444-4444-8444-444444444444", projectId: "P1", siteId: "S1" },
    });
    expect(jest.requireMock("../src/drafts").setMeta).toHaveBeenCalledWith(mockDb, "recentTarget", { siteId: "S1" }, "P1");
    await act(async () => tree!.unmount());
  });

  it("uses the selected project's mode for registration and validates before saving", async () => {
    Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
    mockParams = { userId: "u1", projectId: "P1", clientDeathId: "local-1" };
    (
      jest.requireMock("../src/cases").getRegistration as jest.Mock
    ).mockResolvedValueOnce({
      client_death_id: "local-1",
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      state: "pending",
      created_at: "2026-10-03T00:00:00.000Z",
      fields: {
        deceased_name: "Asha",
        deceased_sex: "female",
        date_of_death: "2026-09-30",
        date_of_birth: "1980-01-01",
      },
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Register />);
    });
    await settle();
    expect(
      tree!.root.findByProps({ "data-label": "registerSaveStart" }).props
        .disabled,
    ).toBe(false);
    await act(async () =>
      tree!.root
        .findByProps({ "data-label": "registerSaveStart" })
        .props.onClick(),
    );
    expect(saveRegistration).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({ project_id: "P1" }),
    );
    await act(async () => tree!.unmount());
  });

  it("downloads active cases again after the forced post-login settings refresh", async () => {
    mockParams = { userId: "u1", refresh: "1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    expect(refreshCases).toHaveBeenCalledWith("u1", mockDb);
    await act(async () => tree!.unmount());
  });

  it("ignores old hash mismatch issues while keeping completed drafts disabled", async () => {
    const drafts = [{
      id: "draft-mismatch",
      project_id: "P1",
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      unique_id: "VA-LOCAL",
      upload_issue: "hash_mismatch",
      upload_issue_unique_id: "VA-STORED",
    }, {
      id: "draft-completed",
      project_id: "P1",
      completed: 1,
      updated_at: "2026-10-04T00:00:00.000Z",
      unique_id: "VA-COMPLETED",
      upload_issue: null,
      upload_issue_unique_id: null,
    }];
    (
      jest.requireMock("../src/drafts").listDrafts as jest.Mock
    ).mockResolvedValue(drafts);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    const rendered = dump(tree!);
    expect(rendered).not.toContain("This interview was already uploaded");
    expect(rendered).not.toContain("VA-STORED");
    // A draft that is not finished offers Resume; one already marked ready to send offers nothing to press.
    const resume = tree!.root.findAllByProps({ "data-label": "actionResume" });
    expect(resume).toHaveLength(1);
    expect(dump(tree!)).toContain("VA-COMPLETED");
    expect(dump(tree!)).toContain("draftReady");
    const oldIssueDraft = { props: { onPress: resume[0].props.onClick } };
    await act(async () => oldIssueDraft?.props.onPress());
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({ pathname: "/form", params: expect.objectContaining({ draftId: "draft-mismatch" }) }),
    );
    await act(async () => tree!.unmount());
  });

  it("shows server-kept history and locked notices when the later refresh fails", async () => {
    (syncInterviewer as jest.Mock).mockImplementationOnce(
      async (
        _userId: string,
        _db: unknown,
        _onSuperseded?: (uniqueId: string) => void,
        _onDraftConflict?: (draftId: string) => void,
        onServerKept?: (notice: { uniqueId: string; locked: boolean }) => void,
        onCanCodeNow?: (uniqueId: string) => void,
      ) => {
        onServerKept?.({ uniqueId: "VA-KEPT", locked: true });
        onCanCodeNow?.("VA-KEPT");
        return {
          sent: 1,
          failed: 0,
          remaining: 0,
          supersededUniqueIds: [],
          serverKeptUploads: [{ uniqueId: "VA-KEPT", locked: true }],
          canCodeNowUniqueIds: ["VA-KEPT"],
        };
      },
    );
    (refreshReferenceData as jest.Mock).mockRejectedValueOnce(new TypeError("Network request failed"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick());
    await settle();

    const rendered = dump(tree!);
    expect(rendered).toContain("A newer completed version is already with the coder; yours was saved as history.");
    expect(rendered).toContain("Coding has finished; only a send-back or reopen can change the coder's version.");
    expect(rendered).toContain("Stored interview: VA-KEPT");
    expect(rendered).toContain("readyForCode");
    // The send result is a toast, never in-flow text.
    expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: expect.any(String) });
    await act(async () => tree!.unmount());
  });

  it("shows a valid upload hint through a later network failure and clears it on the next sync", async () => {
    (syncInterviewer as jest.Mock).mockImplementationOnce(async (
      _userId: string,
      _db: unknown,
      _onSuperseded?: (uniqueId: string) => void,
      _onDraftConflict?: (draftId: string) => void,
      _onServerKept?: (notice: { uniqueId: string; locked: boolean }) => void,
      onCanCodeNow?: (uniqueId: string) => void,
    ) => {
      onCanCodeNow?.("VA-CODE");
      return { sent: 1, failed: 0, remaining: 0, supersededUniqueIds: [], canCodeNowUniqueIds: ["VA-CODE"] };
    });
    mockCachedCases = [{ death_id: "d1", project_id: "P1", unique_id: "VA-CODE", state: "submitted", code_now: false }];
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Worklist />); });
    await settle();
    (refreshReferenceData as jest.Mock).mockRejectedValueOnce(new TypeError("Network request failed"));
    await act(async () => tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick());
    await settle();
    expect(dump(tree!)).toContain("readyForCode");

    const refreshButtons = tree!.root.findAllByProps({ "data-label": "refresh" });
    await act(async () => refreshButtons[refreshButtons.length - 1].props.onClick());
    await settle();
    expect(dump(tree!)).not.toContain("readyForCode");

    (syncInterviewer as jest.Mock).mockResolvedValueOnce({ sent: 0, failed: 0, remaining: 0, supersededUniqueIds: [] });
    await act(async () => tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick());
    await settle();
    expect(dump(tree!)).not.toContain("readyForCode");
    await act(async () => tree!.unmount());
  });

  it("marks an invalid-hash draft for attention and leaves it editable", async () => {
    const draft = {
      id: "draft-invalid",
      project_id: "P1",
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      unique_id: "VA-LOCAL",
      upload_issue: "answers_hash_invalid",
      upload_issue_unique_id: null,
    };
    (
      jest.requireMock("../src/drafts").listDrafts as jest.Mock
    ).mockResolvedValue([draft]);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    expect(dump(tree!)).toContain(
      "This interview could not be verified. Open it, review the answers, and try sending it again.",
    );
    const draftButton = tree!.root.findAllByProps({ "data-label": "actionResume" })[0];
    expect(draftButton).toBeDefined();
    await act(async () => draftButton!.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ draftId: "draft-invalid" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("shows a superseded notice with each unique id after sync", async () => {
    (syncInterviewer as jest.Mock).mockResolvedValueOnce({
      sent: 1,
      failed: 0,
      remaining: 0,
      supersededUniqueIds: ["VA-FIRST"],
      serverKeptUploads: [{ uniqueId: "VA-FIRST", locked: true }],
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick(),
    );
    const rendered = dump(tree!);
    expect(rendered).toContain(
      "Another interview of this case is with the coder; yours was saved as history.",
    );
    expect(rendered).toContain("Stored interview: VA-FIRST");
    expect(rendered).not.toContain("A newer completed version is already with the coder");
    await act(async () => tree!.unmount());
  });

  it("keeps a superseded notice when a later sync request fails", async () => {
    (syncInterviewer as jest.Mock).mockImplementationOnce(
      async (
        _userId: string,
        _db: unknown,
        onSuperseded?: (uniqueId: string) => void,
      ) => {
        onSuperseded?.("VA-FIRST");
        throw new TypeError("Network request failed");
      },
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick(),
    );
    await settle();
    const rendered = dump(tree!);
    expect(rendered).toContain(
      "Another interview of this case is with the coder; yours was saved as history.",
    );
    expect(rendered).toContain("Stored interview: VA-FIRST");
    await act(async () => tree!.unmount());
  });

  it("keeps the fixed draft-conflict notice when a later sync request fails", async () => {
    (syncInterviewer as jest.Mock).mockImplementationOnce(
      async (
        _userId: string,
        _db: unknown,
        _onSuperseded?: (uniqueId: string) => void,
        onDraftConflict?: (draftId: string) => void,
      ) => {
        onDraftConflict?.("local-draft-id");
        throw new TypeError("Network request failed");
      },
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "homeSendNow" }).props.onClick(),
    );
    await settle();
    const rendered = dump(tree!);
    expect(rendered).toContain(
      "This interview was also edited on another device; the newer version was kept.",
    );
    expect(rendered).not.toContain("local-draft-id");
    expect(rendered).not.toContain("Network request failed");
    await act(async () => tree!.unmount());
  });

  it("re-reads the sanitized pack and clears visible revoked-project data after refresh failure", async () => {
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const second = pack("both", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...second.bootstrap.projects],
      },
      projects: [...first.projects, ...second.projects],
    };
    mockCachedReference = mockReference;
    mockCachedCases = [
      {
        death_id: "removed",
        project_id: "P2",
        unique_id: "VA-REMOVED",
        state: "registered",
        deceased: {
          name: "Removed contact",
          sex: null,
          age_years: null,
          date_of_birth: null,
          date_of_birth_partial: null,
          date_of_death: null,
          place_of_death: null,
        },
        household_address: {
          address: null,
          house_street: null,
          village_ward: null,
          landmark: null,
        },
        informant: { name: null, phone: null, phone_2: null },
        remarks: null,
        prefill: {},
        links: { self: "", attempts: "", visit: "" },
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
      },
    ];
    const refresh = refreshReferenceData as jest.Mock;
    refresh.mockImplementationOnce(async () => {
      mockCachedReference = pack("both", "P1");
      mockCachedCases = [];
      throw new Error("settings_unavailable");
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await settle();
    expect(dump(tree!)).not.toContain("Removed contact");
    await act(async () => tree!.unmount());
  });

  it("fetches reported-death pages online by project and keeps pagination in memory", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findAllByProps({ "data-label": "refresh" })[0].props.onClick(),
    );
    await settle();
    expect(fetchCasePage).toHaveBeenCalledWith("u1", "P1", { limit: 50 });
    await act(async () => tree!.unmount());
  });

  it("drops a delayed online page when the interviewer switches projects", async () => {
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const second = pack("both", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...second.bootstrap.projects],
      },
      projects: [...first.projects, ...second.projects],
    };
    let resolvePage!: (page: unknown) => void;
    (fetchCasePage as jest.Mock).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePage = resolve;
        }),
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findAllByProps({ "data-label": "refresh" })[0].props.onClick(),
    );
    await settle();
    await act(async () => pressStarting(tree!, "Project P1 · Interviewer"));
    await act(async () => press(tree!, "Project P2"));
    resolvePage({
      cases: [
        {
          death_id: "old",
          project_id: "P1",
          unique_id: "OLD",
          state: "registered",
          deceased_name: "Old project contact",
        },
      ],
      next_cursor: null,
    });
    await settle();
    expect(dump(tree!)).not.toContain("Old project contact");
    await act(async () => tree!.unmount());
  });
});

describe("immersive interview form", () => {
  const FORM_ID = "44444444-4444-4444-8444-444444444444";
  const press = (tree: ReturnType<typeof create>, label: string) =>
    act(async () => {
      tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0].props.onPress();
    });
  const open = async () => {
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: FORM_ID };
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();
    return tree;
  };
  const choose = async (tree: ReturnType<typeof create>, label: string) => {
    await press(tree, "moreActions");
    await press(tree, label);
  };

  it("uses the immersive screen with a single top bar and no in-flow button rows", async () => {
    const tree = await open();
    expect(tree.root.findByType("main").props["data-variant"]).toBe("immersive");
    expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "header")).toHaveLength(1);
    expect(tree.root.findAllByProps({ "data-label": "finishIncomplete" })).toHaveLength(0);
    expect(mockFormProps.instrument).toBeTruthy();
    await act(async () => tree.unmount());
  });

  it("runs Save now, Finish as incomplete and Back through their handlers", async () => {
    const tree = await open();
    const saveDraft = jest.fn(async () => undefined);
    const validate = jest.fn(() => ({ valid: false, issues: [], data: { Id10017: "A", Id10019: "male", Id10023: "2026-01-02" } }));
    await act(async () => {
      (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft });
      (mockFormProps.onReady as (s: unknown) => void)({ validate, getSnapshot: () => ({ data: {} }) });
    });
    await choose(tree, "saveNow");
    await settle();
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "draftSaved" });
    await choose(tree, "finishIncomplete");
    expect(validate).not.toHaveBeenCalled();
    expect(mockConfirmProps).toMatchObject({ title: "finishIncompleteTitle", cancelLabel: "stay" });
    await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
    expect(validate).not.toHaveBeenCalled();
    await choose(tree, "finishIncomplete");
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    expect(validate).toHaveBeenCalledTimes(1);
    await press(tree, "back");
    await settle();
    // Save now, the save inside Finish as incomplete, and the save on Back.
    expect(saveDraft).toHaveBeenCalledTimes(3);
    expect(mockRouter.back).toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("hardware back flushes the open answer, then leaves", async () => {
    const tree = await open();
    const saveDraft = jest.fn(async () => undefined);
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft }); });
    mockRouter.back.mockClear();
    let event!: ReturnType<typeof mockHardwareBack>;
    await act(async () => { event = mockHardwareBack(); });
    await settle();
    expect(event.preventDefault).toHaveBeenCalled();
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("a failed save on back asks first: Stay keeps the form, Leave anyway leaves", async () => {
    const tree = await open();
    const saveDraft = jest.fn(async () => undefined);
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft }); });
    mockRouter.back.mockClear();
    saveDraft.mockRejectedValueOnce(new Error("disk"));
    await act(async () => { mockHardwareBack(); });
    await settle();
    expect(mockRouter.back).not.toHaveBeenCalled();
    expect(mockConfirmProps).toMatchObject({ title: "leaveUnsavedTitle", message: "leaveUnsavedMessage", cancelLabel: "stay" });
    await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
    expect(mockRouter.back).not.toHaveBeenCalled();
    saveDraft.mockRejectedValueOnce(new Error("disk"));
    await act(async () => { mockHardwareBack(); });
    await settle();
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("reports a failed save as a Not saved dot and an error toast, not in-flow text", async () => {
    const tree = await open();
    await act(async () => { (mockFormProps.onDraftError as () => void)(); });
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "saveStateUnsaved").length).toBeGreaterThan(0);
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "errGeneric" });
    await act(async () => { (mockFormProps.onDraftSaved as () => void)(); });
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "saveStateSaved").length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
  });
});

describe("respondent consent in the interview form", () => {
  const FORM_ID = "44444444-4444-4444-8444-444444444444";
  const NOTICE = "Notice";
  const consentConfig = (required = true) => ({
    project_id: "P1", consent_required: required, refusal_behaviour: "interview_without_informant_data",
    notice_versions: [{
      notice_version_id: "n1", version: 1, language: "en", text: NOTICE, text_sha256: computeUtf8Sha256HexSync(NOTICE),
      purposes: [{ code: "a", label: "A", required: true }], covered_fields: ["Id10007"], allowed_modes: ["spoken"], witness_allowed: false,
    }],
  });
  const stored = (decision: "granted" | "refused") => ({
    envelope: { client_id: "c1", decision, client_draft_id: null }, project_id: "P1", covered_fields: ["Id10007"], recorded_by: "u1",
  });
  const setup = (config: unknown, rows: Array<{ key: string; value: unknown }> = []) => {
    (getMeta as jest.Mock).mockImplementation(async (_db: unknown, key: string) => (key === "consentConfig" ? config : undefined));
    mockDb.getAllAsync.mockImplementation((async (_sql: string, params: string[]) =>
      rows.filter((row) => row.key.startsWith(String(params[0]).replace("%", "")))
        .map((row) => ({ key: row.key, value: JSON.stringify(row.value) }))) as never);
  };
  const open = async () => {
    mockParams = { userId: "u1", projectId: "P1", siteId: "S1", draftId: FORM_ID };
    mockConsentProps = undefined;
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<Form />); });
    await settle();
    await settle();
    return tree;
  };
  afterEach(() => {
    (jest.requireMock("../src/cases").resolveDraftHost as jest.Mock).mockResolvedValue({ projectId: "P1", siteId: "S1", binding: {}, prefill: undefined });
    (jest.requireMock("../src/cases").getRegistration as jest.Mock).mockResolvedValue(undefined);
    (getMeta as jest.Mock).mockReset().mockResolvedValue(undefined);
    mockDb.getAllAsync.mockReset().mockResolvedValue([] as never);
  });

  it("shows the consent screen, not the questionnaire, until a decision is recorded; granted is stored and opens the form unlocked", async () => {
    setup(consentConfig());
    const tree = await open();
    expect(mockConsentProps).toMatchObject({ clientDraftId: FORM_ID, language: "en" });
    expect(mockFormProps.instrument).toBeUndefined();
    const envelope = { client_id: "c1", client_draft_id: FORM_ID, notice_version_id: "n1", decision: "granted" };
    await act(async () => { (mockConsentProps!.onDecision as (e: unknown) => void)(envelope); });
    await settle();
    expect(setMeta).toHaveBeenCalledWith(expect.anything(), `consent:draft:${FORM_ID}`, expect.objectContaining({ envelope, covered_fields: ["Id10007"], recorded_by: "u1", project_id: "P1" }));
    expect(mockFormProps.instrument).toBeTruthy();
    expect(mockFormProps.lockedQuestionNames ?? []).toEqual([]);
    await act(async () => tree.unmount());
  });

  it("under a refusal locks the covered questions and drops covered answers a saved draft holds", async () => {
    setup(consentConfig());
    const tree = await open();
    await act(async () => {
      (mockConsentProps!.onDecision as (e: unknown) => void)({ client_id: "c1", client_draft_id: FORM_ID, notice_version_id: "n1", decision: "refused" });
    });
    await settle();
    expect(mockFormProps.lockedQuestionNames).toEqual(["Id10007"]);
    // The stored draft and its prefill lose the covered answers at once, not only the copy in memory.
    expect(jest.requireMock("../src/drafts").stripDraftCovered).toHaveBeenCalledWith(expect.anything(), FORM_ID, ["Id10007"]);
    const replaceData = jest.fn();
    const saveDraft = jest.fn(async () => undefined);
    await act(async () => {
      (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft });
      (mockFormProps.onReady as (s: unknown) => void)({ getSnapshot: () => ({ data: { Id10007: "Asha", Id10013: "yes" } }), replaceData });
    });
    expect(replaceData).toHaveBeenCalledWith({ Id10013: "yes" });
    expect(saveDraft).toHaveBeenCalledTimes(1); // persisted
    await act(async () => tree.unmount());
  });

  it("reuses a decision already on file (its registration's) and asks nothing", async () => {
    (jest.requireMock("../src/cases").resolveDraftHost as jest.Mock).mockResolvedValue({
      projectId: "P1", siteId: "S1", binding: { projectId: "P1", clientDeathId: "reg-1" }, prefill: undefined,
    });
    setup(consentConfig(), [{ key: "consent:reg:reg-1", value: stored("granted") }]);
    const tree = await open();
    expect(mockConsentProps).toBeUndefined();
    expect(mockFormProps.instrument).toBeTruthy();
    expect(mockFormProps.lockedQuestionNames ?? []).toEqual([]);
    await act(async () => tree.unmount());
  });

  it("asks nothing where the project does not require consent, and locks the covered questions with a reason when the settings are not on the phone", async () => {
    setup(consentConfig(false));
    let tree = await open();
    expect(mockConsentProps).toBeUndefined();
    expect(mockFormProps.lockedQuestionNames ?? []).toEqual([]);
    await act(async () => tree.unmount());

    setup(undefined);
    tree = await open();
    expect(mockConsentProps).toBeUndefined();
    // The server's whole covered list, the family and address answers included.
    expect(mockFormProps.lockedQuestionNames).toEqual(expect.arrayContaining(
      ["Id10007", "informant_name", "father_name", "mother_name", "Id10055", "Id10057", "Id10061", "Id10062"]));
    expect(tree.root.findAll((n) => n.props.testID === "consent-unavailable").length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
  });

  it("hands a stored refusal to the form's problems list (no in-flow banner); a consent refusal opens the consent screen", async () => {
    const refusal = { ref: "HTTP 422 invalid_interview", status: 422, message: "Record the name, date of death and sex of the deceased before submitting.", fields: ["Id10019"], at: "2026-10-23T10:15:00Z" };
    setup(consentConfig(false), [{ key: `senderr:${FORM_ID}`, value: refusal }]);
    const tree = await open();
    expect(tree.root.findAll((n) => n.props.testID === "refusal-banner")).toHaveLength(0);
    expect(mockFormProps.serverProblems).toEqual([
      {
        question: "Id10019",
        message: "Record the name, date of death and sex of the deceased before submitting. · Ref: HTTP 422 invalid_interview · 10:15Z",
      },
    ]);
    expect(mockFormProps.compactFooter).toBe(true);
    // The chip shows the form's count and opens the list.
    const showProblems = jest.fn();
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft: jest.fn(), showProblems }); });
    await act(async () => { (mockFormProps.onProblemsChange as (n: number) => void)(2); });
    await act(async () => { tree.root.findAll((n) => n.props.testID === "problems-chip" && typeof n.props.onPress === "function")[0].props.onPress(); });
    expect(showProblems).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("asks again when the server refused the decision this interview inherited from its registration", async () => {
    (jest.requireMock("../src/cases").resolveDraftHost as jest.Mock).mockResolvedValue({
      projectId: "P1", siteId: "S1", binding: { projectId: "P1", clientDeathId: "reg-1" }, prefill: undefined,
    });
    setup(consentConfig(), [{ key: "consent:reg:reg-1", value: stored("granted") }]);
    (getMeta as jest.Mock).mockImplementation(async (_db: unknown, key: string) =>
      key === "consentConfig" ? consentConfig() : key === `consentRefused:${FORM_ID}` ? true : undefined);
    const tree = await open();
    expect(mockConsentProps).toMatchObject({ clientDraftId: FORM_ID });
    expect(mockFormProps.instrument).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("shows every pre-send issue at once, in the server's order", async () => {
    setup(consentConfig(false));
    const tree = await open();
    const showProblems = jest.fn();
    await act(async () => { (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft: jest.fn(), showProblems }); });
    await act(async () => { (mockFormProps.onComplete as (r: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "refused" } }); });
    await settle();
    // Both messages travel to the form's problems list, in the server's order, and the list opens.
    const message = (mockFormProps.serverProblems as Array<{ message: string }>)[0]!.message;
    expect(message).toContain("preOutcomeConflictsConsent");
    expect(message).toContain("preIdentityMissing");
    expect(message.indexOf("preOutcomeConflictsConsent")).toBeLessThan(message.indexOf("preIdentityMissing"));
    expect(showProblems).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("keeps an interview a draft, with the server's message, when the pre-send checks fail", async () => {
    setup(consentConfig(false));
    const tree = await open();
    const saveDraft = jest.fn(async () => undefined);
    await act(async () => {
      (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft, showProblems: jest.fn() });
      (mockFormProps.onReady as (s: unknown) => void)({ getSnapshot: () => ({ data: {} }) });
    });
    await act(async () => { (mockFormProps.onComplete as (r: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes" } }); });
    await settle();
    expect(jest.requireMock("../src/drafts").markCompleted).not.toHaveBeenCalled();
    expect((mockFormProps.serverProblems as Array<{ message: string }>)[0]!.message).toContain("preIdentityMissing");
    await act(async () => { (mockFormProps.onComplete as (r: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", Id10017: "A", Id10019: "male", Id10023: "2026-01-02" } }); });
    await settle();
    expect(jest.requireMock("../src/drafts").markCompleted).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  describe("status chip and changing the decision", () => {
    const chip = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props.testID === "consent-chip" && typeof n.type !== "string")[0];
    const menu = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props.accessibilityLabel === "moreActions" && typeof n.props.onPress === "function")[0];
    const decide = (decision: "granted" | "refused") =>
      act(async () => { (mockConsentProps!.onDecision as (e: unknown) => void)({ client_id: "c2", client_draft_id: FORM_ID, notice_version_id: "n1", decision }); });
    const mountController = async (saveDraft: jest.Mock) => act(async () => {
      (mockFormProps.onDraftController as (c: unknown) => void)({ saveDraft });
    });
    const own = (decision: "granted" | "refused") => [{ key: `consent:draft:${FORM_ID}`, value: stored(decision) }];

    it("shows agreed, refused and not recorded in words, and nothing where consent is off", async () => {
      setup(consentConfig(), own("granted"));
      let tree = await open();
      expect(chip(tree).props.accessibilityLabel).toBe("consentChipAgreed");
      await act(async () => tree.unmount());

      setup(consentConfig(), own("refused"));
      tree = await open();
      expect(chip(tree).props.accessibilityLabel).toBe("consentChipRefused");
      await act(async () => tree.unmount());

      // Required but no usable notice: nothing recorded and nothing to change it with.
      setup(undefined);
      tree = await open();
      expect(chip(tree).props.accessibilityLabel).toBe("consentChipNotRecorded");
      expect(chip(tree).props.disabled).toBe(true);
      await act(async () => tree.unmount());

      setup(consentConfig(false), own("granted"));
      tree = await open();
      expect(mockFormProps.instrument).toBeTruthy(); // the subject is there
      expect(chip(tree)).toBeUndefined();
      await act(async () => tree.unmount());
    });

    it("saves what is typed, then agreed to refused strips the covered answers, stores the new decision and locks them", async () => {
      setup(consentConfig(), own("granted"));
      const tree = await open();
      const saveDraft = jest.fn(async () => undefined);
      await mountController(saveDraft);
      expect(mockFormProps.lockedQuestionNames ?? []).toEqual([]);
      (setMeta as jest.Mock).mockClear();
      await act(async () => { chip(tree).props.onPress(); });
      await settle();
      // Saved first, then the questionnaire closes for the consent screen.
      expect(saveDraft).toHaveBeenCalledTimes(1);
      expect(mockConsentProps).toMatchObject({ clientDraftId: FORM_ID });
      expect(tree.root.findAllByProps({ "data-consent-panel": true })).toHaveLength(1);
      await decide("refused");
      await settle();
      expect(setMeta).toHaveBeenCalledWith(expect.anything(), `consent:draft:${FORM_ID}`, expect.objectContaining({ envelope: expect.objectContaining({ client_id: "c2", decision: "refused" }), covered_fields: ["Id10007"] }));
      expect(jest.requireMock("../src/drafts").stripDraftCovered).toHaveBeenCalledWith(expect.anything(), FORM_ID, ["Id10007"]);
      expect(mockFormProps.lockedQuestionNames).toEqual(["Id10007"]);
      expect(chip(tree).props.accessibilityLabel).toBe("consentChipRefused");
      expect(mockToast).toHaveBeenCalledWith({ kind: "info", text: "consentChangedRefused" });
      await act(async () => tree.unmount());
    });

    it("refused to agreed reopens the covered questions; the menu item does the same as the chip; cancel changes nothing", async () => {
      setup(consentConfig(), own("refused"));
      const tree = await open();
      expect(mockFormProps.lockedQuestionNames).toEqual(["Id10007"]);
      await mountController(jest.fn(async () => undefined));
      await act(async () => { menu(tree).props.onPress(); });
      await act(async () => { tree.root.findAll((n) => n.props.accessibilityLabel === "consentChangeDecision" && typeof n.props.onPress === "function")[0].props.onPress(); });
      await settle();
      expect(tree.root.findAllByProps({ "data-consent-panel": true })).toHaveLength(1);
      const jestDrafts = jest.requireMock("../src/drafts");
      jestDrafts.stripDraftCovered.mockClear();
      await act(async () => { tree.root.findAll((n) => n.props["data-label"] === "cancel")[0].props.onClick(); });
      expect(tree.root.findAllByProps({ "data-consent-panel": true })).toHaveLength(0);
      expect(mockFormProps.lockedQuestionNames).toEqual(["Id10007"]);

      await mountController(jest.fn(async () => undefined));
      await act(async () => { chip(tree).props.onPress(); });
      await settle();
      await decide("granted");
      await settle();
      expect(jestDrafts.stripDraftCovered).not.toHaveBeenCalled();
      expect(mockFormProps.lockedQuestionNames ?? []).toEqual([]);
      expect(chip(tree).props.accessibilityLabel).toBe("consentChipAgreed");
      expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "consentChangedAgreed" });
      await act(async () => tree.unmount());
    });
  });

  describe("delete draft", () => {
    const drafts = () => jest.requireMock("../src/drafts");
    const choose = async (tree: ReturnType<typeof create>, label: string) => {
      await act(async () => { tree.root.findAll((n) => n.props.accessibilityLabel === "moreActions" && typeof n.props.onPress === "function")[0].props.onPress(); });
      await act(async () => { tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0].props.onPress(); });
    };
    const hasItem = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props.accessibilityLabel === "deleteDraft" && typeof n.props.onPress === "function").length > 0;
    const menuOpen = async (tree: ReturnType<typeof create>) =>
      act(async () => { tree.root.findAll((n) => n.props.accessibilityLabel === "moreActions" && typeof n.props.onPress === "function")[0].props.onPress(); });
    beforeEach(() => {
      mockConfirmProps = undefined;
      drafts().isNeverSentDraft.mockReset().mockResolvedValue(true);
      drafts().deleteUnsentDraft.mockReset().mockResolvedValue(true);
      mockRouter.replace.mockClear();
      mockToast.mockClear();
      setup(consentConfig(false));
    });

    it("is not in the menu for a draft that was sent or queued", async () => {
      drafts().isNeverSentDraft.mockResolvedValue(false);
      const tree = await open();
      await menuOpen(tree);
      expect(tree.root.findAll((n) => n.props.accessibilityLabel === "saveNow").length).toBeGreaterThan(0); // the menu is open
      expect(hasItem(tree)).toBe(false);
      await act(async () => tree.unmount());
    });

    it("cancel keeps the draft; confirm deletes it, shows the toast and returns to the worklist", async () => {
      const tree = await open();
      await menuOpen(tree);
      expect(hasItem(tree)).toBe(true);
      await choose(tree, "deleteDraft");
      expect(mockConfirmProps).toMatchObject({ destructive: true, title: "deleteDraftTitle" });
      await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
      expect(drafts().deleteUnsentDraft).not.toHaveBeenCalled();
      expect(tree.root.findAllByProps({ "data-confirm": true })).toHaveLength(0);

      await choose(tree, "deleteDraft");
      await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
      await settle();
      expect(drafts().deleteUnsentDraft).toHaveBeenCalledWith(expect.anything(), FORM_ID);
      expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "deleteDraftDone" });
      expect(mockRouter.replace).toHaveBeenCalledWith(expect.objectContaining({ pathname: "/worklist" }));
      await act(async () => tree.unmount());
    });

    it("keeps the screen and says so when the store refuses (the draft was sent meanwhile)", async () => {
      drafts().deleteUnsentDraft.mockResolvedValue(false);
      const tree = await open();
      await choose(tree, "deleteDraft");
      await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
      await settle();
      expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "deleteDraftFailed" });
      expect(mockRouter.replace).not.toHaveBeenCalled();
      await act(async () => tree.unmount());
    });
  });

});
