/**
 * Characterization of the browser interview screen (src/web/InterviewScreen.tsx) before digitva-r8nh.22 moves its
 * consent/refusal handlers and splits its initialise. Pinned at the boundaries that do not move: the client API
 * calls (paths, bodies, CSRF, if-updated-at), the server draft store, the router and the page reload. The mock
 * preamble is interview-language.test.tsx's, with requestClientJson, the confirm dialog and the store's locale
 * metadata observable.
 */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockChoose = jest.fn(async () => undefined);
const mockDefinitionSha256 = "a".repeat(64);
const mockDefinitionCache = {
  get: jest.fn(async (identity: {accountId: string; projectId: string; instrumentCode: "WHO_2022_VA"; composedVersion: string; sha256: string}) => ({
    identity, etag: null, engineVersion: 1, rawJson: "{}",
    definition: {id: "WHO_2022_VA", version: identity.composedVersion, engineVersion: 1, extensions: [], sections: [], questions: []},
  })),
  put: jest.fn(async () => undefined),
  removeProject: jest.fn(), clear: jest.fn(),
};
const mockBootstrap = {
  user: {user_id: "u1", name: "Worker"},
  csrf: {header: "X-CSRFToken", token: "csrf"},
  capabilities: {intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false},
  access: {
    user: {user_id: "u1", name: "Worker"},
    is_admin: false,
    roles: ["interviewer"],
    demo_coding: {available: false, project_ids: []},
    projects: [{
      project_id: "P",
      project_name: "Project",
      has_tree: false,
      grants: [{role: "interviewer", scope: "project", active: true, source: "assigned"}],
      sites: [{site_id: "S", site_name: "Site", roles: ["interviewer"]}],
      actions: {
        interview: [{site_id: "S", site_name: "Site", web_intake_mode: "both", org_units: []}],
        register_death: [{site_id: "S", site_name: "Site", web_intake_mode: "both", org_units: []}],
      },
    }],
  },
  links: {login: "/vaauth/valogin", logout: "/vaauth/valogout", intakeDrafts: "/api/v1/intake/drafts", intakeCases: "/api/v1/intake/cases"},
};
let mockCurrentBootstrap = mockBootstrap;
let mockParams: {draftId?: string; deathId?: string; projectId?: string; siteId?: string; orgUnitId?: string; revisionDraftId?: string; revisionProjectId?: string; revisionSiteId?: string; revisionVaSid?: string} = {draftId: "draft-1"};
const mockRouter = {back: jest.fn(), replace: jest.fn()};
const mockServerFlush = jest.fn(async () => undefined);
const mockResumeConsent = jest.fn(async () => undefined);
const mockRetrySave = jest.fn(async () => undefined);
let mockSaveHeld = false;
let mockHeldStale: {updatedAt: string; change: Record<string, unknown>} | undefined;
let mockOvertaken: Record<string, unknown> | undefined;
const mockUseMine = jest.fn(async () => undefined);
const mockKeepNewer = jest.fn();
const mockUseOvertaken = jest.fn(async () => undefined);
const mockDiscardOvertaken = jest.fn();
const mockHasServed = jest.fn(() => false);
const mockMarkServed = jest.fn(async () => undefined);
let mockBeforeRemove: ((event: {preventDefault: () => void; data: {action: unknown}}) => void) | undefined;
const mockNavigation = {
  addListener: jest.fn((_event: string, listener: typeof mockBeforeRemove) => { mockBeforeRemove = listener; return () => { mockBeforeRemove = undefined; }; }),
  dispatch: jest.fn(),
};
jest.mock("expo-router", () => ({useRouter: () => mockRouter, useLocalSearchParams: () => mockParams, useIsFocused: () => true, useNavigation: () => mockNavigation}));
jest.mock("../src/AppState", () => ({useAppState: () => ({bootstrap: mockCurrentBootstrap, chooseUiLocale: mockChoose, onBeforeLock: () => () => undefined, definitionCache: mockDefinitionCache, hasServedDefinition: mockHasServed, markServedDefinition: mockMarkServed, sessionGeneration: 0})}));
// The real `ui` tokens, so the form theme the screen derives is the app's own; `mockColorMode` flips light and dark.
let mockColorMode: "light" | "dark" = "light";
jest.mock("../src/theme", () => ({radius: { sm: 4, md: 6, lg: 8, full: 9999 }, fontSize: { body: 14 }, spacing: jest.requireActual("../src/theme").spacing, typography: jest.requireActual("../src/theme").typography, controls: jest.requireActual("../src/theme").controls, disabledButtonTone: jest.requireActual("../src/theme").disabledButtonTone, useTheme: () => ({colors: {}, typography: jest.requireActual("../src/theme").typography, ui: jest.requireActual("../src/theme").ui[mockColorMode]})}));
jest.mock("../src/ui", () => ({
  Button: (props: {label: string; onPress: () => void}) => jest.requireActual("react").createElement("mock-button", props),
  useUiStyles: () => ({}),
}));
let mockShellProps: {lead?: React.ReactElement<{sticky?: boolean}>} = {};
jest.mock("../src/web/common", () => ({WebShell: (props: {children: ReactNode; lead?: React.ReactElement<{sticky?: boolean}>}) => { mockShellProps = props; return <>{props.children}</>; }, browserErrorText: (error: Error) => error.message}));
jest.mock("../src/client/api", () => ({
  ...jest.requireActual("../src/client/api"),
  getIntakeContext: jest.fn(async () => ({})),
  getDraft: jest.fn(), getProjectFormOptions: jest.fn(), getInstrumentTranslations: jest.fn(), getCaseDetail: jest.fn(), startDraft: jest.fn(), submitDraft: jest.fn(),
  requestClientJson: jest.fn(async () => ({})),
}));
const mockSetLocaleMetadata = jest.fn();
const mockRestoreLocaleMetadata = jest.fn();
const mockEnterRefusal = jest.fn();
let mockConfirmProps: Record<string, unknown> | undefined;
jest.mock("../src/client/revisions", () => ({
  ...jest.requireActual("../src/client/revisions"),
  getRevisionDetail: jest.fn(),
  postRevision: jest.fn(),
}));
jest.mock("../src/client/serverDraftStore", () => ({
  ServerDraftStore: jest.fn().mockImplementation(function (this: Record<string, unknown>) {
    Object.assign(this, {
      load: jest.fn(async () => ({})),
      flush: mockServerFlush,
      enterRefusal: mockEnterRefusal,
      resumeAfterConsentGrant: mockResumeConsent,
      recordTimelineEvent: jest.fn(async () => undefined),
      getLocaleMetadata: () => ({ locale: "previous", translationVersion: 1 }),
      getServerUpdatedAt: () => "revision-1",
      isSignedOut: () => false,
      isSaveHeld: () => mockSaveHeld,
      retrySave: mockRetrySave,
      heldStaleChange: () => mockHeldStale,
      overtakenAnswers: () => mockOvertaken,
      useMyAnswers: mockUseMine,
      keepNewerVersion: mockKeepNewer,
      useOvertakenAnswers: mockUseOvertaken,
      discardOvertakenAnswers: mockDiscardOvertaken,
      restoreLocaleMetadata: mockRestoreLocaleMetadata,
      setLocaleMetadata: mockSetLocaleMetadata,
      dispose: jest.fn(),
    });
  }),
}));
jest.mock("@drguptavivek/who-2022-va", () => ({
  createWhoVa2022Instrument: () => ({id: "WHO_2022_VA", version: "1", sections: [], questions: []}),
  createWhoVaInitialDataFromPrefill: () => ({}),
  compileInstrumentDefinition: jest.fn(), ENGINE_VERSION: 1, reduceNationalIdData: (data: unknown) => data, WHO_VA_FORM_VERSION: "2022",
  WHO_VA_BUILT_IN_UI_TRANSLATIONS: {hi: {back: "पीछे", moreSectionsNote: "उत्तर देने पर और अनुभाग दिखेंगे"}},
}), {virtual: true});
jest.mock("@drguptavivek/who-2022-va/web", () => ({WhoVaForm: () => null}), {virtual: true});
// InterviewScreen downloads the browser WHO runtime through the shared loader;
// keep this unit suite synchronous and focused on screen behaviour.
jest.mock("../src/web/whoRuntimeLoader", () => ({
  loadWhoCoreRuntime: jest.fn(async () => jest.requireMock("@drguptavivek/who-2022-va")),
  loadWhoWebRuntime: jest.fn(async () => jest.requireMock("@drguptavivek/who-2022-va/web")),
}));
// The attachment services are their own module (tested in web-interview-attachments.test.ts); the screen's part is
// handing their platform to the form and sending files before a submit.
const mockAttachmentPlatform = { captureImage: jest.fn(), selectImage: jest.fn(), startAudioRecording: jest.fn(), selectFile: jest.fn() };
const mockAttachments = {
  platform: undefined as typeof mockAttachmentPlatform | undefined,
  unavailable: false, status: "", notices: [] as string[], held: [] as Array<{id: string; text: string}>,
  dismissNotices: jest.fn(), deleteHeld: jest.fn(async () => undefined), send: jest.fn(async () => 0),
};
const mockUseAttachments = jest.fn((_options: unknown) => mockAttachments);
jest.mock("../src/web/interviewAttachments", () => ({useInterviewAttachments: (options: unknown) => mockUseAttachments(options)}));
const mockGetDraftConsent = jest.fn();
const mockPostDraftConsent = jest.fn();
const mockFetchConsentConfig = jest.fn();
jest.mock("../src/web/StationConsentPanel", () => ({
  RespondentConsentPanel: (props: {language: string; onDecision: (envelope: unknown) => void}) =>
    jest.requireActual("react").createElement("mock-consent-panel", props),
}));
jest.mock("../src/ConfirmDialog", () => ({
  ConfirmDialog: (props: Record<string, unknown>) => {
    mockConfirmProps = props;
    return jest.requireActual("react").createElement("mock-confirm", { title: props.title });
  },
}));
jest.mock("../src/consent", () => ({
  ...jest.requireActual("../src/consent"),
  getDraftConsent: (...args: unknown[]) => mockGetDraftConsent(...args),
  postDraftConsent: (...args: unknown[]) => mockPostDraftConsent(...args),
  fetchProjectConsentConfig: (...args: unknown[]) => mockFetchConsentConfig(...args),
}));

import InterviewScreen, { draftChangeText, INTERVIEW_FORM_CSS } from "../src/web/InterviewScreen";
import { formatDisplayTimestamp } from "../src/ui/CaseCard";
import { ClientApiError, getCaseDetail, getDraft, getIntakeContext, getProjectFormOptions, getInstrumentTranslations, startDraft, submitDraft } from "../src/client/api";
import { getRevisionDetail, postRevision } from "../src/client/revisions";
import { ServerDraftStore } from "../src/client/serverDraftStore";
import { WhoVaForm } from "@drguptavivek/who-2022-va/web";
import { t, setUiLocale } from "../src/i18n";
import { guardedNavigate, leaveDialogOpen, leavePage, leaveSaveFailed, saveAndLeave, stayOnPage } from "../src/web/navigationGuard";
import { AppHeaderBar } from "../src/web/AppHeader";
import { whoFormTheme } from "../src/whoWebTheme";
import { loadWhoCoreRuntime, loadWhoWebRuntime } from "../src/web/whoRuntimeLoader";

jest.mock("../src/prefill", () => ({initialDataFromPrefill: () => ({})}));

beforeEach(() => {
  window.addEventListener = jest.fn();
  window.removeEventListener = jest.fn();
  jest.clearAllMocks();
  mockCurrentBootstrap = mockBootstrap;
  mockServerFlush.mockReset().mockResolvedValue(undefined);
  mockParams = {draftId: "draft-1"};
  setUiLocale("en");
  mockDefinitionCache.get.mockClear();
  mockDefinitionCache.put.mockClear();
  mockHasServed.mockReset().mockReturnValue(false);
  mockMarkServed.mockReset().mockResolvedValue(undefined);
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P", updated_at: "revision-1"}, envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", definitionSha256: mockDefinitionSha256, definitionExtensions: [], locale: "hi", translation_version: 7, data: {}}, prefill: {}});
  (getProjectFormOptions as jest.Mock).mockResolvedValue({instrument_version: "server-v1", definition_sha256: mockDefinitionSha256, enabled_extensions: [], narration_languages: [{code: "en", label: "English"}, {code: "hi", label: "Hindi"}], form_types: [{instrument_code: "WHO_2022_VA", is_default: true}], available_locales: [{code: "en", label: "English"}, {code: "hi", label: "Hindi"}], translation_versions: {hi: 9}});
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(404, "not_found"));
  mockRouter.replace.mockClear();
  mockGetDraftConsent.mockReset().mockResolvedValue({consent_required: false, decision: null, covered_fields: [], client_draft_id: null});
  mockPostDraftConsent.mockReset();
  mockFetchConsentConfig.mockReset().mockResolvedValue(null);
  (loadWhoCoreRuntime as jest.Mock).mockReset().mockResolvedValue(jest.requireMock("@drguptavivek/who-2022-va"));
  (loadWhoWebRuntime as jest.Mock).mockReset().mockResolvedValue(jest.requireMock("@drguptavivek/who-2022-va/web"));
});

beforeEach(() => {
  Object.assign(mockAttachments, {platform: undefined, unavailable: false, status: "", notices: [], held: []});
  mockAttachments.send.mockReset().mockResolvedValue(0);
  mockUseAttachments.mockClear();
});


import { RefusalPanel } from "../src/RefusalPanel";
import { requestClientJson } from "../src/client/api";
import { draftReloadUrl } from "../src/web/draftReload";

const DRAFTS = "/api/v1/intake/drafts";
const HREF = "https://app.test/interview?projectId=P&siteId=S#top";
const originalLocation = Object.getOwnPropertyDescriptor(window, "location");
const mockLocationReplace = jest.fn();

function draftWith(data: Record<string, unknown>, locale = "hi") {
  return {
    draft: {project_id: "P", updated_at: "revision-1"},
    envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", definitionSha256: mockDefinitionSha256, definitionExtensions: [], locale, translation_version: 7, data},
    prefill: {},
  };
}
const render = async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  return tree;
};
const panel = (tree: ReturnType<typeof create>) => tree.root.findByType(RefusalPanel);
const shown = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());
const confirmOpen = (tree: ReturnType<typeof create>) => tree.root.findAllByType("mock-confirm" as unknown as React.ElementType).length > 0;
const consentPanels = (tree: ReturnType<typeof create>) => tree.root.findAllByType("mock-consent-panel" as unknown as React.ElementType);
/** Whether the invocation orders are strictly increasing. */
const inOrder = (order: Array<number | undefined>) => order.every((value, index) => value !== undefined && (index === 0 || value > order[index - 1]!));

beforeEach(() => {
  mockConfirmProps = undefined;
  mockSetLocaleMetadata.mockReset();
  mockRestoreLocaleMetadata.mockReset();
  mockEnterRefusal.mockReset();
  mockLocationReplace.mockReset();
  (requestClientJson as jest.Mock).mockReset().mockResolvedValue({});
  (submitDraft as jest.Mock).mockReset().mockResolvedValue({va_sid: "sid-1", draft: {draft_id: "draft-1", project_id: "P", site_id: "S"}, superseded: false, validation_err: []});
  Object.defineProperty(window, "location", {configurable: true, value: {href: HREF, replace: mockLocationReplace}});
});
afterAll(() => {
  if (originalLocation) Object.defineProperty(window, "location", originalLocation);
  else delete (window as {location?: unknown}).location;
});

it("opens a saved draft in order: intake context, draft, form options, store, store load", async () => {
  const tree = await render();
  expect(getIntakeContext).toHaveBeenCalledWith(mockBootstrap.csrf, "interview", "all");
  expect(getDraft).toHaveBeenCalledWith(DRAFTS, "draft-1", mockBootstrap.csrf);
  expect(getProjectFormOptions).toHaveBeenCalledWith("P", mockBootstrap.csrf);
  const store = (ServerDraftStore as unknown as jest.Mock).mock.instances[0] as {load: jest.Mock};
  expect(store.load).toHaveBeenCalledWith("draft-1");
  expect(inOrder([
    (getIntakeContext as jest.Mock).mock.invocationCallOrder[0],
    (getDraft as jest.Mock).mock.invocationCallOrder[0],
    (getProjectFormOptions as jest.Mock).mock.invocationCallOrder[0],
    mockChoose.mock.invocationCallOrder[0],
    (ServerDraftStore as unknown as jest.Mock).mock.invocationCallOrder[0],
    store.load.mock.invocationCallOrder[0],
  ])).toBe(true);
  expect(mockChoose).toHaveBeenCalledWith("hi");
  expect(tree.root.findByType(WhoVaForm).props.locale).toBe("hi");
  await act(async () => tree.unmount());
});

describe("refusal after the WHO consent question was answered No", () => {
  const SAVED = {Id10013: "no", Id10007: "Name", refusal_age_group: "child", refusal_sex: "male"};

  it("restores the refusal profile from the saved draft and puts the store in refusal", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    const tree = await render();
    expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
    expect(panel(tree).props).toMatchObject({locale: "hi", age: "child", sex: "male"});
    expect(mockEnterRefusal).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("Save refusal flushes, re-reads the draft and submits only the refusal answers at its updated_at", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    const tree = await render();
    await act(async () => { panel(tree).props.onAge("15_49y"); });
    await act(async () => { panel(tree).props.onSex("female"); });
    (getDraft as jest.Mock).mockClear();
    mockServerFlush.mockClear();
    await act(async () => { panel(tree).props.onSave(); });
    expect(getDraft).toHaveBeenCalledWith(DRAFTS, "draft-1", mockBootstrap.csrf);
    expect(submitDraft).toHaveBeenCalledWith(DRAFTS, "draft-1", {valid: true, issues: [], data: {Id10013: "no", refusal_age_group: "15_49y", refusal_sex: "female"}}, mockBootstrap.csrf, "revision-1");
    expect(mockRouter.replace).toHaveBeenCalledWith({pathname: "/collection", params: {submitted: "1"}});
    expect(inOrder([
      mockServerFlush.mock.invocationCallOrder[0],
      (getDraft as jest.Mock).mock.invocationCallOrder[0],
      (submitDraft as jest.Mock).mock.invocationCallOrder[0],
      mockRouter.replace.mock.invocationCallOrder[0],
    ])).toBe(true);
    await act(async () => tree.unmount());
  });

  it("a refused Save refusal stays on the panel with the error", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    (submitDraft as jest.Mock).mockRejectedValue(new Error("submit_failed"));
    const tree = await render();
    await act(async () => { panel(tree).props.onSave(); });
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(shown(tree)).toContain("submit_failed");
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => tree.unmount());
  });

  it("Change consent asks to confirm in the interview language; Cancel closes the dialog", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConfirmProps).toMatchObject({
      title: "सहमति की पुष्टि करें",
      message: "क्या उत्तरदाता ने अब साक्षात्कार के लिए सहमति दी है? हटाए गए उत्तर वापस नहीं आएंगे।",
      confirmLabel: "हाँ, सहमति दी",
      cancelLabel: t("cancel"),
    });
    expect(mockFetchConsentConfig).not.toHaveBeenCalled();
    await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
    expect(confirmOpen(tree)).toBe(false);
    await act(async () => tree.unmount());
  });

  it("the confirm dialog is in English for an English interview", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED, "en"));
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockConfirmProps).toMatchObject({
      title: "Confirm consent",
      message: "Has the respondent now agreed to the interview? Removed answers will not be restored.",
      confirmLabel: "Yes, consent granted",
    });
    await act(async () => tree.unmount());
  });

  it("confirming flushes, re-reads the draft, PATCHes Id10013 yes with resume_refused, then reloads onto the draft", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    (getDraft as jest.Mock).mockClear();
    mockServerFlush.mockClear();
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    expect(getDraft).toHaveBeenCalledWith(DRAFTS, "draft-1", mockBootstrap.csrf);
    expect(requestClientJson).toHaveBeenCalledTimes(1);
    expect(requestClientJson).toHaveBeenCalledWith(`${DRAFTS}/draft-1`, {
      method: "PATCH", csrf: mockBootstrap.csrf, json: {sections: {_other: {Id10013: "yes"}}, resume_refused: true, if_updated_at: "revision-1"},
    });
    expect(mockLocationReplace).toHaveBeenCalledWith(draftReloadUrl(HREF, "draft-1"));
    expect(inOrder([
      mockServerFlush.mock.invocationCallOrder[0],
      (getDraft as jest.Mock).mock.invocationCallOrder[0],
      (requestClientJson as jest.Mock).mock.invocationCallOrder[0],
      mockLocationReplace.mock.invocationCallOrder[0],
    ])).toBe(true);
    expect(confirmOpen(tree)).toBe(false);
    await act(async () => tree.unmount());
  });

  it("a refused PATCH shows the error, closes the dialog and keeps the refusal", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith(SAVED));
    (requestClientJson as jest.Mock).mockRejectedValue(new Error("patch_failed"));
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
    expect(mockLocationReplace).not.toHaveBeenCalled();
    expect(shown(tree)).toContain("patch_failed");
    expect(confirmOpen(tree)).toBe(false);
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => tree.unmount());
  });
});

describe("refusal of the consent notice on file", () => {
  const REFUSED = {consent_required: true, decision: "refused", covered_fields: ["Id10007"], client_draft_id: "client-1"};
  const consentConfig = {project_id: "P", consent_required: true, notice_versions: []};

  it("Change consent fetches the project's notice, then opens the consent screen", async () => {
    mockGetDraftConsent.mockResolvedValue(REFUSED);
    mockFetchConsentConfig.mockResolvedValue(consentConfig);
    const tree = await render();
    expect(mockFetchConsentConfig).not.toHaveBeenCalled();
    expect(consentPanels(tree)).toHaveLength(0);
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(mockFetchConsentConfig).toHaveBeenCalledWith("P", mockBootstrap.csrf);
    expect(consentPanels(tree)).toHaveLength(1);
    expect(consentPanels(tree)[0]!.props).toMatchObject({config: consentConfig, clientDraftId: "client-1", language: "hi"});
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(0);
    expect(mockConfirmProps).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("a failed notice fetch stays on the refusal panel with the error", async () => {
    mockGetDraftConsent.mockResolvedValue(REFUSED);
    mockFetchConsentConfig.mockRejectedValue(new Error("notice_failed"));
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    expect(consentPanels(tree)).toHaveLength(0);
    expect(shown(tree)).toContain("notice_failed");
    expect(tree.root.findAllByType(RefusalPanel)).toHaveLength(1);
    await act(async () => tree.unmount());
  });

  it("a grant on the consent screen resumes the store and reloads onto the draft", async () => {
    mockGetDraftConsent.mockResolvedValue(REFUSED);
    mockFetchConsentConfig.mockResolvedValue(consentConfig);
    mockPostDraftConsent.mockResolvedValue({...REFUSED, decision: "granted"});
    const tree = await render();
    await act(async () => { panel(tree).props.onChangeConsent(); });
    const envelope = {client_id: "c1", decision: "granted"};
    await act(async () => { await consentPanels(tree)[0]!.props.onDecision(envelope); });
    expect(mockPostDraftConsent).toHaveBeenCalledWith(DRAFTS, "draft-1", envelope, mockBootstrap.csrf);
    expect(mockResumeConsent).toHaveBeenCalled();
    expect(mockLocationReplace).toHaveBeenCalledWith(draftReloadUrl(HREF, "draft-1"));
    await act(async () => tree.unmount());
  });
});

describe("questionnaire language switch", () => {
  const select = async (tree: ReturnType<typeof create>, locale: string) => {
    const shell = tree.root.findByType(jest.requireMock("../src/web/common").WebShell);
    let result: unknown;
    await act(async () => { result = await shell.props.headerAction.props.onSelect(locale); });
    return result;
  };
  const withController = async (tree: ReturnType<typeof create>, saveDraft: jest.Mock) => {
    await act(async () => { tree.root.findByType(WhoVaForm).props.onDraftController({saveDraft}); });
  };

  it("saves and flushes, re-reads the form options, records the new locale, saves again, then switches", async () => {
    const tree = await render();
    const saveDraft = jest.fn(async () => undefined);
    await withController(tree, saveDraft);
    mockServerFlush.mockClear();
    mockChoose.mockClear();
    (getProjectFormOptions as jest.Mock).mockClear();
    expect(await select(tree, "en")).toBe(true);
    expect(getProjectFormOptions).toHaveBeenCalledWith("P", mockBootstrap.csrf);
    expect(mockSetLocaleMetadata).toHaveBeenCalledWith("en", 0);
    expect(saveDraft).toHaveBeenCalledTimes(2);
    expect(mockServerFlush).toHaveBeenCalledTimes(2);
    expect(mockChoose).toHaveBeenCalledWith("en");
    expect(inOrder([
      saveDraft.mock.invocationCallOrder[0],
      mockServerFlush.mock.invocationCallOrder[0],
      (getProjectFormOptions as jest.Mock).mock.invocationCallOrder[0],
      mockSetLocaleMetadata.mock.invocationCallOrder[0],
      saveDraft.mock.invocationCallOrder[1],
      mockServerFlush.mock.invocationCallOrder[1],
      mockChoose.mock.invocationCallOrder[0],
    ])).toBe(true);
    expect(tree.root.findByType(WhoVaForm).props.locale).toBe("en");
    expect(mockRestoreLocaleMetadata).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("records the project's translation version for the chosen language", async () => {
    (getDraft as jest.Mock).mockResolvedValue(draftWith({}, "en"));
    const tree = await render();
    await withController(tree, jest.fn(async () => undefined));
    expect(await select(tree, "hi")).toBe(true);
    expect(mockSetLocaleMetadata).toHaveBeenCalledWith("hi", 9);
    expect(tree.root.findByType(WhoVaForm).props.locale).toBe("hi");
    await act(async () => tree.unmount());
  });

  it("the current language only re-applies the UI language", async () => {
    const tree = await render();
    const saveDraft = jest.fn(async () => undefined);
    await withController(tree, saveDraft);
    mockChoose.mockClear();
    (getProjectFormOptions as jest.Mock).mockClear();
    expect(await select(tree, "hi")).toBe(true);
    expect(mockChoose).toHaveBeenCalledWith("hi");
    expect(saveDraft).not.toHaveBeenCalled();
    expect(getProjectFormOptions).not.toHaveBeenCalled();
    expect(mockSetLocaleMetadata).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("a failed switch restores the store's locale metadata and keeps the language", async () => {
    const tree = await render();
    await withController(tree, jest.fn(async () => undefined));
    (getProjectFormOptions as jest.Mock).mockRejectedValueOnce(new Error("options_failed"));
    expect(await select(tree, "en")).toBe(false);
    expect(mockRestoreLocaleMetadata).toHaveBeenCalledWith({locale: "previous", translationVersion: 1});
    expect(mockSetLocaleMetadata).not.toHaveBeenCalled();
    expect(shown(tree)).toContain("options_failed");
    expect(tree.root.findByType(WhoVaForm).props.locale).toBe("hi");
    await act(async () => tree.unmount());
  });
});
