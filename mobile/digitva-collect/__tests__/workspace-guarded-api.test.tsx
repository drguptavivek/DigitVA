/** The guarded api CaseWorkspaceScreen hands SimpleCodPanel stays the same object across unrelated re-renders. */
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
jest.mock("../src/workspace/WorkspaceLayout", () => {
  const React = require("react") as typeof import("react");
  const actual = jest.requireActual("../src/workspace/WorkspaceLayout");
  return { ...actual, WorkspaceLayout: (props: any) => React.createElement(React.Fragment, null, React.createElement(actual.WorkspaceLayout, props), props.notes) };
});

import { CaseWorkspaceScreen } from "../src/workspace/CaseWorkspaceScreen";
import type { WorkspaceApi } from "../src/workspace/api";
import type { WorkspacePayload } from "../src/workspace/contracts";

function workspace(step: "initial" | "final"): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [{ code: "vacodassessment", label: "COD", nav_label: "COD assessment", render_mode: "workflow_panel" }],
    default_category: "vacodassessment", step, blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: step === "final" ? { conclusive_cod: "J18.9" } : null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: [], doris: null, narrative_qa: null, social_autopsy: null,
  } as unknown as WorkspacePayload;
}

function apiFor(payload: WorkspacePayload) {
  return {
    getWorkspace: jest.fn(async () => payload),
    getCategory: jest.fn(async () => ({ code: "vacodassessment", label: "COD", render_mode: "workflow_panel", summary_items: [], subcategories: [] })),
    getWorkflowEvents: jest.fn(async () => ({ va_sid: "sid-1", events: [], limit: 50, next_cursor: null })),
    getNote: jest.fn(async () => ({ va_sid: "sid-1", content: null, updated_at: null })),
    // Queued forever, so useSmartvaLifecycle re-renders the screen every 3 s.
    getSmartvaStatus: jest.fn(async () => ({ status: "running", can_run: false })),
    searchIcd: jest.fn(async () => ({ results: [] })),
    getVaDefinitionForIcd: jest.fn(async () => ({ icd_code: "J18.9", classification: "icd10", va_code: "VAs-01.03", title: "Pneumonia", definition_html: "<p>Lung infection.</p>" })),
  } as unknown as WorkspaceApi;
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

async function mount(api: WorkspaceApi) {
  let tree!: ReactTestRenderer;
  const assertIcd11DorisEnabled = jest.fn(async () => undefined);
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} assertIcd11DorisEnabled={assertIcd11DorisEnabled} />);
    await flush();
  });
  return tree;
}

async function pollThreeTimes() {
  for (let i = 0; i < 3; i += 1) {
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await flush();
    });
  }
}

beforeEach(() => {
  jest.useFakeTimers();
  AppState.currentState = "active";
  jest.spyOn(AppState, "addEventListener").mockImplementation(() => ({ remove: jest.fn() }));
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it("does not refetch the VA definition when SmartVA polling re-renders the screen", async () => {
  const api = apiFor(workspace("final"));
  const tree = await mount(api);
  expect(api.getVaDefinitionForIcd).toHaveBeenCalledTimes(1);
  await pollThreeTimes();
  expect((api.getSmartvaStatus as jest.Mock).mock.calls.length).toBeGreaterThan(2);
  expect(api.getVaDefinitionForIcd).toHaveBeenCalledTimes(1);
  expect(tree.root.findAllByProps({ testID: "va-definition" }).length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});

it("does not resend an ICD search when SmartVA polling re-renders the screen", async () => {
  const api = apiFor(workspace("initial"));
  const tree = await mount(api);
  await act(async () => tree.root.findAllByProps({ accessibilityLabel: "Immediate Cause of Death" }).find((node) => node.props.onChangeText)!.props.onChangeText("stro"));
  await act(async () => {
    jest.advanceTimersByTime(250);
    await flush();
  });
  expect(api.searchIcd).toHaveBeenCalledTimes(1);
  await pollThreeTimes();
  expect(api.searchIcd).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});
