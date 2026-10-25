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
jest.mock("../src/theme", () => ({radius: { sm: 4, md: 6, lg: 8, full: 9999 }, fontSize: { body: 14 }, useTheme: () => ({colors: {}, ui: jest.requireActual("../src/theme").ui[mockColorMode]})}));
jest.mock("../src/ui", () => ({
  Button: (props: {label: string; onPress: () => void}) => jest.requireActual("react").createElement("mock-button", props),
  useUiStyles: () => ({}),
}));
let mockShellProps: {lead?: React.ReactElement<{sticky?: boolean}>} = {};
jest.mock("../src/web/common", () => ({WebShell: (props: {children: ReactNode; lead?: React.ReactElement<{sticky?: boolean}>}) => { mockShellProps = props; return <>{props.children}</>; }, browserErrorText: (error: Error) => error.message}));
jest.mock("../src/client/api", () => ({
  ...jest.requireActual("../src/client/api"),
  getIntakeContext: jest.fn(async () => ({})),
  getDraft: jest.fn(), getProjectFormOptions: jest.fn(), getInstrumentTranslations: jest.fn(), getCaseDetail: jest.fn(), startDraft: jest.fn(), submitDraft: jest.fn()
}));
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
      getLocaleMetadata: () => ({}),
      getServerUpdatedAt: () => "revision-1",
      restoreLocaleMetadata: jest.fn(),
      setLocaleMetadata: jest.fn(),
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
const mockGetDraftConsent = jest.fn();
const mockPostDraftConsent = jest.fn();
const mockFetchConsentConfig = jest.fn();
jest.mock("../src/web/StationConsentPanel", () => ({
  RespondentConsentPanel: (props: {language: string; onDecision: (envelope: unknown) => void}) =>
    jest.requireActual("react").createElement("mock-consent-panel", props),
}));
jest.mock("../src/consent", () => ({
  ...jest.requireActual("../src/consent"),
  getDraftConsent: (...args: unknown[]) => mockGetDraftConsent(...args),
  postDraftConsent: (...args: unknown[]) => mockPostDraftConsent(...args),
  fetchProjectConsentConfig: (...args: unknown[]) => mockFetchConsentConfig(...args),
}));

import InterviewScreen, { INTERVIEW_FORM_CSS } from "../src/web/InterviewScreen";
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function submittedDetail(id: string) {
  return {
    draft: { draft_id: id, project_id: "P", site_id: "S", status: "submitted", va_sid: `sid-${id}`, created_at: "2026-10-04T10:00:00+05:30", updated_at: "2026-10-04T11:00:00+05:30" },
    envelope: { schemaVersion: 1, formVersion: "2022", id, instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [], currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", data: { Id10007: id, interview_outcome: "partially_completed" } },
    prefill: { lockedQuestionNames: [] },
    answers_sha256: null,
  };
}

it("starts a later-page case using its authorized detail by id", async () => {
  mockParams = {deathId: "later-page"};
  (getCaseDetail as jest.Mock).mockResolvedValue({case: {project_id: "P2", site_id: "S2", org_unit_id: "U2", prefill: {}}});
  (startDraft as jest.Mock).mockResolvedValue({draft: {draft_id: "new-draft"}});
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P2"}, envelope: {id: "new-draft", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "en", data: {}}, prefill: {}});
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(getCaseDetail).toHaveBeenCalledWith("/api/v1/intake/cases", "later-page", mockBootstrap.csrf);
  expect(startDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", {project_id: "P2", site_id: "S2", org_unit_id: "U2", death_id: "later-page"}, mockBootstrap.csrf);
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("retries a failed WHO runtime download before creating a new draft", async () => {
  const core = jest.requireMock("@drguptavivek/who-2022-va");
  const web = jest.requireMock("@drguptavivek/who-2022-va/web");
  (loadWhoCoreRuntime as jest.Mock)
    .mockRejectedValueOnce(new Error("chunk download failed"))
    .mockResolvedValue(core);
  (loadWhoWebRuntime as jest.Mock).mockResolvedValue(web);
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect(startDraft).not.toHaveBeenCalled();
  const retry = tree.root.findAllByType("mock-button" as unknown as React.ElementType)
    .find((node) => node.props.label === "Try again");
  expect(retry).toBeDefined();
  await act(async () => { retry?.props.onPress(); });
  expect(getDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", mockBootstrap.csrf);
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("shows the reported death's case strip when the draft is linked to a death, not for a direct interview", async () => {
  const caseDraft = {draft: {project_id: "P", death_id: "death-1"}, envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [], currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "en", data: {}}, prefill: {deceased: {givenNames: "Asha", surname: "Devi", sex: "female", dateOfDeath: "2026-09-22", ageInYears: 51}}};
  (getDraft as jest.Mock).mockResolvedValue(caseDraft);
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(JSON.stringify(tree.toJSON())).toContain("Asha Devi · DOD: 2026-09-22 · Age: 51 yr · Sex: Female");
  await act(async () => tree.unmount());

  (getDraft as jest.Mock).mockResolvedValue({...caseDraft, draft: {project_id: "P", death_id: null}});
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  expect(JSON.stringify(tree.toJSON())).not.toContain("Asha Devi");
  expect(JSON.stringify(tree.toJSON())).toContain("— · DOD: — · Age: — · Sex: —");
  await act(async () => tree.unmount());
});

it("shows the Before you begin welcome card on a new draft with intake_screen andintake_note, and opens WhoVaForm on Start questionnaire", async () => {
  const note = "Before you begin: confirm the respondent has consented and you are in a private setting.";
  (getIntakeContext as jest.Mock).mockResolvedValue({
    context: [
      {
        project_id: "P",
        project_name: "Project",
        site_id: "S",
        site_name: "Site",
        web_intake_mode: "direct",
        org_units: [{ org_unit_id: "U1", unit_name: "PHC 1", level_name: "PHC-AAM" }],
      },
    ],
  });
  (getProjectFormOptions as jest.Mock).mockResolvedValue({
    instrument_version: "server-v1",
    definition_sha256: mockDefinitionSha256,
    enabled_extensions: ["digitva_core", "intake_screen"],
    intake_note: note,
    narration_languages: [{ code: "en", label: "English" }],
    form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
    available_locales: [{ code: "en", label: "English" }],
    translation_versions: {},
  });
  (getDraft as jest.Mock).mockResolvedValue({
    draft: {
      draft_id: "draft-1",
      unique_id: "PHC01-000146",
      project_id: "P",
      site_id: "S",
      org_unit_id: "U1",
      current_section: null,
      updated_at: "2026-10-04T11:00:00+05:30",
    },
    envelope: {
      id: "draft-1",
      schemaVersion: 1,
      formVersion: "2022",
      instrumentId: "WHO_2022_VA",
      instrumentVersion: "server-v1",
      definitionSha256: mockDefinitionSha256,
      definitionExtensions: [],
      currentSection: "",
      createdAt: "2026-10-04T10:00:00+05:30",
      updatedAt: "2026-10-04T11:00:00+05:30",
      locale: "en",
      data: {},
    },
    prefill: {},
  });

  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<InterviewScreen />);
  });

  expect(tree.root.findByProps({ testID: "interview-welcome-card" })).toBeDefined();
  expect(tree.root.findByProps({ testID: "interview-welcome-title" }).props.children).toBe("Before you begin");
  expect(tree.root.findByProps({ testID: "interview-welcome-note" }).props.children).toBe(note);
  expect(tree.root.findByProps({ testID: "interview-case-meta" }).props.children).toBe("Case id PHC01-000146 · PHC-AAM PHC 1");
  expect(tree.root.findByProps({ testID: "interview-save-status" }).props.children).toBe("Not saved yet");
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);

  const startBtn = tree.root.findByProps({ testID: "interview-welcome-start" });
  await act(async () => {
    startBtn.props.onPress();
  });

  expect(tree.root.findAllByProps({ testID: "interview-welcome-card" })).toHaveLength(0);
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("hands the form the app theme tokens, light and dark", async () => {
  const {ui: tokens} = jest.requireActual("../src/theme");
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  const light = tree.root.findByType(WhoVaForm).props.theme;
  expect(light).toEqual(whoFormTheme({ui: tokens.light}));
  expect(light.primary).toBe(tokens.light.primary);
  mockColorMode = "dark";
  await act(async () => {tree.update(<InterviewScreen />);});
  const dark = tree.root.findByType(WhoVaForm).props.theme;
  mockColorMode = "light";
  expect(dark).toEqual(whoFormTheme({ui: tokens.dark}));
  expect(dark.primary).not.toBe(light.primary);
  await act(async () => tree.unmount());
});

it("blanks the more-sections note in every UI locale and keeps the built-in packs", async () => {
  const {resolveUiMessages} = jest.requireActual("../../../vendor/who-va-2022/dist/index.js");
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  const uiTranslations = tree.root.findByType(WhoVaForm).props.uiTranslations;
  // The subject is there: the package's English note is non-empty by default.
  expect(resolveUiMessages("en").moreSectionsNote).toBe("More sections appear as you answer");
  for (const locale of ["en", "hi", "hi-IN", "fr", "bn"]) {
    expect(resolveUiMessages(locale, uiTranslations).moreSectionsNote).toBe("");
  }
  expect(resolveUiMessages("hi", uiTranslations).back).toBe("पीछे");
  await act(async () => tree.unmount());
});

it("does not start an interview when case detail access is denied", async () => {
  mockParams = {deathId: "unavailable"};
  (getCaseDetail as jest.Mock).mockRejectedValue(new ClientApiError(404, "not_found"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(startDraft).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("keeps saved locale/version when its translation is missing or disabled", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  const form = tree.root.findByType(WhoVaForm);
  expect(form.props.locale).toBe("hi");
  expect(JSON.stringify(tree.toJSON())).toContain(t("questionnaireEnglishFallback"));
  expect(ServerDraftStore).toHaveBeenCalledWith(expect.objectContaining({locale: "hi", translationVersion: 7}));
  await act(async () => {form.props.onDraftSaved();});
  expect(JSON.stringify(tree.toJSON())).toContain(t("questionnaireEnglishFallback"));
  await act(async () => tree.unmount());
});

it.each([401, 403])("blocks access for translation HTTP %s", async status => {
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(status, "forbidden"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  expect(ServerDraftStore).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain(`HTTP ${status}`);
  await act(async () => tree.unmount());
});

it.each([429, 500])("surfaces translation HTTP %s without replacing saved language metadata", async status => {
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(status, "temporary_failure"));
  const savedDraft = {draft: {project_id: "P"}, envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [], currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "hi", translation_version: 7, data: {}}, prefill: {}};
  (getDraft as jest.Mock).mockResolvedValue(savedDraft);
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  expect(ServerDraftStore).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain(`HTTP ${status} temporary_failure`);
  expect(savedDraft.envelope).toMatchObject({locale: "hi", translation_version: 7, definitionSha256: mockDefinitionSha256, definitionExtensions: []});
  await act(async () => tree.unmount());
});

it("removes an already rendered form when a language request loses permission", async () => {
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P"}, envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [], currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "en", data: {}}, prefill: {}});
  (getInstrumentTranslations as jest.Mock).mockRejectedValue(new ClientApiError(403, "forbidden"));
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findByType(WhoVaForm)).toBeDefined();
  const shell = tree.root.findByType(jest.requireMock("../src/web/common").WebShell);
  await act(async () => {await shell.props.headerAction.props.onSelect("hi");});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("blocks a deep-linked new interview when the valid case detail omits prefill", async () => {
  mockParams = { deathId: "held-by-other-worker" };
  (getCaseDetail as jest.Mock).mockResolvedValue({ case: { project_id: "P2", site_id: "S2", informant: { name: "Contact" } } });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect(getCaseDetail).toHaveBeenCalled();
  expect(startDraft).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("returns to collection after a normal 201 draft submission", async () => {
  (submitDraft as jest.Mock).mockResolvedValue({ va_sid: "sid-1", draft: { draft_id: "draft-1", project_id: "P", site_id: "S" }, superseded: false, validation_err: [] });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  const data = { Id10013: "yes", interview_outcome: "completed" };
  await act(async () => { await form.props.onComplete({ valid: true, issues: [], data }); });
  expect(submitDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", { valid: true, issues: [], data }, mockBootstrap.csrf, "revision-1");
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: { submitted: "1" } });
  await act(async () => tree.unmount());
});

it("routes an acknowledged can-code-now response to collection as a hint", async () => {
  (submitDraft as jest.Mock).mockResolvedValue({
    va_sid: "sid-1", draft: { draft_id: "draft-1", project_id: "P", site_id: "S", unique_id: "VA-1" },
    superseded: false, validation_err: [], can_code_now: true,
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [], data: { Id10013: "yes" } }); });
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: { submitted: "1", submittedId: "VA-1", canCodeNow: "1", readyUniqueId: "VA-1", readyVaSid: "sid-1" } });
  await act(async () => tree.unmount());
});

it("submits a stale completed tab's current answers after confirming the draft is submitted", async () => {
  const answers = { Id10013: "yes", interview_outcome: "completed" };
  const response = { draft: { draft_id: "draft-1", project_id: "P", site_id: "S", status: "submitted", updated_at: "submitted-at" }, envelope: {}, prefill: {} };
  mockServerFlush.mockRejectedValueOnce(new ClientApiError(409, "draft_not_editable"));
  (submitDraft as jest.Mock).mockResolvedValue({
    va_sid: "sid-1", draft: { ...response.draft, unique_id: "VA-1" }, superseded: false,
    validation_err: [], kept: "server", locked: true, can_code_now: true
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  (getDraft as jest.Mock).mockResolvedValueOnce(response);
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [], data: answers }); });

  expect(getDraft).toHaveBeenCalledTimes(2);
  expect(submitDraft).toHaveBeenCalledWith(
    "/api/v1/intake/drafts", "draft-1", { valid: true, issues: [], data: answers }, mockBootstrap.csrf, "revision-1"
  );
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: {
    submitted: "1", submittedId: "VA-1", submissionHistory: "1", submissionLocked: "1", canCodeNow: "1", readyUniqueId: "VA-1", readyVaSid: "sid-1"
  } });
  await act(async () => tree.unmount());
});

it("keeps an open draft stale after a 409 save and does not submit it", async () => {
  mockServerFlush.mockRejectedValueOnce(new ClientApiError(409, "draft_stale", undefined, undefined, {
    error: "This interview was also edited on another device; reload before saving."
  }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  (getDraft as jest.Mock).mockResolvedValueOnce({
    draft: { draft_id: "draft-1", project_id: "P", site_id: "S", status: "draft", updated_at: "revision-1" },
    envelope: {}, prefill: {},
  });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [], data: { Id10013: "yes" } }); });

  expect(getDraft).toHaveBeenCalledTimes(2);
  expect(submitDraft).not.toHaveBeenCalled();
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("This interview was also edited on another device; reload before saving.");
  await act(async () => tree.unmount());
});

it("does not submit a stale tab after the account changes during the submitted-status check", async () => {
  const statusCheck = deferred<Awaited<ReturnType<typeof getDraft>>>();
  mockServerFlush.mockRejectedValueOnce(new ClientApiError(409, "draft_not_editable"));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  (getDraft as jest.Mock).mockReturnValueOnce(statusCheck.promise);
  const form = tree.root.findByType(WhoVaForm);
  let completion!: Promise<void>;
  await act(async () => {
    completion = form.props.onComplete({ valid: true, issues: [], data: { Id10013: "yes" } });
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(getDraft).toHaveBeenCalledTimes(2);

  mockCurrentBootstrap = {
    ...mockBootstrap,
    user: { user_id: "u2", name: "Other worker" },
    csrf: { header: "X-CSRFToken", token: "other-csrf" },
  };
  await act(async () => { tree.update(<InterviewScreen />); });
  const submitted = submittedDetail("draft-1");
  statusCheck.resolve({
    draft: { ...submitted.draft, status: "submitted" },
    envelope: submitted.envelope as Awaited<ReturnType<typeof getDraft>>["envelope"],
    prefill: submitted.prefill,
  });
  await act(async () => { await completion; });

  expect(submitDraft).not.toHaveBeenCalled();
  expect(mockRouter.replace).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("keeps a valid revision editable and refuses the POST when consent is missing", async () => {
  mockParams = { revisionDraftId: "d1", revisionProjectId: "P", revisionSiteId: "S", revisionVaSid: "sid-d1" };
  (getRevisionDetail as jest.Mock).mockReset().mockResolvedValue(submittedDetail("d1"));
  (postRevision as jest.Mock).mockReset();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const reasonButton = tree.root.findAll((node) => String(node.type) === "mock-button" && node.props.label === t("revisionReasonInterviewerCorrection"))[0];
  expect(reasonButton).toBeDefined();
  await act(async () => { reasonButton?.props.onPress(); });
  const form = tree.root.findByType(WhoVaForm);
  const store = form.props.draftStore;
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(postRevision).not.toHaveBeenCalled();
  expect(store.getCurrent().data).toMatchObject({ Id10007: "d1", interview_outcome: "partially_completed" });
  expect(JSON.stringify(tree.toJSON())).toContain(t("revisionConsentRequired"));
  await act(async () => tree.unmount());
});

it.each([
  ["refused", true, { Id10013: "no", interview_outcome: "refused" }],
  ["partially_completed", false, { Id10013: "yes", interview_outcome: "partially_completed" }],
] as const)("allows a completed public revision to change to %s", async (outcome, valid, data) => {
  mockParams = { revisionDraftId: "d1", revisionProjectId: "P", revisionSiteId: "S", revisionVaSid: "sid-d1" };
  const detail = submittedDetail("d1");
  detail.envelope.data = { ...detail.envelope.data, interview_outcome: "completed" };
  (getRevisionDetail as jest.Mock).mockReset().mockResolvedValue(detail);
  (postRevision as jest.Mock).mockReset().mockImplementation(async (_csrf, snapshot) => ({
    changed: true,
    va_sid: "sid-d1",
    payload_version_id: "version-2",
    answers_sha256: snapshot.answersSha256,
    outcome,
    workflow_state: "paused",
  }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  const store = form.props.draftStore;
  const currentDraft = store.getCurrent();
  store.save({ ...currentDraft, data: data as typeof currentDraft.data });
  await act(async () => { form.props.onChange(); });
  const reasonButton = tree.root.findAll((node) =>
    String(node.type) === "mock-button" && node.props.label === t("revisionReasonInterviewerCorrection"),
  )[0];
  await act(async () => { reasonButton.props.onPress(); });
  await act(async () => { await form.props.onComplete({ valid, issues: [], data }); });

  expect(postRevision).toHaveBeenCalledTimes(1);
  const snapshot = (postRevision as jest.Mock).mock.calls[0][1];
  expect(snapshot).toMatchObject({ reasonCode: "interviewer_correction", completion: { valid } });
  expect(snapshot.answersJson).toBe(JSON.stringify(data));
  expect(snapshot.answersSha256).toMatch(/^[a-f0-9]{64}$/);
  expect(snapshot.draft.completedAt).toMatch(/T.*[+-]\d{2}:\d{2}$/);
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: { submitted: "correction" } });
  await act(async () => tree.unmount());
});

it("does not remount a newer revision when an older same-account request resolves late", async () => {
  const first = deferred<ReturnType<typeof submittedDetail>>();
  const second = deferred<ReturnType<typeof submittedDetail>>();
  mockParams = { revisionDraftId: "d1", revisionProjectId: "P", revisionSiteId: "S", revisionVaSid: "sid-d1" };
  (getRevisionDetail as jest.Mock).mockImplementation((_endpoint, id: string) => id === "d1" ? first.promise : second.promise);
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect((getRevisionDetail as jest.Mock).mock.calls.map(([ , id]) => id)).toEqual(["d1"]);

  mockParams = { revisionDraftId: "d2", revisionProjectId: "P", revisionSiteId: "S", revisionVaSid: "sid-d2" };
  await act(async () => { tree.update(<InterviewScreen />); });
  expect((getRevisionDetail as jest.Mock).mock.calls.map(([ , id]) => id)).toEqual(["d1", "d2"]);

  await act(async () => { second.resolve(submittedDetail("d2")); await Promise.resolve(); });
  const form = tree.root.findByType(WhoVaForm);
  const currentStore = form.props.draftStore;
  const currentDraft = currentStore.getCurrent();
  currentStore.save({ ...currentDraft, data: { ...currentDraft.data, Id10007: "edited-d2" } });
  await act(async () => { form.props.onChange(); });

  await act(async () => { first.resolve(submittedDetail("d1")); await Promise.resolve(); });
  const mountedForm = tree.root.findByType(WhoVaForm);
  expect(mountedForm.props.draftStore).toBe(currentStore);
  expect(mountedForm.props.draftStore.getCurrent().data.Id10007).toBe("edited-d2");
  expect((getRevisionDetail as jest.Mock).mock.calls.map(([ , id]) => id)).toEqual(["d1", "d2"]);
  await act(async () => tree.unmount());
});

it("does not continue initialization after the screen unmounts", async () => {
  const pending = deferred<ReturnType<typeof submittedDetail>>();
  mockParams = { revisionDraftId: "d1", revisionProjectId: "P", revisionSiteId: "S", revisionVaSid: "sid-d1" };
  (getRevisionDetail as jest.Mock).mockReturnValue(pending.promise);
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect(getRevisionDetail).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());

  await act(async () => { pending.resolve(submittedDetail("d1")); await Promise.resolve(); });
  expect(mockChoose).not.toHaveBeenCalled();
});

it("returns to collection with a notice after a superseded 200 response", async () => {
  (submitDraft as jest.Mock).mockResolvedValue({ va_sid: null, draft: { draft_id: "draft-1", project_id: "P", site_id: "S" }, superseded: true, validation_err: null, can_code_now: true });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/collection", params: { submitted: "1", superseded: "1" } });
  await act(async () => tree.unmount());
});

it("stays on the interview when the submit acknowledgement is malformed", async () => {
  (submitDraft as jest.Mock).mockRejectedValue(new ClientApiError(200, "malformed_response"));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("HTTP 200 malformed_response");
  await act(async () => tree.unmount());
});

it("shows the server stale-draft explanation and stays on the interview", async () => {
  (submitDraft as jest.Mock).mockRejectedValue(new ClientApiError(409, "draft_stale", undefined, undefined, {
    error: "This interview was also edited on another device; reload before saving."
  }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  const form = tree.root.findByType(WhoVaForm);
  await act(async () => { await form.props.onComplete({ valid: true, issues: [] }); });
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("This interview was also edited on another device; reload before saving.");
  await act(async () => tree.unmount());
});

it("asks for the translation when the project's only extra extensions are untagged ones (digitva-oxvt staging)", async () => {
  (getProjectFormOptions as jest.Mock).mockResolvedValue({instrument_version: "server-v1", definition_sha256: mockDefinitionSha256, enabled_extensions: ["digitva_core", "intake_screen", "geography", "doris_support_whova_2022"], narration_languages: [{code: "en", label: "English"}, {code: "hi", label: "Hindi"}], form_types: [{instrument_code: "WHO_2022_VA", is_default: true}], available_locales: [{code: "en", label: "English"}, {code: "hi", label: "Hindi"}], translation_versions: {hi: 40}});
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P"}, envelope: {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [], currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "hi", translation_version: 40, data: {}}, prefill: {}});
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  // Untagged extensions never appear in the definition, so they must not
  // make the pin look different and skip the Hindi request.
  expect(getInstrumentTranslations).toHaveBeenCalledWith(expect.anything(), "hi", expect.anything());
  await act(async () => tree.unmount());
});

it("resolves and pins the current served form before creating a direct browser draft", async () => {
  mockParams = { projectId: "P", siteId: "S" };
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [{ project_id: "P", site_id: "S", web_intake_mode: "direct" }] });
  (startDraft as jest.Mock).mockResolvedValue({ draft: { draft_id: "new-draft" } });
  (getDraft as jest.Mock).mockResolvedValue({
    draft: { project_id: "P", updated_at: "revision-1" },
    envelope: { id: "new-draft", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "server-v1", currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", definitionSha256: mockDefinitionSha256, definitionExtensions: [], locale: "en", data: {} },
    prefill: {},
  });

  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });

  expect(mockDefinitionCache.get).toHaveBeenCalledWith({
    accountId: "u1", projectId: "P", instrumentCode: "WHO_2022_VA", composedVersion: "server-v1", sha256: mockDefinitionSha256,
  });
  expect(mockDefinitionCache.get.mock.invocationCallOrder[0]).toBeLessThan((startDraft as jest.Mock).mock.invocationCallOrder[0]);
  expect(mockMarkServed).toHaveBeenCalledWith("P");
  expect(tree.root.findByType(WhoVaForm).props.instrument.version).toBe("server-v1");
  expect(ServerDraftStore).toHaveBeenCalledWith(expect.objectContaining({
    definitionPin: { instrumentVersion: "server-v1", definitionSha256: mockDefinitionSha256, definitionExtensions: [] },
  }));
  await act(async () => tree.unmount());
});

it("uses the original bundled form only when project definition metadata is first missing", async () => {
  mockParams = { projectId: "P", siteId: "S" };
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [{ project_id: "P", site_id: "S", web_intake_mode: "direct" }] });
  (getProjectFormOptions as jest.Mock).mockResolvedValue({
    instrument_version: null,
    definition_sha256: null,
    enabled_extensions: [],
    narration_languages: [{ code: "en", label: "English" }],
    form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
    available_locales: [{ code: "en", label: "English" }],
  });
  (startDraft as jest.Mock).mockResolvedValue({ draft: { draft_id: "new-draft" } });

  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });

  expect(startDraft).toHaveBeenCalled();
  expect(mockDefinitionCache.get).not.toHaveBeenCalled();
  expect(mockMarkServed).not.toHaveBeenCalled();
  expect(tree.root.findByType(WhoVaForm).props.instrument.version).toBe("1");
  expect(ServerDraftStore).toHaveBeenCalledWith(expect.objectContaining({ definitionPin: null }));
  await act(async () => tree.unmount());
});

it("blocks a new interview when definition metadata disappears after a served version", async () => {
  mockParams = { projectId: "P", siteId: "S" };
  mockHasServed.mockReturnValue(true);
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [{ project_id: "P", site_id: "S", web_intake_mode: "direct" }] });
  (getProjectFormOptions as jest.Mock).mockResolvedValue({
    instrument_version: null,
    definition_sha256: null,
    enabled_extensions: [],
    narration_languages: [{ code: "en", label: "English" }],
    form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
    available_locales: [{ code: "en", label: "English" }],
  });

  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });

  expect(startDraft).not.toHaveBeenCalled();
  expect(mockDefinitionCache.get).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("moves an unpinned saved draft to the served form, never relabelling it with the extension-bearing bundle", async () => {
  const savedDraft = {
    draft: { project_id: "P", updated_at: "revision-1" },
    envelope: {
      id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "1",
      currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30",
      locale: "en", data: { Id10007: "server-answer" },
    },
    prefill: {},
  };
  (getDraft as jest.Mock).mockResolvedValue(savedDraft);
  (getProjectFormOptions as jest.Mock).mockResolvedValue({
    instrument_version: "1",
    definition_sha256: mockDefinitionSha256,
    enabled_extensions: ["geography"],
    narration_languages: [{ code: "en", label: "English" }],
    form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
    available_locales: [{ code: "en", label: "English" }],
  });

  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });

  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  expect(JSON.stringify(tree.toJSON())).toContain(t("formDefinitionAdopted"));
  expect(savedDraft.envelope.data).toEqual({ Id10007: "server-answer" });
  // Pinned to the served definition, not left pinless on the bundle.
  expect((ServerDraftStore as unknown as jest.Mock).mock.calls.at(-1)[0].definitionPin).toMatchObject({ definitionSha256: mockDefinitionSha256 });
  expect(mockDefinitionCache.get).toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("does not create a draft when a served definition resolves after unmount", async () => {
  const pending = deferred<Awaited<ReturnType<typeof mockDefinitionCache.get>>>();
  mockParams = { projectId: "P", siteId: "S" };
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [{ project_id: "P", site_id: "S", web_intake_mode: "direct" }] });
  mockDefinitionCache.get.mockReturnValue(pending.promise);
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<InterviewScreen />); });
  expect(mockDefinitionCache.get).toHaveBeenCalledTimes(1);

  await act(async () => tree.unmount());
  await act(async () => {
    pending.resolve({
      identity: { accountId: "u1", projectId: "P", instrumentCode: "WHO_2022_VA", composedVersion: "server-v1", sha256: mockDefinitionSha256 },
      etag: null,
      engineVersion: 1,
      rawJson: "{}",
      definition: { id: "WHO_2022_VA", version: "server-v1", engineVersion: 1, extensions: [], sections: [], questions: [] },
    });
    await Promise.resolve();
  });

  expect(startDraft).not.toHaveBeenCalled();
  expect(mockMarkServed).not.toHaveBeenCalled();
});

describe("leave guard of an open interview", () => {
  const backButton = (tree: ReturnType<typeof create>) =>
    tree.root.findAll((node) => String(node.type) === "mock-button" && node.props.label === t("backToCollection"))[0];
  async function openEdited(edit = true) {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<InterviewScreen />); });
    const form = tree.root.findByType(WhoVaForm);
    const saveDraft = jest.fn(async () => { form.props.onDraftSaved(); });
    await act(async () => { form.props.onDraftController({draftId: "draft-1", saveDraft}); });
    if (edit) await act(async () => { form.props.onChange(); });
    return {tree, form, saveDraft};
  }
  afterEach(() => stayOnPage());

  it("saves the typed answers to the server before a session reset reloads the draft", async () => {
    const {tree, saveDraft} = await openEdited();
    const order: string[] = [];
    saveDraft.mockImplementation(async () => { order.push("save"); });
    mockServerFlush.mockImplementation(async () => { order.push("flush"); });
    const loadDraft = (getDraft as jest.Mock).getMockImplementation()!;
    (getDraft as jest.Mock).mockImplementation(async (...args: unknown[]) => { order.push("load"); return loadDraft(...args); });
    // A re-read whose access really changed hands the screen a new bootstrap object for the same account.
    mockCurrentBootstrap = {...mockBootstrap, access: {...mockBootstrap.access}};
    await act(async () => { tree.update(<InterviewScreen />); });
    expect(order.slice(0, 3)).toEqual(["save", "flush", "load"]);
    await act(async () => tree.unmount());
  });

  it("does not write the open draft under another account's session", async () => {
    const {tree, saveDraft} = await openEdited();
    saveDraft.mockClear();
    mockServerFlush.mockClear();
    mockCurrentBootstrap = {...mockBootstrap, user: {user_id: "u2", name: "Other"}};
    await act(async () => { tree.update(<InterviewScreen />); });
    expect(saveDraft).not.toHaveBeenCalled();
    expect(mockServerFlush).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("keeps Back to collection above the form with no second Save: answers autosave", async () => {
    const {tree} = await openEdited(false);
    expect(backButton(tree)).toBeDefined();
    const labels = tree.root.findAll((node) => String(node.type) === "mock-button").map((node) => node.props.label);
    expect(labels).toContain(t("backToCollection"));
    expect(labels).not.toContain(t("save"));
    await act(async () => tree.unmount());
  });

  it("returns a pristine draft to collection without requiring router history", async () => {
    const {tree} = await openEdited(false);
    await act(async () => { backButton(tree).props.onPress(); });
    expect(leaveDialogOpen()).toBe(false);
    expect(mockRouter.replace).toHaveBeenCalledWith("/collection");
    expect(mockRouter.back).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("asks before leaving an edited draft; Stay keeps the user, Leave without saving goes back", async () => {
    const {tree, saveDraft} = await openEdited();
    await act(async () => { backButton(tree).props.onPress(); });
    expect(leaveDialogOpen()).toBe(true);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    await act(async () => { stayOnPage(); });
    expect(leaveDialogOpen()).toBe(false);
    expect(mockRouter.replace).not.toHaveBeenCalled();
    await act(async () => { backButton(tree).props.onPress(); });
    await act(async () => { leavePage(); });
    expect(mockRouter.replace).toHaveBeenCalledWith("/collection");
    expect(saveDraft).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("returns a direct training form link to the training interview list", async () => {
    mockCurrentBootstrap = {
      ...mockBootstrap,
      access: { ...mockBootstrap.access, training: { project_id: "P" } },
    } as typeof mockBootstrap;
    const {tree} = await openEdited(false);
    expect(backButton(tree)).toBeDefined();
    await act(async () => { backButton(tree).props.onPress(); });
    expect(mockRouter.replace).toHaveBeenCalledWith("/training/interview");
    expect(mockRouter.back).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("Save and leave saves the form and the server write, then leaves", async () => {
    const {tree, saveDraft} = await openEdited();
    const leave = jest.fn();
    guardedNavigate(leave);
    expect(leave).not.toHaveBeenCalled();
    await act(async () => { expect(await saveAndLeave()).toBe(true); });
    expect(saveDraft).toHaveBeenCalledTimes(1);
    expect(mockServerFlush).toHaveBeenCalled();
    expect(leave).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("a failed save keeps the user on the interview and shows the error", async () => {
    const {tree} = await openEdited();
    mockServerFlush.mockRejectedValueOnce(new Error("save failed"));
    const leave = jest.fn();
    guardedNavigate(leave);
    await act(async () => { expect(await saveAndLeave()).toBe(false); });
    expect(leave).not.toHaveBeenCalled();
    expect(leaveDialogOpen()).toBe(false);
    expect(JSON.stringify(tree.toJSON())).toContain("save failed");
    await act(async () => tree.unmount());
  });

  it("holds router back and the tab close while edited, and unregisters on unmount", async () => {
    const {tree} = await openEdited();
    const preventDefault = jest.fn();
    mockBeforeRemove!({preventDefault, data: {action: {type: "GO_BACK"}}});
    expect(preventDefault).toHaveBeenCalled();
    expect(leaveDialogOpen()).toBe(true);
    await act(async () => { leavePage(); });
    expect(mockNavigation.dispatch).toHaveBeenCalledWith({type: "GO_BACK"});
    const unload = (window.addEventListener as jest.Mock).mock.calls.filter(([name]) => name === "beforeunload").map(([, handler]) => handler);
    expect(unload.length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
    const leave = jest.fn();
    guardedNavigate(leave);
    expect(leave).toHaveBeenCalledTimes(1);
    expect(leaveDialogOpen()).toBe(false);
  });

  it("asks on tab close or reload while edited, not once saved", async () => {
    const {tree, form} = await openEdited();
    const handlers = (window.addEventListener as jest.Mock).mock.calls.filter(([name]) => name === "beforeunload").map(([, handler]) => handler);
    const unloadEvent = () => ({preventDefault: jest.fn(), returnValue: undefined as unknown});
    const edited = unloadEvent();
    handlers.forEach((handler) => handler(edited));
    expect(edited.preventDefault).toHaveBeenCalled();
    await act(async () => { form.props.onDraftSaved(); });
    const saved = unloadEvent();
    handlers.forEach((handler) => handler(saved));
    expect(saved.preventDefault).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("a save of older answers settling late keeps newer answers pending; the save of the latest ones clears it", async () => {
    const {tree, form} = await openEdited(false);
    const older = {Id10007: "a"};
    const newer = {Id10007: "ab"};
    await act(async () => { form.props.onChange(older); form.props.onChange(newer); });
    await act(async () => { form.props.onDraftSaved({data: older}); });
    const leave = jest.fn();
    guardedNavigate(leave);
    expect(leaveDialogOpen()).toBe(true);
    expect(leaveSaveFailed()).toBe(false);
    await act(async () => { stayOnPage(); });
    await act(async () => { form.props.onDraftSaved({data: newer}); });
    guardedNavigate(leave);
    expect(leave).toHaveBeenCalledTimes(1);
    expect(leaveDialogOpen()).toBe(false);
    await act(async () => tree.unmount());
  });

  it("reports a failed autosave to the leave dialog until a later save succeeds", async () => {
    const {tree, form} = await openEdited(false);
    const answers = {Id10007: "a"};
    await act(async () => { form.props.onChange(answers); });
    expect(leaveSaveFailed()).toBe(false);
    await act(async () => { form.props.onDraftError(new Error("offline")); });
    expect(leaveSaveFailed()).toBe(true);
    guardedNavigate(jest.fn());
    expect(leaveDialogOpen()).toBe(true);
    await act(async () => { stayOnPage(); });
    await act(async () => { form.props.onDraftSaved({data: answers}); });
    expect(leaveSaveFailed()).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe("pinned case strip", () => {
  it("renders the header bar as the scroller's first, non-sticky row", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<InterviewScreen />); });
    expect(mockShellProps.lead).toBeDefined();
    expect(mockShellProps.lead!.type).toBe(AppHeaderBar);
    expect(mockShellProps.lead!.props.sticky).toBe(false);
    await act(async () => tree.unmount());
  });

  it("spans the phone viewport like the footer", () => {
    expect(INTERVIEW_FORM_CSS).toMatch(/@media \(max-width: 767px\)[\s\S]*#digitva-interview-case-strip \{\s*width: 100vw;\s*margin-inline: calc\(50% - 50vw\);/);
  });
});

const mockPinlessEnvelope = {id: "draft-1", schemaVersion: 1, formVersion: "2022", instrumentId: "va_who_2022", instrumentVersion: "2026081401", currentSection: "s1", createdAt: "2026-10-04T10:00:00+05:30", updatedAt: "2026-10-04T11:00:00+05:30", locale: "en", data: {Id10007: "kept", gone_question: "kept"}};

it("opens a pinless draft from an earlier build on the current served form with a notice and pins it", async () => {
  mockDefinitionCache.get.mockImplementation(async (identity) => ({
    identity, etag: null, engineVersion: 1, rawJson: "{}",
    definition: {id: "WHO_2022_VA", version: identity.composedVersion, engineVersion: 1, extensions: [], sections: [], questions: []},
  }));
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P", updated_at: "revision-1"}, envelope: mockPinlessEnvelope, prefill: {}});
  (getProjectFormOptions as jest.Mock).mockResolvedValue({instrument_version: "2026081401-503d5dd1bb", definition_sha256: mockDefinitionSha256, enabled_extensions: ["geography"], narration_languages: [{code: "en", label: "English"}], form_types: [{instrument_code: "WHO_2022_VA", is_default: true}], available_locales: [{code: "en", label: "English"}], translation_versions: {}});
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  expect(JSON.stringify(tree.toJSON())).toContain(t("formDefinitionAdopted"));
  const options = (ServerDraftStore as unknown as jest.Mock).mock.calls.at(-1)[0];
  expect(options.definitionPin).toMatchObject({instrumentVersion: "2026081401-503d5dd1bb", definitionSha256: mockDefinitionSha256});
  expect(mockMarkServed).toHaveBeenCalledWith("P");
  await act(async () => tree.unmount());
});

it("names an unavailable current form instead of a server error when a pinless draft cannot open", async () => {
  mockHasServed.mockReturnValue(true);
  (getDraft as jest.Mock).mockResolvedValue({draft: {project_id: "P", updated_at: "revision-1"}, envelope: mockPinlessEnvelope, prefill: {}});
  (getProjectFormOptions as jest.Mock).mockResolvedValue({instrument_version: null, definition_sha256: null, enabled_extensions: ["geography"], narration_languages: [{code: "en", label: "English"}], form_types: [{instrument_code: "WHO_2022_VA", is_default: true}], available_locales: [{code: "en", label: "English"}], translation_versions: {}});
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
  const text = JSON.stringify(tree.toJSON());
  expect(text).toContain(t("formDefinitionCurrentUnavailable"));
  expect(text).not.toContain(t("formDefinitionAdopted"));
  await act(async () => tree.unmount());
});

it("does not show the form-change notice for a draft on its own pinned form", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => {tree = create(<InterviewScreen />);});
  expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
  expect(JSON.stringify(tree.toJSON())).not.toContain(t("formDefinitionAdopted"));
  await act(async () => tree.unmount());
});

// ── respondent consent before a web interview (digitva-athy) ─────────────────

describe("respondent consent before the interview", () => {
  const consentConfig = {project_id: "P", consent_required: true, notice_versions: []};

  it("shows the consent screen instead of the form until a decision is recorded", async () => {
    mockGetDraftConsent.mockResolvedValue({consent_required: true, decision: null, covered_fields: [], client_draft_id: null});
    mockFetchConsentConfig.mockResolvedValue(consentConfig);
    mockPostDraftConsent.mockResolvedValue({consent_required: true, decision: "granted", covered_fields: ["Id10007"], client_draft_id: null});
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<InterviewScreen />); });
    expect(mockGetDraftConsent).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", mockBootstrap.csrf);
    expect(mockFetchConsentConfig).toHaveBeenCalledWith("P", mockBootstrap.csrf);
    expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(0);
    const panel = tree.root.findByType("mock-consent-panel" as unknown as React.ElementType);
    // The notice opens in the questionnaire's language.
    expect(panel.props.language).toBe("hi");
    const envelope = {client_id: "c1", decision: "granted"};
    await act(async () => { await panel.props.onDecision(envelope); });
    expect(mockPostDraftConsent).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", envelope, mockBootstrap.csrf);
    expect(tree.root.findAllByType("mock-consent-panel" as unknown as React.ElementType)).toHaveLength(0);
    expect(tree.root.findByType(WhoVaForm).props.lockedQuestionNames ?? []).not.toContain("Id10007");
    await act(async () => tree.unmount());
  });

  it("opens the form at once when consent is not required or already on file", async () => {
    for (const status of [
      {consent_required: false, decision: null, covered_fields: [], client_draft_id: null},
      {consent_required: true, decision: "granted", covered_fields: ["Id10007"], client_draft_id: null},
    ]) {
      mockGetDraftConsent.mockResolvedValue(status);
      mockFetchConsentConfig.mockClear();
      let tree!: ReturnType<typeof create>;
      await act(async () => { tree = create(<InterviewScreen />); });
      expect(tree.root.findAllByType("mock-consent-panel" as unknown as React.ElementType)).toHaveLength(0);
      expect(tree.root.findAllByType(WhoVaForm)).toHaveLength(1);
      expect(mockFetchConsentConfig).not.toHaveBeenCalled();
      await act(async () => tree.unmount());
    }
  });

  it("after a refusal, locks the covered questions and never submits their answers", async () => {
    mockGetDraftConsent.mockResolvedValue({consent_required: true, decision: null, covered_fields: [], client_draft_id: null});
    mockFetchConsentConfig.mockResolvedValue(consentConfig);
    mockPostDraftConsent.mockResolvedValue({consent_required: true, decision: "refused", covered_fields: ["Id10007", "Id10061"], client_draft_id: null});
    (submitDraft as jest.Mock).mockResolvedValue({ va_sid: "sid-1", draft: { draft_id: "draft-1", project_id: "P", site_id: "S" }, superseded: false, validation_err: [] });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<InterviewScreen />); });
    const panel = tree.root.findByType("mock-consent-panel" as unknown as React.ElementType);
    await act(async () => { await panel.props.onDecision({client_id: "c2", decision: "refused"}); });
    const form = tree.root.findByType(WhoVaForm);
    expect(form.props.lockedQuestionNames).toEqual(expect.arrayContaining(["Id10007", "Id10061"]));
    expect(tree.root.findByProps({testID: "consent-refused-note"})).toBeDefined();
    await act(async () => { await form.props.onComplete({ valid: true, issues: [], data: { Id10013: "yes", Id10007: "Ram", interview_outcome: "completed" } }); });
    expect(submitDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", "draft-1", { valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "completed" } }, mockBootstrap.csrf, "revision-1");
    await act(async () => tree.unmount());
  });
});
