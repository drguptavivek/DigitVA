/** SimpleCodPanel against the Flask ICD-10 Step 1 / Step 2 screens (docs/policy/coder-browser-presentation.md). */
import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { Linking } from "react-native";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    errorText: () => "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
    useUiStyles: () => new Proxy({}, { get: () => undefined }),
  };
});

jest.mock("@drguptavivek/who-2022-va/native", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  const SingleChoice = ({ question, value, onAnswer }: any) => React.createElement(MockView, null, question.choices.map((choice: any) => React.createElement(
    MockPressable,
    { key: choice.value, accessibilityRole: "radio", accessibilityState: { selected: value === choice.value }, testID: `question-${question.name}-choice-${choice.value}`, onPress: () => onAnswer(choice.value) },
    React.createElement(MockText, null, choice.label.en),
  )));
  return { WhoVaQuestionControls: { SingleChoice, MultipleChoice: SingleChoice } };
});

import type { WorkspaceApi } from "../src/workspace/api";
import type { IcdSearchReply, WorkspacePayload } from "../src/workspace/contracts";
import { SimpleCodPanel } from "../src/workspace/SimpleCodPanel";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function workspace(step: "initial" | "final" = "initial"): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [],
    default_category: "vacodassessment",
    step,
    blocked_by: [],
    assessments: {
      initial: step === "final" ? { immediate_cod: "A41.9", antecedent_cod: "J18.9", other_conditions: ["Cough", "Fever"] } : null,
      initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null,
    },
    smartva: null,
    other_conditions_options: ["Cough", "Fever"],
    doris: null,
    narrative_qa: null,
    social_autopsy: null,
  };
}

function apiFor(overrides: Partial<WorkspaceApi> = {}) {
  return {
    saveInitial: jest.fn(async () => ({ va_sid: "sid-1", initial_assessment_id: "initial-1" })),
    saveFinal: jest.fn(async () => ({ va_sid: "sid-1", final_assessment_id: "final-1" })),
    saveNotCodeable: jest.fn(async () => ({ va_sid: "sid-1", workflow_state: "not_codeable" })),
    searchIcd: jest.fn(async (): Promise<IcdSearchReply> => ({ results: [] })),
    getVaDefinitionForIcd: jest.fn(async () => null),
    listVaDefinitions: jest.fn(async () => [
      { va_code: "VAs-01.01", title: "Sepsis", definition_text: "Infection with organ dysfunction." },
      { va_code: "VAs-01.03", title: "Pulmonary tuberculosis", definition_text: "TB of the lungs." },
    ]),
    ...overrides,
  } as unknown as WorkspaceApi;
}

function render(api: WorkspaceApi, payload = workspace(), extra: { onDone?: () => void; serverOrigin?: string; mode?: "coding" | "reviewing" } = {}) {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<SimpleCodPanel workspace={payload} identity={{ vaSid: "sid-1", mode: extra.mode ?? "coding" }} api={api} serverOrigin={extra.serverOrigin} onSaved={async () => undefined} onAllocationLost={jest.fn()} onDone={extra.onDone ?? jest.fn()} />);
  });
  return tree;
}

function control(tree: ReactTestRenderer, label: string): ReactTestInstance {
  const node = tree.root.findAllByProps({ accessibilityLabel: label }).find((candidate) => typeof candidate.props.onPress === "function" || typeof candidate.props.onChangeText === "function");
  if (!node) throw new Error(`Missing control: ${label}`);
  return node;
}

/** The rendered text only (no props), so a code shown once counts once. */
function text(tree: ReactTestRenderer): string {
  const walk = (node: unknown): string => {
    if (typeof node === "string") return node;
    if (Array.isArray(node)) return node.map(walk).join("");
    if (!node || typeof node !== "object") return "";
    return `${walk((node as { children?: unknown }).children)}\n`;
  };
  return walk(tree.toJSON());
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

async function search(tree: ReactTestRenderer, label: string, query: string) {
  await act(async () => control(tree, label).props.onChangeText(query));
  await act(async () => {
    jest.advanceTimersByTime(250);
    await flush();
  });
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it("groups results under Focused and Term matches and shows each code once", async () => {
  const api = apiFor({ searchIcd: jest.fn(async () => ({ results: [
    { icd_code: "A15", icd_to_display: "A15 Respiratory tuberculosis, bacteriologically confirmed", tier: "term" },
    { icd_code: "A16", icd_to_display: "A16 Respiratory tuberculosis, not confirmed", tier: "focused" },
    { icd_code: "A17", icd_to_display: "A17 Tuberculosis of nervous system" },
  ] })) });
  const tree = render(api);
  await search(tree, "Immediate Cause of Death", "tuber");
  const rendered = text(tree);
  expect(rendered).toContain("Focused matches");
  expect(rendered.indexOf("Focused matches")).toBeLessThan(rendered.indexOf("A16 Respiratory"));
  expect(rendered.indexOf("A16 Respiratory")).toBeLessThan(rendered.indexOf("Term matches"));
  expect(rendered.indexOf("Term matches")).toBeLessThan(rendered.indexOf("A15 Respiratory"));
  expect(rendered).toContain("A17 Tuberculosis");
  expect(rendered).not.toContain("—");
  expect(rendered.match(/A16/g)).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("asks for two characters before searching, as Select2 does", async () => {
  const api = apiFor();
  const tree = render(api);
  await act(async () => control(tree, "Immediate Cause of Death").props.onFocus());
  expect(text(tree)).toContain("Please enter 2 or more characters");
  await search(tree, "Immediate Cause of Death", "a");
  expect(text(tree)).toContain("Please enter 1 or more characters");
  expect(api.searchIcd).not.toHaveBeenCalled();
  await search(tree, "Immediate Cause of Death", "ab");
  expect(text(tree)).not.toContain("or more characters");
  expect(api.searchIcd).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("says when matches were hidden for the deceased's age or sex, and Flask's no-results text otherwise", async () => {
  const searchIcd = jest.fn()
    .mockResolvedValueOnce({ results: [], excludedMessage: "3 matching codes are not allowed for this death's age or sex." })
    .mockResolvedValueOnce({ results: [] });
  const tree = render(apiFor({ searchIcd }));
  await search(tree, "Immediate Cause of Death", "pregnan");
  expect(text(tree)).toContain("3 matching codes are not allowed for this death's age or sex.");
  expect(text(tree)).not.toContain("No results found");
  await search(tree, "Immediate Cause of Death", "zzzz");
  expect(text(tree)).toContain("No results found");
  await act(async () => tree.unmount());
});

it("sends a search_id per search and forwards it with the chosen code and 0-based rank on the Step 2 save", async () => {
  const searchIcd = jest.fn(async () => ({ results: [
    { icd_code: "I63", icd_to_display: "I63 Cerebral infarction", tier: "term" },
    { icd_code: "I64", icd_to_display: "I64 Stroke, not specified", tier: "focused" },
  ] }));
  const api = apiFor({ searchIcd });
  const onDone = jest.fn();
  const tree = render(api, workspace("final"), { onDone });
  await search(tree, "Final Underlying / Antecedent Cause of Death", "stro");
  const searchId = (searchIcd.mock.calls[0] as unknown[])[3] as { searchId: string };
  expect(searchIcd).toHaveBeenCalledWith("sid-1", "icd10", "stro", { searchId: expect.stringMatching(UUID) });
  await act(async () => {
    control(tree, "I64 Stroke, not specified").props.onPress();
    await flush();
  });
  await act(async () => {
    control(tree, "Save Assessment").props.onPress();
    await flush();
  });
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", {
    conclusive_cod: "I64", remark: "", cod_search_id: searchId.searchId, cod_chosen_code: "I64", cod_chosen_rank: 1,
  }, "coding");
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("keeps Step 1 saves and a prefilled Step 2 code free of search telemetry", async () => {
  const searchIcd = jest.fn(async () => ({ results: [{ icd_code: "I64", icd_to_display: "I64 Stroke, not specified", tier: "focused" }] }));
  const api = apiFor({ searchIcd });
  const payload = workspace("final");
  payload.assessments.final = { conclusive_cod: "J18.9" };
  const tree = render(api, payload);
  await act(async () => {
    control(tree, "Save Assessment").props.onPress();
    await flush();
  });
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", { conclusive_cod: "J18.9", remark: "" }, "coding");
  await act(async () => tree.unmount());

  const step1 = render(api, workspace("initial"));
  await search(step1, "Immediate Cause of Death", "stro");
  await act(async () => control(step1, "I64 Stroke, not specified").props.onPress());
  await search(step1, "Antecedent Cause of Death", "stro");
  await act(async () => control(step1, "I64 Stroke, not specified").props.onPress());
  await act(async () => {
    control(step1, "Save Assessment").props.onPress();
    await flush();
  });
  expect(api.saveInitial).toHaveBeenCalledWith("sid-1", { immediate_cod: "I64", antecedent_cod: "I64", other_conditions: [] }, "coding");
  await act(async () => step1.unmount());
});

const STROKE = { results: [
  { icd_code: "I63", icd_to_display: "I63 Cerebral infarction", tier: "term" },
  { icd_code: "I64", icd_to_display: "I64 Stroke, not specified", tier: "focused" },
] };

it("forwards search telemetry on a reviewer's final save", async () => {
  const searchIcd = jest.fn(async () => STROKE);
  const api = apiFor({ searchIcd });
  const tree = render(api, workspace("final"), { mode: "reviewing" });
  await search(tree, "Final Underlying / Antecedent Cause of Death", "stro");
  const searchId = ((searchIcd.mock.calls[0] as unknown[])[3] as { searchId: string }).searchId;
  await act(async () => control(tree, "I64 Stroke, not specified").props.onPress());
  await act(async () => {
    control(tree, "Save Assessment").props.onPress();
    await flush();
  });
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", {
    conclusive_cod: "I64", remark: "", cod_search_id: searchId, cod_chosen_code: "I64", cod_chosen_rank: 1,
  }, "reviewing");
  await act(async () => tree.unmount());
});

it("attaches search telemetry to conclusive_cod on an unmasked final save, not to immediate_cod", async () => {
  const searchIcd = jest.fn(async () => STROKE);
  const api = apiFor({ searchIcd });
  const payload = workspace("final");
  payload.case.project_mode = "unmasked_simple";
  const tree = render(api, payload);
  await search(tree, "Immediate cause", "stro");
  await act(async () => control(tree, "I63 Cerebral infarction").props.onPress());
  await search(tree, "Underlying cause", "stro");
  const searchId = ((searchIcd.mock.calls[1] as unknown[])[3] as { searchId: string }).searchId;
  await act(async () => control(tree, "I64 Stroke, not specified").props.onPress());
  await act(async () => {
    control(tree, "Save final assessment").props.onPress();
    await flush();
  });
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", {
    conclusive_cod: "I64", remark: "", immediate_cod: "I63", other_conditions: "",
    cod_search_id: searchId, cod_chosen_code: "I64", cod_chosen_rank: 1,
  }, "coding");
  await act(async () => tree.unmount());
});

it("sends no telemetry for a picked code that is then cleared or retyped before saving", async () => {
  const searchIcd = jest.fn(async () => STROKE);
  const api = apiFor({ searchIcd });
  const tree = render(api, workspace("final"));
  const label = "Final Underlying / Antecedent Cause of Death";
  await search(tree, label, "stro");
  await act(async () => control(tree, "I64 Stroke, not specified").props.onPress());
  // Clearing the box leaves no code, so Save is unavailable and nothing is sent.
  await act(async () => control(tree, label).props.onChangeText(""));
  expect(control(tree, "Save Assessment").props.disabled).toBe(true);
  expect(api.saveFinal).not.toHaveBeenCalled();
  // Retyping and picking again links only to the new search and rank, never the earlier pick.
  await search(tree, label, "stro");
  const second = ((searchIcd.mock.calls[1] as unknown[])[3] as { searchId: string }).searchId;
  await act(async () => control(tree, "I63 Cerebral infarction").props.onPress());
  await act(async () => {
    control(tree, "Save Assessment").props.onPress();
    await flush();
  });
  expect(api.saveFinal).toHaveBeenCalledTimes(1);
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", {
    conclusive_cod: "I63", remark: "", cod_search_id: second, cod_chosen_code: "I63", cod_chosen_rank: 0,
  }, "coding");
  await act(async () => tree.unmount());
});

it("keeps Close in the VA definitions header, before the list and outside the scrolling area", async () => {
  const tree = render(apiFor());
  await act(async () => {
    control(tree, "VA Definitions").props.onPress();
    await flush();
  });
  const rendered = text(tree);
  expect(rendered.indexOf("Close")).toBeGreaterThan(-1);
  expect(rendered.indexOf("Close")).toBeLessThan(rendered.indexOf("VAs-01.01 Sepsis"));
  const header = tree.root.findByProps({ testID: "va-definitions-header" });
  const list = tree.root.findByProps({ testID: "va-definitions-list" });
  expect(header.findAllByProps({ accessibilityLabel: "Close" }).length).toBeGreaterThan(0);
  expect(list.findAllByProps({ accessibilityLabel: "Close" })).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("shows the ICD-10 VA definition under a chosen code, and nothing when none maps", async () => {
  const getVaDefinitionForIcd = jest.fn(async (code: string) => code === "A16"
    ? { icd_code: "A16", classification: "icd10", va_code: "VAs-01.03", title: "Pulmonary tuberculosis", definition_html: "<p>TB <b>of the lungs</b>.</p>" }
    : null);
  const searchIcd = jest.fn(async () => ({ results: [
    { icd_code: "A16", icd_to_display: "A16 Respiratory tuberculosis", tier: "focused" },
    { icd_code: "Z99", icd_to_display: "Z99 Dependence on machines", tier: "term" },
  ] }));
  const tree = render(apiFor({ getVaDefinitionForIcd, searchIcd }));
  await search(tree, "Immediate Cause of Death", "tuber");
  await act(async () => {
    control(tree, "A16 Respiratory tuberculosis").props.onPress();
    await flush();
  });
  expect(getVaDefinitionForIcd).toHaveBeenCalledWith("A16", "icd10");
  expect(control(tree, "Immediate Cause of Death").props.value).toBe("A16 Respiratory tuberculosis");
  const note = tree.root.findAllByProps({ testID: "va-definition" });
  expect(note.length).toBeGreaterThan(0);
  expect(text(tree)).toContain("VAs-01.03 Pulmonary tuberculosis");
  expect(text(tree)).toContain("TB of the lungs");
  expect(text(tree)).not.toContain("<b>");

  await search(tree, "Antecedent Cause of Death", "machine");
  await act(async () => {
    control(tree, "Z99 Dependence on machines").props.onPress();
    await flush();
  });
  expect(getVaDefinitionForIcd).toHaveBeenCalledWith("Z99", "icd10");
  expect(tree.root.findAllByProps({ testID: "va-definition" }).filter((node) => typeof node.type === "string")).toHaveLength(1);
  await act(async () => tree.unmount());
});

it("words Step 1 as Flask: heading, Important box, required marks and hints", async () => {
  const tree = render(apiFor());
  const rendered = text(tree);
  for (const phrase of [
    "Cause of Death Ascertainment - Step 1",
    "Important:",
    "Please choose the most likely antecendent and immediate causes of death.",
    "Immediate Cause of Death",
    "State the disease, injury or complication which caused death, not the mode of dying such as heart failure, asthenia.",
    "Antecedent Cause of Death",
    "copy the Immediate cause if no underlying cause of death can be identified.",
    "Other significant conditions (if any)",
    "Please select other underlying conditions, if any.",
    "Save Assessment",
    "Not Codeable",
  ]) expect(rendered).toContain(phrase);
  expect(rendered.match(/Cause of Death \*/g)).toHaveLength(2);
  await act(async () => tree.unmount());
});

it("shows the coder's Step 1 causes and a previous final above the Step 2 field", async () => {
  const payload = workspace("final");
  let tree = render(apiFor(), payload);
  let rendered = text(tree);
  expect(rendered).toContain("Cause of Death Ascertainment - Step 2");
  expect(rendered).toContain("Your Step 1 Assigned Causes:");
  expect(rendered).toContain("A41.9");
  expect(rendered).toContain("J18.9");
  expect(rendered).toContain("Cough, Fever");
  expect(rendered).not.toContain("Previous Final COD");
  expect(rendered.indexOf("Your Step 1 Assigned Causes:")).toBeLessThan(rendered.indexOf("Final Underlying / Antecedent Cause of Death"));
  await act(async () => tree.unmount());

  tree = render(apiFor(), { ...payload, assessments: { ...payload.assessments, final: { conclusive_cod: "I21.9" } } });
  rendered = text(tree);
  expect(rendered).toContain("Previous Final COD (Before This Recode):");
  expect(rendered).toContain("I21.9");
  await act(async () => tree.unmount());
});

it("opens the WHO browser, the Selected ICD Codes PDF on the server, and the VA definitions list", async () => {
  const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
  const api = apiFor();
  const tree = render(api, workspace(), { serverOrigin: "https://digitva.example/" });
  await act(async () => control(tree, "ICD-10 Browser").props.onPress());
  await act(async () => control(tree, "Selected ICD Codes").props.onPress());
  expect(open).toHaveBeenNthCalledWith(1, "https://icd.who.int/browse10/2019/en");
  expect(open).toHaveBeenNthCalledWith(2, "https://digitva.example/static/WHO_2022_VA_CODES.pdf");
  await act(async () => {
    control(tree, "VA Definitions").props.onPress();
    await flush();
  });
  expect(api.listVaDefinitions).toHaveBeenCalledTimes(1);
  expect(text(tree)).toContain("VAs-01.01 Sepsis");
  await act(async () => control(tree, "Filter VA definitions").props.onChangeText("lungs"));
  expect(text(tree)).not.toContain("VAs-01.01 Sepsis");
  expect(text(tree)).toContain("VAs-01.03 Pulmonary tuberculosis");
  await act(async () => control(tree, "Close").props.onPress());
  expect(text(tree)).not.toContain("VA Codes, Titles and Definitions");
  open.mockRestore();
  await act(async () => tree.unmount());
});

it("goes to the Not Codeable screen and back with entries kept, then reports the issue", async () => {
  const api = apiFor();
  const onDone = jest.fn();
  const payload = workspace();
  payload.assessments.initial_prefill = { immediate_cod: "A00", antecedent_cod: "B00", other_conditions: ["Cough"] };
  const tree = render(api, payload, { onDone });
  await act(async () => control(tree, "Not Codeable").props.onPress());
  let rendered = text(tree);
  expect(rendered).toContain("VA Form Not Codeable");
  expect(rendered).toContain("Once reported an error, this VA form will be flagged for review by the Site PI.");
  expect(tree.root.findAllByProps({ accessibilityLabel: "Save Assessment" })).toHaveLength(0);
  await act(async () => tree.root.findAllByProps({ testID: "question-simple_cod_not_codeable-choice-no_info" }).find((node) => node.props.onPress)!.props.onPress());
  await act(async () => control(tree, "Back to assessment").props.onPress());
  rendered = text(tree);
  expect(rendered).toContain("Selected code: A00");
  expect(rendered).toContain("Selected code: B00");
  expect(tree.root.findAllByProps({ testID: "other-condition-remove-Cough" }).length).toBeGreaterThan(0);
  expect(api.saveNotCodeable).not.toHaveBeenCalled();
  await act(async () => control(tree, "Not Codeable").props.onPress());
  expect(tree.root.findAllByProps({ testID: "question-simple_cod_not_codeable-choice-no_info" }).find((node) => node.props.onPress)!.props.accessibilityState).toEqual({ selected: true });
  await act(async () => {
    control(tree, "Report Issue").props.onPress();
    await flush();
  });
  expect(api.saveNotCodeable).toHaveBeenCalledWith("sid-1", { reason: "no_info", other: "" });
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});
