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
  },
};
let mockLocalRow: unknown = null;
let mockReference: unknown;
let mockFormProps: Record<string, unknown> = {};
let mockLockCallback: (() => Promise<void>) | undefined;
const mockSaveDraft = jest.fn(async () => undefined);
const mockQueue = jest.fn(async (..._args: unknown[]) => undefined);
const mockReload = jest.fn();
const mockChooseUiLocale = jest.fn(async () => undefined);
const mockActivity = jest.fn();

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: mockAccounts,
    activity: mockActivity,
    onBeforeLock: (callback: () => Promise<void>) => {
      mockLockCallback = callback;
      return jest.fn();
    },
    chooseUiLocale: mockChooseUiLocale,
    reload: mockReload,
  }),
}));
jest.mock("../src/api", () => ({ ApiError: class ApiError extends Error { code?: string; status?: number } }));
jest.mock("../src/auth", () => ({
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
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
  getCachedReferenceData: jest.fn(async () => mockReference),
  isUploadable: jest.fn(() => true),
  translationsFor: jest.fn(async () => null),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string) => key,
  questionnaireDefault: (_available: unknown, fallback?: string) => fallback ?? "en",
  UI_LOCALES: [{ code: "en", label: "English" }],
}));
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: () => ({}) }));
jest.mock("../src/translations", () => ({ applyTranslations: (instrument: unknown) => instrument }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    Row: ({ children }: { children: ReactNode }) => ReactActual.createElement("div", null, children),
    Screen: ({ children }: { children: ReactNode }) => ReactActual.createElement("main", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
  };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({
  WhoVaForm: (props: Record<string, unknown>) => {
    mockFormProps = props;
    const ReactActual = jest.requireActual("react") as typeof React;
    return ReactActual.createElement("section", { "data-revision-form": true });
  },
}), { virtual: true });
jest.mock("@drguptavivek/who-2022-va", () => ({
  createWhoVa2022Instrument: jest.fn(() => ({ id: "WHO_2022_VA", version: "v1", sections: [], questions: [] })),
  WHO_VA_FORM_VERSION: "v1",
}), { virtual: true });

import Revision from "../src/nativeRoutes/revision";
import { fetchSubmittedRevisions, beginRevision, queueRevision } from "../src/revisions";

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

beforeEach(() => {
  jest.clearAllMocks();
  mockLocalRow = null;
  mockFormProps = {};
  mockLockCallback = undefined;
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

  it("begins an authorized direct revision without requiring a death id", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();

    expect(beginRevision).toHaveBeenCalledWith("u1", mockDb, "draft-1");
    expect(JSON.stringify(tree!.toJSON())).toContain("data-revision-form");
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

    const reason = tree!.root.findByProps({ "data-label": "revisionReasonInterviewerCorrection" });
    await act(async () => { reason.props.onClick(); });
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

    const reason = tree!.root.findByProps({ "data-label": "revisionReasonInterviewerCorrection" });
    await act(async () => { reason.props.onClick(); });
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({
        valid: true,
        issues: [],
        data: { interview_outcome: "completed", Id10013: "  " },
      });
    });

    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain("revisionConsentRequired");
    expect(rendered).toContain("data-revision-form");
    expect(mockQueue).not.toHaveBeenCalled();
  });

  it("requires finish_partial when a partial original becomes effectively completed", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Revision />); });
    await settle();
    await settle();
    await act(async () => { (mockFormProps.onDraftController as (value: unknown) => void)?.({ saveDraft: mockSaveDraft }); });
    const ordinaryReason = tree!.root.findByProps({ "data-label": "revisionReasonMoreInformation" });
    await act(async () => { ordinaryReason.props.onClick(); });
    await act(async () => {
      (mockFormProps.onComplete as (result: unknown) => void)({ valid: true, issues: [], data: { Id10013: "yes", interview_outcome: "partially_completed" } });
    });
    expect(mockQueue).not.toHaveBeenCalled();

    const finishReason = tree!.root.findByProps({ "data-label": "revisionReasonFinishPartial" });
    await act(async () => { finishReason.props.onClick(); });
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
});
