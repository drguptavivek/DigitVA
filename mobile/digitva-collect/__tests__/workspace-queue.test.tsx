import React from "react";
import { Alert, Modal, Platform } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { errorText } from "../src/ui";
import { QueueScreen, recodeDeadlineText } from "../src/workspace/QueueScreen";
import type { WorkspaceApi } from "../src/workspace/api";

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

function button(root: ReactTestInstance, label: string) {
  return root.findAll((node) => node.props.accessibilityRole === "button" && node.props.accessibilityLabel === label)[0];
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
    await press(screen.renderer, "Pick case");
    expect(api.allocateCoding).toHaveBeenCalledWith(coderRow.va_sid, "P2");
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: coderRow.va_sid, mode: "coding" });
    await unmount(screen.renderer);

    const noMore = await render("coding", makeApi());
    expect(button(noMore.renderer.root, "Next")?.props.accessibilityState.disabled).toBe(true);
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
    await press(screen.renderer, "Recode");
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
    const pick = button(screen.renderer.root, "Pick case");
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
    expect(button(coder.renderer.root, "Pick case")?.props.accessibilityState.disabled).toBe(true);
    await press(coder.renderer, "History");
    await settle();
    expect(button(coder.renderer.root, "Recode")?.props.accessibilityState.disabled).toBe(true);
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
    await press(screen.renderer, "Cancel");
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
    expect(button(screen.renderer.root, "All projects")?.props.accessibilityState.selected).toBe(true);
    expect(button(screen.renderer.root, long)).toBeDefined();
    await press(screen.renderer, long);
    expect(api.getCodingAvailable).toHaveBeenLastCalledWith({ projectId: "P1", limit: 50, offset: 0 });
    expect(button(screen.renderer.root, long)).toBeUndefined();
    expect(button(screen.renderer.root, "Project: " + long)).toBeDefined();
    await unmount(screen.renderer);
  });

  test("a single project is plain text, not a dropdown", async () => {
    const api = makeApi({ getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1"], project_options: [options[0]], last_project_id: null }) });
    const screen = await render("coding", api);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(long);
    expect(button(screen.renderer.root, "Project: All projects")).toBeUndefined();
    await unmount(screen.renderer);
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

  test("the Available tab exists only in pick mode and random-only coders see their history", async () => {
    const pick = await render("coding", makeApi());
    expect(button(pick.renderer.root, "Available")).toBeDefined();
    expect(JSON.stringify(pick.renderer.toJSON())).toContain("2 ready");
    await unmount(pick.renderer);

    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 21, has_random_mode: true, has_pick_mode: false }) });
    const randomOnly = await render("coding", api);
    await settle();
    expect(button(randomOnly.renderer.root, "Start a random case")).toBeDefined();
    expect(button(randomOnly.renderer.root, "Available")).toBeUndefined();
    expect(button(randomOnly.renderer.root, "Pick case")).toBeUndefined();
    expect(api.getCodingHistory).toHaveBeenCalled();
    expect(JSON.stringify(randomOnly.renderer.toJSON())).toContain("My coded cases");
    await unmount(randomOnly.renderer);
  });

  test("a random-only coder never fetches the available page", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: false }) });
    const screen = await render("coding", api);
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
    expect(button(screen.renderer.root, "Available")).toBeUndefined();
    expect(api.getCodingHistory).toHaveBeenCalled();
    await pickProject(screen.renderer, "Project Two");
    await settle();
    await settle();
    expect(button(screen.renderer.root, "Available")).toBeDefined();
    expect(api.getCodingAvailable).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P2" }));
    expect(button(screen.renderer.root, "Available").props.kind ?? "primary").toBe("primary");
    await unmount(screen.renderer);
  });

  test("a pick-only project is titled Pick a case, counts pick_ready and has no random button", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, pick_ready: 5, has_random_mode: false, has_pick_mode: true }) });
    const screen = await render("coding", api);
    await settle();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("Pick a case");
    expect(text).toContain("5 ready");
    expect(text).not.toContain("Random allocation");
    expect(button(screen.renderer.root, "Start a random case")).toBeUndefined();
    expect(button(screen.renderer.root, "Available")).toBeDefined();
    await unmount(screen.renderer);
  });

  test("a project mixing both modes shows the random button and both counts", async () => {
    const api = makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 3, pick_ready: 4, has_random_mode: true, has_pick_mode: true }) });
    const screen = await render("coding", api);
    await settle();
    const text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("Random allocation");
    expect(text).toContain("3 random · 4 to pick");
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
    await press(screen.renderer, "Close project list");
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
    expect(JSON.stringify(history.renderer.toJSON())).toContain("No coded cases yet.");
    await unmount(history.renderer);

    const available = await render("coding", makeApi({ getCodingAvailable: jest.fn().mockResolvedValue({ forms: [], ...empty }) }));
    expect(JSON.stringify(available.renderer.toJSON())).toContain("No cases to pick right now.");
    await unmount(available.renderer);
  });

  test("renders rich case card metadata and filters queue cases by search, sex, site, and recodeable status", async () => {
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
    expect(text).toContain("Form: WHO2022_ADULT");

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

    // Filter by area: Within Area
    await press(screen.renderer, "Filter area: Within Area");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-FEM-1");
    expect(text).not.toContain("UID-MALE-2");

    // Filter by area: All
    await press(screen.renderer, "Filter area: All");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-FEM-1");
    expect(text).toContain("UID-MALE-2");

    // Filter by area: S2
    await press(screen.renderer, "Filter area: S2");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-MALE-2");
    expect(text).not.toContain("UID-FEM-1");

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
    expect(text).toContain("Coded: 2026-10-09");

    await press(screen.renderer, "Filter recodeable only");
    text = JSON.stringify(screen.renderer.toJSON());
    expect(text).toContain("UID-HIST-1");
    expect(text).not.toContain("UID-HIST-2");

    await unmount(screen.renderer);
  });

  test("shows Project: All projects picker when single offered project does not match requested project", async () => {
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
    expect(button(renderer.root, "Project: All projects")).toBeDefined();
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
    const status = (sid: string) => renderer.root.findAll((n) => typeof n.type === "string" && n.props.testID === `coding-server-status-${sid}`).map((n) => n.props.children);
    expect(status("held")).toEqual(["Sent — waiting for the server's DORIS"]);
    expect(status("refused")).toEqual(["Refused by the server: the coding mode does not match the project's"]);
    expect(status("odd")).toEqual(["Refused by the server: code brand_new_code"]);
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
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
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

  test("history rows carry the deadline next to the Recode action", async () => {
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
    const line = (sid: string) => renderer.root.findAll((n) => typeof n.type === "string" && n.props.testID === `recode-deadline-${sid}`).map((n) => n.props.children);
    expect(line("open")).toEqual([`Recode until ${local("2999-01-01T00:00:00+00:00")}`]);
    expect(line("closed")).toEqual(["Recode window closed"]);
    expect(line("none")).toEqual([]);
    await unmount(renderer);
  });
});
