import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
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
          accessibilityLabel: `${question.label.en}: ${choice.label.en}`,
          accessibilityState: multiple ? { checked: selected, disabled: question.readOnly } : { selected, disabled: question.readOnly },
          disabled: question.readOnly,
          testID: `question-${question.name}-choice-${choice.value}`,
          onPress: () => onAnswer(multiple ? (selected ? value.filter((item: string) => item !== choice.value) : [...value, choice.value]) : choice.value),
        },
        React.createElement(MockText, null, choice.label.en),
      );
    }),
  );
  return { WhoVaQuestionControls: { SingleChoice: (props: any) => React.createElement(Choice, { ...props, multiple: false }), MultipleChoice: (props: any) => React.createElement(Choice, { ...props, multiple: true }) } };
});

import type { WorkspaceApi } from "../src/workspace/api";
import type { WorkspacePayload } from "../src/workspace/contracts";
import { SimpleCodPanel } from "../src/workspace/SimpleCodPanel";

function workspace(): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [],
    default_category: "vacodassessment",
    step: "initial",
    blocked_by: [],
    assessments: { initial: null, initial_prefill: { immediate_cod: "A00", antecedent_cod: "B00", other_conditions: ["Cough"] }, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
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
    searchIcd: jest.fn(async () => []),
    ...overrides,
  } as unknown as WorkspaceApi;
}

function byTestId(tree: ReactTestRenderer, testID: string): ReactTestInstance {
  const node = tree.root.findAllByProps({ testID }).find((candidate) => typeof candidate.props.onPress === "function");
  if (!node) throw new Error(`Missing control: ${testID}`);
  return node;
}

function byLabel(tree: ReactTestRenderer, accessibilityLabel: string): ReactTestInstance {
  const node = tree.root.findAllByProps({ accessibilityLabel }).find((candidate) => typeof candidate.props.onPress === "function" || typeof candidate.props.onChangeText === "function");
  if (!node) throw new Error(`Missing control: ${accessibilityLabel}`);
  return node;
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

it("uses WHO multiple choice controls while preserving option order and save payload", async () => {
  const api = apiFor();
  const { tree } = render(api);
  const cough = byTestId(tree, "question-simple_cod_other_conditions-choice-Cough");
  const fever = byTestId(tree, "question-simple_cod_other_conditions-choice-Fever");
  expect(cough.props.accessibilityState).toEqual({ checked: true, disabled: false });
  expect(fever.props.accessibilityState).toEqual({ checked: false, disabled: false });
  await act(async () => {
    fever.props.onPress();
    await flush();
  });
  expect(api.saveInitial).not.toHaveBeenCalled();
  await act(async () => {
    byLabel(tree, "Save initial COD").props.onPress();
    await flush();
  });
  expect(api.saveInitial).toHaveBeenCalledWith("sid-1", { immediate_cod: "A00", antecedent_cod: "B00", other_conditions: ["Cough", "Fever"] }, "coding");
  await act(async () => tree.unmount());
});

it("keeps not-codeable reasons exclusive and submits the documented reason payload", async () => {
  const api = apiFor();
  const { tree } = render(api);
  await act(async () => {
    byTestId(tree, "question-simple_cod_not_codeable-choice-no_info").props.onPress();
    await flush();
  });
  expect(byTestId(tree, "question-simple_cod_not_codeable-choice-no_info").props.accessibilityState).toEqual({ selected: true, disabled: false });
  await act(async () => {
    byTestId(tree, "question-simple_cod_not_codeable-choice-others").props.onPress();
    await flush();
  });
  expect(byTestId(tree, "question-simple_cod_not_codeable-choice-no_info").props.accessibilityState).toEqual({ selected: false, disabled: false });
  const otherInput = byLabel(tree, "Other not-codeable reason");
  await act(async () => otherInput.props.onChangeText("No usable information"));
  await act(async () => {
    byLabel(tree, "Submit not-codeable report").props.onPress();
    await flush();
  });
  expect(api.saveNotCodeable).toHaveBeenCalledWith("sid-1", { reason: "others", other: "No usable information" });
  await act(async () => tree.unmount());
});

function render(api: WorkspaceApi) {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<SimpleCodPanel workspace={workspace()} identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onSaved={async () => undefined} onAllocationLost={jest.fn()} onDone={jest.fn()} />);
  });
  return { tree };
}
