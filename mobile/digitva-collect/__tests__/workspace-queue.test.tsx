import { formatWhen } from "../src/ui/interviewRows";
import React from "react";
import { Alert, Modal, Platform, Share } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { DetailsChip, errorText } from "../src/ui";
import { QueueCaseCard, QueueScreen, codedCaseSupportText, recodeDeadlineText, reviewedCaseSupportText } from "../src/workspace/QueueScreen";
import { Select } from "../src/ui/Select";
import { parseAccessSummary, type AccessProject } from "../src/api";
import { APP_VERSION } from "../src/appVersion";
import type { WorkspaceApi } from "../src/workspace/api";
import type { CodingHistoryCache, CodingHistoryIdentity } from "../src/codingHistoryCache";
import type { CoderHistory } from "../src/workspace/contracts";

const originalPlatformDescriptor = Object.getOwnPropertyDescriptor(Platform, "OS");
const originalConfirmDescriptor = Object.getOwnPropertyDescriptor(window, "confirm");

const row = {
  va_sid: "review-sid",
  va_uniqueid_masked: "MASKED-1",
  va_form_id: "FORM-1",
  project_id: "P1",
  site_id: "P1-S1",
  va_submission_date: "2026-10-01",
  va_data_collector: null,
  va_deceased_age: 52,
  va_deceased_gender: "female",
  va_narration_language: "en",
};

const coderRow = {
  va_sid: "coder-sid",
  va_uniqueid_masked: "CODER-MASKED-1",
  va_form_id: "FORM-1",
  project_id: "P1",
  site_id: "P1-S1",
  va_submission_date: "2026-10-01",
  va_data_collector: null,
  va_deceased_age: 52,
  va_deceased_gender: "female",
};

function makeApi(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: true }),
    getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }], last_project_id: null }),
    // One project: no last project and nothing to choose between, so the queue opens on All projects.
    getReviewerProjects: jest.fn().mockResolvedValue({ project_options: [{ project_id: "P1", project_name: "Project One" }], last_project_id: null }),
    getCodingAllocation: jest.fn().mockResolvedValue(null),
    getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 3, completed: 1, available: 2, allocation: null }),
    getReviewerAllocation: jest.fn().mockResolvedValue(null),
    allocateCoding: jest.fn().mockResolvedValue({ va_sid: "coding-sid" }),
    allocateReviewer: jest.fn().mockResolvedValue({ va_sid: row.va_sid }),
    releaseCoding: jest.fn().mockResolvedValue({ va_sid: "coding-sid", workflow_state: "ready_for_coding" }),
    releaseReviewer: jest.fn().mockResolvedValue({ va_sid: row.va_sid, workflow_state: "reviewer_eligible" }),
    getWorkspace: jest.fn(), getCategory: jest.fn(),
    getCodingAvailable: jest.fn().mockResolvedValue({ forms: [coderRow], count: 1, limit: 50, offset: 0, has_more: false }),
    getCodingHistory: jest.fn().mockResolvedValue({ history: [{ ...coderRow, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: true }], count: 1, limit: 50, offset: 0, has_more: false }),
    getReviewerAvailable: jest.fn().mockResolvedValue({ cases: [row], count: 1, limit: 50, offset: 0, has_more: false }),
    getReviewerHistory: jest.fn().mockResolvedValue({ history: [{ ...row, va_reviewed_at: "2026-10-02T12:00:00+00:00" }], count: 1, limit: 50, offset: 0, has_more: false }),
    searchIcd: jest.fn(), codeOwnSubmission: jest.fn(), recode: jest.fn(), saveInitial: jest.fn(), saveFinal: jest.fn(), saveNotCodeable: jest.fn(),
    saveNarrativeQuality: jest.fn(), saveSocialAutopsy: jest.fn(), getNote: jest.fn(), saveNote: jest.fn(), searchDorisTerms: jest.fn(),
    getDorisCodeInfo: jest.fn(), checkDorisSelection: jest.fn(), processDoris: jest.fn(), getWorkflowEvents: jest.fn(),
    ...overrides,
  } as unknown as WorkspaceApi;
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function render(mode: "coding" | "reviewing", api = makeApi(), onOpen = jest.fn()) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<QueueScreen api={api} mode={mode} onOpen={onOpen} />);
  });
  await settle();
  return { renderer, api, onOpen };
}

/** A button, or a row of the project menu (role radio). */
function button(root: ReactTestInstance, label: string) {
  // The phone's segmented control names the history tab by its text; the browser's button says "History".
  const labels = label === "History" ? ["History", "My coded cases", "My reviewed cases"] : [label];
  return root.findAll((node) => (node.props.accessibilityRole === "button" || node.props.accessibilityRole === "radio") && labels.includes(node.props.accessibilityLabel))[0];
}

async function press(renderer: ReactTestRenderer, label: string) {
  const target = button(renderer.root, label);
  expect(target).toBeDefined();
  await act(async () => {
    target.props.onPress();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function tabKind(root: ReactTestInstance, label: string) {
  const radio = root.findAll((node) => node.props.accessibilityRole === "radio" && node.props.accessibilityLabel === label)[0];
  if (radio) return radio.props.accessibilityState.checked ? "primary" : "secondary";
  return root.findAll((node) => node.props.label === label && node.props.kind !== undefined)[0]?.props.kind;
}

async function pickProject(renderer: ReactTestRenderer, name: string) {
  await press(renderer, "Project: " + (renderer.root.findAll((n) => n.props.accessibilityRole === "button" && String(n.props.accessibilityLabel).startsWith("Project: "))[0].props.accessibilityLabel as string).slice(9));
  await press(renderer, name);
}

async function unmount(renderer: ReactTestRenderer) {
  await act(async () => { renderer.unmount(); });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

describe("QueueScreen", () => {
  afterEach(() => {
    if (originalPlatformDescriptor) Object.defineProperty(Platform, "OS", originalPlatformDescriptor);
    if (originalConfirmDescriptor) Object.defineProperty(window, "confirm", originalConfirmDescriptor);
    else delete (window as Partial<Window>).confirm;
  });

  test("coder lists are bounded, resumes a held case, and allocates random only when stats allow it", async () => {
    const heldApi = makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) });
    const held = await render("coding", heldApi);
    await press(held.renderer, "Resume case");
    expect(held.onOpen).toHaveBeenCalledWith({ vaSid: "held-sid", mode: "coding" });
    expect(heldApi.getCodingAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(heldApi.getCodingHistory).not.toHaveBeenCalled();
    await unmount(held.renderer);

    const api = makeApi();
    const screen = await render("coding", api);
    expect(api.getCodingAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(api.getCodingHistory).not.toHaveBeenCalled();
    await press(screen.renderer, "Start a random case");
    expect(api.allocateCoding).toHaveBeenCalledWith(undefined, undefined);
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: "coding-sid", mode: "coding" });
    await unmount(screen.renderer);

    const unavailable = await render("coding", makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, has_random_mode: true }) }));
    expect(button(unavailable.renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    await unmount(unavailable.renderer);
  });

  test("a pick card leads with the deceased's name when sent, else shows the masked id alone", async () => {
    const named = await render("coding", makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [{ ...coderRow, deceased_name: "Asha Rao" }], count: 1, limit: 50, offset: 0, has_more: false }),
    }));
    const output = JSON.stringify(named.renderer.toJSON());
    expect(output).toContain("Asha Rao");
    expect(output).toContain(coderRow.va_uniqueid_masked);
    await unmount(named.renderer);

    const masked = await render("coding", makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [{ ...coderRow, deceased_name: null }], count: 1, limit: 50, offset: 0, has_more: false }),
    }));
    expect(JSON.stringify(masked.renderer.toJSON())).toContain(coderRow.va_uniqueid_masked);
    expect(JSON.stringify(masked.renderer.toJSON())).not.toContain("Asha Rao");
    await unmount(masked.renderer);
  });

  test("coder paging respects has_more, resets for project and tab changes, and allocates only on pick", async () => {
    const api = makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [coderRow], count: 1, limit: 50, offset: 0, has_more: true }),
      allocateCoding: jest.fn().mockResolvedValue({ va_sid: coderRow.va_sid }),
    });
    const screen = await render("coding", api);
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    await press(screen.renderer, "Next");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 50 });
    await pickProject(screen.renderer, "Project Two");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    await press(screen.renderer, "History");
    await settle();
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    await press(screen.renderer, "Available");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    await press(screen.renderer, "Code case");
    expect(api.allocateCoding).toHaveBeenCalledWith(coderRow.va_sid, "P2");
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: coderRow.va_sid, mode: "coding" });
    await unmount(screen.renderer);

    // One page only: no pager row at all (owner 2026-11-27).
    const noMore = await render("coding", makeApi());
    expect(button(noMore.renderer.root, "Next")).toBeUndefined();
    await unmount(noMore.renderer);
  });

  test("coder history opens read-only and offers recode only for recodeable rows", async () => {
    const api = makeApi({ recode: jest.fn().mockResolvedValue({ va_sid: coderRow.va_sid }) });
    const screen = await render("coding", api);
    await press(screen.renderer, "History");
    expect(api.getCodingHistory).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    await press(screen.renderer, "View case");
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: coderRow.va_sid, mode: "view" });
    expect(api.recode).not.toHaveBeenCalled();
    await press(screen.renderer, "Recode case");
    expect(api.recode).toHaveBeenCalledWith(coderRow.va_sid);
    expect(screen.onOpen).toHaveBeenLastCalledWith({ vaSid: coderRow.va_sid, mode: "coding" });
    await unmount(screen.renderer);
  });

  test("late coder project and page responses are discarded after their scope changes", async () => {
    const lateProjectPage = deferred<{ forms: typeof coderRow[]; count: number; limit: number; offset: number; has_more: boolean }>();
    const lateNextPage = deferred<{ forms: typeof coderRow[]; count: number; limit: number; offset: number; has_more: boolean }>();
    const p2Row = { ...coderRow, va_sid: "p2-sid", va_uniqueid_masked: "P2-MASKED", project_id: "P2" };
    const api = makeApi({
      getCodingAvailable: jest.fn((options?: { projectId?: string; offset?: number }) => {
        if (options?.projectId === "P1") return lateProjectPage.promise;
        if (options?.projectId === "P2" && options.offset === 50) return lateNextPage.promise;
        return Promise.resolve({ forms: [p2Row], count: 1, limit: 50, offset: options?.offset ?? 0, has_more: true });
      }),
    });
    const screen = await render("coding", api);
    await pickProject(screen.renderer, "Project One");
    await pickProject(screen.renderer, "Project Two");
    await settle();
    lateProjectPage.resolve({ forms: [{ ...coderRow, va_uniqueid_masked: "STALE-PROJECT" }], count: 1, limit: 50, offset: 0, has_more: false });
    await settle();
    expect(JSON.stringify(screen.renderer.toJSON())).toContain("P2-MASKED");
    expect(JSON.stringify(screen.renderer.toJSON())).not.toContain("STALE-PROJECT");

    await press(screen.renderer, "Next");
    await press(screen.renderer, "History");
    await settle();
    lateNextPage.resolve({ forms: [{ ...coderRow, va_uniqueid_masked: "STALE-PAGE" }], count: 1, limit: 50, offset: 50, has_more: false });
    await settle();
    expect(JSON.stringify(screen.renderer.toJSON())).not.toContain("STALE-PAGE");
    await unmount(screen.renderer);
  });

  test("coder pick guards duplicate clicks and refreshes live availability from page zero after an allocation conflict", async () => {
    const allocation = deferred<{ va_sid: string }>();
    const api = makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [coderRow], count: 1, limit: 50, offset: 0, has_more: true }),
      allocateCoding: jest.fn(() => allocation.promise),
    });
    const screen = await render("coding", api);
    await press(screen.renderer, "Next");
    await settle();
    const pick = button(screen.renderer.root, "Code case");
    await act(async () => {
      pick?.props.onPress();
      pick?.props.onPress();
    });
    expect(api.allocateCoding).toHaveBeenCalledTimes(1);
    allocation.reject(new ApiError(409, "allocation_conflict"));
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(JSON.stringify(errorText(new ApiError(409, "allocation_conflict"))).slice(1, -1));
    await unmount(screen.renderer);
  });

  test("review queue pages in bounded chunks and allocates only after the server replies", async () => {
    const api = makeApi({
      getReviewerAvailable: jest.fn().mockResolvedValue({ cases: [row], count: 1, limit: 50, offset: 0, has_more: true }),
      allocateReviewer: jest.fn().mockResolvedValue({ va_sid: row.va_sid }),
    });
    const screen = await render("reviewing", api);
    expect(api.getReviewerAvailable).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(api.getReviewerHistory).not.toHaveBeenCalled();
    await press(screen.renderer, "Next");
    await settle();
    expect(api.getReviewerAvailable).toHaveBeenLastCalledWith({ limit: 50, offset: 50 });
    await press(screen.renderer, "Previous");
    await settle();
    await press(screen.renderer, "Review case");
    expect(api.allocateReviewer).toHaveBeenCalledWith(row.va_sid);
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: row.va_sid, mode: "reviewing" });
    await unmount(screen.renderer);
  });

  test("history opens read-only view without acquiring an allocation", async () => {
    const api = makeApi();
    const screen = await render("reviewing", api);
    await press(screen.renderer, "History");
    await settle();
    expect(api.getReviewerHistory).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(api.getReviewerAvailable).toHaveBeenCalledTimes(1);
    await press(screen.renderer, "View case");
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: row.va_sid, mode: "view" });
    expect(api.allocateReviewer).not.toHaveBeenCalled();
    await unmount(screen.renderer);
  });

  test("review release waits for confirmation and explains what is kept and cleared", async () => {
    const api = makeApi({ getReviewerAllocation: jest.fn().mockResolvedValue({ va_sid: row.va_sid }) });
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    const screen = await render("reviewing", api);
    await press(screen.renderer, "Release case");
    expect(api.releaseReviewer).not.toHaveBeenCalled();
    expect(alert.mock.calls[0]?.[1]).toContain("Step 1 is kept");
    expect(alert.mock.calls[0]?.[1]).toContain("cleared");
    const actions = alert.mock.calls[0]?.[2];
    const release = actions?.find((action) => action.text === "Release");
    await act(async () => { release?.onPress?.(); await Promise.resolve(); await Promise.resolve(); });
    expect(api.releaseReviewer).toHaveBeenCalledTimes(1);
    await unmount(screen.renderer);
    alert.mockRestore();
  });

  test("active coder allocation remains resumable and releasable when the page fails", async () => {
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    const api = makeApi({
      getCodingAllocation: jest.fn().mockResolvedValueOnce({ va_sid: "held-sid" }).mockResolvedValue(null),
      getCodingAvailable: jest.fn().mockRejectedValue(new ApiError(503, "unavailable")),
    });
    const screen = await render("coding", api);
    expect(button(screen.renderer.root, "Resume case")).toBeDefined();
    expect(button(screen.renderer.root, "Release case")).toBeDefined();
    expect(button(screen.renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(JSON.stringify(errorText(new ApiError(503, "unavailable"))).slice(1, -1));

    await press(screen.renderer, "Release case");
    await press(screen.renderer, "Release");
    await settle();
    expect(api.releaseCoding).toHaveBeenCalledTimes(1);
    expect(button(screen.renderer.root, "Resume case")).toBeUndefined();
    expect(button(screen.renderer.root, "Release case")).toBeUndefined();
    await unmount(screen.renderer);
  });

  test("active reviewer allocation remains resumable and releasable when the page fails", async () => {
    const api = makeApi({
      getReviewerAllocation: jest.fn().mockResolvedValueOnce({ va_sid: row.va_sid }).mockResolvedValue(null),
      getReviewerAvailable: jest.fn().mockRejectedValue(new ApiError(503, "unavailable")),
    });
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    const screen = await render("reviewing", api);
    expect(button(screen.renderer.root, "Resume case")).toBeDefined();
    expect(button(screen.renderer.root, "Release case")).toBeDefined();
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(JSON.stringify(errorText(new ApiError(503, "unavailable"))).slice(1, -1));

    await press(screen.renderer, "Release case");
    const release = alert.mock.calls[0]?.[2]?.find((action) => action.text === "Release");
    await act(async () => { release?.onPress?.(); await Promise.resolve(); await Promise.resolve(); });
    await settle();
    expect(api.releaseReviewer).toHaveBeenCalledTimes(1);
    expect(button(screen.renderer.root, "Resume case")).toBeUndefined();
    expect(button(screen.renderer.root, "Release case")).toBeUndefined();
    await unmount(screen.renderer);
    alert.mockRestore();
  });

  test("a return to the queue (reloadKey) hides the held case before the server answers again (digitva-iycg)", async () => {
    const next = deferred<{ va_sid: string } | null>();
    const api = makeApi({
      getCodingAllocation: jest.fn().mockResolvedValueOnce({ va_sid: "held-sid" }).mockImplementation(() => next.promise),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} reloadKey={0} />); });
    await settle();
    expect(button(renderer.root, "Resume case")).toBeDefined();
    // The coder saved the final COD and came back: the server has closed the allocation but has not answered yet.
    await act(async () => { renderer.update(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} reloadKey={1} />); });
    expect(api.getCodingAllocation).toHaveBeenCalledTimes(2);
    expect(button(renderer.root, "Resume case")).toBeUndefined();
    await act(async () => { next.resolve(null); await next.promise; });
    await settle();
    expect(button(renderer.root, "Resume case")).toBeUndefined();
    await unmount(renderer);
  });

  test("allocation refresh failure hides a previously active allocation", async () => {
    const api = makeApi({
      getCodingAllocation: jest.fn().mockResolvedValueOnce({ va_sid: "held-sid" }).mockRejectedValue(new ApiError(403, "forbidden")),
    });
    const screen = await render("coding", api);
    expect(button(screen.renderer.root, "Release case")).toBeDefined();
    await press(screen.renderer, "Refresh cases");
    await settle();
    expect(api.getCodingAllocation).toHaveBeenCalledTimes(2);
    expect(button(screen.renderer.root, "Release case")).toBeUndefined();
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(errorText(new ApiError(403, "forbidden")));
    await unmount(screen.renderer);
  });

  test("allocation lookup failure disables every new case acquisition", async () => {
    const coderApi = makeApi({ getCodingAllocation: jest.fn().mockRejectedValue(new ApiError(403, "forbidden")) });
    const coder = await render("coding", coderApi);
    expect(button(coder.renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    expect(button(coder.renderer.root, "Code case")?.props.accessibilityState.disabled).toBe(true);
    await press(coder.renderer, "History");
    await settle();
    expect(button(coder.renderer.root, "Recode case")?.props.accessibilityState.disabled).toBe(true);
    await unmount(coder.renderer);

    const reviewerApi = makeApi({ getReviewerAllocation: jest.fn().mockRejectedValue(new ApiError(401, "session_revoked")) });
    const reviewer = await render("reviewing", reviewerApi);
    expect(button(reviewer.renderer.root, "Review case")?.props.accessibilityState.disabled).toBe(true);
    await unmount(reviewer.renderer);
  });

  test("late allocation snapshots are discarded after the API and mode change", async () => {
    const allocation = deferred<{ va_sid: string } | null>();
    const oldApi = makeApi({ getCodingAllocation: jest.fn(() => allocation.promise) });
    const nextApi = makeApi();
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={oldApi} mode="coding" onOpen={jest.fn()} />); });
    await act(async () => { renderer.update(<QueueScreen api={nextApi} mode="reviewing" onOpen={jest.fn()} />); });
    await settle();
    await act(async () => { allocation.resolve({ va_sid: "stale-held-sid" }); await allocation.promise; });
    expect(button(renderer.root, "Resume case")).toBeUndefined();
    expect(button(renderer.root, "Release case")).toBeUndefined();
    await unmount(renderer);
  });

  test("reviewer can retry a failed page from the queue", async () => {
    const api = makeApi({
      getReviewerAvailable: jest.fn()
        .mockRejectedValueOnce(new ApiError(503, "unavailable"))
        .mockResolvedValue({ cases: [row], count: 1, limit: 50, offset: 0, has_more: false }),
    });
    const screen = await render("reviewing", api);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(JSON.stringify(errorText(new ApiError(503, "unavailable"))).slice(1, -1));
    await press(screen.renderer, "Refresh cases");
    await settle();
    expect(api.getReviewerAvailable).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(row.va_uniqueid_masked);
    await unmount(screen.renderer);
  });

  test("web release asks in the in-app dialog; cancel keeps the case, Release releases it", async () => {
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    const nativeConfirm = jest.fn();
    Object.defineProperty(window, "confirm", { configurable: true, value: nativeConfirm });
    const api = makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) });
    const screen = await render("coding", api);
    await press(screen.renderer, "Release case");
    expect(JSON.stringify(screen.renderer.toJSON())).toContain("An unfinished saved Step 1 will be discarded");
    await press(screen.renderer, "Keep my case");
    expect(api.releaseCoding).not.toHaveBeenCalled();
    await press(screen.renderer, "Release case");
    await press(screen.renderer, "Release");
    expect(api.releaseCoding).toHaveBeenCalledTimes(1);
    expect(nativeConfirm).not.toHaveBeenCalled();
    await unmount(screen.renderer);
  });

  test("native release confirmation from an old scope cannot release a case", async () => {
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    const firstApi = makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) });
    const nextApi = makeApi({ getReviewerAllocation: jest.fn().mockResolvedValue({ va_sid: row.va_sid }) });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={firstApi} mode="coding" onOpen={jest.fn()} />); });
    await settle();
    await act(async () => { button(renderer.root, "Release case")?.props.onPress(); });
    const actions = alert.mock.calls[0]?.[2];
    await act(async () => { renderer.update(<QueueScreen api={nextApi} mode="reviewing" onOpen={jest.fn()} />); });
    await settle();
    await act(async () => { actions?.find((action) => action.text === "Release")?.onPress?.(); });
    expect(firstApi.releaseCoding).not.toHaveBeenCalled();
    expect(nextApi.releaseReviewer).not.toHaveBeenCalled();
    await unmount(renderer);
    alert.mockRestore();
  });

  test("delayed queue data from an old API is discarded after the scope render", async () => {
    const oldStats = deferred<{ random_ready: number; has_random_mode: boolean }>();
    const oldApi = makeApi({ getCodingStats: jest.fn(() => oldStats.promise) });
    const nextApi = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, has_random_mode: true }) });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={oldApi} mode="coding" onOpen={jest.fn()} />); });
    await act(async () => { renderer.update(<QueueScreen api={nextApi} mode="coding" onOpen={jest.fn()} />); });
    await settle();
    await act(async () => { oldStats.resolve({ random_ready: 9, has_random_mode: true }); await oldStats.promise; });
    expect(button(renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    await unmount(renderer);
  });

  test("stale allocation responses do not open a case after API/account scope changes", async () => {
    const allocation = deferred<{ va_sid: string }>();
    const firstApi = makeApi({ allocateCoding: jest.fn(() => allocation.promise) });
    const nextApi = makeApi();
    const onOpen = jest.fn();
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={firstApi} mode="coding" onOpen={onOpen} />); });
    await settle();
    await act(async () => { button(renderer.root, "Start a random case")?.props.onPress(); });
    await act(async () => { renderer.update(<QueueScreen api={nextApi} mode="reviewing" onOpen={onOpen} />); });
    await settle();
    await act(async () => { allocation.resolve({ va_sid: "stale" }); await allocation.promise; });
    expect(onOpen).not.toHaveBeenCalled();
    await unmount(renderer);
  });

  test("out-of-scope allocation errors remain visible and refresh queue state", async () => {
    const api = makeApi({ allocateReviewer: jest.fn().mockRejectedValue(new ApiError(403, "forbidden")) });
    const screen = await render("reviewing", api);
    await press(screen.renderer, "Review case");
    await settle();
    expect(api.getReviewerStats).toHaveBeenCalledTimes(2);
    const visibleError = errorText(new ApiError(403, "forbidden"));
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(visibleError);
    await unmount(screen.renderer);
  });
});

describe("queue project defaults", () => {
  const projectOptions = [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }];

  async function flush() {
    await act(async () => {
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
  }

  test("the coding queue opens on the last project when it is offered", async () => {
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: projectOptions, last_project_id: "P2" }) });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />); });
    await flush();
    expect(api.getCodingStats).toHaveBeenCalledWith("P2");
    expect(api.getCodingAvailable).toHaveBeenCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    expect(api.getCodingAvailable).not.toHaveBeenCalledWith(expect.objectContaining({ projectId: undefined }));
  });

  test("a last project that is not offered is ignored and the queue starts on all projects", async () => {
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: projectOptions, last_project_id: "OTHER" }) });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />); });
    await flush();
    expect(api.getCodingAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(api.getCodingAvailable).not.toHaveBeenCalledWith(expect.objectContaining({ projectId: "OTHER" }));
  });

  test("the reviewing queue reads its projects and opens on the last project", async () => {
    const api = makeApi({ getReviewerProjects: jest.fn().mockResolvedValue({ project_options: projectOptions, last_project_id: "P2" }) });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="reviewing" onOpen={jest.fn()} />); });
    await flush();
    expect(api.getReviewerProjects).toHaveBeenCalled();
    expect(api.getReviewerStats).toHaveBeenCalledWith("P2");
    expect(api.getReviewerAvailable).toHaveBeenCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    expect(button(renderer.root, "Project: Project Two")).toBeDefined();
  });

  test("without a last project the review queue opens on the first project with cases to review", async () => {
    const api = makeApi({
      getReviewerProjects: jest.fn().mockResolvedValue({ project_options: projectOptions, last_project_id: null }),
      getReviewerStats: jest.fn(async (projectId?: string) => ({ in_scope: 3, completed: 0, available: projectId === "P2" ? 3 : 0, allocation: null })),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="reviewing" onOpen={jest.fn()} />); });
    await flush();
    expect(api.getReviewerStats).toHaveBeenCalledWith("P1");
    expect(api.getReviewerAvailable).toHaveBeenCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    expect(api.getReviewerAvailable).not.toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1" }));
    expect(button(renderer.root, "Project: Project Two")).toBeDefined();
    await unmount(renderer);
  });

  test("with nothing to review anywhere, or a failed count, the review queue opens on All projects", async () => {
    const api = makeApi({
      getReviewerProjects: jest.fn().mockResolvedValue({ project_options: projectOptions, last_project_id: null }),
      getReviewerStats: jest.fn(async (projectId?: string) => {
        if (projectId === "P2") throw new ApiError(503, "unavailable");
        return { in_scope: 3, completed: 0, available: 0, allocation: null };
      }),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="reviewing" onOpen={jest.fn()} />); });
    await flush();
    expect(api.getReviewerAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(button(renderer.root, "Project: All projects")).toBeDefined();
    await unmount(renderer);
  });

  test("an explicit All projects in the URL skips the per-project counts", async () => {
    const api = makeApi({ getReviewerProjects: jest.fn().mockResolvedValue({ project_options: projectOptions, last_project_id: null }) });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="reviewing" initialView={{ allProjects: true, showHistory: false, offset: 0 }} onOpen={jest.fn()} />);
    });
    await flush();
    expect(api.getReviewerStats).not.toHaveBeenCalledWith("P1");
    expect(api.getReviewerStats).not.toHaveBeenCalledWith("P2");
    expect(api.getReviewerAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    await unmount(renderer);
  });

  test("Back to another project in the URL moves the mounted queue there; a project it does not offer is All", async () => {
    const api = makeApi({ getReviewerProjects: jest.fn().mockResolvedValue({ project_options: projectOptions, last_project_id: null }) });
    const onViewChange = jest.fn();
    const at = (view: { projectId?: string; allProjects: boolean; offset: number }) =>
      <QueueScreen api={api} mode="reviewing" initialView={{ showHistory: false, ...view }} onViewChange={onViewChange} onOpen={jest.fn()} />;
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(at({ projectId: "P2", allProjects: false, offset: 0 })); });
    await flush();
    expect(api.getReviewerAvailable).toHaveBeenLastCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    await act(async () => { renderer.update(at({ projectId: "P1", allProjects: false, offset: 50 })); });
    await flush();
    expect(api.getReviewerAvailable).toHaveBeenLastCalledWith({ projectId: "P1", limit: 50, offset: 50 });
    expect(onViewChange).toHaveBeenLastCalledWith({ projectId: "P1", showHistory: false, offset: 50 });
    await act(async () => { renderer.update(at({ projectId: "GONE", allProjects: false, offset: 0 })); });
    await flush();
    expect(api.getReviewerAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    await unmount(renderer);
  });

  test("offline history uses the saved page as read-only and never exposes case actions", async () => {
    const page: CoderHistory = {
      history: [{ ...coderRow, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: true }],
      count: 1, limit: 50, offset: 0, has_more: false,
    };
    const identity: CodingHistoryIdentity = { mode: "enrolled", serverOrigin: "https://va.example.org", userId: "u1" };
    const cache: CodingHistoryCache = {
      cachedProjects: jest.fn().mockResolvedValue(["P1"]),
      fingerprintForProject: jest.fn().mockReturnValue("a".repeat(64)),
      readPage: jest.fn().mockResolvedValue({ page, fetchedAt: "2026-10-03T12:00:00Z", accessFingerprint: "a".repeat(64) }),
      writePage: jest.fn(), invalidateCase: jest.fn(), invalidateProject: jest.fn(),
    };
    const api = makeApi({
      getCodingStats: jest.fn().mockRejectedValue(new TypeError("Network request failed")),
      getCodingHistory: jest.fn().mockRejectedValue(new TypeError("Network request failed")),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} historyCache={cache} historyIdentity={identity}
        initialView={{ projectId: "P1", allProjects: false, showHistory: true, offset: 0 }} />);
    });
    await settle();
    expect(JSON.stringify(renderer.toJSON())).toContain("Saved on this phone");
    expect(JSON.stringify(renderer.toJSON())).toContain("CODER-MASKED-1");
    for (const label of ["View case", "Recode case", "Code case", "Start a random case", "Release case"]) {
      expect(button(renderer.root, label)).toBeUndefined();
    }
    expect(cache.readPage).toHaveBeenCalledWith(identity, "P1", 0);
    expect(cache.invalidateProject).not.toHaveBeenCalled();
    await unmount(renderer);
  });

  test("permission failures invalidate history and never show cached rows", async () => {
    const identity: CodingHistoryIdentity = { mode: "enrolled", serverOrigin: "https://va.example.org", userId: "u1" };
    const cache: CodingHistoryCache = {
      cachedProjects: jest.fn().mockResolvedValue(["P1"]),
      fingerprintForProject: jest.fn().mockReturnValue("a".repeat(64)),
      readPage: jest.fn().mockResolvedValue({
        page: { history: [], count: 0, limit: 50, offset: 0, has_more: false },
        fetchedAt: "2026-10-03T12:00:00Z", accessFingerprint: "a".repeat(64),
      }),
      writePage: jest.fn(), invalidateCase: jest.fn(), invalidateProject: jest.fn(),
    };
    const api = makeApi({
      getCodingStats: jest.fn().mockRejectedValue(new ApiError(403, "no_coding_access")),
      getCodingHistory: jest.fn().mockRejectedValue(new ApiError(403, "no_coding_access")),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} historyCache={cache} historyIdentity={identity}
        initialView={{ projectId: "P1", allProjects: false, showHistory: true, offset: 0 }} />);
    });
    await settle();
    expect(cache.invalidateProject).toHaveBeenCalledWith(identity, "P1");
    expect(cache.readPage).not.toHaveBeenCalled();
    expect(JSON.stringify(renderer.toJSON())).not.toContain("Saved on this phone");
    await unmount(renderer);
  });
});

describe("active case banner and empty reasons", () => {
  async function flush() {
    await act(async () => {
      for (let i = 0; i < 8; i++) await Promise.resolve();
    });
  }

  test("the held case is named once, with its project and site, and looked up once per case", async () => {
    const api = makeApi({
      getReviewerAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }),
      getWorkspace: jest.fn().mockResolvedValue({ case: { instance_name: "FORM-HELD-1", project_code: "P1", site_code: "S9" } }),
    });
    const screen = await render("reviewing", api);
    await flush();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("You have an active review case");
    expect(text).toContain("FORM-HELD-1 · Project / Site: P1/S9 · Project One");
    expect(text.split("You have an active review case").length).toBe(2);
    expect(api.getWorkspace).toHaveBeenCalledWith("held-sid", "reviewing");
    await press(screen.renderer, "Refresh cases");
    await flush();
    expect(api.getReviewerAllocation).toHaveBeenCalledTimes(2);
    expect(api.getWorkspace).toHaveBeenCalledTimes(1);
    expect(button(screen.renderer.root, "Resume case")).toBeDefined();
    expect(button(screen.renderer.root, "Release case")).toBeDefined();
    // The release dialog names the case being given up, with Keep my case as the safe choice.
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
    await press(screen.renderer, "Release case");
    expect(alert.mock.calls.at(-1)?.[1]).toContain("Releasing FORM-HELD-1.");
    expect((alert.mock.calls.at(-1)?.[2] as Array<{ text: string }>)[0].text).toBe("Keep my case");
    alert.mockRestore();
    await unmount(screen.renderer);
  });

  test("a failed case lookup keeps the banner and its actions without a label", async () => {
    const api = makeApi({
      getReviewerAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }),
      getWorkspace: jest.fn().mockRejectedValue(new ApiError(503, "unavailable")),
    });
    const screen = await render("reviewing", api);
    await flush();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("You have an active review case");
    expect(text).not.toContain("Project / Site:");
    expect(button(screen.renderer.root, "Resume case")).toBeDefined();
    await unmount(screen.renderer);
  });

  test("an empty review list says why", async () => {
    const empty = { cases: [], count: 0, limit: 50, offset: 0, has_more: false };
    const waiting = await render("reviewing", makeApi({
      getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 1, completed: 0, available: 0, allocation: null }),
      getReviewerAvailable: jest.fn().mockResolvedValue(empty),
    }));
    expect(JSON.stringify(waiting.renderer.toJSON())).toContain("Nothing to review in your projects yet: cases appear here after a coder finalises them.");
    expect(JSON.stringify(waiting.renderer.toJSON())).not.toContain("No available cases on this page.");
    await unmount(waiting.renderer);

    const none = await render("reviewing", makeApi({
      getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 0, completed: 0, available: 0, allocation: null }),
      getReviewerAvailable: jest.fn().mockResolvedValue(empty),
    }));
    expect(JSON.stringify(none.renderer.toJSON())).toContain("No cases in your projects yet.");
    await unmount(none.renderer);
  });
});

describe("queue layout", () => {
  const long = "Implementation and scaling up of model physician ascertained verbal autopsy in a very long named project";
  const options = [{ project_id: "P1", project_name: long }, { project_id: "P2", project_name: "Project Two" }];

  test("project dropdown opens, lists every project, selects and closes", async () => {
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: options, last_project_id: null }) });
    const screen = await render("coding", api);
    expect(button(screen.renderer.root, "Project: All projects")).toBeDefined();
    expect(button(screen.renderer.root, long)).toBeUndefined();
    await press(screen.renderer, "Project: All projects");
    expect(button(screen.renderer.root, "All projects")?.props.accessibilityState.checked).toBe(true);
    expect(button(screen.renderer.root, long)).toBeDefined();
    await press(screen.renderer, long);
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", limit: 50, offset: 0 });
    expect(button(screen.renderer.root, long)).toBeUndefined();
    expect(button(screen.renderer.root, "Project: " + long)).toBeDefined();
    await unmount(screen.renderer);
  });

  test("on the phone a single project is plain text, not a dropdown", async () => {
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1"], project_options: [options[0]], last_project_id: null }) });
    const screen = await render("coding", api);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(long);
    expect(button(screen.renderer.root, "Project: " + long)).toBeUndefined();
    expect(button(screen.renderer.root, "Project: All projects")).toBeUndefined();
    await unmount(screen.renderer);
  });

  test("web with a Shell hands the project control to the shell's title row; no line of its own", async () => {
    const seen: { headerProject?: unknown } = {};
    const Shell = ({ headerProject, children }: { headerProject?: React.ReactNode; children: React.ReactNode }) => {
      seen.headerProject = headerProject;
      return <>{children}</>;
    };
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: options, last_project_id: null }) });
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    let renderer!: ReactTestRenderer;
    await act(async () => { renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} Shell={Shell as never} />); });
    await settle();
    try {
      expect(seen.headerProject).toBeTruthy();
      expect(button(renderer.root, "Project: All projects")).toBeUndefined();
    } finally {
      if (originalPlatformDescriptor) Object.defineProperty(Platform, "OS", originalPlatformDescriptor);
      await unmount(renderer);
    }
  });

  test("resume and release share one row with their handlers", async () => {
    const screen = await render("coding", makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) }));
    const resume = button(screen.renderer.root, "Resume case");
    const release = button(screen.renderer.root, "Release case");
    expect(resume).toBeDefined();
    expect(release).toBeDefined();
    const rowOf = (node: ReactTestInstance) => { let n = node.parent; while (n && n.props.style === undefined) n = n.parent; return n?.parent; };
    expect(rowOf(resume)).toBe(rowOf(release));
    await press(screen.renderer, "Resume case");
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: "held-sid", mode: "coding" });
    await unmount(screen.renderer);
  });

  test("random-only coders get the segmented control: Available is the random panel, My coded cases the filter and list", async () => {
    const pick = await render("coding", makeApi());
    expect(button(pick.renderer.root, "Available")).toBeDefined();
    expect(JSON.stringify(pick.renderer.toJSON())).toContain("Random pool");
    await unmount(pick.renderer);

    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 21, has_random_mode: true, has_pick_mode: false }) });
    const randomOnly = await render("coding", api);
    await settle();
    expect(button(randomOnly.renderer.root, "Start a random case")).toBeDefined();
    expect(button(randomOnly.renderer.root, "Available")).toBeDefined();
    expect(button(randomOnly.renderer.root, "Code case")).toBeUndefined();
    expect(button(randomOnly.renderer.root, "Next")).toBeUndefined();
    expect(api.getCodingHistory).not.toHaveBeenCalled();
    await press(randomOnly.renderer, "My coded cases");
    await settle();
    expect(api.getCodingHistory).toHaveBeenCalled();
    expect(button(randomOnly.renderer.root, "Start a random case")).toBeUndefined();
    // The list is drawn; one page of it, so no pager.
    expect(button(randomOnly.renderer.root, "Next")).toBeUndefined();
    expect(JSON.stringify(randomOnly.renderer.toJSON())).toContain("CODER-MASKED-1");
    await unmount(randomOnly.renderer);
  });

  test("the My coded cases deep link opens segment two for a random-only coder", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false }) });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" initialView={{ allProjects: false, showHistory: true, offset: 0 }} onOpen={jest.fn()} />);
    });
    await settle();
    expect(tabKind(renderer.root, "My coded cases")).toBe("primary");
    expect(api.getCodingHistory).toHaveBeenCalled();
    expect(JSON.stringify(renderer.toJSON())).toContain("CODER-MASKED-1");
    await unmount(renderer);
  });

  test("random-only with pick_ready 0 (server shape): Available stays selectable, history only by deep link", async () => {
    const stats = { random_ready: 3, pick_ready: 0, has_random_mode: true, has_pick_mode: false };
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue(stats) });
    const screen = await render("coding", api);
    await settle();
    expect(tabKind(screen.renderer.root, "Available")).toBe("primary");
    await press(screen.renderer, "My coded cases");
    await settle();
    expect(tabKind(screen.renderer.root, "My coded cases")).toBe("primary");
    await press(screen.renderer, "Available");
    await settle();
    expect(tabKind(screen.renderer.root, "Available")).toBe("primary");
    expect(button(screen.renderer.root, "Start a random case")).toBeDefined();
    await unmount(screen.renderer);

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" initialView={{ allProjects: false, showHistory: true, offset: 0 }} onOpen={jest.fn()} />);
    });
    await settle();
    expect(tabKind(renderer.root, "My coded cases")).toBe("primary");
    await press(renderer, "Available");
    await settle();
    expect(tabKind(renderer.root, "Available")).toBe("primary");
    await unmount(renderer);
  });

  test("changing project returns the segment to Available; empty My coded cases still shows the filter", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 3, pick_ready: 0, has_random_mode: true, has_pick_mode: false }) });
    const screen = await render("coding", api);
    await settle();
    await press(screen.renderer, "My coded cases");
    await settle();
    expect(tabKind(screen.renderer.root, "My coded cases")).toBe("primary");
    await pickProject(screen.renderer, "All projects");
    await settle();
    expect(tabKind(screen.renderer.root, "Available")).toBe("primary");
    await unmount(screen.renderer);

    const empty = makeApi({
      getCodingStats: jest.fn().mockResolvedValue({ random_ready: 3, pick_ready: 0, has_random_mode: true, has_pick_mode: false }),
      getCodingHistory: jest.fn().mockResolvedValue({ history: [], has_more: false }),
    });
    const e = await render("coding", empty);
    await settle();
    await press(e.renderer, "My coded cases");
    await settle();
    expect(e.renderer.root.findAll((n) => n.props.accessibilityLabel === "Filter cases").length).toBeGreaterThan(0);
    await unmount(e.renderer);
  });

  test("a random-only coder never fetches the available page", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false }) });
    const screen = await render("coding", api);
    await settle();
    await press(screen.renderer, "My coded cases");
    await settle();
    expect(api.getCodingHistory).toHaveBeenCalled();
    expect(JSON.stringify(screen.renderer.toJSON())).toContain("CODER-MASKED-1");
    expect(api.getCodingAvailable).not.toHaveBeenCalled();
    await unmount(screen.renderer);
  });

  test("moving from a random-only project to one with pick mode leaves the history tab", async () => {
    const getCodingStats = jest.fn(async (projectId?: string) => ({ random_ready: 2, has_random_mode: true, has_pick_mode: projectId === "P2" }));
    const api = makeApi({ getCodingStats } as Partial<WorkspaceApi>);
    const screen = await render("coding", api);
    await settle();
    await press(screen.renderer, "My coded cases");
    await settle();
    expect(api.getCodingHistory).toHaveBeenCalled();
    await pickProject(screen.renderer, "Project Two");
    await settle();
    await settle();
    expect(button(screen.renderer.root, "Available")).toBeDefined();
    expect(api.getCodingAvailable).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P2" }));
    expect(button(screen.renderer.root, "Available").props.kind ?? "primary").toBe("primary");
    await unmount(screen.renderer);
  });

  test("pick 0 with random cases settles on the history tab without reloading in a loop", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 7, pick_ready: 0, has_random_mode: true, has_pick_mode: true }) });
    const screen = await render("coding", api);
    for (let i = 0; i < 6; i += 1) await settle();
    const historyLoads = (api.getCodingHistory as jest.Mock).mock.calls.length;
    const availableLoads = (api.getCodingAvailable as jest.Mock).mock.calls.length;
    for (let i = 0; i < 6; i += 1) await settle();
    expect(historyLoads).toBeGreaterThan(0);
    expect(availableLoads).toBeLessThanOrEqual(1);
    expect((api.getCodingHistory as jest.Mock).mock.calls.length).toBe(historyLoads);
    expect((api.getCodingAvailable as jest.Mock).mock.calls.length).toBe(availableLoads);
    expect(tabKind(screen.renderer.root, "My coded cases")).toBe("primary");
    await unmount(screen.renderer);
  });

  test("a pick-only project with nothing to pick keeps the history tab the coder chose, with Recode reachable", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, pick_ready: 0, has_random_mode: false, has_pick_mode: true }) });
    const screen = await render("coding", api);
    expect(tabKind(screen.renderer.root, "My coded cases")).toBe("secondary");
    await press(screen.renderer, "History");
    for (let i = 0; i < 6; i += 1) await settle();
    expect(tabKind(screen.renderer.root, "My coded cases")).toBe("primary");
    expect((api.getCodingHistory as jest.Mock).mock.calls.length).toBe(1);
    expect(button(screen.renderer.root, "Recode case")).toBeDefined();
    await unmount(screen.renderer);
  });

  test("a pick-only project has no card title, counts pick_ready and has no random button", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, pick_ready: 5, has_random_mode: false, has_pick_mode: true }) });
    const screen = await render("coding", api);
    await settle();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(button(screen.renderer.root, "Ready to pick: 5")).toBeDefined();
    expect(text).not.toContain("Pick a case");
    expect(text).not.toContain("Random allocation");
    expect(text).not.toContain("Random pool");
    expect(button(screen.renderer.root, "Start a random case")).toBeUndefined();
    expect(button(screen.renderer.root, "Available")).toBeDefined();
    await unmount(screen.renderer);
  });

  test("a project mixing both modes shows the random button and both counts", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 3, pick_ready: 4, has_random_mode: true, has_pick_mode: true }) });
    const screen = await render("coding", api);
    await settle();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("Random pool");
    expect(button(screen.renderer.root, "Ready to pick: 4")).toBeDefined();
    // No card title in any mode, and no summary line beside the page title (owner 2026-11-27).
    expect(text).not.toContain("Random allocation");
    expect(text).not.toContain("Pick a case");
    expect(text).not.toContain("3 random · 4 to pick");
    expect(button(screen.renderer.root, "Start a random case")).toBeDefined();
    expect(button(screen.renderer.root, "Available")).toBeDefined();
    await unmount(screen.renderer);
  });

  test("the project sheet opens on press and closes on Escape (Modal onRequestClose) and on the backdrop", async () => {
    const screen = await render("coding");
    const sheetVisible = () => screen.renderer.root.findByType(Modal).props.visible;
    expect(sheetVisible()).toBe(false);
    await press(screen.renderer, "Project: All projects");
    expect(sheetVisible()).toBe(true);
    await act(async () => { screen.renderer.root.findByType(Modal).props.onRequestClose(); });
    expect(sheetVisible()).toBe(false);
    await press(screen.renderer, "Project: All projects");
    await press(screen.renderer, "Close list");
    expect(sheetVisible()).toBe(false);
    await unmount(screen.renderer);
  });

  test("empty states read plainly", async () => {
    const empty = { count: 0, limit: 50, offset: 0, has_more: false };
    const history = await render("coding", makeApi({
      getCodingStats: jest.fn().mockResolvedValue({ random_ready: 1, has_random_mode: true, has_pick_mode: false }),
      getCodingHistory: jest.fn().mockResolvedValue({ history: [], ...empty }),
    }));
    await settle();
    await press(history.renderer, "My coded cases");
    await settle();
    expect(JSON.stringify(history.renderer.toJSON())).toContain("No coded cases yet.");
    await unmount(history.renderer);

    const available = await render("coding", makeApi({ getCodingAvailable: jest.fn().mockResolvedValue({ forms: [], ...empty }) }));
    expect(JSON.stringify(available.renderer.toJSON())).toContain("No cases to pick right now.");
    await unmount(available.renderer);
  });

  test("renders rich case card metadata and filters queue cases by search, sex, and recodeable status", async () => {
    const api = makeApi({
      getCodingStats: jest.fn().mockResolvedValue({
        random_ready: 3,
        pick_ready: 2,
        completed: 14,
        not_codeable: 1,
        has_random_mode: true,
        has_pick_mode: true,
      }),
      getCodingAvailable: jest.fn().mockResolvedValue({
        forms: [
          {
            va_sid: "sid-f1",
            va_uniqueid_masked: "UID-FEM-1",
            va_form_id: "WHO2022_ADULT",
            project_id: "P1",
            site_id: "S1",
            va_submission_date: "2026-10-10",
            va_data_collector: "Collector Anita",
            va_deceased_age: 64,
            va_deceased_gender: "Female",
          },
          {
            va_sid: "sid-m2",
            va_uniqueid_masked: "UID-MALE-2",
            va_form_id: "WHO2022_CHILD",
            project_id: "P1",
            site_id: "S2",
            va_submission_date: "2026-10-11",
            va_data_collector: "Collector Ravi",
            va_deceased_age: 4,
            va_deceased_gender: "Male",
          },
        ],
        count: 2,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
      getCodingHistory: jest.fn().mockResolvedValue({
        history: [
          {
            va_sid: "sid-h1",
            va_uniqueid_masked: "UID-HIST-1",
            va_form_id: "WHO2022_ADULT",
            project_id: "P1",
            site_id: "S1",
            va_submission_date: "2026-10-08",
            va_coding_date: "2026-10-09",
            va_code_status: "Coded",
            va_deceased_age: 71,
            va_deceased_gender: "Female",
            recodeable: true,
          },
          {
            va_sid: "sid-h2",
            va_uniqueid_masked: "UID-HIST-2",
            va_form_id: "WHO2022_ADULT",
            project_id: "P1",
            site_id: "S2",
            va_submission_date: "2026-10-07",
            va_coding_date: "2026-10-08",
            va_code_status: "Final",
            va_deceased_age: 52,
            va_deceased_gender: "Male",
            recodeable: false,
          },
        ],
        count: 2,
        limit: 50,
        offset: 0,
        has_more: false,
      }),
    });

    const screen = await render("coding", api);
    await settle();

    let text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("Random pool");
    expect(text).toContain("Ready to pick");
    expect(text).toContain("Not codeable");
    expect(text).toContain("Age: 64");
    expect(text).toContain("Sex: Female");
    expect(text).toContain("Interviewer: Collector Anita");
    // The card has no Form chip and no status or Recodeable pill any more (owner 2026-11-27).
    expect(text).not.toContain("Form: WHO2022_ADULT");

    // Filter by sex: Female
    await press(screen.renderer, "Filter sex: Female");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-FEM-1");
    expect(text).not.toContain("UID-MALE-2");

    // Clear filters
    await press(screen.renderer, "Clear filters");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-FEM-1");
    expect(text).toContain("UID-MALE-2");

    // The page's own sites are no longer chips: the place filter is the server-side "Site and unit" field.
    expect(button(screen.renderer.root, "Filter area: S2")).toBeUndefined();

    // Filter by text search that matches nothing
    const filterInput = screen.renderer.root.findByProps({ accessibilityLabel: "Filter cases" });
    await act(async () => { filterInput.props.onChangeText("no-such-case"); });
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("No cases match your filters.");

    // Switch to History tab (resets filters automatically) and test Recodeable filter
    await press(screen.renderer, "History");
    await settle();
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-HIST-1");
    expect(text).toContain("UID-HIST-2");
    expect(text).toContain("Coded: 09-Oct-2026");

    await press(screen.renderer, "Filter recodeable only");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-HIST-1");
    expect(text).not.toContain("UID-HIST-2");

    await unmount(screen.renderer);
  });

  test("a requested project that is not the single offered one opens All projects, shown as that one project", async () => {
    const api = makeApi({
      getCodingProjects: jest.fn().mockResolvedValue({
        projects: ["SADEMO"],
        project_options: [{ project_id: "SADEMO", project_name: "WHO 2022 Demo" }],
        last_project_id: null,
      }),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" initialView={{ projectId: "TST001", allProjects: false, showHistory: false, offset: 0 }} onOpen={jest.fn()} />);
    });
    await settle();
    await settle();
    expect(api.getCodingAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    // One project is plain text everywhere (the shared control); All projects then holds that project's cases only.
    expect(button(renderer.root, "Project: All projects")).toBeUndefined();
    expect(JSON.stringify(renderer.toJSON())).toContain("Project: WHO 2022 Demo");
    await unmount(renderer);
  });
});

describe("offline station coding status", () => {
  const coded = (va_sid: string, extra: Record<string, unknown>) => ({
    ...coderRow, va_sid, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "coded", recodeable: true, ...extra,
  });

  test("history shows the server's held and refused answers in plain words", async () => {
    const api = makeApi({
      getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, has_random_mode: true, has_pick_mode: false }),
      getCodingHistory: jest.fn().mockResolvedValue({
        history: [
          coded("held", { server_status: "pending", server_code: "doris_pending" }),
          coded("refused", { server_status: "refused", server_code: "coding_mode_mismatch" }),
          coded("odd", { server_status: "refused", server_code: "brand_new_code" }),
          coded("plain", {}),
        ],
        count: 4, limit: 50, offset: 0, has_more: false,
      }),
    });
    const { renderer } = await render("coding", api);
    await press(renderer, "My coded cases");
    await settle();
    const status = (sid: string) => renderer.root.findAll((n) => typeof n.type === "string" && n.props.testID === `coding-server-status-${sid}`).map((n) => n.props.children);
    expect(status("held")).toEqual(["Sent — waiting for the server's DORIS"]);
    expect(status("refused")).toEqual(["Refused by the server: the coding mode does not match the project's"]);
    expect(status("odd")).toEqual(["Refused by the server: a reason this app does not know"]);
    expect(status("plain")).toEqual([]);
    await unmount(renderer);
  });

  test("says coding is done on the server when the station codes none of its projects", async () => {
    const api = makeApi({
      getCodingProjects: jest.fn().mockResolvedValue({ projects: [], project_options: [], last_project_id: null, station_coding_disabled: true }),
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [], count: 0, limit: 50, offset: 0, has_more: false }),
    });
    const { renderer } = await render("coding", api);
    const note = renderer.root.findAll((n) => n.props.testID === "coding-done-on-server");
    expect(note[0]?.props.children).toBe("Coding for this project is done on the server.");
    await unmount(renderer);
  });
});

describe("coder recode deadline", () => {
  const coded = (va_sid: string, extra: Record<string, unknown>) => ({
    ...coderRow, va_sid, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: false, ...extra,
  });
  const local = (iso: string) => {
    return formatWhen(iso);
  };

  test("recodeDeadlineText shows the deadline in local time, the closed state, or nothing", () => {
    const now = Date.parse("2026-10-02T12:30:00Z");
    expect(recodeDeadlineText({ recodeable: true, recode_until: "2026-10-02T13:00:00+00:00" }, now)).toBe(`Recode until ${local("2026-10-02T13:00:00+00:00")}`);
    expect(recodeDeadlineText({ recodeable: false, recode_until: "2026-10-02T12:00:00+00:00" }, now)).toBe("Recode window closed");
    // Not offered for another reason while the window is still open: say nothing.
    expect(recodeDeadlineText({ recodeable: false, recode_until: "2026-10-02T13:00:00+00:00" }, now)).toBeNull();
    expect(recodeDeadlineText({ recodeable: false, recode_until: null }, now)).toBeNull();
    expect(recodeDeadlineText({ recodeable: true }, now)).toBeNull();
  });

  test("history cards no longer carry the recode deadline line (it stays in the copied support text)", async () => {
    const api = makeApi({
      getCodingHistory: jest.fn().mockResolvedValue({
        history: [
          coded("open", { recodeable: true, recode_until: "2999-01-01T00:00:00+00:00" }),
          coded("closed", { recode_until: "2000-01-01T00:00:00+00:00" }),
          coded("none", { va_code_status: "Not Codeable", recode_until: null }),
        ],
        count: 3, limit: 50, offset: 0, has_more: false,
      }),
    });
    const { renderer } = await render("coding", api);
    await press(renderer, "History");
    const text = JSON.stringify(renderer.toJSON());
    expect(button(renderer.root, "Recode case")).toBeDefined();
    expect(text).not.toContain("Recode until");
    expect(text).not.toContain("Recode window closed");
    await unmount(renderer);
  });
});

describe("codedCaseSupportText", () => {
  it("copies the card's visible details with the full case id and app version, never a name", () => {
    const text = codedCaseSupportText({
      va_sid: "sid-1", va_uniqueid_masked: "SC01-000184_150845443", project_id: "TST001", site_id: "O002",
      va_submission_date: "2026-11-08", va_deceased_age: 61, va_deceased_gender: "female", va_form_id: "TST001O000201",
      va_coding_date: "2026-11-21", va_code_status: "VA Coding Completed", recodeable: true,
      recode_until: "2026-11-22T04:59:00+00:00", deceased_name: "Secret Name",
    } as never, Date.parse("2026-11-21T00:00:00Z"));
    expect(text).toContain("Case SC01-000184_150845443");
    expect(text).toContain("TST001 · O002");
    expect(text).toContain("Age: 61 · Sex: female · Form: TST001O000201");
    expect(text).toContain("VA Coding Completed · Recodeable");
    expect(text).toContain("Recode until");
    expect(text).toContain(`App ${APP_VERSION}`);
    expect(text).not.toContain("Secret Name");
  });
});

const placeUnit = (id: string, name: string, path: string, over: Record<string, unknown> = {}) =>
  ({ org_unit_id: id, unit_code: id, unit_name: name, level_code: "x", path, is_active: true, selectable: true, roles: [], can_code: true, ...over });
const placeAccess = [
  {
    project_id: "P1", project_name: "Project One", has_tree: true, grants: [], sites: [{ site_id: "S1", site_name: "Site One", roles: ["coder"] }],
    actions: { interview: [], register_death: [], code: { project: false, site_ids: [], org_unit_ids: ["chc1"] }, review: { project: false, site_ids: [], org_unit_ids: ["phc1"] } },
    units: [placeUnit("d1", "District", "D", { selectable: false }), placeUnit("chc1", "CHC 01", "D.C"), placeUnit("phc1", "PHC 1", "D.C.P"),
      placeUnit("chc2", "CHC 02", "D.O"), placeUnit("gone", "Closed PHC", "D.C.G", { is_active: false })],
    levels: [],
  },
  {
    project_id: "P2", project_name: "Project Two", has_tree: false, grants: [],
    sites: [{ site_id: "S7", site_name: "Site Seven", roles: ["coder"] }, { site_id: "S8", site_name: "Site Eight", roles: ["reviewer"] }],
    actions: { interview: [], register_death: [], code: { project: false, site_ids: ["S7"], org_unit_ids: [] } },
  },
] as unknown as AccessProject[];

/** *accessProjects* null renders the queue without any (the training route). */
async function renderPlaces(mode: "coding" | "reviewing", api = makeApi(), accessProjects: AccessProject[] | null = placeAccess) {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<QueueScreen api={api} mode={mode} onOpen={jest.fn()} accessProjects={accessProjects ?? undefined} />);
  });
  await settle();
  return { renderer, api };
}

const placeSelect = (renderer: ReactTestRenderer) => renderer.root.findAllByType(Select)[0];

async function choosePlace(renderer: ReactTestRenderer, value: string) {
  await act(async () => { placeSelect(renderer).props.onChange(value); });
  await settle();
}

describe("QueueScreen Site and unit filter", () => {
  test("coding offers only the places the code reach covers, units with their lineage, sites with their project", async () => {
    const { renderer } = await renderPlaces("coding");
    const field = placeSelect(renderer);
    expect(field.props.label).toBe("Site and unit");
    expect(field.props.value).toBe("");
    expect(field.props.options).toEqual([
      { value: "", label: "All areas" },
      { value: "P1::chc1", label: "CHC 01", detail: "District · Project One" },
      { value: "P1::phc1", label: "PHC 1", detail: "CHC 01 < District · Project One" },
      { value: "P2:S7", label: "Site Seven", detail: "Project Two" },
    ]);
    await unmount(renderer);
  });

  test("a choice narrows the server list from page one, keeps across paging, and a site on All names its project", async () => {
    const api = makeApi({ getCodingAvailable: jest.fn().mockResolvedValue({ forms: [coderRow], count: 1, limit: 50, offset: 0, has_more: true }) });
    const { renderer } = await renderPlaces("coding", api);
    await press(renderer, "Next");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 50 });
    expect(api.getCodingStats).toHaveBeenLastCalledWith(undefined);
    await choosePlace(renderer, "P1::phc1");
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    // The counts follow the place (owner 2026-11-27), refetched on every change.
    expect(api.getCodingStats).toHaveBeenLastCalledWith("P1", { siteId: undefined, orgUnitId: "phc1" });
    await press(renderer, "Next");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 50 });
    await choosePlace(renderer, "P2:S7");
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P2", siteId: "S7", limit: 50, offset: 0 });
    expect(api.getCodingStats).toHaveBeenLastCalledWith("P2", { siteId: "S7", orgUnitId: undefined });
    await press(renderer, "History");
    await settle();
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: "P2", siteId: "S7", limit: 50, offset: 0 });
    await choosePlace(renderer, "");
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    // All areas again: the stats call is exactly the one without a place.
    expect((api.getCodingStats as jest.Mock).mock.calls.at(-1)).toEqual([undefined]);
    await unmount(renderer);
  });

  test("a project change drops the place and lists only that project's places", async () => {
    const api = makeApi();
    const { renderer } = await renderPlaces("coding", api);
    await choosePlace(renderer, "P1::chc1");
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "chc1", limit: 50, offset: 0 });
    await pickProject(renderer, "Project Two");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P2", limit: 50, offset: 0 });
    expect(placeSelect(renderer).props.options.map((option: { value: string }) => option.value)).toEqual(["", "P2:S7"]);
    await unmount(renderer);
  });

  test("random-only coding shows no place choice and sends none", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false }) });
    const { renderer } = await renderPlaces("coding", api);
    expect(button(renderer.root, "Start a random case")).toBeDefined();
    expect(renderer.root.findAllByType(Select)).toHaveLength(0);
    await press(renderer, "History");
    await settle();
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(renderer.root.findAllByType(Select)).toHaveLength(0);
    await press(renderer, "Available");
    await settle();
    await press(renderer, "Start a random case");
    expect(api.allocateCoding).toHaveBeenCalledWith(undefined, undefined);
    await unmount(renderer);
  });

  test("reviewing offers the review reach and narrows the review list", async () => {
    const api = makeApi();
    const { renderer } = await renderPlaces("reviewing", api);
    // Only P1 is a review project here, and its review reach is PHC 1 alone; P2 has no review reach.
    expect(placeSelect(renderer).props.options).toEqual([
      { value: "", label: "All areas" },
      { value: "P1::phc1", label: "PHC 1", detail: "CHC 01 < District" },
    ]);
    await choosePlace(renderer, "P1::phc1");
    expect(api.getReviewerAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    expect(api.getReviewerStats).toHaveBeenLastCalledWith("P1", { siteId: undefined, orgUnitId: "phc1" });
    await unmount(renderer);
  });

  test("a tree project with site reach offers its reached sites and the units under reached units, never another unit", async () => {
    const tree = placeAccess[0] as unknown as Record<string, unknown> & { actions: Record<string, unknown> };
    const siteReach = [{ ...tree, sites: [...(tree.sites as unknown[]), { site_id: "S9", site_name: "Site Nine", roles: [] }],
      actions: { ...tree.actions, code: { project: false, site_ids: ["S1"], org_unit_ids: ["phc1"] } } }] as unknown as AccessProject[];
    const { renderer } = await renderPlaces("coding", makeApi(), siteReach);
    expect(placeSelect(renderer).props.options).toEqual([
      { value: "", label: "All areas" },
      { value: "P1::phc1", label: "PHC 1", detail: "CHC 01 < District" },
      { value: "P1:S1", label: "Site One" },
    ]);
    await choosePlace(renderer, "P1:S1");
    expect(renderer.root.findAllByType(Select)[0].props.value).toBe("P1:S1");
    await unmount(renderer);
  });

  test("a pick on the project the URL names keeps the place and its request; re-choosing that project keeps it too", async () => {
    const api = makeApi();
    let renderer!: ReactTestRenderer;
    const view = (offset: number) => ({ projectId: "P1", allProjects: false, showHistory: false, offset });
    const onViewChange = jest.fn((next: { offset: number }) => {
      // The web route writes the view back into the URL, so the queue gets a fresh initialView each time.
      renderer.update(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} accessProjects={placeAccess} initialView={view(next.offset)} onViewChange={onViewChange} />);
    });
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} accessProjects={placeAccess} initialView={view(0)} onViewChange={onViewChange} />);
    });
    await settle();
    await choosePlace(renderer, "P1::phc1");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    expect(placeSelect(renderer).props.value).toBe("P1::phc1");
    await pickProject(renderer, "Project One");
    await settle();
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    expect(placeSelect(renderer).props.value).toBe("P1::phc1");
    await unmount(renderer);
  });

  test("on All projects a place scopes the list and the counts to its own project", async () => {
    const api = makeApi();
    const { renderer } = await renderPlaces("coding", api);
    await choosePlace(renderer, "P1::phc1");
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    expect(api.getCodingStats).toHaveBeenLastCalledWith("P1", { siteId: undefined, orgUnitId: "phc1" });
    await unmount(renderer);
  });

  test("a place-filtered history load offline never reads, writes or clears the history cache", async () => {
    const page: CoderHistory = { history: [{ ...coderRow, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: true }], count: 1, limit: 50, offset: 0, has_more: false };
    const identity: CodingHistoryIdentity = { mode: "enrolled", serverOrigin: "https://va.example.org", userId: "u1" };
    const cache: CodingHistoryCache = {
      cachedProjects: jest.fn().mockResolvedValue(["P1"]),
      fingerprintForProject: jest.fn().mockReturnValue("a".repeat(64)),
      readPage: jest.fn().mockResolvedValue({ page, fetchedAt: "2026-10-03T12:00:00Z", accessFingerprint: "a".repeat(64) }),
      writePage: jest.fn().mockResolvedValue(undefined), invalidateCase: jest.fn(), invalidateProject: jest.fn(),
    };
    const api = makeApi({
      getCodingHistory: jest.fn((options: { orgUnitId?: string }) => options.orgUnitId ? Promise.reject(new TypeError("Network request failed")) : Promise.resolve(page)),
    });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} historyCache={cache} historyIdentity={identity} accessProjects={placeAccess}
        initialView={{ projectId: "P1", allProjects: false, showHistory: true, offset: 0 }} />);
    });
    await settle();
    // Present first: the unfiltered page is saved as the project's history.
    expect(cache.writePage).toHaveBeenCalledTimes(1);
    await choosePlace(renderer, "P1::chc1");
    await settle();
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "chc1", limit: 50, offset: 0 });
    expect(cache.writePage).toHaveBeenCalledTimes(1);
    expect(cache.readPage).not.toHaveBeenCalled();
    expect(cache.invalidateProject).not.toHaveBeenCalled();
    const text = JSON.stringify(renderer.toJSON());
    expect(text).not.toContain("Saved on this phone");
    expect(text).not.toContain("CODER-MASKED-1");
    expect(text).toContain(errorText(new TypeError("Network request failed")));
    await unmount(renderer);
  });

  test("a network failure on the unfiltered Available page leaves the history cache alone", async () => {
    const identity: CodingHistoryIdentity = { mode: "enrolled", serverOrigin: "https://va.example.org", userId: "u1" };
    const cache: CodingHistoryCache = {
      cachedProjects: jest.fn().mockResolvedValue(["P1"]), fingerprintForProject: jest.fn().mockReturnValue("a".repeat(64)),
      readPage: jest.fn(), writePage: jest.fn(), invalidateCase: jest.fn(), invalidateProject: jest.fn(),
    };
    const api = makeApi({ getCodingAvailable: jest.fn().mockRejectedValue(new TypeError("Network request failed")) });
    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} historyCache={cache} historyIdentity={identity}
        initialView={{ projectId: "P1", allProjects: false, showHistory: false, offset: 0 }} />);
    });
    await settle();
    expect(api.getCodingAvailable).toHaveBeenCalled();
    expect(cache.invalidateProject).not.toHaveBeenCalled();
    await unmount(renderer);
  });

  test("a malformed reach from the server offers no place choice", async () => {
    const project = placeAccess[1] as unknown as { actions: Record<string, unknown> };
    const access = parseAccessSummary({ user: { user_id: "u1", name: "W" }, is_admin: false, roles: ["coder"], demo_coding: { available: false, project_ids: [] },
      projects: [{ ...project, actions: { ...project.actions, code: { project: "yes", site_ids: [], org_unit_ids: [] } } }] });
    const { renderer } = await renderPlaces("coding", makeApi(), access.projects);
    expect(renderer.root.findAllByType(Select)).toHaveLength(0);
    await unmount(renderer);
  });

  test("without access projects, or with no reach for the action, there is no place choice", async () => {
    const none = await renderPlaces("coding", makeApi(), null);
    expect(none.renderer.root.findAllByType(Select)).toHaveLength(0);
    await unmount(none.renderer);
    const noReach = await renderPlaces("reviewing", makeApi(), [placeAccess[1]]);
    expect(noReach.renderer.root.findAllByType(Select)).toHaveLength(0);
    await unmount(noReach.renderer);
  });
});

describe("queue counts, pager, tiles and cards (owner 2026-11-27)", () => {
  const texts = (node: ReactTestInstance) => node.findAll((n) => (n.type as unknown) === "Text")
    .map((n) => n.children.filter((c) => typeof c === "string").join(""));

  test("no count-driven switch to My coded cases while a place is chosen", async () => {
    // Both modes: the whole pool has pick work, the chosen place has none.
    const stats = jest.fn((_projectId?: string, place?: unknown) => Promise.resolve(
      { random_ready: 3, pick_ready: place ? 0 : 2, has_random_mode: true, has_pick_mode: true }));
    const api = makeApi({ getCodingStats: stats as unknown as WorkspaceApi["getCodingStats"] });
    const { renderer } = await renderPlaces("coding", api);
    await choosePlace(renderer, "P1::phc1");
    for (let i = 0; i < 4; i += 1) await settle();
    expect(stats).toHaveBeenLastCalledWith("P1", { siteId: undefined, orgUnitId: "phc1" });
    expect(tabKind(renderer.root, "My coded cases")).toBe("secondary");
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", orgUnitId: "phc1", limit: 50, offset: 0 });
    await unmount(renderer);
  });

  test.each([
    ["coding Available", "coding" as const, "getCodingAvailable" as const, (rows: unknown[], hasMore: boolean) => ({ forms: rows, count: rows.length, limit: 50, offset: 0, has_more: hasMore }), coderRow, false],
    ["coding history", "coding" as const, "getCodingHistory" as const, (rows: unknown[], hasMore: boolean) => ({ history: rows, count: rows.length, limit: 50, offset: 0, has_more: hasMore }), { ...coderRow, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: false }, true],
    ["review Available", "reviewing" as const, "getReviewerAvailable" as const, (rows: unknown[], hasMore: boolean) => ({ cases: rows, count: rows.length, limit: 50, offset: 0, has_more: hasMore }), row, false],
  ])("%s: the pager shows only when there is another page", async (_name, mode, method, body, item, history) => {
    const open = async (rows: unknown[], hasMore: boolean | ((options: { offset: number }) => boolean)) => {
      const fetch = jest.fn((options: { offset: number }) => Promise.resolve({ ...body(rows, typeof hasMore === "function" ? hasMore(options) : hasMore), offset: options.offset }));
      const screen = await render(mode, makeApi({ [method]: fetch } as Partial<WorkspaceApi>));
      if (history) { await press(screen.renderer, "History"); await settle(); }
      return screen;
    };
    const empty = await open([], false);
    expect(button(empty.renderer.root, "Next")).toBeUndefined();
    expect(button(empty.renderer.root, "Previous")).toBeUndefined();
    await unmount(empty.renderer);
    const onePage = await open([item], false);
    expect(button(onePage.renderer.root, "Next")).toBeUndefined();
    await unmount(onePage.renderer);
    // A next page shows the row; on page two (offset > 0) it stays though nothing follows.
    const more = await open([item], (options) => options.offset === 0);
    expect(button(more.renderer.root, "Next")?.props.accessibilityState.disabled).toBe(false);
    await press(more.renderer, "Next");
    await settle();
    expect(button(more.renderer.root, "Previous")?.props.accessibilityState.disabled).toBe(false);
    expect(button(more.renderer.root, "Next")?.props.accessibilityState.disabled).toBe(true);
    await unmount(more.renderer);
  });

  test("review tiles: Available to review, Pending coding, Reviewed by me; no summary line beside the title", async () => {
    const api = makeApi({ getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 9, completed: 1, available: 2, pending_coding: 4, allocation: null }) });
    const { renderer } = await render("reviewing", api);
    const text = texts(renderer.root);
    const order = ["Available to review", "Pending coding", "Reviewed by me"].map((label) => text.indexOf(label));
    expect(order.every((index) => index >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(text).not.toContain("In scope");
    expect(JSON.stringify(renderer.toJSON())).not.toContain("available ·");
    // Pending coding is a count, not a button; the other two are.
    expect(renderer.root.findAll((n) => n.props.accessibilityRole === "button" && String(n.props.accessibilityLabel).startsWith("Pending coding"))).toHaveLength(0);
    expect(button(renderer.root, "Available to review: 2")).toBeDefined();
    expect(button(renderer.root, "Reviewed by me: 1")).toBeDefined();
    await unmount(renderer);
  });

  test("an older reviewer /stats without pending_coding keeps the In scope tile", async () => {
    const { renderer } = await render("reviewing");
    const text = texts(renderer.root);
    expect(text).toContain("In scope");
    expect(text).not.toContain("Pending coding");
    await unmount(renderer);
  });

  test("review tiles do exactly what the segment buttons do", async () => {
    const api = makeApi();
    const { renderer } = await render("reviewing", api);
    await press(renderer, "History");
    await settle();
    const viaSegment = (api.getReviewerHistory as jest.Mock).mock.calls.at(-1);
    await press(renderer, "Available");
    await settle();
    const availableViaSegment = (api.getReviewerAvailable as jest.Mock).mock.calls.at(-1);
    await press(renderer, "Reviewed by me: 1");
    await settle();
    expect((api.getReviewerHistory as jest.Mock).mock.calls.at(-1)).toEqual(viaSegment);
    expect(tabKind(renderer.root, "My reviewed cases")).toBe("primary");
    expect(button(renderer.root, "Reviewed by me: 1")?.props.accessibilityState.selected).toBe(true);
    await press(renderer, "Available to review: 2");
    await settle();
    expect((api.getReviewerAvailable as jest.Mock).mock.calls.at(-1)).toEqual(availableViaSegment);
    expect(tabKind(renderer.root, "My reviewed cases")).toBe("secondary");
    expect(button(renderer.root, "Available to review: 2")?.props.accessibilityState.selected).toBe(true);
    await unmount(renderer);
  });

  test("coding tiles: Ready to pick acts as Available, Coded as My coded cases; Random pool is not a button", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 3, pick_ready: 4, completed: 2, has_random_mode: true, has_pick_mode: true }) });
    const { renderer } = await render("coding", api);
    expect(renderer.root.findAll((n) => n.props.accessibilityRole === "button" && String(n.props.accessibilityLabel).startsWith("Random pool"))).toHaveLength(0);
    await press(renderer, "Coded: 2");
    await settle();
    expect(api.getCodingHistory).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(tabKind(renderer.root, "My coded cases")).toBe("primary");
    const loads = (api.getCodingAvailable as jest.Mock).mock.calls.length;
    await press(renderer, "Ready to pick: 4");
    await settle();
    expect((api.getCodingAvailable as jest.Mock).mock.calls.length).toBe(loads + 1);
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: undefined, limit: 50, offset: 0 });
    expect(tabKind(renderer.root, "My coded cases")).toBe("secondary");
    await unmount(renderer);
  });

  test("on All projects a place in a random-only project keeps the choice and its request", async () => {
    const stats = jest.fn((_projectId?: string, place?: unknown) => Promise.resolve(place
      ? { random_ready: 1, has_random_mode: true, has_pick_mode: false }
      : { random_ready: 3, pick_ready: 2, has_random_mode: true, has_pick_mode: true }));
    const api = makeApi({ getCodingStats: stats as unknown as WorkspaceApi["getCodingStats"] });
    const { renderer } = await renderPlaces("coding", api);
    await choosePlace(renderer, "P2:S7");
    for (let i = 0; i < 4; i += 1) await settle();
    expect(stats).toHaveBeenLastCalledWith("P2", { siteId: "S7", orgUnitId: undefined });
    expect(placeSelect(renderer)?.props.value).toBe("P2:S7");
    await choosePlace(renderer, "");
    for (let i = 0; i < 4; i += 1) await settle();
    // Back on All areas the All-projects modes return: the pick list and its tile.
    expect(button(renderer.root, "Ready to pick: 2")).toBeDefined();
    await unmount(renderer);
  });

  test("random-only coding has no card title either", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false }) });
    const { renderer } = await render("coding", api);
    expect(button(renderer.root, "Start a random case")).toBeDefined();
    expect(JSON.stringify(renderer.toJSON())).not.toContain("Random allocation");
    await unmount(renderer);
  });

  test("Review shows Your languages with the same edit action; a save reloads the review counts and list", async () => {
    const api = makeApi({ getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 3, completed: 1, available: 2, languages: { mine: ["english", "hindi"] }, allocation: null }) });
    const onEditLanguages = jest.fn();
    let renderer!: ReactTestRenderer;
    const view = (reloadKey: number) => <QueueScreen api={api} mode="reviewing" onOpen={jest.fn()} onEditLanguages={onEditLanguages} reloadKey={reloadKey} />;
    await act(async () => { renderer = create(view(0)); });
    await settle();
    expect(texts(renderer.root)).toContain("Your languages: English, Hindi");
    const edit = renderer.root.findAll((n) => n.props.testID === "coding-languages-edit" && n.props.onPress)[0];
    await act(async () => { edit.props.onPress(); });
    expect(onEditLanguages).toHaveBeenCalledTimes(1);
    const statsLoads = (api.getReviewerStats as jest.Mock).mock.calls.length;
    const listLoads = (api.getReviewerAvailable as jest.Mock).mock.calls.length;
    await act(async () => { renderer.update(view(1)); });
    await settle();
    expect((api.getReviewerStats as jest.Mock).mock.calls.length).toBeGreaterThan(statsLoads);
    expect((api.getReviewerAvailable as jest.Mock).mock.calls.length).toBeGreaterThan(listLoads);
    await unmount(renderer);
  });

  test("an older reviewer /stats without languages draws no languages line", async () => {
    const { renderer } = await render("reviewing");
    expect(renderer.root.findAll((n) => n.props.testID === "coding-languages")).toHaveLength(0);
    await unmount(renderer);
  });

  const cardRow = {
    ...coderRow, va_uniqueid_masked: "PHC01-000020_172313647", va_narration_language: "english", unit_name: "PHC Rampur",
    site_name: "Site One", project_nickname: "Nick One", va_deceased_age_normalized_days: 12, date_of_death: "2026-09-30",
    va_data_collector: "S. Devi",
  };
  const cardOf = (renderer: ReactTestRenderer, index = 0) => renderer.root.findAllByType(QueueCaseCard)[index];
  const testIdText = (card: ReactTestInstance, id: string) => {
    const node = card.findAll((n) => n.props.testID === id && typeof n.type !== "string")[0] ?? card.findAll((n) => n.props.testID === id)[0];
    return node ? texts(node) : [];
  };

  test("a named card: name title, both pills, the id first on the place line, dates, pills, then its button", async () => {
    const coding = await render("coding", makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [{ ...cardRow, deceased_name: "Esha Testcase" }], count: 1, limit: 50, offset: 0, has_more: false }),
    }));
    const card = cardOf(coding.renderer);
    expect(texts(card)).toEqual([
      "Esha Testcase", "english", "Interviewed",
      "Case 000020", "· PHC Rampur", "· Nick One",
      "Died: 30-Sep-2026", "· Interviewed: 01-Oct-2026",
      "Age: 12 d", "Sex: female", "Interviewer: S. Devi",
      "Code case",
    ]);
    await unmount(coding.renderer);
  });

  test("an unnamed card: the id is the title and the place line has no id; a picked project drops the nickname", async () => {
    const api = makeApi({ getCodingAvailable: jest.fn().mockResolvedValue({ forms: [cardRow], count: 1, limit: 50, offset: 0, has_more: false }) });
    const { renderer } = await render("coding", api);
    expect(texts(cardOf(renderer)).slice(0, 5)).toEqual(["Case 000020", "english", "Interviewed", "PHC Rampur", "· Nick One"]);
    await pickProject(renderer, "Project One");
    await settle();
    expect(testIdText(cardOf(renderer), `queue-case-place-${cardRow.va_sid}`)).toEqual(["PHC Rampur"]);
    await unmount(renderer);
  });

  test("the place line names the site of a site project, never a code, and hides a placeholder site", async () => {
    const site = { ...cardRow, unit_name: null, site_name: "Jodhpur Site" };
    const placeholder = { ...cardRow, va_sid: "c-ph", unit_name: null, site_id: "sites_in_project_P1", site_name: "sites_in_project_P1" };
    const old = { ...coderRow, va_sid: "c-old" };
    const { renderer } = await render("coding", makeApi({ getCodingAvailable: jest.fn().mockResolvedValue({ forms: [site, placeholder, old], count: 3, limit: 50, offset: 0, has_more: false }) }));
    expect(testIdText(cardOf(renderer, 0), `queue-case-place-${site.va_sid}`)).toEqual(["Jodhpur Site", "· Nick One"]);
    expect(testIdText(cardOf(renderer, 1), "queue-case-place-c-ph")).toEqual(["Nick One"]);
    // An older server sends no names: no place line, and still no code (P1, P1-S1).
    expect(testIdText(cardOf(renderer, 2), "queue-case-place-c-old")).toEqual([]);
    expect(texts(cardOf(renderer, 2))).not.toContain("P1-S1");
    await unmount(renderer);
  });

  test("Review: Coded or Recoded with the coding dates; Review history: Reviewed, View case and the copy icon", async () => {
    const coded = { ...row, va_sid: "r1", first_coded_at: "2026-10-02T12:00:00+00:00", recoded: false, last_coded_at: "2026-10-02T12:00:00+00:00" };
    const recoded = { ...row, va_sid: "r2", first_coded_at: "2026-10-02T12:00:00+00:00", last_coded_at: "2026-10-05T12:00:00+00:00", recoded: true };
    const api = makeApi({
      getReviewerAvailable: jest.fn().mockResolvedValue({ cases: [coded, recoded], count: 2, limit: 50, offset: 0, has_more: false }),
      getReviewerHistory: jest.fn().mockResolvedValue({ history: [{ ...coded, va_reviewed_at: "2026-10-07T12:00:00+00:00" }], count: 1, limit: 50, offset: 0, has_more: false }),
    });
    const { renderer } = await render("reviewing", api);
    expect(testIdText(cardOf(renderer, 0), "queue-case-action-r1")).toEqual(["Coded"]);
    expect(testIdText(cardOf(renderer, 0), "queue-case-dates-r1")).toEqual(["Interviewed: 01-Oct-2026", "· Coded: 02-Oct-2026"]);
    expect(testIdText(cardOf(renderer, 1), "queue-case-action-r2")).toEqual(["Recoded"]);
    expect(testIdText(cardOf(renderer, 1), "queue-case-dates-r2")).toEqual(["Interviewed: 01-Oct-2026", "· Coded: 02-Oct-2026", "· Recoded: 05-Oct-2026"]);
    expect(button(renderer.root, "Review case")).toBeDefined();
    await press(renderer, "History");
    await settle();
    const card = cardOf(renderer);
    expect(testIdText(card, "queue-case-action-r1")).toEqual(["Reviewed"]);
    expect(testIdText(card, "queue-case-dates-r1")).toEqual(["Interviewed: 01-Oct-2026", "· Coded: 02-Oct-2026", "· Reviewed: 07-Oct-2026"]);
    expect(button(renderer.root, "View case")).toBeDefined();
    expect(button(renderer.root, "Review case")).toBeUndefined();
    const share = jest.spyOn(Share, "share").mockResolvedValue({ action: "sharedAction" } as never);
    await press(renderer, "Copy details of MASKED-1");
    expect(share.mock.calls[0][0].message).toBe(reviewedCaseSupportText({ ...coded, va_reviewed_at: "2026-10-07T12:00:00+00:00" } as never));
    share.mockRestore();
    await unmount(renderer);
  });

  test("Coding history: Coded, Recoded or Not codeable; Recode case only while recodeable; the copy icon; no Form chip or Recodeable pill", async () => {
    const history = [
      { ...coderRow, va_sid: "h1", va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: true, first_coded_at: "2026-10-02T12:00:00+00:00", last_coded_at: "2026-10-02T12:00:00+00:00", recoded: false },
      { ...coderRow, va_sid: "h2", va_coding_date: "2026-10-05T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: false, first_coded_at: "2026-10-02T12:00:00+00:00", last_coded_at: "2026-10-05T12:00:00+00:00", recoded: true },
      { ...coderRow, va_sid: "h3", va_coding_date: "2026-10-06T12:00:00+00:00", va_code_status: "Not Codeable", recodeable: false },
    ];
    const api = makeApi({ getCodingHistory: jest.fn().mockResolvedValue({ history, count: 3, limit: 50, offset: 0, has_more: false }) });
    const { renderer } = await render("coding", api);
    await press(renderer, "History");
    await settle();
    expect(testIdText(cardOf(renderer, 0), "queue-case-action-h1")).toEqual(["Coded"]);
    expect(testIdText(cardOf(renderer, 1), "queue-case-action-h2")).toEqual(["Recoded"]);
    expect(testIdText(cardOf(renderer, 1), "queue-case-dates-h2")).toEqual(["Interviewed: 01-Oct-2026", "· Coded: 02-Oct-2026", "· Recoded: 05-Oct-2026"]);
    expect(testIdText(cardOf(renderer, 2), "queue-case-action-h3")).toEqual(["Not codeable"]);
    expect(testIdText(cardOf(renderer, 2), "queue-case-dates-h3")).toEqual(["Interviewed: 01-Oct-2026", "· Not codeable: 06-Oct-2026"]);
    const labels = (index: number) => cardOf(renderer, index).findAll((n) => n.props.accessibilityRole === "button" && typeof n.props.accessibilityLabel === "string").map((n) => n.props.accessibilityLabel);
    expect(new Set(labels(0))).toEqual(new Set(["View case", "Recode case", "Copy details of CODER-MASKED-1"]));
    expect(new Set(labels(1))).toEqual(new Set(["View case", "Copy details of CODER-MASKED-1"]));
    const text = JSON.stringify(renderer.toJSON());
    expect(text).toContain("Age: 52 y");
    expect(text).not.toContain("Form:");
    expect(text).not.toContain('"Recodeable"');
    expect(text).not.toContain("VA Coding Completed");
    await unmount(renderer);
  });

  test("the Sync pill: phone only, Pending, Failed (dark, with the details chip) or Done", async () => {
    const history = [
      { ...coderRow, va_sid: "s1", va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: false, server_status: "pending" },
      { ...coderRow, va_sid: "s2", va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: false, server_status: "refused", server_code: "doris_pending" },
      { ...coderRow, va_sid: "s3", va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "VA Coding Completed", recodeable: false },
    ];
    const api = () => makeApi({ getCodingHistory: jest.fn().mockResolvedValue({ history, count: 3, limit: 50, offset: 0, has_more: false }) });
    const phone = await render("coding", api());
    await press(phone.renderer, "History");
    await settle();
    expect(["s1", "s2", "s3"].map((sid, index) => testIdText(cardOf(phone.renderer, index), `queue-case-sync-${sid}`))).toEqual([["Sync: Pending"], ["Sync: Failed"], ["Sync: Done"]]);
    expect(cardOf(phone.renderer, 1).findAllByType(DetailsChip)).toHaveLength(1);
    expect(cardOf(phone.renderer, 1).findAll((n) => n.props.testID === "coding-server-status-s2")).not.toHaveLength(0);
    await unmount(phone.renderer);
    Object.defineProperty(Platform, "OS", { configurable: true, get: () => "web" });
    try {
      const web = await render("coding", api());
      await press(web.renderer, "History");
      await settle();
      expect(web.renderer.root.findAll((n) => String(n.props.testID ?? "").startsWith("queue-case-sync-"))).toHaveLength(0);
      await unmount(web.renderer);
    } finally {
      if (originalPlatformDescriptor) Object.defineProperty(Platform, "OS", originalPlatformDescriptor);
    }
  });
});

describe("additive queue keys are parsed leniently", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { parseReviewerStats, parseCoderQueue, parseCoderHistory } = require("../src/workspace/contracts") as typeof import("../src/workspace/contracts");
  const base = { in_scope: 3, completed: 1, available: 2, allocation: null };

  test("reviewer stats keep a numeric pending_coding and a languages list, and drop malformed ones", () => {
    expect(parseReviewerStats({ ...base, pending_coding: 4, languages: { mine: ["english", 7] } })).toEqual({ ...base, pending_coding: 4, languages: { mine: ["english"] } });
    expect(parseReviewerStats({ ...base, pending_coding: "4", languages: "english" })).toEqual(base);
    expect(parseReviewerStats(base)).toEqual(base);
  });

  test("the card keys are kept when well-formed and dropped one by one when not, on every list", () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { parseReviewerQueue } = require("../src/workspace/contracts") as typeof import("../src/workspace/contracts");
    const good = { unit_name: "PHC 1", site_name: null, project_nickname: "Nick", va_deceased_age_normalized_days: 12.5,
      date_of_death: "2026-09-30", first_coded_at: "2026-10-02T12:00:00+00:00", last_coded_at: null, recoded: true, deceased_name: "Asha" };
    const bad = { unit_name: 3, site_name: {}, project_nickname: [], va_deceased_age_normalized_days: "12", date_of_death: 20260930,
      first_coded_at: false, last_coded_at: 1, recoded: "yes", deceased_name: 7 };
    const review = (item: Record<string, unknown>) => parseReviewerQueue({ cases: [{ ...row, ...item }], count: 1, limit: 50, offset: 0, has_more: false }, 50, 0).cases[0];
    expect(review(good)).toMatchObject(good);
    const dropped = review(bad) as unknown as Record<string, unknown>;
    for (const key of Object.keys(bad)) expect(key in dropped).toBe(false);
    const page = (item: Record<string, unknown>) => ({ history: [{ ...coderRow, va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: false, ...item }], count: 1, limit: 50, offset: 0, has_more: false });
    expect(parseCoderHistory(page(good), 50, 0).history[0]).toMatchObject(good);
    expect("recoded" in parseCoderHistory(page({ recoded: "yes" }), 50, 0).history[0]).toBe(false);
    expect(parseCoderQueue({ forms: [{ ...coderRow, va_deceased_age_normalized_days: -1 }], count: 1, limit: 50, offset: 0, has_more: false }, 50, 0).forms[0].va_deceased_age_normalized_days).toBeUndefined();
  });

  test("coding items keep a string narration language and drop anything else", () => {
    const page = (item: Record<string, unknown>) => ({ forms: [item], count: 1, limit: 50, offset: 0, has_more: false });
    expect(parseCoderQueue(page({ ...coderRow, va_narration_language: "english" }), 50, 0).forms[0].va_narration_language).toBe("english");
    expect("va_narration_language" in parseCoderQueue(page({ ...coderRow, va_narration_language: 3 }), 50, 0).forms[0]).toBe(false);
    const history = { history: [{ ...coderRow, va_narration_language: "odia", va_coding_date: "2026-10-02T12:00:00+00:00", va_code_status: "completed", recodeable: false }], count: 1, limit: 50, offset: 0, has_more: false };
    expect(parseCoderHistory(history, 50, 0).history[0].va_narration_language).toBe("odia");
  });
});

describe("no place without personal-data access; a year-only date of death (owner 2026-11-27)", () => {
  const texts = (node: ReactTestInstance) => node.findAll((n) => (n.type as unknown) === "Text")
    .map((n) => n.children.filter((c) => typeof c === "string").join(""));

  test("a project without pii_visible offers no Site and unit choice, on both queues", async () => {
    const noPii = placeAccess.map((project) => ({ ...project, pii_visible: false })) as AccessProject[];
    for (const mode of ["coding", "reviewing"] as const) {
      const shown = await renderPlaces(mode, makeApi(), placeAccess.map((project) => ({ ...project, pii_visible: true })) as AccessProject[]);
      expect(shown.renderer.root.findAllByType(Select)).toHaveLength(1);
      await unmount(shown.renderer);
      const hidden = await renderPlaces(mode, makeApi(), noPii);
      expect(hidden.renderer.root.findAllByType(Select)).toHaveLength(0);
      await unmount(hidden.renderer);
    }
    // One project without access drops only its own places.
    const mixed = await renderPlaces("coding", makeApi(), [{ ...placeAccess[0], pii_visible: false }, placeAccess[1]] as AccessProject[]);
    expect(placeSelect(mixed.renderer).props.options.map((option: { value: string }) => option.value)).toEqual(["", "P2:S7"]);
    await unmount(mixed.renderer);
  });

  test("a card without the place keys (no personal-data access) has no place line, on both queues", async () => {
    const coding = await render("coding", makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [{ ...coderRow, date_of_death: "2026-09-30" }], count: 1, limit: 50, offset: 0, has_more: false }),
    }));
    const card = coding.renderer.root.findAllByType(QueueCaseCard)[0];
    expect(card.findAll((n) => typeof n.type === "string" && n.props.testID === `queue-case-place-${coderRow.va_sid}`)).toHaveLength(0);
    expect(texts(card).slice(0, 3)).toEqual(["CODER-MASKED-1", "Interviewed", "Died: 30-Sep-2026"]);
    await unmount(coding.renderer);
    const review = await render("reviewing");
    expect(review.renderer.root.findAll((n) => typeof n.type === "string" && n.props.testID === `queue-case-place-${row.va_sid}`)).toHaveLength(0);
    await unmount(review.renderer);
  });

  test("a year-only date of death shows its year alone", async () => {
    const { renderer } = await render("coding", makeApi({
      getCodingAvailable: jest.fn().mockResolvedValue({ forms: [
        { ...coderRow, date_of_death: "2026-07-01", death_date_year_only: true },
        { ...coderRow, va_sid: "c-exact", date_of_death: "2026-07-01", death_date_year_only: false },
      ], count: 2, limit: 50, offset: 0, has_more: false }),
    }));
    const dates = (index: number, sid: string) => texts(renderer.root.findAllByType(QueueCaseCard)[index].findAll((n) => n.props.testID === `queue-case-dates-${sid}`)[0]);
    expect(dates(0, coderRow.va_sid)[0]).toBe("Died: 2026");
    expect(dates(1, "c-exact")[0]).toBe("Died: 01-Jul-2026");
    await unmount(renderer);
  });
});
