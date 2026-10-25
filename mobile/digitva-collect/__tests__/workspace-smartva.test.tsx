import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { createWorkspaceApi, type WorkspaceApi } from "../src/workspace/api";
import { SmartvaStatusPanel } from "../src/workspace/SmartvaStatusPanel";
import { parseWorkspace, WorkspaceContractError } from "../src/workspace/contracts";
import { useSmartvaLifecycle } from "../src/workspace/useSmartvaLifecycle";

const baseWorkspace = {
  case: {
    va_sid: "sid/1", instance_name: "MASKED-1", form_type_code: "FORM",
    project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding",
    narrative_qa_enabled: false, social_autopsy_enabled: false,
  },
  categories: [{ code: "demographic", label: "Demographic", nav_label: "Demographic", render_mode: "table" }],
  default_category: "demographic", step: "initial",
  blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
};

function makeApi(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    runSmartva: jest.fn().mockResolvedValue({ va_sid: "sid/1", status: "queued" }),
    ...overrides,
  } as unknown as WorkspaceApi;
}

function action(renderer: ReactTestRenderer, label: string) {
  return renderer.root.findAll((node) => node.props.accessibilityLabel === label)[0];
}

function LifecycleProbe({ api, active = true, status = "not_requested", canRun = true, onChanged = jest.fn() }: { api: WorkspaceApi; active?: boolean; status?: "not_requested" | "queued" | "running" | "done" | "failed"; canRun?: boolean; onChanged?: () => void }) {
  const state = useSmartvaLifecycle({ api, identity: { vaSid: "sid/1", mode: "coding" }, status, canRun, active, onChanged });
  return <>{`${state.status}:${state.busy}:${state.error}`}</>;
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

test("workspace SmartVA metadata is optional but validated when served", () => {
  expect(parseWorkspace(baseWorkspace, "coding")).not.toHaveProperty("smartva_status");
  expect(parseWorkspace({ ...baseWorkspace, smartva_status: "done", smartva_can_run: false }, "coding")).toMatchObject({
    smartva_status: "done",
    smartva_can_run: false,
  });
  expect(() => parseWorkspace({ ...baseWorkspace, smartva_status: "leaked-result" }, "coding")).toThrow("workspace.smartva_status");
  expect(() => parseWorkspace({ ...baseWorkspace, smartva_can_run: "yes" }, "coding")).toThrow("workspace.smartva_can_run");
});

test("runSmartva uses the allocation-scoped POST and validates the queued reply", async () => {
  const calls: Array<{ path: string; init?: unknown }> = [];
  const api = createWorkspaceApi(async (path, init) => {
    calls.push({ path, init });
    return { va_sid: "sid/1", status: "queued" };
  });
  await expect(api.runSmartva("sid/1", true)).resolves.toEqual({ va_sid: "sid/1", status: "queued" });
  expect(calls).toEqual([{
    path: "/api/v1/coding/submissions/sid%2F1/smartva",
    init: { method: "POST", json: { regenerate: true } },
  }]);
  await expect(createWorkspaceApi(async () => ({ va_sid: "sid/1", status: "unexpected" })).runSmartva("sid/1")).rejects.toBeInstanceOf(WorkspaceContractError);
});

test("status API uses a non-PII GET and validates can_run", async () => {
  const calls: Array<{ path: string; init?: unknown }> = [];
  const api = createWorkspaceApi(async (path, init) => {
    calls.push({ path, init });
    return { va_sid: "sid/1", status: "queued", can_run: true };
  });
  await expect(api.getSmartvaStatus("sid/1")).resolves.toEqual({ va_sid: "sid/1", status: "queued", can_run: true });
  expect(calls).toEqual([{ path: "/api/v1/coding/submissions/sid%2F1/smartva", init: undefined }]);
  await expect(createWorkspaceApi(async () => ({ va_sid: "sid/1", status: "queued", can_run: "yes" })).getSmartvaStatus("sid/1")).rejects.toThrow("smartva.status.can_run");
});

test("coding lifecycle auto-queues once, polls terminal status, and never retries failed", async () => {
  jest.useFakeTimers();
  const getSmartvaStatus = jest.fn()
    .mockResolvedValueOnce({ va_sid: "sid/1", status: "not_requested", can_run: true })
    .mockResolvedValueOnce({ va_sid: "sid/1", status: "queued", can_run: true })
    .mockResolvedValueOnce({ va_sid: "sid/1", status: "done", can_run: true });
  const runSmartva = jest.fn().mockResolvedValue({ va_sid: "sid/1", status: "queued" });
  const onChanged = jest.fn();
  const api = makeApi({ getSmartvaStatus, runSmartva });
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(<LifecycleProbe api={api} onChanged={onChanged} />); await Promise.resolve(); await Promise.resolve(); });
  expect(runSmartva).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(3_000); await Promise.resolve(); await Promise.resolve(); });
  await act(async () => { jest.advanceTimersByTime(3_000); await Promise.resolve(); await Promise.resolve(); });
  expect(getSmartvaStatus).toHaveBeenCalledTimes(3);
  expect(onChanged).toHaveBeenCalledTimes(1);
  const failedApi = makeApi({ getSmartvaStatus: jest.fn(async () => ({ va_sid: "sid/1", status: "failed" as const, can_run: true })), runSmartva: jest.fn() });
  await act(async () => { renderer.update(<LifecycleProbe api={failedApi} />); await Promise.resolve(); await Promise.resolve(); });
  expect(failedApi.runSmartva).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
  jest.useRealTimers();
});

test("coding lifecycle pauses hidden polling and ignores stale case responses", async () => {
  jest.useFakeTimers();
  let resolveStatus!: (value: { va_sid: string; status: "queued"; can_run: boolean }) => void;
  const getSmartvaStatus = jest.fn((_sid: string) => new Promise<{ va_sid: string; status: "queued"; can_run: boolean }>(resolve => { resolveStatus = resolve; }));
  const api = makeApi({ getSmartvaStatus });
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(<LifecycleProbe api={api} />); });
  expect(getSmartvaStatus).toHaveBeenCalledTimes(1);
  await act(async () => { renderer.update(<LifecycleProbe api={api} active={false} />); jest.advanceTimersByTime(9_000); });
  expect(getSmartvaStatus).toHaveBeenCalledTimes(1);
  await act(async () => { resolveStatus({ va_sid: "sid/1", status: "queued", can_run: true }); await Promise.resolve(); });
  await act(async () => { renderer.update(<LifecycleProbe api={api} active />); await Promise.resolve(); });
  expect(getSmartvaStatus).toHaveBeenCalledTimes(2);
  await act(async () => renderer.unmount());
  jest.useRealTimers();
});

test("SmartVA panel mirrors source labels, keeps result details out, and refreshes after queueing", async () => {
  const api = makeApi();
  const changed = jest.fn();
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<SmartvaStatusPanel api={api} identity={{ vaSid: "sid/1", mode: "coding" }} status="done" canRun resultVisible onChanged={changed} />);
  });
  expect(action(renderer, "Regenerate")).toBeDefined();
  expect(JSON.stringify(renderer.toJSON())).toContain("result shown in the assessment steps");
  expect(JSON.stringify(renderer.toJSON())).not.toContain("cause");
  await act(async () => { action(renderer, "Regenerate").props.onPress(); await Promise.resolve(); });
  await settle();
  expect(api.runSmartva).toHaveBeenCalledWith("sid/1", true);
  expect(changed).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(renderer.toJSON())).toContain("Queued");
  await act(async () => { renderer.unmount(); });
});

test("read-only and absent metadata render no run controls", () => {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(<SmartvaStatusPanel api={makeApi()} identity={{ vaSid: "sid/1", mode: "view" }} status="done" canRun={true} />);
  });
  expect(renderer.root.findAll((node) => node.props.accessibilityRole === "button")).toHaveLength(0);
  act(() => renderer.unmount());
  act(() => { renderer = create(<SmartvaStatusPanel api={makeApi()} identity={{ vaSid: "sid/1", mode: "coding" }} />); });
  expect(renderer.toJSON()).toBeNull();
  act(() => renderer.unmount());
});

test("late SmartVA responses cannot update another case or a hidden tab", async () => {
  let resolve!: (value: { va_sid: string; status: "queued" }) => void;
  const oldApi = makeApi({ runSmartva: jest.fn(() => new Promise(resolvePromise => { resolve = resolvePromise; })) });
  const changed = jest.fn();
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<SmartvaStatusPanel api={oldApi} identity={{ vaSid: "sid/1", mode: "coding" }} status="not_requested" canRun onChanged={changed} />);
  });
  await act(async () => { action(renderer, "Run SmartVA").props.onPress(); });
  await act(async () => {
    renderer.update(<SmartvaStatusPanel api={oldApi} identity={{ vaSid: "sid/2", mode: "coding" }} status="not_requested" canRun onChanged={changed} />);
  });
  await act(async () => {
    resolve({ va_sid: "sid/1", status: "queued" });
    await Promise.resolve();
  });
  expect(changed).not.toHaveBeenCalled();
  expect(JSON.stringify(renderer.toJSON())).not.toContain("SmartVA has been queued");
  await act(async () => renderer.unmount());

  const hiddenApi = makeApi({ runSmartva: jest.fn(() => new Promise(resolvePromise => { resolve = resolvePromise; })) });
  const previousDocument = (globalThis as { document?: unknown }).document;
  const fakeDocument = {
    visibilityState: "visible",
    addEventListener: jest.fn((_event: string, listener: () => void) => { visibilityHandler = listener; }),
    removeEventListener: jest.fn(),
  };
  let visibilityHandler: () => void = () => undefined;
  Object.defineProperty(globalThis, "document", { configurable: true, value: fakeDocument });
  await act(async () => {
    renderer = create(<SmartvaStatusPanel api={hiddenApi} identity={{ vaSid: "sid/3", mode: "coding" }} status="not_requested" canRun onChanged={changed} />);
  });
  await act(async () => { action(renderer, "Run SmartVA").props.onPress(); });
  fakeDocument.visibilityState = "hidden";
  await act(async () => { visibilityHandler(); });
  await act(async () => { resolve({ va_sid: "sid/3", status: "queued" }); await Promise.resolve(); });
  expect(changed).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
  if (previousDocument === undefined) delete (globalThis as { document?: unknown }).document;
  else Object.defineProperty(globalThis, "document", { configurable: true, value: previousDocument });
});


test("done SmartVA with masked results explains their current visibility", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(<SmartvaStatusPanel api={makeApi()} identity={{ vaSid: "sid/1", mode: "coding" }} status="done" canRun resultVisible={false} />); });
  expect(JSON.stringify(renderer.toJSON())).toContain("result not displayed in this assessment step");
  expect(JSON.stringify(renderer.toJSON())).not.toContain("result shown in the assessment steps");
  await act(async () => renderer.unmount());
});
