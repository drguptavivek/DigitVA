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

function makeApi(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: true }),
    getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1"], project_options: [{ project_id: "P1", project_name: "Project One" }] }),
    getCodingAllocation: jest.fn().mockResolvedValue(null),
    getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 3, completed: 1, available: 2, allocation: null }),
    getReviewerAllocation: jest.fn().mockResolvedValue(null),
    allocateCoding: jest.fn().mockResolvedValue({ va_sid: "coding-sid" }),
    allocateReviewer: jest.fn().mockResolvedValue({ va_sid: row.va_sid }),
    releaseCoding: jest.fn().mockResolvedValue({ va_sid: "coding-sid", workflow_state: "ready_for_coding" }),
    releaseReviewer: jest.fn().mockResolvedValue({ va_sid: row.va_sid, workflow_state: "reviewer_eligible" }),
    getWorkspace: jest.fn(), getCategory: jest.fn(), getCodingAvailable: jest.fn(), getCodingHistory: jest.fn(),
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
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("QueueScreen", () => {
  afterEach(() => {
    if (originalPlatformDescriptor) Object.defineProperty(Platform, "OS", originalPlatformDescriptor);
    if (originalConfirmDescriptor) Object.defineProperty(window, "confirm", originalConfirmDescriptor);
    else delete (window as Partial<Window>).confirm;
  });

  test("coder resumes a held case, allocates random only when stats allow it, and never reads unbounded lists", async () => {
    const heldApi = makeApi({ getCodingAllocation: jest.fn().mockResolvedValue({ va_sid: "held-sid" }) });
    const held = await render("coding", heldApi);
    await press(held.renderer, "Resume case");
    expect(held.onOpen).toHaveBeenCalledWith({ vaSid: "held-sid", mode: "coding" });
    expect(heldApi.getCodingAvailable).not.toHaveBeenCalled();
    expect(heldApi.getCodingHistory).not.toHaveBeenCalled();
    await unmount(held.renderer);

    const api = makeApi();
    const screen = await render("coding", api);
    await press(screen.renderer, "Start a random case");
    expect(api.allocateCoding).toHaveBeenCalledWith(undefined, undefined);
    expect(screen.onOpen).toHaveBeenCalledWith({ vaSid: "coding-sid", mode: "coding" });
    await unmount(screen.renderer);

    const unavailable = await render("coding", makeApi({ getCodingStats: jest.fn().mockResolvedValue({ random_ready: 0, has_random_mode: true }) }));
    expect(button(unavailable.renderer.root, "Start a random case")?.props.accessibilityState.disabled).toBe(true);
    await unmount(unavailable.renderer);
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
