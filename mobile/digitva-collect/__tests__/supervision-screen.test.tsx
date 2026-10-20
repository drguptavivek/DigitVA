import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { readFileSync } from "fs";
import { join } from "path";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

const mockRequest = jest.fn();

jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "server error",
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled, loading }: { label: string; onPress: () => void; disabled?: boolean; loading?: boolean }) => (
    <button data-label={loading ? "loading" : label} disabled={disabled} onClick={onPress} />
  ),
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ row: {}, card: {}, headline: {}, text: {}, muted: {}, error: {}, input: {} }),
}));
jest.mock("@drguptavivek/who-2022-va/native", () => {
  const { createElement } = require("react");
  // A stand-in control: one button per choice, so tests pick an answer by value.
  const SingleChoice = ({ question, onAnswer }: { question: { name: string; choices: Array<{ value: string }> }; onAnswer: (value: string) => void }) =>
    createElement("div", null, question.choices.map((choice) =>
      createElement("button", { key: choice.value, "data-choice": question.name, "data-value": choice.value, onClick: () => onAnswer(choice.value) }),
    ));
  return { WhoVaQuestionControls: { SingleChoice, MultipleChoice: () => null } };
});

import { SupervisionPanel } from "../src/web/SupervisionPanel";
import { ApiError } from "../src/api";

const ACCESS_ROLES = ["interview_supervisor"];
let mockBootstrap: { csrf: { header: string; token: string }; access: { roles: string[] } };

function caseRow(overrides: Record<string, unknown> = {}) {
  return {
    death_id: "D1", va_sid: "VA1", unique_id: "UID-1", project_id: "P1", state: "registered",
    pending_flag: null, details_pending: false, deceased_name: "Asha", deceased_sex: "female",
    age_years: 40, date_of_death: "2026-09-01", unit_name: "Unit A", registered_by_name: "ANM One",
    started_by_name: null, updated_at: "2026-10-01T10:00:00Z", other_complete_interview: false,
    ...overrides,
  };
}

function page(cases: unknown[], extra: Record<string, unknown> = {}) {
  return {
    cases, counts: { registered: cases.length || 1 }, tiles: { needs_decision: 4, overdue: 2, stuck: 1, total: 9 },
    next_cursor: null, ...extra,
  };
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function buttons(tree: ReactTestRenderer, label: string) {
  return tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === label);
}

async function press(tree: ReactTestRenderer, label: string, index = 0) {
  const found = buttons(tree, label);
  if (!found[index]) throw new Error(`no button "${label}" at ${index}`);
  await act(async () => {
    found[index].props.onClick();
  });
  await settle();
}

async function pick(tree: ReactTestRenderer, choice: string, value: string) {
  const found = tree.root.findAll((node) => node.type === "button" && node.props["data-choice"] === choice && node.props["data-value"] === value);
  await act(async () => {
    found[0].props.onClick();
  });
}

function typeReason(tree: ReactTestRenderer, text: string) {
  const input = tree.root.findAll((node) => typeof node.props.onChangeText === "function" && node.props.maxLength !== undefined)[0];
  act(() => {
    input.props.onChangeText(text);
  });
}

function requestedPaths(): string[] {
  return mockRequest.mock.calls.map((call) => call[0] as string);
}

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<SupervisionPanel />);
  });
  await settle();
  return tree;
}

/** A fake supervision API: list pages by query, detail and duplicates by case, POST replies by path. */
function fakeApi(options: {
  list?: (path: string) => unknown;
  detail?: unknown;
  duplicates?: unknown[];
  keepCases?: unknown[];
  reply?: unknown;
  refuse?: ApiError;
} = {}) {
  mockRequest.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "POST") {
      if (options.refuse) throw options.refuse;
      return options.reply ?? { case: caseRow() };
    }
    if (path.includes("/possible-duplicates")) return { possible_duplicates: options.duplicates ?? [] };
    if (/\/cases\/D1$/.test(path)) return options.detail;
    if (path.includes("limit=200")) return page(options.keepCases ?? []);
    return options.list ? options.list(path) : page([]);
  });
}

describe("SupervisionPanel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: ACCESS_ROLES } };
  });

  it("opens on Needs my decision, oldest first, shows the reported date, and pages with the keyset cursor", async () => {
    fakeApi({
      list: (path) => path.includes("cursor=C2")
        ? page([caseRow({ death_id: "D2", deceased_name: "Second woman" })])
        : page([caseRow({ pending_flag: "duplicate", created_at: "2026-09-02T08:00:00Z" })], { next_cursor: "C2" }),
    });
    const tree = await render();

    expect(requestedPaths()[0]).toBe("/api/v1/intake/supervision/cases?needs_decision=true&sort=oldest");
    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain("Asha");
    expect(text).toContain(en.supervisionPendingDuplicate);
    expect(text).toContain(en.supervisionReported.replace("{date}", new Date("2026-09-02T08:00:00Z").toLocaleString()));

    await press(tree, en.loadMore);
    expect(requestedPaths()).toContain("/api/v1/intake/supervision/cases?needs_decision=true&sort=oldest&cursor=C2");
    expect(JSON.stringify(tree.toJSON())).toContain("Second woman");
  });

  it("shows a count button per state in scope, each filtering the list", async () => {
    fakeApi({ list: () => page([caseRow()], { counts: { registered: 3, submitted: 2 } }) });
    const tree = await render();

    expect(buttons(tree, `${en.supervisionAnyState} (5)`)).toHaveLength(1);
    expect(buttons(tree, "registered (3)")).toHaveLength(1);
    expect(buttons(tree, "submitted (2)")).toHaveLength(1);
    expect(buttons(tree, "cancelled (0)")).toHaveLength(0);

    await press(tree, "submitted (2)");
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?needs_decision=true&state=submitted&sort=oldest");
  });

  it("shows the four tiles with their counts and sends each tile's filter", async () => {
    fakeApi();
    const tree = await render();
    const labels = [
      `${en.supervisionTileDecision} (4)`, `${en.supervisionTileOverdue} (2)`,
      `${en.supervisionTileStuck} (1)`, `${en.supervisionTileTotal} (9)`,
    ];
    for (const label of labels) expect(buttons(tree, label)).toHaveLength(1);

    await press(tree, labels[1]);
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?overdue=true&sort=oldest");
    await press(tree, labels[2]);
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?stuck=true&sort=oldest");
    await press(tree, labels[3]);
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?");
    await press(tree, labels[0]);
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?needs_decision=true&sort=oldest");
  });

  it("combines the state and visit-note chips with the tile", async () => {
    fakeApi();
    const tree = await render();

    await press(tree, "registered (1)");
    await press(tree, en.supervisionVisitNotes);
    expect(requestedPaths().at(-1)).toBe("/api/v1/intake/supervision/cases?needs_decision=true&state=registered&visit_note=1&sort=oldest");
  });

  it("shows confirm and reject for a pending flag, and no duplicate action", async () => {
    fakeApi({ list: () => page([caseRow({ pending_flag: "cancel" })]) });
    const tree = await render();

    expect(buttons(tree, en.supervisionConfirmFlag)).toHaveLength(1);
    expect(buttons(tree, en.supervisionRejectFlag)).toHaveLength(1);
    expect(buttons(tree, en.supervisionMarkDuplicate)).toHaveLength(0);
    // Cancel follows the state alone, as in the Flask page: the flag does not hide it.
    expect(buttons(tree, en.supervisionCancelCase)).toHaveLength(1);
  });

  it("offers each action only in the states the server allows it", async () => {
    fakeApi({ list: () => page([caseRow({ state: "registered" })]) });
    const registered = await render();
    expect(buttons(registered, en.supervisionCancelCase)).toHaveLength(1);
    expect(buttons(registered, en.supervisionMarkDuplicate)).toHaveLength(1);
    expect(buttons(registered, en.supervisionReopen)).toHaveLength(0);

    fakeApi({ list: () => page([caseRow({ state: "submitted" })]) });
    const submitted = await render();
    expect(buttons(submitted, en.supervisionCancelCase)).toHaveLength(0);
    expect(buttons(submitted, en.supervisionMarkDuplicate)).toHaveLength(1);
    expect(buttons(submitted, en.supervisionReopen)).toHaveLength(1);

    fakeApi({ list: () => page([caseRow({ state: "cancelled" })]) });
    const cancelled = await render();
    expect(buttons(cancelled, en.supervisionCancelCase)).toHaveLength(0);
    expect(buttons(cancelled, en.supervisionMarkDuplicate)).toHaveLength(0);
    expect(buttons(cancelled, en.supervisionReopen)).toHaveLength(1);
  });

  it("confirms a flag with its optional reason", async () => {
    fakeApi({ list: () => page([caseRow({ pending_flag: "duplicate" })]) });
    const tree = await render();

    await press(tree, en.supervisionConfirmFlag, 0);
    typeReason(tree, "Checked with ANM");
    await press(tree, en.supervisionConfirmFlag, 1);

    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/resolve-flag");
    expect(post?.[1]).toEqual({ method: "POST", json: { confirm: true, reason: "Checked with ANM" } });
  });

  it("requires a reason to cancel and posts it trimmed", async () => {
    fakeApi({ list: () => page([caseRow({ state: "registered" })]) });
    const tree = await render();

    await press(tree, en.supervisionCancelCase, 0);
    expect(buttons(tree, en.supervisionCancelCase)[1].props.disabled).toBe(true);

    typeReason(tree, "  Moved away  ");
    expect(buttons(tree, en.supervisionCancelCase)[1].props.disabled).toBe(false);
    await press(tree, en.supervisionCancelCase, 1);

    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/cancel");
    expect(post?.[1]).toEqual({ method: "POST", json: { reason: "Moved away" } });
  });

  it("reopens a cancelled case with its reason", async () => {
    fakeApi({ list: () => page([caseRow({ state: "cancelled" })]) });
    const tree = await render();

    await press(tree, en.supervisionReopen, 0);
    typeReason(tree, "Entered in error");
    await press(tree, en.supervisionReopen, 1);

    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/reopen");
    expect(post?.[1]).toEqual({ method: "POST", json: { reason: "Entered in error" } });
  });

  it("marks a duplicate with the kept case, possible matches first and same-project cases only", async () => {
    fakeApi({
      list: () => page([caseRow({ state: "registered" })]),
      duplicates: [{ death_id: "D9", unique_id: "UID-9", state: "registered", deceased_name: "Match", date_of_death: "2026-08-01" }],
      keepCases: [
        caseRow({ death_id: "D1" }),
        caseRow({ death_id: "D2", project_id: "P1" }),
        caseRow({ death_id: "D3", project_id: "P2" }),
        caseRow({ death_id: "D4", project_id: "P1", state: "cancelled" }),
      ],
    });
    const tree = await render();

    await press(tree, en.supervisionMarkDuplicate, 0);
    const options = tree.root.findAll((node) => node.type === "button" && node.props["data-choice"] === "supervision-keep")
      .map((node) => node.props["data-value"]);
    expect(options).toEqual(["D9", "D2"]);

    await pick(tree, "supervision-keep", "D9");
    await press(tree, en.supervisionMarkDuplicate, 1);
    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/duplicate");
    expect(post?.[1]).toEqual({ method: "POST", json: { duplicate_of: "D9", reason: "" } });
  });

  it("shows a redacted visit note as withheld, not the address", async () => {
    fakeApi({
      list: () => page([caseRow()]),
      detail: {
        case: caseRow(),
        candidates: [],
        visit_note: { date: "2026-09-02", address: null, remarks: null, redacted: true },
      },
    });
    const tree = await render();

    await press(tree, en.viewDetails);
    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain(en.supervisionVisitWithheld);
    expect(text).toContain("2026-09-02");
    expect(text).not.toContain("Some street");
  });

  it("chooses a candidate interview with a reason code", async () => {
    fakeApi({
      list: () => page([caseRow({ state: "submitted" })]),
      detail: {
        case: caseRow({ state: "submitted" }),
        candidates: [{ draft_id: "DR1", interviewer_name: "CHO One", completed_at: "2026-09-30T10:00:00Z", outcome: "completed" }],
        visit_note: null,
      },
    });
    const tree = await render();

    await press(tree, en.viewDetails);
    expect(buttons(tree, en.supervisionChooseInterview)[0].props.disabled).toBe(true);
    await pick(tree, "supervision-choose-reason", "switch_back");
    await press(tree, en.supervisionChooseInterview);

    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/choose-interview");
    expect(post?.[1]).toEqual({ method: "POST", json: { draft_id: "DR1", reason_code: "switch_back" } });
  });

  it("reopens a submitted interview for revision with a reason code", async () => {
    fakeApi({
      list: () => page([caseRow({ state: "submitted" })]),
      detail: { case: caseRow({ state: "submitted" }), candidates: [], visit_note: null },
    });
    const tree = await render();

    await press(tree, en.viewDetails);
    await pick(tree, "supervision-revision-reason", "data_correction");
    await press(tree, en.supervisionReopenRevision);

    const post = mockRequest.mock.calls.find((call) => call[1]?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/submissions/VA1/reopen-for-revision");
    expect(post?.[1]).toEqual({ method: "POST", json: { reason_code: "data_correction" } });
  });

  it("shows reopen for revision for a submitted web case and hides it for an ODK case", async () => {
    fakeApi({
      list: () => page([caseRow({ state: "submitted", source: "register" })]),
      detail: { case: caseRow({ state: "submitted", source: "register" }), candidates: [], visit_note: null },
    });
    const web = await render();
    await press(web, en.viewDetails);
    expect(buttons(web, en.supervisionReopenRevision)).toHaveLength(1);

    fakeApi({
      list: () => page([caseRow({ state: "submitted", source: "odk" })]),
      detail: { case: caseRow({ state: "submitted", source: "odk" }), candidates: [], visit_note: null },
    });
    const odk = await render();
    await press(odk, en.viewDetails);
    expect(buttons(odk, en.supervisionReopenRevision)).toHaveLength(0);
  });

  it.each([
    ["wrong_state", "supervisionErrWrongState"],
    ["not_a_candidate", "supervisionErrNotCandidate"],
    ["form_mismatch", "supervisionErrFormMismatch"],
  ] as const)("shows the mapped text for a refused choose-interview (%s)", async (code, key) => {
    fakeApi({
      list: () => page([caseRow({ state: "submitted" })]),
      detail: {
        case: caseRow({ state: "submitted" }),
        candidates: [{ draft_id: "DR1", interviewer_name: "CHO One", completed_at: null, outcome: "completed" }],
        visit_note: null,
      },
      refuse: new ApiError(409, code, undefined, undefined, { error: "Server English text.", code }),
    });
    const tree = await render();
    await press(tree, en.viewDetails);
    await pick(tree, "supervision-choose-reason", "switch_back");
    await press(tree, en.supervisionChooseInterview);

    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain(en[key]);
    expect(text).not.toContain("Server English text.");
  });

  it.each([
    ["not_web_submission", "supervisionErrNotWeb"],
    ["invalid_reason", "supervisionErrInvalidReason"],
  ] as const)("shows the mapped text for a refused revision (%s)", async (code, key) => {
    fakeApi({
      list: () => page([caseRow({ state: "submitted" })]),
      detail: { case: caseRow({ state: "submitted" }), candidates: [], visit_note: null },
      refuse: new ApiError(409, code, undefined, undefined, { error: "Server English text.", code }),
    });
    const tree = await render();
    await press(tree, en.viewDetails);
    await pick(tree, "supervision-revision-reason", "data_correction");
    await press(tree, en.supervisionReopenRevision);

    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain(en[key]);
    expect(text).not.toContain("Server English text.");
  });

  it("shows the generic text when a refused action has no known code", async () => {
    fakeApi({
      list: () => page([caseRow({ state: "cancelled" })]),
      refuse: new ApiError(500, "server_error"),
    });
    const tree = await render();
    await press(tree, en.supervisionReopen, 0);
    typeReason(tree, "Entered in error");
    await press(tree, en.supervisionReopen, 1);

    expect(JSON.stringify(tree.toJSON())).toContain("server error");
  });

  it("shows an error when the list fails to load", async () => {
    fakeApi({ list: () => Promise.reject(new ApiError(500, "server_error")) });
    const tree = await render();

    expect(JSON.stringify(tree.toJSON())).toContain("server error");
    expect(JSON.stringify(tree.toJSON())).not.toContain(en.supervisionNoDecision);
  });

  it("discards a load-more page that was in flight when an action reloaded the list", async () => {
    let initial = true;
    let resolveStale!: (value: unknown) => void;
    fakeApi({
      list: (path) => {
        if (path.includes("cursor=C2")) return new Promise((resolve) => { resolveStale = resolve; });
        if (initial) {
          initial = false;
          return page([caseRow({ pending_flag: "duplicate" })], { next_cursor: "C2" });
        }
        return page([caseRow({ death_id: "D5", deceased_name: "Fresh woman" })]);
      },
    });
    const tree = await render();

    await press(tree, en.loadMore);
    await press(tree, en.supervisionConfirmFlag, 0);
    await press(tree, en.supervisionConfirmFlag, 1);
    await act(async () => {
      resolveStale(page([caseRow({ death_id: "D2", deceased_name: "Stale woman" })]));
    });
    await settle();

    const text = JSON.stringify(tree.toJSON());
    expect(text).toContain("Fresh woman");
    expect(text).not.toContain("Stale woman");
  });

  it("distinguishes an empty scope from an empty tab", async () => {
    fakeApi({ list: () => ({ cases: [], counts: {}, tiles: { needs_decision: 0, overdue: 0, stuck: 0, total: 0 }, next_cursor: null }) });
    const empty = await render();
    expect(JSON.stringify(empty.toJSON())).toContain(en.supervisionNoScope);

    fakeApi({ list: () => page([]) });
    const scoped = await render();
    // The default tile has its own empty text; the others share the generic one.
    expect(JSON.stringify(scoped.toJSON())).toContain(en.supervisionNoDecision);
    await press(scoped, `${en.supervisionTileOverdue} (2)`);
    expect(JSON.stringify(scoped.toJSON())).toContain(en.supervisionNoCasesHere);
  });

  it("shows the forbidden text and calls nothing without a supervisor role", async () => {
    mockBootstrap = { ...mockBootstrap, access: { roles: ["interviewer"] } };
    fakeApi();
    const tree = await render();

    expect(JSON.stringify(tree.toJSON())).toContain(en.serverForbidden);
    expect(mockRequest).not.toHaveBeenCalled();
  });

  it("has an English and a Hindi string for every supervision key it uses", () => {
    const sources = ["SupervisionPanel.tsx", "SupervisionCase.tsx", "SupervisionActions.tsx"]
      .map((name) => readFileSync(join(__dirname, "../src/web", name), "utf8"))
      .join("\n");
    const keys = new Set(sources.match(/"(supervision[A-Za-z_]*|state_[a-z_]+|emptyDash|viewDetails|loadMore|serverForbidden|loading)"/g) ?? []);
    expect(keys.size).toBeGreaterThan(20);
    for (const quoted of keys) {
      const key = quoted.slice(1, -1);
      expect(en).toHaveProperty([key]);
      expect(hi).toHaveProperty([key]);
    }
  });
});
