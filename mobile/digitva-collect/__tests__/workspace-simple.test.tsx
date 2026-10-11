import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { AppState, Platform } from "react-native";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    Screen: ({ title, children, sidebar, headerAction }: { title: string; children: React.ReactNode; sidebar?: React.ReactNode; headerAction?: React.ReactNode }) => React.createElement(MockView, null, React.createElement(MockText, null, title), headerAction, sidebar, children),
    Row: ({ children }: { children: React.ReactNode }) => React.createElement(MockView, null, children),
    errorText: () => "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
  };
});

jest.mock("@drguptavivek/who-2022-va/native", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  const Choice = ({ question, value, onAnswer, multiple }: any) => React.createElement(
    MockView,
    null,
    question.choices.map((choice: any) => {
      const selected = multiple ? value.includes(choice.value) : value === choice.value;
      return React.createElement(
        MockPressable,
        {
          key: choice.value,
          accessibilityRole: multiple ? "checkbox" : "radio",
          accessibilityState: multiple ? { checked: selected, disabled: question.readOnly } : { selected, disabled: question.readOnly },
          disabled: question.readOnly,
          testID: `question-${question.name}-choice-${choice.value}`,
          onPress: () => onAnswer(multiple ? (selected ? value.filter((item: string) => item !== choice.value) : [...value, choice.value]) : choice.value)
        },
        React.createElement(MockText, null, choice.label.en)
      );
    })
  );
  return { WhoVaQuestionControls: { SingleChoice: (props: any) => React.createElement(Choice, { ...props, multiple: false }), MultipleChoice: (props: any) => React.createElement(Choice, { ...props, multiple: true }) } };
});

jest.mock("../src/workspace/WorkspaceLayout", () => {
  const React = require("react") as typeof import("react");
  const actual = jest.requireActual("../src/workspace/WorkspaceLayout");
  return { ...actual, WorkspaceLayout: (props: any) => React.createElement(React.Fragment, null, React.createElement(actual.WorkspaceLayout, props), props.notes) };
});

jest.mock("../src/workspace/CategoryPanel", () => {
  const React = require("react") as typeof import("react");
  const actual = jest.requireActual("../src/workspace/CategoryPanel");
  return { ...actual, CategoryPanel: (props: any) => React.createElement(React.Fragment, null, React.createElement(actual.CategoryPanel, props), props.afterContent) };
});

import { ApiError } from "../src/api";
import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { PrivateNotePanel } from "../src/workspace/PrivateNotePanel";
import { QualityPanels } from "../src/workspace/QualityPanels";
import { CaseWorkspaceScreen } from "../src/workspace/CaseWorkspaceScreen";
import type { WorkspaceApi } from "../src/workspace/api";
import type { CategoryPayload, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";

const category: CategoryPayload = {
  code: "vacodassessment", label: "COD assessment", render_mode: "workflow_panel", summary_items: [],
  subcategories: [{ code: "narration", label: "Narration", render_mode: "default", items: [{ label: "Narration", value: "Interview text", flip: false, info: false }] }],
};

function workspace(mode: WorkspaceIdentity["mode"], step: WorkspacePayload["step"] = "initial"): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [{ code: "vacodassessment", label: "COD", nav_label: "COD assessment", render_mode: "workflow_panel" }],
    default_category: "vacodassessment", step, blocked_by: [],
    assessments: {
      initial: null,
      initial_prefill: mode === "coding" && step === "initial" ? { immediate_cod: "A00", antecedent_cod: "B00", other_conditions: ["Cough"] } : null,
      final: null, not_codeable: null,
      reviewer_initial: mode === "reviewing" && step === "final" ? { immediate_cod: "A00", antecedent_cod: "B00" } : null,
      reviewer_final: mode === "reviewing" && step === "final" ? { conclusive_cod: "C00", immediate_cod: "A00", other_conditions: ["Cough"] } : null,
    },
    smartva: null, other_conditions_options: ["Cough", "Fever"], doris: null, narrative_qa: null, social_autopsy: null,
  };
}

function apiFor(payload: WorkspacePayload, overrides: Partial<WorkspaceApi> = {}) {
  return {
    getWorkspace: jest.fn(async () => payload),
    getCategory: jest.fn(async () => category),
    getWorkflowEvents: jest.fn(async () => ({ va_sid: "sid-1", events: [], limit: 50, next_cursor: null })),
    searchIcd: jest.fn(async () => []),
    getNote: jest.fn(async () => ({ va_sid: "sid-1", content: null, updated_at: null })),
    saveNote: jest.fn(async (_sid: string, _mode: "coding" | "reviewing", content: string) => ({ va_sid: "sid-1", content, updated_at: null })),
    saveInitial: jest.fn(async () => ({ va_sid: "sid-1", initial_assessment_id: "initial-1" })),
    saveFinal: jest.fn(async () => ({ va_sid: "sid-1", final_assessment_id: "final-1" })),
    saveNotCodeable: jest.fn(async () => ({ va_sid: "sid-1", workflow_state: "not_codeable" })),
    saveNarrativeQuality: jest.fn(async () => ({})),
    saveSocialAutopsy: jest.fn(async () => ({})),
  ...overrides,
  } as unknown as WorkspaceApi;
}

function byLabel(tree: ReactTestRenderer, label: string): ReactTestInstance {
  return tree.root.findByProps({ accessibilityLabel: label });
}

function pressByLabel(tree: ReactTestRenderer, label: string) {
  const button = tree.root.findAllByProps({ accessibilityLabel: label })
    .find((node) => typeof node.props.onPress === "function");
  if (!button) throw new Error(`Missing button: ${label}`);
  button.props.onPress();
}

function pressByTestID(tree: ReactTestRenderer, testID: string) {
  const button = tree.root.findAllByProps({ testID }).find((node) => typeof node.props.onPress === "function");
  if (!button) throw new Error(`Missing control: ${testID}`);
  button.props.onPress();
}

function textContent(node: ReactTestInstance): string {
  return node.children.map((child) => typeof child === "string" ? child : textContent(child)).join("");
}

/** Collect host element names to prove untrusted attachment strings stay text. */
function renderedTypes(node: unknown): string[] {
  if (Array.isArray(node)) return node.flatMap(renderedTypes);
  if (!node || typeof node !== "object") return [];
  const value = node as { type?: unknown; children?: unknown };
  return [...(typeof value.type === "string" ? [value.type] : []), ...renderedTypes(value.children)];
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

let changeNativeAppState!: (state: "active" | "background" | "inactive") => void;

beforeEach(() => {
  AppState.currentState = "active";
  jest.spyOn(AppState, "addEventListener").mockImplementation((_type, listener) => {
    changeNativeAppState = listener as typeof changeNativeAppState;
    return { remove: jest.fn() };
  });
});

it("keeps mode=view read-only and loads only the served case history", async () => {
  const api = apiFor(workspace("view", "view"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenCalledWith("sid-1", { limit: 50 });
  expect(api.getNote).not.toHaveBeenCalled();
  expect(api.saveNote).not.toHaveBeenCalled();
  expect(api.saveInitial).not.toHaveBeenCalled();
  expect(api.saveFinal).not.toHaveBeenCalled();
  expect(api.saveNarrativeQuality).not.toHaveBeenCalled();
  expect(api.saveSocialAutopsy).not.toHaveBeenCalled();
  expect(tree.root.findAllByProps({ accessibilityLabel: "Save private note" })).toHaveLength(0);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Save initial COD" })).toHaveLength(0);
  await act(async () => tree.unmount());
});

it.each([
  ["unknown", null],
  ["background", "background"],
] as const)("loads one bounded history page on the first active event after %s", async (_state, initialState) => {
  AppState.currentState = initialState as unknown as typeof AppState.currentState;
  const api = apiFor(workspace("view", "view"));
  let tree!: ReactTestRenderer;
  try {
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
      await flush();
    });
    expect(api.getWorkflowEvents).not.toHaveBeenCalled();
    expect(api.getWorkspace).not.toHaveBeenCalled();
    await act(async () => {
      AppState.currentState = "active";
      changeNativeAppState("active");
      await flush();
    });
    expect(api.getWorkspace).toHaveBeenCalledTimes(1);
    expect(api.getWorkflowEvents).toHaveBeenCalledTimes(1);
    expect(api.getWorkflowEvents).toHaveBeenCalledWith("sid-1", { limit: 50 });
    await act(async () => {
      changeNativeAppState("active");
      await flush();
    });
    expect(api.getWorkspace).toHaveBeenCalledTimes(1);
    expect(api.getWorkflowEvents).toHaveBeenCalledTimes(1);
  } finally {
    if (tree) await act(async () => tree.unmount());
    AppState.currentState = "active";
  }
});

it("does not load a browser workspace until the hidden page becomes visible", async () => {
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  let visibilityState: "visible" | "hidden" = "hidden";
  let changeVisibility!: () => void;
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      get visibilityState() { return visibilityState; },
      addEventListener: (_type: string, listener: () => void) => { changeVisibility = listener; },
      removeEventListener: jest.fn(),
    },
  });
  const api = apiFor(workspace("coding"));
  let tree!: ReactTestRenderer;
  try {
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} />);
      await flush();
    });
    expect(api.getWorkspace).not.toHaveBeenCalled();
    expect(JSON.stringify(tree.toJSON())).not.toContain("Case 1");
    await act(async () => {
      visibilityState = "visible";
      changeVisibility();
      await flush();
    });
    expect(api.getWorkspace).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(tree.toJSON())).toContain("Case 1");
    expect(JSON.stringify(tree.toJSON())).toContain("Interview text");
    await act(async () => {
      changeVisibility();
      await flush();
    });
    expect(api.getWorkspace).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  } finally {
    AppState.currentState = "active";
    if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});

it("ignores delayed workspace and category data when the native app becomes inactive", async () => {
  let finishFirstWorkspace!: (value: WorkspacePayload) => void;
  let finishCategory!: (value: CategoryPayload) => void;
  const api = apiFor(workspace("coding"), {
    getWorkspace: jest.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { finishFirstWorkspace = resolve; }))
      .mockResolvedValue(workspace("coding")),
    getCategory: jest.fn(() => new Promise((resolve) => { finishCategory = resolve; })),
  });
  let tree!: ReactTestRenderer;
  try {
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} />);
      await flush();
    });
    await act(async () => {
      AppState.currentState = "background";
      finishFirstWorkspace(workspace("coding"));
      await flush();
    });
    expect(JSON.stringify(tree.toJSON())).not.toContain("Case 1");
    await act(async () => changeNativeAppState("background"));
    await act(async () => {
      AppState.currentState = "active";
      changeNativeAppState("active");
      await flush();
    });
    expect(api.getWorkspace).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(tree.toJSON())).toContain("Case 1");
    await act(async () => {
      AppState.currentState = "background";
      finishCategory(category);
      await flush();
    });
    expect(JSON.stringify(tree.toJSON())).not.toContain("Interview text");
    await act(async () => tree.unmount());
  } finally {
    AppState.currentState = "active";
  }
});

it.each(["coding", "reviewing"] as const)("does not read workflow events in %s mode", async (mode) => {
  const api = apiFor(workspace(mode));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  expect(api.getWorkflowEvents).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("clears and exits the case when current workflow history access is denied", async () => {
  const onExit = jest.fn();
  const api = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn().mockRejectedValue(new ApiError(403, "forbidden")),
  });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={onExit} />);
    await flush();
  });
  expect(onExit).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(tree.toJSON())).not.toContain("Case 1");
  await act(async () => tree.unmount());
});

it("ignores a delayed workflow-history denial after the case scope changes", async () => {
  let denyOld!: (error: ApiError) => void;
  const oldApi = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn(() => new Promise((_resolve, reject) => { denyOld = reject; })),
  });
  const nextApi = apiFor(workspace("view", "view"));
  const onExit = jest.fn();
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={oldApi} onExit={onExit} />);
    await flush();
  });
  await act(async () => {
    tree.update(<CaseWorkspaceScreen identity={{ vaSid: "sid-2", mode: "view" }} api={nextApi} onExit={onExit} />);
    await flush();
  });
  await act(async () => {
    denyOld(new ApiError(403, "forbidden"));
    await flush();
  });
  expect(onExit).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("Case 1");
  await act(async () => tree.unmount());
});

it("does not dispatch history from a retained callback after the case context changes", async () => {
  const oldApi = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn(async () => ({ va_sid: "sid-1", events: [], limit: 50, next_cursor: "older" })),
  });
  const nextApi = apiFor(workspace("view", "view"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={oldApi} onExit={jest.fn()} />);
    await flush();
  });
  const retainedOlderCallback = byLabel(tree, "Load older events").props.onPress as () => void;
  await act(async () => {
    tree.update(<CaseWorkspaceScreen identity={{ vaSid: "sid-2", mode: "view" }} api={nextApi} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => {
    retainedOlderCallback();
    await flush();
  });
  expect(oldApi.getWorkflowEvents).toHaveBeenCalledTimes(1);
  expect(nextApi.getWorkflowEvents).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

function workflowEvent(id: string, state: string) {
  return {
    event_id: id, transition_id: `transition-${id}`, previous_state: null, current_state: state,
    actor_kind: "system", actor_role: null, transition_reason: null, event_created_at: "2026-10-07T00:00:00Z",
  };
}

it("loads exact newest-first pages and walks the opaque cursor to the final null cursor", async () => {
  const firstPage = Array.from({ length: 50 }, (_, index) => workflowEvent(`new-${index}`, `Newest ${index}`));
  let tree!: ReactTestRenderer;
  const api = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn()
      .mockResolvedValueOnce({ va_sid: "sid-1", events: firstPage, limit: 50, next_cursor: "opaque / cursor+1" })
      .mockResolvedValueOnce({ va_sid: "sid-1", events: [workflowEvent("old", "Older")], limit: 50, next_cursor: null })
      .mockResolvedValueOnce({ va_sid: "sid-1", events: firstPage, limit: 50, next_cursor: "opaque / cursor+1" }),
  });
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenNthCalledWith(1, "sid-1", { limit: 50 });
  expect(tree.root.findAllByProps({ accessibilityLabel: "Load older events" }).length).toBeGreaterThan(0);
  expect(tree.root.findAllByProps({ accessibilityRole: "header" }).map(textContent)).toContain("Workflow history");
  expect(JSON.stringify(tree.toJSON())).toContain("Newest 0");
  expect(JSON.stringify(tree.toJSON())).toContain("Newest 49");
  await act(async () => {
    pressByLabel(tree, "Load older events");
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenNthCalledWith(2, "sid-1", { limit: 50, cursor: "opaque / cursor+1" });
  expect(JSON.stringify(tree.toJSON())).toContain("Older");
  expect(JSON.stringify(tree.toJSON())).not.toContain("Load older events");
  expect(JSON.stringify(tree.toJSON())).toContain("Latest events");
  await act(async () => {
    pressByLabel(tree, "Latest events");
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenNthCalledWith(3, "sid-1", { limit: 50 });
  expect(JSON.stringify(tree.toJSON())).toContain("Newest 0");
  await act(async () => tree.unmount());
});

it("retains a page after an older-page error and retries its exact cursor", async () => {
  const olderError = new Error("temporary error");
  const api = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn()
      .mockResolvedValueOnce({ va_sid: "sid-1", events: [workflowEvent("new", "Newest")], limit: 50, next_cursor: "older-cursor" })
      .mockRejectedValueOnce(olderError)
      .mockResolvedValueOnce({ va_sid: "sid-1", events: [workflowEvent("old", "Older")], limit: 50, next_cursor: null }),
  });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => {
    pressByLabel(tree, "Load older events");
    await flush();
  });
  expect(JSON.stringify(tree.toJSON())).toContain("Newest");
  expect(JSON.stringify(tree.toJSON())).toContain("Generic error");
  await act(async () => {
    pressByLabel(tree, "Retry workflow history");
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenNthCalledWith(3, "sid-1", { limit: 50, cursor: "older-cursor" });
  expect(JSON.stringify(tree.toJSON())).toContain("Older");
  await act(async () => tree.unmount());
});

it("blocks duplicate older-page clicks while a cursor request is in flight", async () => {
  let resolveOlder!: (value: { va_sid: string; events: ReturnType<typeof workflowEvent>[]; limit: number; next_cursor: null }) => void;
  const api = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn()
      .mockResolvedValueOnce({ va_sid: "sid-1", events: [workflowEvent("new", "Newest")], limit: 50, next_cursor: "older-cursor" })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOlder = resolve; })),
  });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => {
    pressByLabel(tree, "Load older events");
    pressByLabel(tree, "Load older events");
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenCalledTimes(2);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Load older events" }).some((node) => node.props.disabled)).toBe(true);
  await act(async () => {
    resolveOlder({ va_sid: "sid-1", events: [workflowEvent("old", "Older")], limit: 50, next_cursor: null });
    await flush();
  });
  await act(async () => tree.unmount());
});

it("clears a hidden workspace and ignores its delayed history response", async () => {
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  let visibilityState: "visible" | "hidden" = "visible";
  let changeVisibility!: () => void;
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: {
      get visibilityState() { return visibilityState; },
      addEventListener: (_type: string, listener: () => void) => { changeVisibility = listener; },
      removeEventListener: jest.fn(),
    },
  });
  let finishHiddenHistory!: (value: { va_sid: string; events: ReturnType<typeof workflowEvent>[]; limit: number; next_cursor: null }) => void;
  const api = apiFor(workspace("view", "view"), {
    getWorkflowEvents: jest.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { finishHiddenHistory = resolve; }))
      .mockResolvedValueOnce({ va_sid: "sid-1", events: [workflowEvent("visible", "Visible again")], limit: 50, next_cursor: null }),
  });
  let tree!: ReactTestRenderer;
  try {
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
      await flush();
    });
    await act(async () => {
      visibilityState = "hidden";
      changeVisibility();
    });
    await act(async () => changeNativeAppState("active"));
    expect(api.getWorkflowEvents).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(tree.toJSON())).not.toContain("Case 1");
    await act(async () => {
      finishHiddenHistory({ va_sid: "sid-1", events: [workflowEvent("hidden", "Hidden response")], limit: 50, next_cursor: null });
      await flush();
    });
    expect(JSON.stringify(tree.toJSON())).not.toContain("Hidden response");
    await act(async () => {
      visibilityState = "visible";
      changeVisibility();
      await flush();
    });
    expect(JSON.stringify(tree.toJSON())).toContain("Visible again");
    expect(api.getWorkflowEvents).toHaveBeenCalledTimes(2);
    await act(async () => tree.unmount());
  } finally {
    AppState.currentState = "active";
    if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
    else Reflect.deleteProperty(globalThis, "document");
  }
});

it.each([
  ["case", "view" as const, "view" as const, "sid-2", false, false],
  ["account API", "view" as const, "view" as const, "sid-1", true, true],
  ["mode", "view" as const, "coding" as const, "sid-1", false, false],
  ["case", "view" as const, "view" as const, "sid-2", false, true],
  ["account API", "view" as const, "view" as const, "sid-1", true, false],
  ["mode", "view" as const, "coding" as const, "sid-1", false, true],
])("ignores delayed workflow history completion after %s changes", async (_scope, oldMode, nextMode, nextSid, replaceApi, denied) => {
  let finishOld!: (value: { va_sid: string; events: ReturnType<typeof workflowEvent>[]; limit: number; next_cursor: null }) => void;
  let denyOld!: (error: ApiError) => void;
  let oldPending = true;
  const oldApi = apiFor(workspace(oldMode, oldMode), {
    getWorkflowEvents: jest.fn().mockImplementationOnce(() => new Promise((_resolve, reject) => {
      finishOld = (value) => { oldPending = false; _resolve(value); };
      denyOld = (error) => { oldPending = false; reject(error); };
    })).mockImplementation(async (vaSid: string) => ({ va_sid: vaSid, events: [], limit: 50, next_cursor: null })),
  });
  const nextStep = nextMode === "view" ? "view" : "initial";
  const nextApi = replaceApi ? apiFor(workspace(nextMode, nextStep)) : oldApi;
  const onExit = jest.fn();
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: oldMode }} api={oldApi} onExit={onExit} />);
    await flush();
  });
  await act(async () => {
    tree.update(<CaseWorkspaceScreen identity={{ vaSid: nextSid, mode: nextMode }} api={nextApi} onExit={onExit} />);
    await flush();
  });
  if (oldPending) {
    await act(async () => {
      if (denied) denyOld(new ApiError(403, "forbidden"));
      else finishOld({ va_sid: "sid-1", events: [workflowEvent("stale", "Stale")], limit: 50, next_cursor: null });
      await flush();
    });
  }
  expect(onExit).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).not.toContain("Stale");
  await act(async () => tree.unmount());
});

it("shows a recoverable ICD search error without clearing entered text", async () => {
  jest.useFakeTimers();
  try {
    const payload = workspace("coding");
    payload.assessments.initial_prefill = null;
    const api = apiFor(payload, { searchIcd: jest.fn().mockRejectedValue(new ApiError(500, "server_error")) });
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} />);
      await flush();
    });
    await act(async () => {
      byLabel(tree, "Immediate cause").props.onChangeText("stroke");
      await flush();
    });
    await act(async () => {
      jest.advanceTimersByTime(250);
      await flush();
    });
    expect(api.searchIcd).toHaveBeenCalledWith("sid-1", "icd10", "stroke");
    expect(byLabel(tree, "Immediate cause").props.value).toBe("stroke");
    expect(tree.root.findAll((node) => node.props.accessibilityRole === "alert").map(textContent).join(" "))
      .toContain("Unable to search ICD codes. Try again.");
    await act(async () => tree.unmount());
  } finally {
    jest.useRealTimers();
  }
});

it("ignores a delayed ICD 403 after the case scope changes", async () => {
  jest.useFakeTimers();
  try {
    let denyOld!: (error: ApiError) => void;
    const payload = workspace("coding");
    payload.assessments.initial_prefill = null;
    const oldApi = apiFor(payload, {
      searchIcd: jest.fn(() => new Promise((_resolve, reject) => { denyOld = reject; })),
    });
    const nextApi = apiFor(payload);
    const onExit = jest.fn();
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={oldApi} onExit={onExit} />);
      await flush();
    });
    await act(async () => {
      byLabel(tree, "Immediate cause").props.onChangeText("stroke");
      await flush();
    });
    await act(async () => { jest.advanceTimersByTime(250); await flush(); });
    await act(async () => {
      tree.update(<CaseWorkspaceScreen identity={{ vaSid: "sid-2", mode: "coding" }} api={nextApi} onExit={onExit} />);
      await flush();
    });
    await act(async () => {
      denyOld(new ApiError(403, "forbidden"));
      await flush();
    });
    expect(onExit).not.toHaveBeenCalled();
    expect(JSON.stringify(tree.toJSON())).toContain("Case 1");
    await act(async () => tree.unmount());
  } finally {
    jest.useRealTimers();
  }
});

it("exits and clears the case when current ICD search access is denied", async () => {
  jest.useFakeTimers();
  try {
    const payload = workspace("coding");
    payload.assessments.initial_prefill = null;
    const api = apiFor(payload, { searchIcd: jest.fn().mockRejectedValue(new ApiError(403, "forbidden")) });
    const onExit = jest.fn();
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={onExit} />);
      await flush();
    });
    await act(async () => {
      byLabel(tree, "Immediate cause").props.onChangeText("stroke");
      await flush();
    });
    await act(async () => { jest.advanceTimersByTime(250); await flush(); });
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(tree.toJSON())).not.toContain("Case 1");
    await act(async () => tree.unmount());
  } finally {
    jest.useRealTimers();
  }
});

it("routes only API attachment paths to media and renders object values with readable labels", async () => {
  const media = jest.fn((path: string) => `media:${path}`);
  const fixture: CategoryPayload = {
    ...category,
    subcategories: [{
      code: "evidence", label: "Evidence", render_mode: "media_gallery",
      items: [
        { label: "Medical image", value: "/api/v1/attachments/abc123.jpg", flip: false, info: false },
        { label: "Narration", value: "https://example.invalid/file", flip: false, info: false },
        { label: "SmartVA", value: { causes: [{ rank: 1, cause: "Cause", icd10: "A00" }] }, flip: false, info: false },
      ],
    }],
  };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<CategoryPanel category={fixture} renderMedia={media} />); });
  expect(media).toHaveBeenCalledTimes(1);
  expect(media).toHaveBeenCalledWith("/api/v1/attachments/abc123.jpg");
  expect(JSON.stringify(tree.toJSON())).toContain("ICD-10");
  expect(renderedTypes(tree.toJSON())).not.toContain("img");
  await act(async () => tree.unmount());
});

it("saves the editable initial prefill and reloads the workspace", async () => {
  const api = apiFor(workspace("coding"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => byLabel(tree, "Save initial COD").props.onPress());
  await flush();
  expect(api.saveInitial).toHaveBeenCalledWith("sid-1", {
    immediate_cod: "A00", antecedent_cod: "B00", other_conditions: ["Cough"],
  }, "coding");
  expect(api.getWorkspace).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("ignores an initial-save completion after the case identity changes", async () => {
  let finishSave!: (value: { va_sid: string; initial_assessment_id: string }) => void;
  const oldApi = apiFor(workspace("coding"), {
    saveInitial: jest.fn(() => new Promise((resolve) => { finishSave = resolve; })),
  });
  const nextApi = apiFor(workspace("coding"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={oldApi} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => byLabel(tree, "Save initial COD").props.onPress());
  await act(async () => {
    tree.update(<CaseWorkspaceScreen identity={{ vaSid: "sid-2", mode: "coding" }} api={nextApi} onExit={jest.fn()} />);
    await flush();
  });
  await act(async () => {
    finishSave({ va_sid: "sid-1", initial_assessment_id: "initial-1" });
    await flush();
  });
  expect(oldApi.getWorkspace).toHaveBeenCalledTimes(1);
  expect(nextApi.getWorkspace).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("sends the simple final payload and completes reviewer work", async () => {
  const finalWorkspace = workspace("reviewing", "final");
  finalWorkspace.case.project_mode = "unmasked_simple";
  const api = apiFor(finalWorkspace);
  const onDone = jest.fn();
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "reviewing" }} api={api} onExit={jest.fn()} onDone={onDone} />);
    await flush();
  });
  await act(async () => byLabel(tree, "Save final COD").props.onPress());
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", { conclusive_cod: "C00", remark: "", immediate_cod: "A00", other_conditions: "Cough" }, "reviewing");
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("keeps narrative field order and makes None exclusive while answering every SA level", async () => {
  const onSaveNarrative = jest.fn(async () => undefined);
  const onSaveSocialAutopsy = jest.fn(async () => undefined);
  const data = {
    fields: [
      { key: "length", label: "Narrative length", options: [{ value: 0, label: "Poor" }, { value: 2, label: "Good" }] },
      { key: "chronology", label: "Chronology", options: [{ value: 0, label: "Poor" }, { value: 2, label: "Good" }] },
    ], max_score: 10, saved: null,
  };
  const social = { questions: [
    { delay_level: "1", title: "First delay", options: [{ option_code: "none", label: "None", description: "" }, { option_code: "factor", label: "Factor", description: "" }] },
    { delay_level: "2", title: "Second delay", options: [{ option_code: "factor", label: "Factor", description: "" }] },
  ], saved: null };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<QualityPanels narrative={data} socialAutopsy={social} onSaveNarrative={onSaveNarrative} onSaveSocialAutopsy={onSaveSocialAutopsy} />); });
  const rendered = JSON.stringify(tree.toJSON());
  expect(rendered.indexOf("Narrative length")).toBeLessThan(rendered.indexOf("Chronology"));
  expect(() => tree.root.findByProps({ testID: "question-nqa_length-choice-2" })).not.toThrow();
  expect(() => tree.root.findByProps({ testID: "question-nqa_chronology-choice-2" })).not.toThrow();
  for (const testID of ["question-nqa_length-choice-2", "question-nqa_chronology-choice-2", "question-social_autopsy_1-choice-factor", "question-social_autopsy_1-choice-none", "question-social_autopsy_2-choice-factor"]) {
    await act(async () => pressByTestID(tree, testID));
  }
  await act(async () => pressByTestID(tree, "question-social_autopsy_1-choice-factor"));
  expect(tree.root.findByProps({ testID: "question-social_autopsy_1-choice-none" }).props.accessibilityState).toEqual({ checked: false, disabled: false });
  expect(tree.root.findByProps({ testID: "question-social_autopsy_1-choice-factor" }).props.accessibilityState).toEqual({ checked: true, disabled: false });
  await act(async () => pressByTestID(tree, "question-social_autopsy_1-choice-none"));
  await act(async () => byLabel(tree, "Save narrative quality").props.onPress());
  await act(async () => byLabel(tree, "Save social autopsy").props.onPress());
  expect(onSaveNarrative).toHaveBeenCalledWith({ cannot_grade: false, length: 2, chronology: 2 });
  expect(onSaveSocialAutopsy).toHaveBeenCalledWith({
    selected_options: [{ delay_level: "1", option_code: "none" }, { delay_level: "2", option_code: "factor" }], remark: "",
  });
  await act(async () => tree.unmount());
});

it("rejects blank and over-limit private notes before writing", async () => {
  const api = apiFor(workspace("coding"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<PrivateNotePanel identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onAllocationLost={jest.fn()} />);
    await flush();
  });
  const input = byLabel(tree, "Private note");
  await act(async () => input.props.onChangeText("   "));
  await act(async () => byLabel(tree, "Save private note").props.onPress());
  expect(api.saveNote).not.toHaveBeenCalled();
  await act(async () => byLabel(tree, "Private note").props.onChangeText("x".repeat(20_001)));
  expect(byLabel(tree, "Private note").props.value).toHaveLength(20_001);
  await act(async () => byLabel(tree, "Save private note").props.onPress());
  expect(api.saveNote).not.toHaveBeenCalled();
  expect(tree.root.findAll((node) => node.props.accessibilityRole === "alert").map(textContent).join(" ")).toContain("Notes are limited to 20,000 characters.");
  await act(async () => tree.unmount());
});

it("clears the note and exits when the allocation is lost", async () => {
  const onAllocationLost = jest.fn();
  const api = apiFor(workspace("coding"), { getNote: jest.fn().mockRejectedValue(new ApiError(403, "no_allocation")) });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<PrivateNotePanel identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onAllocationLost={onAllocationLost} />);
    await flush();
  });
  expect(onAllocationLost).toHaveBeenCalledTimes(1);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Private note" })).toHaveLength(0);
  await act(async () => tree.unmount());
});


it("updates the narrative score and exposes checked radio state before saving", async () => {
  let tree!: ReactTestRenderer;
  const narrative = { fields: [{ key: "q1", label: "Detail", options: [{ value: 2, label: "Complete" }] }], max_score: 2, saved: null };
  await act(async () => { tree = create(<QualityPanels narrative={narrative} socialAutopsy={null} onSaveNarrative={jest.fn()} onSaveSocialAutopsy={jest.fn()} />); });
  expect(JSON.stringify(tree.toJSON())).toContain("Not Assessed");
  await act(async () => pressByTestID(tree, "question-nqa_q1-choice-2"));
  expect(tree.root.findByProps({ testID: "question-nqa_q1-choice-2" }).props.accessibilityState).toEqual({ selected: true, disabled: false });
  expect(textContent(tree.root)).toContain("Score: 2 / 2 · Poor");
  await act(async () => pressByTestID(tree, "question-nqa-cannot_grade-choice-cannot_grade"));
  expect(textContent(tree.root)).toContain("Score: 0 / 2 · Cannot Grade");
  expect(tree.root.findByProps({ testID: "question-nqa_q1-choice-2" }).props.accessibilityState).toEqual({ selected: true, disabled: true });
  expect(tree.root.findByProps({ testID: "question-nqa-cannot_grade-choice-cannot_grade" }).props.accessibilityState).toEqual({ checked: true, disabled: false });
  await act(async () => tree.unmount());
});

it("keeps the browser category and unsaved private note through a quality refresh", async () => {
  const priorOS = Platform.OS;
  Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
  const payload = workspace("coding");
  payload.categories.push({ code: "docs", label: "Documents", nav_label: "Documents", render_mode: "attachments" });
  payload.narrative_qa = { fields: [], max_score: 0, saved: null };
  const api = apiFor(payload, { getCategory: jest.fn(async (_sid, code) => ({ ...category, code, render_mode: code === "docs" ? "attachments" : "workflow_panel" })) });
  let tree!: ReactTestRenderer;
  try {
    await act(async () => { tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} />); await flush(); });
    const layout = tree.root.findByProps({ selectedCode: "vacodassessment" });
    await act(async () => { layout.props.onSelectCategory("docs"); await flush(); });
    const note = tree.root.findByType(PrivateNotePanel);
    const input = note.findAll((node) => typeof node.props.onChangeText === "function")[0];
    expect(input).toBeDefined();
    await act(async () => input.props.onChangeText("unsaved draft"));
    const quality = tree.root.findByType(QualityPanels);
    expect(quality.props.narrative).toBe(payload.narrative_qa);
    expect(quality.props.socialAutopsy).toBeNull();
    await act(async () => { await quality.props.onSaveNarrative({ cannot_grade: true }); await flush(); });
    expect(api.getCategory).toHaveBeenLastCalledWith("sid-1", "docs", "coding");
    const currentInput = tree.root.findByType(PrivateNotePanel).findAll((node) => typeof node.props.onChangeText === "function")[0];
    expect(currentInput.props.value).toBe("unsaved draft");
    expect(api.saveNote).not.toHaveBeenCalled();
  } finally {
    if (tree) await act(async () => tree.unmount());
    Object.defineProperty(Platform, "OS", { configurable: true, value: priorOS });
  }
});
