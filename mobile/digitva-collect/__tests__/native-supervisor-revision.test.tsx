/*
 * Pins the supervisor "Edit interview" screen (src/nativeRoutes/supervisorRevision.tsx) and the revision helpers it
 * borrows from ./revision (configForRevision, isPrefill, normalizeEnvelope, resolveRevisionInstrument), on their
 * present behaviour, so a move-only refactor of revision.tsx (r8nh.26) can be checked against them.
 * Boundaries mocked: the bearer requester (auth), sync, the device DB and the definition resolver; the screen,
 * src/supervision/interviewRevision, src/revisions' validateDetail, RevisionMemoryStore and the snapshot are real.
 */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockRouter = { back: jest.fn(), replace: jest.fn(), push: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
let mockParams: Record<string, string> = { userId: "sup", draftId: "dr-1", vaSid: "VA1", projectId: "P1", siteId: "S1" };
let mockOffline = false;
const mockReload = jest.fn(async () => undefined);
const mockChooseUiLocale = jest.fn(async (..._args: unknown[]) => undefined);
const mockAccounts = [{ user_id: "sup", name: "Supervisor" }];
const mockDb = {};
let mockClock = 0;
const mockRemoveListeners: Array<(event: { data: { action: { type: string } }; preventDefault: () => void }) => void> = [];
let mockFormProps: Record<string, any> = {};
let mockTopBar: Record<string, any> = {};
let mockConfirm: Record<string, any> | undefined;
const mockToast = jest.fn();
const mockSaveDraft = jest.fn(async () => undefined);
const mockAuthedRequest = jest.fn();
const mockAuthedRaw = jest.fn(async (..._args: unknown[]) => ({ status: 200, headers: {}, body: "{}" }));
const mockFetchOptions = jest.fn();
const mockTranslations = jest.fn(async (..._args: unknown[]) => null);
const mockResolve = jest.fn();

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    digestStringAsync: async (_a: string, value: string) => createHash("sha256").update(value, "utf8").digest("hex"),
  };
});
jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  useNavigation: () => ({
    addListener: (_n: string, cb: (typeof mockRemoveListeners)[number]) => { mockRemoveListeners.push(cb); return () => undefined; },
    dispatch: jest.fn(),
  }),
  Redirect: () => null,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ accounts: mockAccounts, offline: mockOffline, chooseUiLocale: mockChooseUiLocale, reload: mockReload, holdRefresh: undefined }),
}));
jest.mock("../src/auth", () => ({
  authedRequest: (...args: unknown[]) => mockAuthedRequest(...args),
  authedRawRequest: (...args: unknown[]) => mockAuthedRaw(...args),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
}));
jest.mock("../src/interviewerDb", () => ({ openInterviewerDb: jest.fn(async () => mockDb), isUnlocked: () => true }));
jest.mock("../src/formDefinitionCache", () => ({ createNativeDefinitionCache: jest.fn(() => ({ initialize: jest.fn(async () => undefined) })) }));
jest.mock("../src/formDefinitionRuntime", () => ({
  ...jest.requireActual("../src/formDefinitionRuntime"),
  resolveSavedEnvelopeDefinition: (...args: unknown[]) => mockResolve(...args),
}));
jest.mock("../src/sync", () => ({
  fetchProjectFormOptions: (...args: unknown[]) => mockFetchOptions(...args),
  translationsForDraft: (...args: unknown[]) => mockTranslations(...args),
  markProjectDefinitionServed: jest.fn(async () => undefined),
}));
jest.mock("../src/phoneClock", () => ({ ...jest.requireActual("../src/phoneClock"), clockOffsetField: () => ({ clockOffsetSeconds: 7 }) }));
jest.mock("../src/client/localDateTime", () => ({ localDateTimeWithOffset: () => `2026-11-01T10:00:${String(++mockClock).padStart(2, "0")}+05:30` }));
jest.mock("../src/i18n", () => ({ ...jest.requireActual("../src/i18n"), t: (key: string) => key }));
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: () => ({ fromPrefill: "p", Id10013: "from-prefill" }) }));
jest.mock("../src/translations", () => ({
  applyTranslations: (instrument: unknown, translations: unknown, locale: string) => ({ ...(instrument as object), appliedLocale: locale, hadTranslations: translations !== null }),
}));
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("../src/whoWebTheme", () => ({ useWhoFormTheme: () => ({}) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 1, bottom: 2, left: 0, right: 0 }) }));
jest.mock("../src/ConfirmDialog", () => ({
  ConfirmDialog: (props: Record<string, unknown>) => {
    mockConfirm = props;
    return null;
  },
}));
jest.mock("../src/FormTopBar", () => ({
  FormTopBar: (props: Record<string, unknown>) => {
    mockTopBar = props;
    return null;
  },
}));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => R.createElement("button", { "data-label": label, onClick: onPress }, label),
    Notice: ({ children }: { children: ReactNode }) => R.createElement("aside", null, children),
    Screen: ({ children, variant, title }: { children: ReactNode; variant?: string; title?: string }) => R.createElement("main", { "data-variant": variant, title }, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
  };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({
  WhoVaForm: (props: Record<string, any>) => {
    mockFormProps = props;
    const R = jest.requireActual("react") as typeof React;
    R.useEffect(() => {
      props.onDraftController?.({ saveDraft: mockSaveDraft, showProblems: jest.fn(), openPreview: jest.fn() });
      props.onReady?.({ validate: () => ({ valid: false, issues: [{ code: "x" }] }) });
    }, []);
    return R.createElement("section", { "data-form": true });
  },
}), { virtual: true });

import SupervisorRevision from "../src/nativeRoutes/supervisorRevision";
import { configForRevision, isPrefill, normalizeEnvelope } from "../src/nativeRoutes/revision";
import { SessionRevokedError } from "../src/auth";
import { ApiError } from "../src/api";
import { WHO_VA_FORM_VERSION } from "@drguptavivek/who-2022-va";

const { createHash } = require("node:crypto") as typeof import("node:crypto");
const instrument = { id: "WHO_2022_VA", version: "v-served", sections: [{ name: "first_section" }, { name: "second" }], questions: [] };
const optionsBody: Record<string, unknown> = {
  web_intake_mode: "direct",
  default_locale: "en",
  available_locales: [{ code: "en", label: "English" }, { code: "hi", label: "Hindi" }],
  narration_languages: [{ code: "en", label: "English" }],
  form_types: [{ instrument_code: "OTHER_FORM" }, { instrument_code: "DEFAULT_FORM", is_default: true }],
  translation_versions: { en: 4, hi: 9 },
};
const STARTED = "2026-10-01T10:00:00.000Z";
function detailBody(over: { envelope?: Record<string, unknown>; draft?: Record<string, unknown>; prefill?: unknown } = {}) {
  return {
    draft: { draft_id: "dr-1", va_sid: "VA1", project_id: "P1", site_id: "S1", death_id: "D1", status: "submitted", ...over.draft },
    envelope: {
      id: "dr-1", schemaVersion: 1, formVersion: WHO_VA_FORM_VERSION, instrumentId: "WHO_2022_VA", instrumentVersion: "", currentSection: "",
      createdAt: "2026-10-01T09:00:00.000Z", updatedAt: "2026-10-02T09:00:00.000Z", startedAt: STARTED,
      data: { Id10013: "yes", interview_outcome: "completed", age: "40" }, ...over.envelope,
    },
    prefill: over.prefill ?? { deceased: { givenNames: "Asha", surname: "Rao" } },
    answers_sha256: null,
  };
}
let mockDetail: () => unknown;
let posted: Array<{ path: string; options: Record<string, any>; body?: any }>;
let ack: (body: any) => unknown;

beforeEach(() => {
  jest.clearAllMocks();
  mockClock = 0;
  mockOffline = false;
  mockParams = { userId: "sup", draftId: "dr-1", vaSid: "VA1", projectId: "P1", siteId: "S1" };
  mockFormProps = {};
  mockTopBar = {};
  mockConfirm = undefined;
  mockRemoveListeners.length = 0;
  mockDetail = () => detailBody();
  posted = [];
  ack = (body) => ({ changed: true, va_sid: "VA1", answers_sha256: body.answers_sha256 });
  mockAuthedRequest.mockReset();
  mockAuthedRequest.mockImplementation(async (_user: string, path: string, options: Record<string, any>) => {
    const body = options.bodyFactory?.();
    posted.push({ path, options, body });
    if (options.method === "POST") return { body: ack(body) };
    return { body: mockDetail() };
  });
  mockFetchOptions.mockImplementation(async () => optionsBody);
  mockSaveDraft.mockImplementation(async () => undefined);
  mockResolve.mockImplementation(async () => ({ instrument, provenance: "bundled-original", pin: null }));
});

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
async function mount() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<SupervisorRevision />); });
  await settle();
  await settle();
  return tree;
}
const dump = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());
const store = () => mockFormProps.draftStore as { load(id: string): any; save(d: unknown): void };
/** The supervisor changes an answer: the form's autosave lands in the store when saveDraft runs. */
const editAnswer = (patch: Record<string, unknown>) => mockSaveDraft.mockImplementation(async () => {
  store().save({ ...store().load("dr-1"), data: { ...store().load("dr-1").data, ...patch } });
});
const complete = (result: { valid: boolean; issues?: unknown[] }) => act(async () => { mockFormProps.onComplete({ issues: [], ...result }); });
const sha = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
const sends = () => posted.filter((call) => call.options.method === "POST");

describe("supervisor revision: opening", () => {
  it("reads the draft with the bearer requester under the draft's project, then the live project options", async () => {
    await mount();
    expect(posted[0].path).toBe("/api/v1/intake/drafts/dr-1");
    expect(posted[0].options).toMatchObject({ projectId: "P1" });
    expect(posted[0].options.method).toBeUndefined();
    expect(mockAuthedRequest.mock.calls[0][0]).toBe("sup");
    expect(mockFetchOptions).toHaveBeenCalledWith("sup", "P1");
  });

  it("waits offline without any request, shows the connection notice, and loads once online", async () => {
    mockOffline = true;
    const tree = await mount();
    expect(mockAuthedRequest).not.toHaveBeenCalled();
    expect(dump(tree)).toContain("supervisionNeedsConnection");
    mockOffline = false;
    await act(async () => tree.update(<SupervisorRevision />));
    await settle();
    await settle();
    expect(mockAuthedRequest).toHaveBeenCalledTimes(1);
    expect(mockFormProps.draftId).toBe("dr-1");
  });

  it("hands the form the normalized envelope: pinned form ids, first section, saved answers over the prefill", async () => {
    await mount();
    const loaded = store().load("dr-1");
    expect(loaded).toMatchObject({
      formVersion: WHO_VA_FORM_VERSION, instrumentId: "WHO_2022_VA", instrumentVersion: "v-served", currentSection: "first_section", startedAt: STARTED,
    });
    // initialDataFromPrefill first, then the envelope's own answers win.
    expect(loaded.data).toEqual({ fromPrefill: "p", Id10013: "yes", interview_outcome: "completed", age: "40" });
    expect(mockFormProps).toMatchObject({ locale: "en", showEnglish: false, autoSaveDraftOnChange: true, compactFooter: true, safeInsets: { top: 1, bottom: 2 } });
    expect(mockFormProps.instrument).toMatchObject({ id: "WHO_2022_VA", appliedLocale: "en", hadTranslations: false });
    expect(mockTopBar).toMatchObject({ title: "Asha Rao", label: "supervisionEditInterview", saveState: "saved" });
    expect(mockTopBar.menuItems.map((item: { key: string }) => item.key)).toEqual(["finish", "preview"]);
  });

  it("resolves the instrument for the account and project, asking the server with the project header", async () => {
    await mount();
    const args = mockResolve.mock.calls[0][0];
    expect(args).toMatchObject({
      accountId: "sup", projectId: "P1", narrationLanguageCodes: ["en"],
      envelope: expect.objectContaining({ id: "dr-1", instrumentId: "WHO_2022_VA" }),
    });
    await args.request("/definition", { ifNoneMatch: "etag" });
    expect(mockAuthedRaw).toHaveBeenCalledWith("sup", "/definition", { ifNoneMatch: "etag", acceptGzip: true, projectId: "P1" });
  });

  it("takes locale and translation version from the saved envelope, the instrument code from the default form type", async () => {
    mockDetail = () => detailBody({ envelope: { locale: "hi", translation_version: 3 } });
    await mount();
    expect(mockTranslations).toHaveBeenCalledWith("sup", mockDb, "P1", "DEFAULT_FORM", "hi", 3, 9);
    expect(mockChooseUiLocale).toHaveBeenCalledWith("hi");
    expect(mockFormProps).toMatchObject({ locale: "hi", showEnglish: true });
    expect(mockFormProps.instrument).toMatchObject({ appliedLocale: "hi" });
  });

  it("falls back to the project's default locale and its translation version when the envelope has none", async () => {
    await mount();
    expect(mockTranslations).toHaveBeenCalledWith("sup", mockDb, "P1", "DEFAULT_FORM", "en", 4, 4);
  });

  it("shows a refused row's message and no form, and Refresh reads the draft again", async () => {
    mockDetail = () => detailBody({ envelope: { definitionSha256: "bad", definitionExtensions: [] } });
    const tree = await mount();
    expect(dump(tree)).toContain("revisionPinInvalid");
    expect(mockFormProps.draftId).toBeUndefined();
    expect(mockFetchOptions).not.toHaveBeenCalled();
    mockDetail = () => detailBody();
    await act(async () => tree.root.findByProps({ "data-label": "refresh" }).props.onClick());
    await settle();
    await settle();
    expect(mockAuthedRequest).toHaveBeenCalledTimes(2);
    expect(mockFormProps.draftId).toBe("dr-1");
  });

  it.each([
    ["a prefill with a malformed part", { prefill: { interviewer: "text" } }],
    ["an envelope from another form version", { envelope: { formVersion: "other-form-version" } }],
    ["an envelope for another instrument id", { envelope: { instrumentId: "OTHER" } }],
    ["an envelope for another instrument version", { envelope: { instrumentVersion: "v-old" } }],
  ])("refuses %s with the retry text and no form", async (_name, over) => {
    mockDetail = () => detailBody(over as never);
    const tree = await mount();
    expect(dump(tree)).toContain("revisionRetry");
    expect(mockFormProps.draftId).toBeUndefined();
  });

  it("refuses a body about another draft with the retry text", async () => {
    mockDetail = () => detailBody({ draft: { draft_id: "other" } });
    expect(dump(await mount())).toContain("revisionRetry");
  });

  it("words a 404 as unavailable", async () => {
    mockAuthedRequest.mockReset();
    mockAuthedRequest.mockRejectedValue(new ApiError(404, "not_found"));
    expect(dump(await mount())).toContain("revisionUnavailable");
  });

  it("leaves for the accounts list when the session is revoked", async () => {
    mockAuthedRequest.mockReset();
    mockAuthedRequest.mockRejectedValue(new SessionRevokedError());
    await mount();
    expect(mockReload).toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
  });
});

describe("supervisor revision: saving", () => {
  it("sends one POST to the submission's revisions with the supervisor_correction reason, the frozen answers and the draft pin", async () => {
    mockDetail = () => detailBody({ envelope: { definitionSha256: "b".repeat(64), definitionExtensions: ["mobility"], instrumentVersion: "v-served" } });
    await mount();
    editAnswer({ age: "41" });
    await complete({ valid: true });
    expect(sends()).toHaveLength(1);
    const { path, options, body } = sends()[0];
    expect(path).toBe("/api/v1/intake/submissions/VA1/revisions");
    expect(options).toMatchObject({ method: "POST", projectId: "P1", timeoutMs: 120_000 });
    expect(JSON.parse(body.answers_json)).toEqual({ fromPrefill: "p", Id10013: "yes", interview_outcome: "completed", age: "41" });
    expect(body).toMatchObject({
      reason_code: "supervisor_correction",
      answers_sha256: sha(body.answers_json),
      completion: { valid: true, issues: [] },
      draft: {
        startedAt: STARTED, instrumentVersion: "v-served", definitionSha256: "b".repeat(64), definitionExtensions: ["mobility"],
        clockOffsetSeconds: 7,
      },
    });
    expect(typeof body.draft.completedAt).toBe("string");
    expect(typeof body.draft.deviceClockAt).toBe("string");
    expect(Object.keys(body).sort()).toEqual(["answers_json", "answers_sha256", "completion", "draft", "reason_code"]);
    expect(mockSaveDraft).toHaveBeenCalled();
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    expect(mockToast).not.toHaveBeenCalled();
  });

  it("refuses a valid form with no consent answer, and an invalid one without a partial outcome, before any request", async () => {
    mockDetail = () => detailBody({ envelope: { data: { age: "40" } } });
    await mount();
    // The prefill's consent would otherwise fill the gap: blank it in the store.
    store().save({ ...store().load("dr-1"), data: { age: "40" } });
    await complete({ valid: true });
    expect(mockToast).toHaveBeenLastCalledWith({ kind: "error", text: "revisionConsentRequired" });
    await complete({ valid: false, issues: [{ code: "x" }] });
    expect(mockToast).toHaveBeenLastCalledWith({ kind: "error", text: "serverValidation" });
    expect(sends()).toHaveLength(0);
    expect(mockRouter.back).not.toHaveBeenCalled();
  });

  it("sends an incomplete form that names a partial outcome, with its issues", async () => {
    mockDetail = () => detailBody({ envelope: { data: { Id10013: "yes", interview_outcome: "partially_completed" } } });
    await mount();
    await complete({ valid: false, issues: [{ code: "x" }] });
    expect(sends()[0].body.completion).toEqual({ valid: false, issues: [{ code: "x" }] });
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
  });

  it("will not send offline, and tells the supervisor so", async () => {
    const tree = await mount();
    mockOffline = true;
    await act(async () => tree.update(<SupervisorRevision />));
    await complete({ valid: true });
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "supervisionNeedsConnection" });
    expect(sends()).toHaveLength(0);
  });

  it("retries a network failure with the identical frozen snapshot; only the clock stamp is fresh", async () => {
    await mount();
    mockAuthedRequest.mockImplementation(async (_u: string, path: string, options: Record<string, any>) => {
      const body = options.bodyFactory?.();
      posted.push({ path, options, body });
      if (options.method === "POST" && sends().length === 1) throw new Error("network");
      return { body: options.method === "POST" ? ack(body) : mockDetail() };
    });
    await complete({ valid: true });
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: expect.stringContaining("revisionRetry") });
    expect(mockRouter.back).not.toHaveBeenCalled();
    await complete({ valid: true });
    const [a, b] = sends().map((call) => call.body);
    expect(sends()).toHaveLength(2);
    expect(b.answers_json).toBe(a.answers_json);
    expect(b.answers_sha256).toBe(a.answers_sha256);
    expect(b.draft.completedAt).toBe(a.draft.completedAt);
    expect(b.draft.deviceClockAt).not.toBe(a.draft.deviceClockAt);
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
  });

  it("freezes a new snapshot after the server decides, and words a 422 as a validation failure", async () => {
    await mount();
    mockAuthedRequest.mockImplementation(async (_u: string, path: string, options: Record<string, any>) => {
      const body = options.bodyFactory?.();
      posted.push({ path, options, body });
      if (options.method === "POST") throw new ApiError(422, "invalid");
      return { body: mockDetail() };
    });
    await complete({ valid: true });
    expect(mockToast).toHaveBeenLastCalledWith({ kind: "error", text: "serverValidation" });
    await complete({ valid: true });
    const [a, b] = sends().map((call) => call.body.draft.completedAt);
    expect(a).not.toBe(b);
    expect(mockRouter.back).not.toHaveBeenCalled();
  });

  it("treats an acknowledgement for other answers as malformed and stays on the form", async () => {
    await mount();
    ack = () => ({ changed: true, va_sid: "VA1", answers_sha256: "0".repeat(64) });
    await complete({ valid: true });
    expect(mockToast).toHaveBeenLastCalledWith({ kind: "error", text: expect.stringContaining("revisionRetry") });
    expect(mockRouter.back).not.toHaveBeenCalled();
  });

  it("leaves for the accounts list when the session is revoked during the send", async () => {
    await mount();
    mockAuthedRequest.mockReset();
    mockAuthedRequest.mockImplementation(async () => { throw new SessionRevokedError(); });
    await complete({ valid: true });
    expect(mockReload).toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
    expect(mockToast).not.toHaveBeenCalled();
  });

  it("Finish incomplete asks first, then validates the form and sends what it holds", async () => {
    mockDetail = () => detailBody({ envelope: { data: { Id10013: "yes", interview_outcome: "partially_completed" } } });
    await mount();
    await act(async () => mockTopBar.menuItems.find((item: { key: string }) => item.key === "finish").onPress());
    expect(mockConfirm).toMatchObject({ title: "finishIncompleteTitle", confirmLabel: "finishIncomplete" });
    expect(sends()).toHaveLength(0);
    await act(async () => mockConfirm!.onConfirm());
    await settle();
    expect(sends()).toHaveLength(1);
    expect(sends()[0].body.completion.valid).toBe(false);
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
  });
});

describe("supervisor revision: leaving", () => {
  const hardwareBack = async () => {
    const event = { data: { action: { type: "GO_BACK" } }, preventDefault: jest.fn() };
    await act(async () => { mockRemoveListeners.forEach((listener) => listener(event)); });
    return event;
  };

  it("lets Back go when nothing was edited, and asks first when an answer changed", async () => {
    await mount();
    expect((await hardwareBack()).preventDefault).not.toHaveBeenCalled();
    await act(async () => { store().save({ ...store().load("dr-1"), data: { ...store().load("dr-1").data, age: "99" } }); });
    expect((await hardwareBack()).preventDefault).toHaveBeenCalled();
    expect(mockConfirm).toMatchObject({ title: "supervisionEditLeaveTitle", confirmLabel: "leaveAnyway", cancelLabel: "stay" });
  });
});

describe("helpers shared with the supervisor screen", () => {
  const project = { project_id: "P1", form_options: { default_locale: "en", available_locales: [{ code: "en", label: "English" }], translation_versions: { en: 2 } } } as never;
  const row = (extra: Record<string, unknown> = {}) => ({ envelope: { data: {} }, ...extra }) as never;

  it("isPrefill accepts absent parts and rejects a malformed one", () => {
    expect(isPrefill({})).toBe(true);
    expect(isPrefill({ interviewer: {}, deceased: {}, answers: {}, lockedQuestionNames: ["a"] })).toBe(true);
    expect(isPrefill({ interviewer: "x" })).toBe(false);
    expect(isPrefill({ answers: [] })).toBe(false);
    expect(isPrefill({ lockedQuestionNames: [1] })).toBe(false);
    expect(isPrefill({ lockedQuestionNames: "a" })).toBe(false);
  });

  it("configForRevision prefers the saved config, then the envelope, then the project's defaults", () => {
    expect(configForRevision(row(), project)).toEqual({ projectId: "P1", locale: "en", translationVersion: 2, enabledExtensions: [], instrumentCode: "WHO_2022_VA" });
    expect(configForRevision(row({ config: { projectId: "P1", instrumentCode: "X", enabledExtensions: ["m"], locale: "hi", translationVersion: 5 } }), project))
      .toEqual({ projectId: "P1", locale: "hi", translationVersion: 5, enabledExtensions: ["m"], instrumentCode: "X" });
    expect(configForRevision({ envelope: { data: {}, locale: "en", translation_version: 8 }, config: { translationVersion: 5 } } as never, project).translationVersion).toBe(8);
    expect(() => configForRevision(row({ config: { projectId: "P2" } }), project)).toThrow("revision_project_mismatch");
    expect(() => configForRevision({ envelope: { data: {}, locale: "not a locale" } } as never, project)).toThrow("revision_locale_unavailable");
  });

  it("normalizeEnvelope fills the ids and first section, keeps given ones, and refuses a mismatch", () => {
    const filled = normalizeEnvelope({ data: { a: 1 } } as never, instrument as never);
    expect(filled).toMatchObject({ formVersion: WHO_VA_FORM_VERSION, instrumentId: "WHO_2022_VA", instrumentVersion: "v-served", currentSection: "first_section", data: { a: 1 } });
    expect(normalizeEnvelope({ currentSection: "second" } as never, instrument as never).currentSection).toBe("second");
    expect(normalizeEnvelope({} as never, { ...instrument, sections: [] } as never).currentSection).toBe("_root");
    expect(() => normalizeEnvelope({ instrumentVersion: "v0" } as never, instrument as never)).toThrow("revision_instrument_mismatch");
    expect(() => normalizeEnvelope({ instrumentId: "Z" } as never, instrument as never)).toThrow("revision_instrument_mismatch");
    expect(() => normalizeEnvelope({ formVersion: "Z" } as never, instrument as never)).toThrow("revision_instrument_mismatch");
  });
});
