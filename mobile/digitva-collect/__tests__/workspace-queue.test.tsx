import React from "react";
import { Alert, Platform } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { errorText } from "../src/ui";
import { QueueScreen } from "../src/workspace/QueueScreen";
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
    getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }] }),
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
    await press(screen.renderer, "Project Two");
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
    await press(screen.renderer, "Project One");
    await press(screen.renderer, "Project Two");
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
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(errorText(new ApiError(409, "allocation_conflict")));
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
    Object.defineProperty(window, "confirm", { configurable: true, value: jest.fn().mockReturnValue(true) });
    const api = makeApi({
      getCodingAllocation: jest.fn().mockResolvedValueOnce({ va_sid: "held-sid" }).mockResolvedValue(null),
      getCodingAvailable: jest.fn().mockRejectedValue(new ApiError(503, "unavailable")),
    });
    const screen = await render("coding", api);
    expect(button(screen.renderer.root, "Resume case")).toBeDefined();
    expect(button(screen.renderer.root, "Release case")).toBeDefined();
    expect(button(screen.renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(errorText(new ApiError(503, "unavailable")));

    await press(screen.renderer, "Release case");
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
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(errorText(new ApiError(503, "unavailable")));

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
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(errorText(new ApiError(503, "unavailable")));
    await press(screen.renderer, "Refresh queue");
    await settle();
    expect(api.getReviewerAvailable).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(screen.renderer.toJSON())).toContain(row.va_uniqueid_masked);
    await unmount(screen.renderer);
  });

  test("web release asks before releasing and cancellation leaves the allocation held", async () => {
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    const confirmation = jest.fn().mockReturnValue(false);
    Object.defineProperty(window, "confirm", { configurable: true, value: confirmation });
    const api = makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) });
    const screen = await render("coding", api);
    await press(screen.renderer, "Release case");
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining("An unfinished saved Step 1 will be discarded"));
    expect(api.releaseCoding).not.toHaveBeenCalled();
    confirmation.mockReturnValue(true);
    await press(screen.renderer, "Release case");
    expect(api.releaseCoding).toHaveBeenCalledTimes(1);
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
