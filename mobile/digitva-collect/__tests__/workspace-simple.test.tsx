import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

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
    getWorkflowEvents: jest.fn(async () => ({ va_sid: "sid-1", events: [] })),
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

it("keeps mode=view read-only and loads only the served case history", async () => {
  const api = apiFor(workspace("view", "view"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "view" }} api={api} onExit={jest.fn()} />);
    await flush();
  });
  expect(api.getWorkflowEvents).toHaveBeenCalledWith("sid-1");
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
  expect(rendered.indexOf("Narrative length: Poor")).toBeLessThan(rendered.indexOf("Chronology: Poor"));
  expect(() => byLabel(tree, "Narrative length: Good")).not.toThrow();
  expect(() => byLabel(tree, "Chronology: Good")).not.toThrow();
  for (const label of ["Narrative length: Good", "Chronology: Good", "First delay: Factor", "First delay: None", "Second delay: Factor"]) {
    await act(async () => byLabel(tree, label).props.onPress());
  }
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
