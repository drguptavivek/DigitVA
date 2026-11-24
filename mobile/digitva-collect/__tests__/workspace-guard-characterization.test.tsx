/**
 * Characterization (digitva-r8nh.24): the api CaseWorkspaceScreen hands its COD editors guards exactly these nine
 * methods with the ICD-11 editor gate, checks the gate before the call, refuses a stale workspace, and is the
 * plain api when no gate is supplied. A method added to or dropped from the guard changes this list.
 */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { AppState } from "react-native";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    Screen: ({ title, children, sidebar, headerAction }: { title: string; children: React.ReactNode; sidebar?: React.ReactNode; headerAction?: React.ReactNode }) => React.createElement(MockView, null, React.createElement(MockText, null, title), headerAction, sidebar, children),
    Row: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
    errorText: () => "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
    useUiStyles: () => new Proxy({}, { get: () => undefined }),
  };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({ WhoVaQuestionControls: { SingleChoice: () => null, MultipleChoice: () => null } }));

import { CaseWorkspaceScreen } from "../src/workspace/CaseWorkspaceScreen";
import type { WorkspaceApi } from "../src/workspace/api";
import type { WorkspacePayload } from "../src/workspace/contracts";

const GUARDED = [
  "checkDorisSelection",
  "getDorisCodeInfo",
  "getVaDefinitionForIcd",
  "processDoris",
  "saveFinal",
  "saveInitial",
  "saveNotCodeable",
  "searchDorisTerms",
  "searchIcd",
];

const ALL_METHODS = [
  "allocateCoding", "allocateReviewer", "checkDorisSelection", "codeOwnSubmission", "getCategory", "getCertificate",
  "getCodingAllocation", "getCodingAvailable", "getCodingHistory", "getCodingProjects", "getCodingStats", "getDorisCodeInfo",
  "getNote", "getReviewerAllocation", "getReviewerAvailable", "getReviewerHistory", "getReviewerProjects", "getReviewerStats",
  "getSmartvaStatus", "getVaDefinitionForIcd", "getWorkflowEvents", "getWorkspace", "listVaDefinitions", "processDoris",
  "recode", "releaseCoding", "releaseReviewer", "runSmartva", "saveFinal", "saveInitial", "saveNarrativeQuality",
  "saveNotCodeable", "saveNote", "saveSocialAutopsy", "searchDorisTerms", "searchIcd",
];

function payload(version: string): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "unmasked_doris", icd_classification: "icd11", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false, payload_version_id: version },
    categories: [{ code: "vacodassessment", label: "COD", nav_label: "COD assessment", render_mode: "workflow_panel" }],
    default_category: "vacodassessment", step: "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
  } as unknown as WorkspacePayload;
}

const category = { code: "vacodassessment", label: "COD", render_mode: "workflow_panel", summary_items: [], subcategories: [] };

function apiFor(current: { payload: WorkspacePayload }) {
  const api: Record<string, jest.Mock> = {};
  for (const name of ALL_METHODS) api[name] = jest.fn(async () => ({ answeredBy: name }));
  api.getWorkspace = jest.fn(async () => current.payload);
  api.getCategory = jest.fn(async () => category);
  api.getWorkflowEvents = jest.fn(async () => ({ va_sid: "sid-1", events: [], limit: 50, next_cursor: null }));
  api.getNote = jest.fn(async () => ({ va_sid: "sid-1", content: null, updated_at: null }));
  api.getSmartvaStatus = jest.fn(async () => ({ va_sid: "sid-1", status: "not_requested", can_run: false }));
  return api as unknown as WorkspaceApi & Record<string, jest.Mock>;
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

async function mount(api: WorkspaceApi, gate?: () => Promise<void>) {
  let tree!: ReactTestRenderer;
  let guarded: WorkspaceApi | undefined;
  let reload: (() => Promise<void>) | undefined;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen
      identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()}
      icd11DorisEnabled={true}
      assertIcd11DorisEnabled={gate}
      renderDoris={(_workspace, onSaved, _onDone, provided) => { guarded = provided; reload = onSaved; return null; }}
    />);
    await flush();
  });
  if (!guarded || !reload) throw new Error("DORIS slot not rendered");
  return { tree, guarded: guarded as WorkspaceApi & Record<string, (...args: unknown[]) => Promise<unknown>>, reload };
}

beforeEach(() => {
  AppState.currentState = "active";
  jest.spyOn(AppState, "addEventListener").mockImplementation(() => ({ remove: jest.fn() }));
});
afterEach(() => jest.restoreAllMocks());

it("guards exactly the nine COD editor methods with the gate, and no other method", async () => {
  const api = apiFor({ payload: payload("v1") });
  const gate = jest.fn(async () => { throw new Error("icd11_doris_disabled"); });
  const { tree, guarded } = await mount(api, gate);
  expect(Object.keys(guarded).sort()).toEqual(ALL_METHODS);

  const refused: string[] = [];
  for (const name of ALL_METHODS) {
    api[name].mockClear();
    gate.mockClear();
    let rejected: unknown;
    try { await guarded[name]("sid-1", "x", "y", {}); } catch (error) { rejected = error; }
    if (rejected) {
      expect((rejected as Error).message).toBe("icd11_doris_disabled");
      expect(gate).toHaveBeenCalledTimes(1);
      expect(api[name]).not.toHaveBeenCalled();
      refused.push(name);
    } else {
      expect(gate).not.toHaveBeenCalled();
      expect(api[name]).toHaveBeenCalledTimes(1);
    }
  }
  expect(refused.sort()).toEqual(GUARDED);
  await act(async () => tree.unmount());
});

it("checks the gate before each guarded call and passes the arguments and reply through", async () => {
  const api = apiFor({ payload: payload("v1") });
  const gate = jest.fn(async () => undefined);
  const { tree, guarded } = await mount(api, gate);
  for (const name of GUARDED) {
    api[name].mockClear();
    gate.mockClear();
    await expect(guarded[name]("sid-1", "a", "b", { c: 1 })).resolves.toEqual({ answeredBy: name });
    expect(api[name]).toHaveBeenCalledWith("sid-1", "a", "b", { c: 1 });
    expect(gate.mock.invocationCallOrder[0]).toBeLessThan(api[name].mock.invocationCallOrder[0]);
  }
  await act(async () => tree.unmount());
});

it("refuses a guarded call from an api handed out for an older workspace", async () => {
  const current = { payload: payload("v1") };
  const api = apiFor(current);
  const gate = jest.fn(async () => undefined);
  const { tree, guarded: old, reload } = await mount(api, gate);
  current.payload = payload("v2");
  await act(async () => { await reload(); await flush(); });
  for (const name of GUARDED) {
    api[name].mockClear();
    await expect(old[name]("sid-1", "a")).rejects.toThrow("workspace_stale");
    expect(api[name]).not.toHaveBeenCalled();
  }
  await expect(old.getNote("sid-1", "coding")).resolves.toBeDefined();
  await act(async () => tree.unmount());
});

it("hands over the plain api when no gate is supplied", async () => {
  const api = apiFor({ payload: payload("v1") });
  const { tree, guarded } = await mount(api);
  expect(guarded).toBe(api);
  await act(async () => tree.unmount());
});
