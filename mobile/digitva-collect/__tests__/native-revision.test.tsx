import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockAccounts = [mockAccount];
const mockDb = {};
const mockRouter = { push: jest.fn(), replace: jest.fn() };
const mockParams: Record<string, string> = {
  userId: "u1",
  draftId: "draft-1",
  projectId: "P1",
};
const mockRow = {
  draft_id: "draft-1",
  project_id: "P1",
  site_id: "S1",
  death_id: null,
  va_sid: "va-1",
  envelope: {
    data: { Id10013: "yes", interview_outcome: "partially_completed" },
    formVersion: "",
    instrumentId: "",
    instrumentVersion: "",
    locale: "en",
  },
  prefill: {},
  config: undefined,
  original_answers_sha256: "hash",
  original_outcome: "partially_completed",
  reason_code: null,
  completion: null,
  frozen_json: null,
  answers_sha256: null,
  state: "editing",
  refusal_code: null,
  updated_at: "2026-10-05T00:00:00Z",
};
const mockProject = {
  project_id: "P1",
  form_options: {
    default_locale: "en",
    available_locales: [{ code: "en", label: "English" }],
    instrument_version: "served-v2",
    definition_sha256: "b".repeat(64),
    enabled_extensions: ["mobility"],
    translation_versions: { en: 1 },
  },
};
let mockLocalRow: unknown = null;
let mockReference: unknown;
let mockFormProps: Record<string, unknown> = {};
let mockLockCallback: (() => Promise<void>) | undefined;
let mockLockVersion = 0;
let mockObservedLockVersion = 0;
const mockSaveDraft = jest.fn(async () => undefined);
const mockQueue = jest.fn(async (..._args: unknown[]) => undefined);
const mockRevisionInstrument = { id: "WHO_2022_VA", version: "served-v2", sections: [], questions: [] };
const mockRevisionDefinition = {
  instrument: mockRevisionInstrument,
  provenance: "served",
  pin: { instrumentVersion: "served-v2", definitionSha256: "b".repeat(64), definitionExtensions: ["mobility"] },
};
const mockReload = jest.fn();
const mockChooseUiLocale = jest.fn(async () => undefined);
const mockActivity = jest.fn();

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => {
    mockObservedLockVersion = mockLockVersion;
    return {
    accounts: mockAccounts,
    activity: mockActivity,
    onBeforeLock: (callback: () => Promise<void>) => {
      mockLockCallback = callback;
      return jest.fn();
    },
    chooseUiLocale: mockChooseUiLocale,
    reload: mockReload,
    lockVersion: mockLockVersion,
    };
  },
}));
jest.mock("../src/api", () => ({ ApiError: class ApiError extends Error { code?: string; status?: number } }));
jest.mock("../src/auth", () => ({
  authedRawRequest: jest.fn(async () => ({ status: 200, headers: {}, body: "{}" })),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
}));
jest.mock("../src/drafts", () => ({ getMeta: jest.fn(async () => undefined) }));
jest.mock("../src/formDefinitionCache", () => ({
  createNativeDefinitionCache: jest.fn(() => ({ initialize: jest.fn(async () => undefined) })),
}));
jest.mock("../src/formDefinitionRuntime", () => ({
  PinnedDefinitionError: class PinnedDefinitionError extends Error { code?: string },
  resolveSavedEnvelopeDefinition: jest.fn(async () => mockRevisionDefinition),
}));
jest.mock("../src/formDefinitions", () => ({
  FormDefinitionError: class FormDefinitionError extends Error { code?: string },
}));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => true,
  openInterviewerDb: jest.fn(async () => mockDb),
}));
jest.mock("../src/revisions", () => ({
  beginRevision: jest.fn(async () => mockRow),
  createRevisionDraftStore: jest.fn(() => ({
    load: jest.fn(async () => mockRow.envelope),
    save: jest.fn(async () => undefined),
    remove: jest.fn(async () => undefined),
  })),
  discardRevision: jest.fn(async () => undefined),
  effectiveRevisionOutcome: (data: Record<string, unknown>, completion: { valid: boolean }) => {
    const consent = typeof data.Id10013 === "string" ? data.Id10013.trim().toLowerCase() : "";
    if (consent === "no") return "refused";
    if (completion.valid && !consent) return null;
    return completion.valid ? "completed" : data.interview_outcome;
  },
  fetchSubmittedRevisions: jest.fn(async () => [{ draft_id: "draft-1", project_id: "P1", site_id: "S1", death_id: null, va_sid: "va-1" }]),
  getRevisionRow: jest.fn(async () => mockLocalRow),
  listLocalRevisions: jest.fn(async () => []),
  queueRevision: (...args: unknown[]) => mockQueue(...args),
  reopenRevision: jest.fn(async () => undefined),
}));
jest.mock("../src/sync", () => ({
  markProjectDefinitionServed: jest.fn(async () => undefined),
  getCachedReferenceData: jest.fn(async () => mockReference),
  isUploadable: jest.fn(() => true),
  translationsForDraft: jest.fn(async () => null),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string) => key,
  questionnaireDefault: (_available: unknown, fallback?: string) => fallback ?? "en",
  UI_LOCALES: [{ code: "en", label: "English" }],
}));
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: () => ({}) }));
jest.mock("../src/translations", () => ({ applyTranslations: (instrument: unknown) => instrument }));
const mockToast = jest.fn();
const mockOpenSheet = jest.fn();
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ openSheet: mockOpenSheet, header: false, tabs: false }) }));
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    Row: ({ children }: { children: ReactNode }) => ReactActual.createElement("div", null, children),
    Screen: ({ children, variant }: { children: ReactNode; variant?: string }) => ReactActual.createElement("main", { "data-variant": variant }, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
  };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({
  WhoVaForm: (props: Record<string, unknown>) => {
    mockFormProps = props;
    const ReactActual = jest.requireActual("react") as typeof React;
    return ReactActual.createElement("section", {
      "data-revision-form": true,
      "data-form-version": (props.instrument as { version?: string } | undefined)?.version,
    });
  },
}), { virtual: true });
jest.mock("@drguptavivek/who-2022-va", () => ({
  createWhoVa2022Instrument: jest.fn(() => ({ id: "WHO_2022_VA", version: "v1", sections: [], questions: [] })),
  WHO_VA_FORM_VERSION: "v1",
}), { virtual: true });

import Revision from "../src/nativeRoutes/revision";
import { fetchSubmittedRevisions, beginRevision, queueRevision, reopenRevision } from "../src/revisions";

/** Opens the single-line reason select and taps the reason's row in the sheet. */
const chooseReason = async (tree: ReturnType<typeof create>, label: string) => {
  const press = (node: { props: Record<string, any> }) => node.props.onPress();
  await act(async () => {
    press(tree.root.findAll((n) => n.props.accessibilityLabel === "revisionReason" && typeof n.props.onPress === "function")[0]);
  });
  await act(async () => {
    press(tree.root.findAll((n) => n.props.accessibilityRole === "menuitem" && typeof n.props.onPress === "function" && n.props.accessibilityLabel === label)[0]);
  });
};

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

beforeEach(() => {
  jest.clearAllMocks();
  mockLocalRow = null;
  mockFormProps = {};
  mockLockCallback = undefined;
  mockLockVersion = 0;
  mockObservedLockVersion = 0;
  mockReference = { projects: [{ project: mockProject }] };
});

describe("native submitted-interview revisions", () => {
  it("checks the authorized cached project before fetching raw revision data", async () => {
    mockReference = { projects: [] };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();

    expect(fetchSubmittedRevisions).not.toHaveBeenCalled();
    expect(beginRevision).not.toHaveBeenCalled();
    expect(JSON.stringify(tree!.toJSON())).toContain("revisionUnavailable");
  });

  it("resumes an existing encrypted revision offline without another detail fetch", async () => {
    mockLocalRow = mockRow;
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(fetchSubmittedRevisions).not.toHaveBeenCalled();
    expect(beginRevision).not.toHaveBeenCalled();
    expect(JSON.stringify(tree!.toJSON())).toContain("data-revision-form");
  });

  it("resolves the saved revision pin and gives that immutable instrument to the form", async () => {
    mockLocalRow = {
      ...mockRow,
      envelope: {
        ...mockRow.envelope,
        instrumentVersion: "served-v2",
        definitionSha256: "b".repeat(64),
        definitionExtensions: ["mobility"],
      },
    };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition)
      .toHaveBeenCalledWith(expect.objectContaining({
        projectId: "P1",
        envelope: expect.objectContaining({ instrumentVersion: "served-v2", definitionSha256: "b".repeat(64) }),
      }));
    expect(mockFormProps.instrument).toEqual(mockRevisionInstrument);
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("still looks up translations for a revision whose saved hash differs from current", async () => {
    mockLocalRow = {
      ...mockRow,
      envelope: {
        ...mockRow.envelope,
        instrumentVersion: "served-v2",
        definitionSha256: "b".repeat(64),
        definitionExtensions: ["mobility"],
      },
    };
    mockProject.form_options.definition_sha256 = "c".repeat(64);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(mockFormProps.instrument).toBe(mockRevisionInstrument);
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenCalled();
    expect(jest.requireMock("../src/drafts").getMeta).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("applies translations by name to an unpinned legacy revision", async () => {
    mockLocalRow = {
      ...mockRow,
      envelope: { instrumentId: "WHO_2022_VA", instrumentVersion: "v1", data: { answer: "old" }, locale: "en" },
    };
    const legacyInstrument = { ...mockRevisionInstrument, version: "v1" };
    (jest.requireMock("../src/formDefinitionRuntime").resolveSavedEnvelopeDefinition as jest.Mock)
      .mockResolvedValueOnce({ instrument: legacyInstrument, provenance: "bundled-original", pin: null });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(mockFormProps.instrument).toEqual(legacyInstrument);
    expect(jest.requireMock("../src/sync").translationsForDraft).toHaveBeenCalled();
    expect(jest.requireMock("../src/drafts").getMeta).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("clears a mounted revision after access changes and blocks its stale store", async () => {
    mockLocalRow = mockRow;
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(tree!.root.findAllByProps({ "data-revision-form": true })).toHaveLength(1);
    const staleStore = mockFormProps.draftStore as { save(draft: unknown): Promise<unknown> };
    const stores = jest.requireMock("../src/revisions").createRevisionDraftStore as jest.Mock;
    const underlyingSave = stores.mock.results[stores.mock.results.length - 1].value.save as jest.Mock;
    let releaseReference!: (value: unknown) => void;
    (jest.requireMock("../src/sync").getCachedReferenceData as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => { releaseReference = resolve; }),
    );

    mockLockVersion += 1;
    await act(async () => { tree!.update(<Revision />); });

    expect(mockObservedLockVersion).toBe(mockLockVersion);
    expect(tree!.root.findAllByProps({ "data-revision-form": true })).toHaveLength(0);
    await expect(staleStore.save({ data: { answer: "must-not-write" } })).rejects.toThrow("revision_access_changed");
    expect(underlyingSave).not.toHaveBeenCalled();
    await act(async () => { releaseReference(mockReference); });
    await settle();
    await settle();
    expect(tree!.root.findAllByProps({ "data-revision-form": true })).toHaveLength(1);
    await act(async () => tree!.unmount());
  });

  it("begins an authorized direct revision without requiring a death id", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(beginRevision).toHaveBeenCalledWith("u1", mockDb, "draft-1");
    expect(JSON.stringify(tree!.toJSON())).toContain("data-revision-form");
  });

  it("manually resumes a retained locked revision and queues its saved answers", async () => {
    const savedAnswers = { Id10013: "yes", interview_outcome: "completed", Id10007: "kept correction" };
    mockLocalRow = {
      ...mockRow,
      state: "attention",
      refusal_code: "revision_locked",
      original_outcome: "completed",
      envelope: { ...mockRow.envelope, data: savedAnswers },
      frozen_json: JSON.stringify(savedAnswers),
      answers_sha256: "a".repeat(64),
    };
    (reopenRevision as jest.Mock).mockImplementation(async () => {
      mockLocalRow = {
        ...(mockLocalRow as typeof mockRow),
        state: "editing",
        refusal_code: null,
        frozen_json: null,
        answers_sha256: null,
      };
    });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();

    expect(JSON.stringify(tree!.toJSON())).toContain("revisionLocked");
    expect(tree!.root.findByProps({ "data-label": "reviseInterview" })).toBeTruthy();
    await act(async () => {
      tree!.root.findByProps({ "data-label": "reviseInterview" }).props.onClick();
    });
    await settle();
    await settle();

    expect(reopenRevision).toHaveBeenCalledWith(mockDb, "draft-1");
    expect(fetchSubmittedRevisions).not.toHaveBeenCalled();
    expect((mockLocalRow as typeof mockRow).envelope.data).toEqual(savedAnswers);
    expect(tree!.root.findAllByProps({ "data-revision-form": true })).toHaveLength(1);
    await act(async () => {
      (mockFormProps.onDraftController as (controller: unknown) => void)({ saveDraft: mockSaveDraft });
    });
    await chooseReason(tree!, "revisionReasonInterviewerCorrection");
    await settle();
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({ valid: true, issues: [], data: savedAnswers });
    });
    await settle();

    expect(mockQueue).toHaveBeenCalledWith(mockDb, "draft-1", "interviewer_correction", { valid: true, issues: [] });
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
  });

  it("flushes the encrypted revision before queueing and requires a reason", async () => {
    const order: string[] = [];
    mockLocalRow = {
      ...mockRow,
      original_outcome: "completed",
      envelope: { ...mockRow.envelope, data: { Id10013: "yes", interview_outcome: "completed" } },
    };
    mockSaveDraft.mockImplementation(async () => { order.push("flush"); });
    mockQueue.mockImplementation(async () => { order.push("queue"); return undefined; });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    const completion = { valid: true, issues: [] };
    await act(async () => {
      (mockFormProps.onDraftController as (controller: unknown) => void)({ saveDraft: mockSaveDraft });
      (mockFormProps.onComplete as (result: unknown) => void)({ ...completion, data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    });
    expect(mockQueue).not.toHaveBeenCalled();

    await chooseReason(tree!, "revisionReasonInterviewerCorrection");
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({ ...completion, data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    });
    await settle();

    expect(order).toEqual(["flush", "queue"]);
    expect(mockQueue).toHaveBeenCalledWith(mockDb, "draft-1", "interviewer_correction", completion);
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
  });

  it("requires consent before queueing and keeps the revision editable", async () => {
    mockLocalRow = { ...mockRow, original_outcome: "completed" };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    await chooseReason(tree!, "revisionReasonInterviewerCorrection");
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({
        valid: true,
        issues: [],
        data: { interview_outcome: "completed", Id10013: "  " },
      });
    });

    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "revisionConsentRequired" });
    expect(JSON.stringify(tree!.toJSON())).toContain("data-revision-form");
    expect(mockQueue).not.toHaveBeenCalled();
  });

  it("allows a completed revision to change to refused", async () => {
    mockLocalRow = { ...mockRow, original_outcome: "completed" };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    await act(async () => {
      (mockFormProps.onDraftController as (controller: unknown) => void)({ saveDraft: mockSaveDraft });
    });
    await chooseReason(tree!, "revisionReasonInterviewerCorrection");
    const completion = { valid: true, issues: [] };
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({
        ...completion,
        data: { Id10013: "no", interview_outcome: "refused" },
      });
    });
    await settle();

    expect(mockQueue).toHaveBeenCalledWith(mockDb, "draft-1", "interviewer_correction", completion);
    await act(async () => tree!.unmount());
  });

  it("requires finish_partial when a partial original becomes effectively completed", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();
    await act(async () => { (mockFormProps.onDraftController as (value: unknown) => void)?.({ saveDraft: mockSaveDraft }); });
    await chooseReason(tree!, "revisionReasonMoreInformation");
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    });
    expect(mockQueue).not.toHaveBeenCalled();

    await chooseReason(tree!, "revisionReasonFinishPartial");
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    });
    await settle();
    expect(mockQueue).toHaveBeenCalledWith(mockDb, "draft-1", "finish_partial", { valid: true, issues: [] });
  });

  it("retains unfinished revisions on before-lock flush", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();
    await act(async () => { (mockFormProps.onDraftController as (value: unknown) => void)?.({ saveDraft: mockSaveDraft }); });
    await act(async () => { await mockLockCallback?.(); });
    expect(mockSaveDraft).toHaveBeenCalledTimes(1);
    expect(mockQueue).not.toHaveBeenCalled();
    expect(tree!.toJSON()).not.toBeNull();
  });

  describe("immersive layout", () => {
    const press = (tree: ReturnType<typeof create>, label: string) =>
      act(async () => {
        tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0].props.onPress();
      });
    const openForm = async () => {
      let tree!: ReturnType<typeof create>;
      await act(async () => { tree = create(<Revision />); });
      await settle();
      await settle();
      await act(async () => { (mockFormProps.onDraftController as (value: unknown) => void)?.({ saveDraft: mockSaveDraft }); });
      return tree;
    };

    it("renders the immersive screen with one top bar and a single-line reason select", async () => {
      const tree = await openForm();
      expect(tree.root.findByType("main").props["data-variant"]).toBe("immersive");
      expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "header")).toHaveLength(1);
      expect(tree.root.findAll((n) => n.props.accessibilityLabel === "revisionReason" && typeof n.props.onPress === "function").length).toBeGreaterThan(0);
      // The reasons are not inline buttons any more.
      expect(tree.root.findAllByProps({ "data-label": "revisionReasonInterviewerCorrection" })).toHaveLength(0);
    });

    it("lists the same reasons in the select sheet and shows the picked reason's notice on one line", async () => {
      const tree = await openForm();
      await act(async () => {
        tree.root.findAll((n) => n.props.accessibilityLabel === "revisionReason" && typeof n.props.onPress === "function")[0].props.onPress();
      });
      const rows = tree.root.findAll((n) => n.props.accessibilityRole === "menuitem" && typeof n.props.onPress === "function");
      expect([...new Set(rows.map((n) => n.props.accessibilityLabel))]).toEqual([
        "revisionReasonInterviewerCorrection",
        "revisionReasonRespondentCorrection",
        "revisionReasonMoreInformation",
        "revisionReasonFinishPartial",
      ]);
      await act(async () => { rows[2].props.onPress(); });
      const notice = tree.root.findAll((n) => n.props.numberOfLines === 1 && JSON.stringify(n.props.children) === '"revisionReasonMessageMoreInformation"');
      expect(notice.length).toBeGreaterThan(0);
    });

    const sheetVisible = (tree: ReturnType<typeof create>) =>
      tree.root.findAll((n) => n.props.transparent === true && typeof n.props.onRequestClose === "function").some((n) => n.props.visible === true);

    it("asks for the reason when the revision opens", async () => {
      const tree = await openForm();
      expect(sheetVisible(tree)).toBe(true);
    });

    it("on Complete without a reason opens the reason sheet and marks the field invalid until one is chosen", async () => {
      mockLocalRow = { ...mockRow, original_outcome: "completed" };
      const tree = await openForm();
      // Dismiss the opening prompt without choosing.
      await act(async () => {
        tree.root.findAll((n) => n.props.accessibilityLabel === "cancel" && typeof n.props.onPress === "function")[0].props.onPress();
      });
      expect(sheetVisible(tree)).toBe(false);
      expect(tree.root.findAllByProps({ testID: "revision-reason-error" })).toHaveLength(0);

      await act(async () => {
        (mockFormProps.onComplete as (result: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "completed" } });
      });
      expect(sheetVisible(tree)).toBe(true);
      expect(tree.root.findAll((n) => n.props.testID === "revision-reason-error" && typeof n.type === "string").length).toBeGreaterThan(0);
      const field = tree.root.findAll((n) => n.props.testID === "revision-reason" && typeof n.props.onPress === "function")[0];
      expect(JSON.stringify(field.props.style)).toContain("borderWidth");

      await chooseReason(tree, "revisionReasonInterviewerCorrection");
      expect(tree.root.findAllByProps({ testID: "revision-reason-error" })).toHaveLength(0);
      expect(mockQueue).not.toHaveBeenCalled();
    });

    it("titles the screen with the deceased's name and a small Revision label, and gives the form a phone bar", async () => {
      mockLocalRow = { ...mockRow, deceased_name: "Asha Devi" };
      const tree = await openForm();
      const header = tree.root.findAll((n) => n.props.accessibilityRole === "header" && typeof n.type === "string")[0];
      expect(header.props.children).toBe("Asha Devi");
      expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.children === "formRevisionLabel").length).toBeGreaterThan(0);
      expect(mockFormProps.compactFooter).toBe(true);
      expect(mockFormProps.safeInsets).toEqual({ top: 0, bottom: 0 });
    });

    it("shows the problems count as a chip that opens the list, and offers Preview answers in the menu", async () => {
      const showProblems = jest.fn();
      const openPreview = jest.fn();
      const tree = await openForm();
      await act(async () => { (mockFormProps.onDraftController as (value: unknown) => void)?.({ saveDraft: mockSaveDraft, showProblems, openPreview }); });
      await act(async () => { (mockFormProps.onProblemsChange as (count: number) => void)(3); });
      await press(tree, "problemsChip");
      expect(showProblems).toHaveBeenCalledTimes(1);
      await press(tree, "moreActions");
      await act(async () => {
        tree.root.findAll((n) => n.props.accessibilityRole === "menuitem" && n.props.accessibilityLabel === "formPreviewAnswers")[0].props.onPress();
      });
      expect(openPreview).toHaveBeenCalledTimes(1);
    });

    it("overflow menu runs Save now, Finish as incomplete and Help; Back leaves after a save", async () => {
      const tree = await openForm();
      const choose = async (label: string) => {
        await press(tree, "moreActions");
        await act(async () => {
          tree.root.findAll((n) => n.props.accessibilityRole === "menuitem" && n.props.accessibilityLabel === label)[0].props.onPress();
        });
      };
      await choose("saveNow");
      await settle();
      expect(mockSaveDraft).toHaveBeenCalledTimes(1);
      expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "revisionSaved" });

      const validate = jest.fn(() => ({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "completed" } }));
      await act(async () => { (mockFormProps.onReady as (value: unknown) => void)({ validate }); });
      await choose("finishIncomplete");
      expect(validate).toHaveBeenCalledTimes(1);

      await choose("formHelp");
      expect(mockOpenSheet).toHaveBeenCalledWith("help");

      await press(tree, "back");
      await settle();
      expect(mockSaveDraft).toHaveBeenCalledTimes(2);
      expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    });

    it("shows Not saved after a failed save and Saved after the next one", async () => {
      const tree = await openForm();
      const label = () => tree.root.findAll((n) => n.props.accessibilityLabel === "saveStateSaved" || n.props.accessibilityLabel === "saveStateUnsaved")[0].props.accessibilityLabel;
      await act(async () => { (mockFormProps.onDraftError as () => void)(); });
      expect(label()).toBe("saveStateUnsaved");
      expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "revisionUnsavedWarning" });
      await act(async () => { (mockFormProps.onDraftSaved as () => void)(); });
      expect(label()).toBe("saveStateSaved");
    });
  });
});
