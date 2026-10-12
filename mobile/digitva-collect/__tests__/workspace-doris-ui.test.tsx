import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    errorText: (error: unknown) => error instanceof Error ? error.message : "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
    useUiStyles: () => new Proxy({}, { get: () => undefined }),
  };
});

const mockTheme: { mode: "light" | "dark" } = { mode: "light" };
jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme(mockTheme.mode) };
});

jest.mock("@drguptavivek/who-2022-va/native", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  const Choice = ({ question, value, onAnswer }: any) => React.createElement(MockView, null, question.choices.map((choice: any) => React.createElement(MockPressable, { key: choice.value, accessibilityRole: "radio", accessibilityLabel: `${question.label.en}: ${choice.label.en}`, accessibilityState: { selected: value === choice.value, disabled: question.readOnly }, disabled: question.readOnly, testID: `question-${question.name}-choice-${choice.value}`, onPress: () => onAnswer(choice.value) }, React.createElement(MockText, null, choice.label.en))));
  return { WhoVaQuestionControls: { SingleChoice: (props: any) => React.createElement(Choice, props), MultipleChoice: (props: any) => React.createElement(Choice, props) } };
});

const mockFrame: { props: any } = { props: null };
jest.mock("../src/workspace/doris/IcdPickerFrame", () => ({ IcdPickerFrame: (props: any) => { mockFrame.props = props; return null; } }));

import { ui } from "../src/theme";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import type { DorisProcessReply, JsonObject, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";
import { DorisPanel } from "../src/workspace/doris/DorisPanel";

const identity: WorkspaceIdentity = { vaSid: "sid-1", mode: "coding" };
const line = { Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] };
const reply: DorisProcessReply = {
  schema_version: 1, client_revision: 0, icd_release: "2025-01", certificate: { ICDVersion: "ICD11", Part1: [line] }, certificate_digest: "d", result_digest: "r",
  doris: { status: "completed", result: { code: "CA40" } }, codedit: { status: "completed", result: {} }, process_token: "t",
};

function workspace(seed: JsonObject, age?: string | number | null): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: "unmasked_doris", icd_classification: "icd11", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false, ...(age !== undefined ? { age } : {}) },
    categories: [], default_category: "vacodassessment", step: "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: null,
    doris: { initial_certificate: { ICDVersion: "ICD11", Part1: [line], ...seed }, prefill_provenance: {}, saved_processing: null, step1_certificate: null, step1_processing: null },
    narrative_qa: null, social_autopsy: null,
  };
}

const api = () => ({ processDoris: jest.fn(async () => reply) }) as unknown as WorkspaceApi & { processDoris: jest.Mock };

function render(seed: JsonObject, a = api(), age?: string | number | null) {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<DorisPanel workspace={workspace(seed, age)} identity={identity} api={a} request={jest.fn(async () => ({})) as unknown as JsonRequester} onSaved={async () => undefined} onDone={jest.fn()} />); });
  return { tree, api: a };
}

const has = (tree: ReactTestRenderer, label: string) => tree.root.findAllByProps({ accessibilityLabel: label }).length > 0;
const label = (tree: ReactTestRenderer, l: string) => tree.root.findAllByProps({ accessibilityLabel: l })[0];
const warn = (tree: ReactTestRenderer, key: string) => tree.root.findAllByProps({ testID: `warn-${key}` });
async function process(tree: ReactTestRenderer) {
  await act(async () => { label(tree, "Process current certificate").props.onPress(); await Promise.resolve(); await Promise.resolve(); });
}
function allText(tree: ReactTestRenderer): string {
  const out: string[] = [];
  const walk = (node: any) => { if (typeof node === "string") out.push(node); else if (node?.children) node.children.forEach(walk); };
  walk(tree.toJSON());
  return out.join("|");
}
const setAge = async (tree: ReactTestRenderer, value: string, unit: string) => {
  await act(async () => label(tree, "Estimated age").props.onChangeText(value));
  await act(async () => label(tree, "Estimated age unit").props.onPress());
  await act(async () => label(tree, `Estimated age unit: ${unit}`).props.onPress());
};

describe("age and sex driven cards", () => {
  it("shows the infant cards for a 3 day old and hides the pregnancy card for a male", async () => {
    const { tree } = render({ AdministrativeData: { Sex: 1, EstimatedAge: "P3D" } });
    expect(allText(tree)).toContain("Fetal or infant death *");
    expect(has(tree, "If death within 24h specify number of hours survived")).toBe(true);
    expect(allText(tree)).toContain("Information on pregnancy");
    expect(allText(tree)).toContain("This section is not applicable when the selected sex is male");
    expect(has(tree, "For women, was the deceased pregnant?")).toBe(false);
    await act(async () => tree.unmount());
  });

  it("hides the infant card for an adult and the hours field from a week of age", async () => {
    const adult = render({ AdministrativeData: { Sex: 2, EstimatedAge: "P40Y" } });
    expect(allText(adult.tree)).toContain("Fetal or infant death *");
    expect(allText(adult.tree)).toContain("This section is not applicable when it is not a fetal or infant death");
    expect(has(adult.tree, "Birth weight (in grams)")).toBe(false);
    expect(allText(adult.tree)).toContain("Information on pregnancy");
    await act(async () => adult.tree.unmount());
    const month = render({ AdministrativeData: { Sex: 1, EstimatedAge: "P1M" } });
    expect(allText(month.tree)).toContain("Fetal or infant death *");
    expect(has(month.tree, "If death within 24h specify number of hours survived")).toBe(false);
    await act(async () => month.tree.unmount());
  });

  it("hides hours survived when Stillborn is Yes", async () => {
    const { tree } = render({ AdministrativeData: { EstimatedAge: "P1D" }, FetalOrInfantDeath: { Stillborn: 0 } });
    expect(has(tree, "If death within 24h specify number of hours survived")).toBe(true);
    await act(async () => tree.root.findAll((n) => n.props.testID === "question-doris_stillborn-choice-1" && n.props.accessibilityRole === "radio")[0].props.onPress());
    expect(has(tree, "If death within 24h specify number of hours survived")).toBe(false);
    await act(async () => tree.unmount());
  });

  it("sends hidden keys only while shown, and does not bring typed values back when the card returns", async () => {
    const { tree, api: a } = render({ AdministrativeData: { Sex: 1 } });
    await act(async () => label(tree, "Birth weight (in grams)").props.onChangeText("3000"));
    await process(tree);
    expect(a.processDoris.mock.calls[0][3].FetalOrInfantDeath).toEqual({ BirthWeight: 3000 });
    await setAge(tree, "40", "Years");
    expect(allText(tree)).toContain("Fetal or infant death *");
    expect(allText(tree)).toContain("This section is not applicable when it is not a fetal or infant death");
    expect(has(tree, "Birth weight (in grams)")).toBe(false);
    await process(tree);
    expect(a.processDoris.mock.calls[1][3].FetalOrInfantDeath).toBeUndefined();
    await setAge(tree, "2", "Months");
    expect(label(tree, "Birth weight (in grams)").props.value).toBe("");
    await act(async () => tree.unmount());
  });

  it("ignores the case header age: clearing Estimated age keeps the entered infant data", async () => {
    const { tree } = render({ AdministrativeData: { Sex: 1, EstimatedAge: "P3D" }, FetalOrInfantDeath: { BirthWeight: 3000 } }, api(), 45);
    expect(label(tree, "Birth weight (in grams)").props.value).toBe("3000");
    await act(async () => label(tree, "Estimated age").props.onChangeText(""));
    expect(has(tree, "Birth weight (in grams)")).toBe(true);
    expect(allText(tree)).not.toContain("This section is not applicable when it is not a fetal or infant death");
    expect(label(tree, "Birth weight (in grams)").props.value).toBe("3000");
    await act(async () => tree.unmount());
  });

  it("warns softly about pregnancy outside 10-54 and never blocks processing", async () => {
    const { tree, api: a } = render({ AdministrativeData: { Sex: 2, EstimatedAge: "P77Y" }, MaternalDeath: { WasPregnant: 1 } });
    expect(warn(tree, "MaternalDeath.WasPregnant")[0].props.children).toBe("Pregnancy is unusual at this age");
    await process(tree);
    expect(a.processDoris).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });
});

describe("answer driven fields", () => {
  const radio = (tree: ReactTestRenderer, name: string, value: number) => tree.root.findAll((n) => n.props.testID === `question-${name}-choice-${value}` && n.props.accessibilityRole === "radio")[0];
  const external = ["Date of injury", "Please describe how external cause occurred (If poisoning please specify poisoning agent)", "Place: At home"];

  it("shows the external cause fields for an accident, drops them for Disease and does not restore them", async () => {
    const { tree, api: a } = render({ AdministrativeData: { Sex: 1, EstimatedAge: "P30Y" }, MannerOfDeath: { MannerOfDeath: 1 } });
    for (const l of external) expect(has(tree, l)).toBe(true);
    await act(async () => label(tree, "Please describe how external cause occurred (If poisoning please specify poisoning agent)").props.onChangeText("fall"));
    await process(tree);
    expect(a.processDoris.mock.calls[0][3].MannerOfDeath).toEqual({ MannerOfDeath: 1, DescriptionExternalCause: "fall" });
    await act(async () => radio(tree, "doris_manner_of_death", 0).props.onPress());
    for (const l of external) expect(has(tree, l)).toBe(false);
    await process(tree);
    expect(a.processDoris.mock.calls[1][3].MannerOfDeath).toEqual({ MannerOfDeath: 0 });
    await act(async () => radio(tree, "doris_manner_of_death", 2).props.onPress());
    expect(label(tree, "Please describe how external cause occurred (If poisoning please specify poisoning agent)").props.value).toBe("");
    await act(async () => radio(tree, "doris_manner_of_death", 9).props.onPress());
    expect(has(tree, "Date of injury")).toBe(false);
    await act(async () => tree.unmount());
  });

  it("shows surgery details and autopsy findings only after Yes", async () => {
    const { tree } = render({ AdministrativeData: { Sex: 1, EstimatedAge: "P30Y" } });
    expect(has(tree, "If yes please specify date of surgery*")).toBe(false);
    expect(has(tree, "If yes please specify reason for surgery (disease or condition)*")).toBe(false);
    expect(has(tree, "If yes were the findings used in the certification?*: Yes")).toBe(false);
    await act(async () => radio(tree, "doris_surgery_performed", 1).props.onPress());
    await act(async () => radio(tree, "doris_autopsy_requested", 1).props.onPress());
    expect(has(tree, "If yes please specify date of surgery*")).toBe(true);
    expect(has(tree, "If yes please specify reason for surgery (disease or condition)*")).toBe(true);
    expect(has(tree, "If yes were the findings used in the certification?*: Yes")).toBe(true);
    await act(async () => radio(tree, "doris_surgery_performed", 0).props.onPress());
    expect(has(tree, "If yes please specify date of surgery*")).toBe(false);
    await act(async () => tree.unmount());
  });

  it("warns under the field for an implausible birth weight and a long interval", async () => {
    const { tree } = render({ AdministrativeData: { EstimatedAge: "P3D" }, Part1: [{ Conditions: [{ Text: "Sepsis", Interval: "P2M" }] }] });
    expect(warn(tree, "Part1.0")[0].props.children).toBe("Interval is longer than the age at death");
    await act(async () => label(tree, "Birth weight (in grams)").props.onChangeText("90"));
    expect(warn(tree, "FetalOrInfantDeath.BirthWeight")[0].props.children).toBe("Unusual birth weight (200 to 7000 g)");
    expect(label(tree, "Process current certificate").props.disabled).toBe(false);
    await act(async () => tree.unmount());
  });

  it("dims, but still allows, time units larger than the age", async () => {
    const { tree } = render({ AdministrativeData: { EstimatedAge: "P20D" } });
    await act(async () => label(tree, "Part I line 1 interval unit").props.onPress());
    const style = (l: string) => [label(tree, l).props.style].flat(3).filter(Boolean);
    expect(style("Part I line 1 interval unit: Years").some((s: any) => s.opacity === 0.45)).toBe(true);
    expect(style("Part I line 1 interval unit: Days").some((s: any) => s.opacity === 0.45)).toBe(false);
    expect(label(tree, "Part I line 1 interval unit: Years").props.disabled).toBeFalsy();
    await act(async () => tree.unmount());
  });
});

describe("line titles and controls", () => {
  it("uses Immediate cause and Due to with no numbers, keeping the letter badge", async () => {
    const { tree } = render({});
    const text = allText(tree);
    expect(text).toContain("Immediate cause");
    expect(text).toContain("Due to");
    expect(text).not.toMatch(/Due to \d|Immediate cause \d|Part I line/);
    expect(has(tree, "Line B")).toBe(true);
    await act(async () => tree.unmount());
  });

  it("gives move and remove buttons a visible 1px outline, destructive red for remove, 44px reach", async () => {
    const { tree } = render({});
    const press = (l: string) => tree.root.findAllByProps({ accessibilityLabel: l }).find((n) => n.props.hitSlop !== undefined)!;
    const flat = (l: string) => { const raw = press(l).props.style; return Object.assign({}, ...[typeof raw === "function" ? raw({ pressed: false }) : raw].flat(3).filter(Boolean)); };
    expect(flat("Move Part I line 2 up")).toMatchObject({ borderWidth: 1, borderColor: ui.light.input });
    expect(flat("Remove Part I line 2")).toMatchObject({ borderWidth: 1, borderColor: ui.light.destructiveText });
    expect(flat("Remove Part I line 2").minWidth).toBeGreaterThanOrEqual(36);
    expect(press("Remove Part I line 2").props.hitSlop).toBe(4);
    await act(async () => tree.unmount());
  });
});

describe("search box", () => {
  const input = (tree: ReactTestRenderer) => label(tree, "Search Part I line 2 condition");

  it("opens the picker on the typed term with Enter, passes the theme and clears the box", async () => {
    mockTheme.mode = "dark";
    const { tree } = render({});
    expect(input(tree).props.placeholder).toBe("Search a condition or ICD-11 code");
    await act(async () => input(tree).props.onChangeText("  pneumonia "));
    await act(async () => input(tree).props.onSubmitEditing());
    expect(mockFrame.props.init).toMatchObject({ title: "Due to", query: "pneumonia", theme: "dark", allowUncoded: true });
    expect(input(tree).props.value).toBe("");
    await act(async () => mockFrame.props.onMessage({ t: "close" }, jest.fn()));
    expect(input(tree).props.value).toBe("");
    mockTheme.mode = "light";
    await act(async () => tree.unmount());
  });

  it("opens the picker from the icon, empty or with text, in light mode", async () => {
    const { tree } = render({});
    await act(async () => label(tree, "Open search Part I line 2").props.onPress());
    expect(mockFrame.props.init).toMatchObject({ query: "", theme: "light" });
    await act(async () => mockFrame.props.onMessage({ t: "close" }, jest.fn()));
    await act(async () => input(tree).props.onChangeText("sepsis"));
    await act(async () => label(tree, "Open search Part I line 2").props.onPress());
    expect(mockFrame.props.init.query).toBe("sepsis");
    await act(async () => tree.unmount());
  });

  it("is also on the Part II tile", async () => {
    const { tree } = render({});
    await act(async () => label(tree, "Search Part II condition").props.onChangeText("diabetes"));
    await act(async () => label(tree, "Open search Part II").props.onPress());
    expect(mockFrame.props.init).toMatchObject({ title: "Significant conditions contributing to death", query: "diabetes" });
    await act(async () => tree.unmount());
  });
});

describe("line controls and onset label", () => {
  const second = { Conditions: [{ Text: "Sepsis", Code: "1G40" }] };

  it("labels the onset once with Interval and Units placeholders", async () => {
    const { tree } = render({ Part2: { Conditions: [{ Text: "Diabetes", Code: "5A11" }] } });
    const text = allText(tree);
    expect(text).toContain("Onset to death");
    expect(text).not.toContain("Time unit");
    expect(label(tree, "Part I line 1 interval").props.placeholder).toBe("Interval");
    expect(text).toContain("Units");
    await act(async () => tree.unmount());
  });

  it("inserts an empty line directly below the chosen line and re-letters", async () => {
    const { tree } = render({ Part1: [line, second] });
    await act(async () => label(tree, "Add line below line 1").props.onPress());
    const text = allText(tree);
    expect(text.indexOf("CA40")).toBeLessThan(text.indexOf("Due to"));
    expect(text.indexOf("Due to")).toBeLessThan(text.indexOf("Sepsis"));
    expect(has(tree, "Add line below line 3")).toBe(true);
    expect(has(tree, "Add line below line 5")).toBe(false);
    await process(tree);
    await act(async () => tree.unmount());
  });

  it("hides the per-line add at the five line cap", async () => {
    const { tree } = render({ Part1: [line, second, second, second, second] });
    expect(has(tree, "Add line below line 1")).toBe(false);
    await act(async () => tree.unmount());
  });
});
