import React from "react";
import { AppState, Modal } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    errorText: (error: unknown) => error instanceof Error ? error.message : "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
    useUiStyles: () => new Proxy({}, { get: () => undefined }),
  };
});

jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme("light") };
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

const mockFrame: { props: any } = { props: null };
jest.mock("../src/workspace/doris/IcdPickerFrame", () => ({ IcdPickerFrame: (props: any) => { mockFrame.props = props; return null; } }));

import { ApiError } from "../src/api";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import type { DorisProcessReply, JsonObject, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";
import { DorisPanel } from "../src/workspace/doris/DorisPanel";
import { dorisGuidance, parseDorisOptions } from "../src/workspace/doris/guidance";
import { parseInterval, serializeInterval } from "../src/workspace/doris/interval";

const identity: WorkspaceIdentity = { vaSid: "sid-1", mode: "coding" };
const certificate: JsonObject = {
  ICDVersion: "ICD11",
  Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }],
  Part2: { Conditions: [{ Text: "Diabetes", Code: "5A11", LinearizationURI: "https://who.int/5A11" }] },
};
const processReply: DorisProcessReply = {
  schema_version: 1,
  client_revision: 0,
  icd_release: "2025-01",
  certificate,
  certificate_digest: "certificate-digest",
  result_digest: "result-digest",
  doris: { status: "completed", result: { code: "CA40", stemCode: "CA40", title: "Pneumonia" } },
  codedit: { status: "completed", result: { report: "Independent coding check" } },
  process_token: "opaque-process-token",
};

function makeWorkspace(options: { step?: "initial" | "final"; masked?: boolean; seed?: JsonObject; processing?: JsonObject; prefill?: JsonObject } = {}): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: options.masked ? "masked_doris" : "unmasked_doris", icd_classification: "icd11", workflow_state: options.step === "final" ? "initial_coded" : "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [], default_category: "vacodassessment", step: options.step ?? "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: null,
    doris: {
      initial_certificate: options.seed ?? certificate,
      prefill_provenance: options.prefill ?? {},
      saved_processing: options.processing ?? null,
      step1_certificate: options.masked ? certificate : null,
      step1_processing: options.masked ? { doris: { status: processReply.doris.status, result: processReply.doris.result }, codedit: { status: processReply.codedit.status, result: processReply.codedit.result }, process_token: "private-step1-token" } : null,
    },
    narrative_qa: null, social_autopsy: null,
  };
}

function apiFor(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    processDoris: jest.fn(async () => processReply),
    searchDorisTerms: jest.fn(async (_sid: string, query: string) => ({
      schema_version: 1 as const,
      items: [{ code: query || "Y55", title: "Selected cause", uri: "https://who.int/Y55", release: "2025-01", matching_text: "Selected cause", postcoordination: false, postcoordination_availability: 0, related_maternal: false, related_perinatal: false, has_coding_note: false }],
      truncated: false,
      next_cursor: null,
    })),
    getDorisCodeInfo: jest.fn(async (_sid: string, code: string) => ({ schema_version: 1 as const, item: { code, title: "Selected cause", uri: "https://who.int/Y55", release: "2025-01", postcoordination: false } })),
    checkDorisSelection: jest.fn(async (_sid: string, code: string, uri: string) => ({ schema_version: 1 as const, item: { code, title: "Selected cause", uri, release: "2025-01", postcoordination: false } })),
    getVaDefinitionForIcd: jest.fn(async () => null),
    saveInitial: jest.fn(async () => ({ va_sid: "sid-1", initial_assessment_id: "initial-1" })),
    saveFinal: jest.fn(async () => ({ va_sid: "sid-1", final_assessment_id: "final-1" })),
    saveNotCodeable: jest.fn(async () => ({ va_sid: "sid-1", workflow_state: "not_codeable" })),
    ...overrides,
  } as unknown as WorkspaceApi;
}

function byLabel(tree: ReactTestRenderer, label: string): ReactTestInstance {
  return tree.root.findByProps({ accessibilityLabel: label });
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

async function flushAll() {
  for (let tick = 0; tick < 8; tick += 1) await Promise.resolve();
}

/** Drives the open picker page the way its script does: search, verify with selection-check, then select. */
async function pickViaPicker(code: string, uri = "https://who.int/Y55") {
  const reply = jest.fn();
  await act(async () => { mockFrame.props.onMessage({ t: "req", id: 1, path: "terms", body: { schema_version: 1, query: code, limit: 20, cursor: null } }, reply); await flushAll(); });
  await act(async () => { mockFrame.props.onMessage({ t: "req", id: 2, path: "selection-check", body: { schema_version: 1, code, uri } }, reply); await flushAll(); });
  await act(async () => { mockFrame.props.onMessage({ t: "select", choice: { code, uri } }, reply); await flushAll(); });
  return reply;
}

function renderPanel(workspace: WorkspacePayload, api: WorkspaceApi, onDone = jest.fn(), request: JsonRequester = jest.fn(async () => ({}))) {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<DorisPanel workspace={workspace} identity={identity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} />); });
  return { tree, onDone, request };
}

it("accepts a redacted seed without fabricating administrative data", async () => {
  const seed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [] }] };
  const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
  expect(tree.root.findAllByProps({ accessibilityLabel: "Date of birth" })).toHaveLength(0);
  expect(JSON.stringify(tree.toJSON())).toContain("Administrative data was not supplied");
  await act(async () => tree.unmount());
});

it("renders a centred h2 heading with a step subtitle and bounding separators", async () => {
  const { tree } = renderPanel(makeWorkspace({ seed: certificate }), apiFor());
  const heading = tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "header" && n.props["aria-level"] === 2);
  expect(heading).toHaveLength(1);
  const style = Object.assign({}, ...[heading[0].props.style].flat(3).filter(Boolean));
  expect(style).toMatchObject({ fontWeight: "700", textAlign: "center" });
  expect(style.fontSize).toBeGreaterThanOrEqual(24);
  expect(allText(tree)).toContain("DORIS certificate|Step 1");
  expect(tree.root.findAllByProps({ testID: "doris-heading-separator" }).length).toBeGreaterThan(0);
  expect(tree.root.findAllByProps({ testID: "doris-actions-separator" }).length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});

it("uses the WHO question control for grouped choices with a real selected radio indicator", async () => {
  const seed: JsonObject = { ...certificate, AdministrativeData: { Sex: 2 } };
  const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
  const selected = tree.root.findAllByProps({ testID: "question-doris_sex-choice-2" }).find((node) => node.props.accessibilityRole === "radio");
  expect(selected).toBeDefined();
  expect(selected?.props.accessibilityState).toEqual({ selected: true, disabled: false });
  expect(selected?.props.accessibilityLabel).toBe("Sex: Female");
  expect(JSON.stringify(tree.toJSON())).not.toContain("◉");
  expect(JSON.stringify(tree.toJSON())).not.toContain("○");
  await act(async () => tree.unmount());
});

it("renders Manner of death as nine radios plus Not stated and writes the numeric code", async () => {
  const seed: JsonObject = { ...certificate, MannerOfDeath: { MannerOfDeath: 2 } };
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  const radios = () => {
    const seen = new Set<string>();
    return tree.root.findAll((n) => {
      const id = n.props.testID;
      if (typeof id !== "string" || !id.startsWith("question-doris_manner_of_death-choice-") || n.props.accessibilityRole !== "radio" || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  };
  expect(radios()).toHaveLength(10);
  expect(radios()[0].props.accessibilityLabel).toBe("Manner of death: Not stated");
  expect(radios().filter((n) => n.props.accessibilityState.selected).map((n) => n.props.accessibilityLabel)).toEqual(["Manner of death: Intentional self-harm"]);
  // Choice rows draw the WHO-style 22px radio circle (2px border, full radius).
  expect(radios()[2].findAll((n) => [n.props.style].flat(3).some((s: any) => s?.width === 22 && s?.borderWidth === 2 && s?.borderRadius === 9999)).length).toBeGreaterThan(0);
  await act(async () => radios()[4].props.onPress());
  expect(radios().filter((n) => n.props.accessibilityState.selected).map((n) => n.props.accessibilityLabel)).toEqual(["Manner of death: Assault"]);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(JSON.stringify((api.processDoris as jest.Mock).mock.calls[0])).toContain('"MannerOfDeath":{"MannerOfDeath":3}');
  await act(async () => tree.unmount());
});

it("invalidates the process proof and final choice after a certificate edit", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(JSON.stringify(tree.toJSON())).toContain("DORIS and CoDEdit");
  await act(async () => byLabel(tree, "Part I line 1 interval").props.onChangeText("3"));
  expect(JSON.stringify(tree.toJSON())).not.toContain("DORIS and CoDEdit");
  expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
  expect(api.processDoris).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("shows the computed UCOD as a titled cluster and keeps the raw code", async () => {
  const reply: DorisProcessReply = {
    ...processReply,
    doris: { status: "completed", result: { code: "5A14/BA41.Z", stemCode: "5A14", uri: "http://id.who.int/icd/release/11/mms/1" } },
    ucod_parts: [
      { code: "5A14", title: "Diabetes mellitus, type unspecified", role: "stem", uri: null },
      { code: "BA41.Z", title: "Acute myocardial infarction, unspecified", role: "postcoordinated", uri: null },
    ],
  };
  const { tree } = renderPanel(makeWorkspace(), apiFor({ processDoris: jest.fn(async () => reply) }));
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  const text = allText(tree);
  expect(text).toContain("Underlying cause: 5A14 Diabetes mellitus, type unspecified");
  expect(text).toContain("with BA41.Z Acute myocardial infarction, unspecified (postcoordinated manifestation)");
  expect(text).toContain("joins the stem code DORIS chose");
  expect(text).toContain("Computed UCOD: |5A14/BA41.Z");
  await act(async () => tree.unmount());
});

it("falls back to the raw code when the server sent no UCOD titles", async () => {
  const { tree } = renderPanel(makeWorkspace(), apiFor());
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(allText(tree)).not.toContain("Underlying cause:");
  expect(allText(tree)).toContain("Computed UCOD: |CA40");
  await act(async () => tree.unmount());
});

it("discards an in-flight process reply after an edit", async () => {
  let finish!: (reply: DorisProcessReply) => void;
  const api = apiFor({ processDoris: jest.fn(() => new Promise((resolve) => { finish = resolve; })) });
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  await act(async () => byLabel(tree, "Part I line 1 interval").props.onChangeText("4"));
  await act(async () => { finish(processReply); await flush(); });
  expect(JSON.stringify(tree.toJSON())).not.toContain("DORIS and CoDEdit");
  expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
  await act(async () => tree.unmount());
});

it("installs a fresh 409 result but clears the old final selection for reconfirmation", async () => {
  const freshCertificate: JsonObject = { ...certificate, Part1: [{ Conditions: [{ Text: "Fresh server certificate condition", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }] };
  const conflict = new ApiError(409, "DORIS_CERTIFICATE_CHANGED", undefined, undefined, { processing: { ...processReply, certificate: freshCertificate, result_digest: "fresh-digest" } });
  const api = apiFor({ saveInitial: jest.fn(async () => { throw conflict; }) });
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  await act(async () => byLabel(tree, "Confirm Step 1 underlying cause open search").props.onPress());
  await pickViaPicker("Y55");
  await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flush(); });
  expect(JSON.stringify(tree.toJSON())).toContain("fresh results");
  expect(JSON.stringify(tree.toJSON())).toContain("Fresh server certificate condition");
  expect(tree.root.findAllByProps({ accessibilityLabel: "Confirm Step 1 underlying cause search" })).not.toHaveLength(0);
  expect(JSON.stringify(tree.toJSON())).not.toContain("Final underlying cause selected independently");
  expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
  await act(async () => tree.unmount());
});

it("allows an uncoded immediate cause when the certificate text is valid", async () => {
  const uncodedSeed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Uncoded immediate cause" }] }] };
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed: uncodedSeed }), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(api.processDoris).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(tree.toJSON())).not.toContain("Choose a coded immediate cause");
  await act(async () => tree.unmount());
});

it("keeps masked Step 2 readonly and sends only its final choice", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ step: "final", masked: true, processing: { certificate: { secret: "must-not-render" }, process_token: "must-not-render-either", doris: { status: processReply.doris.status, result: processReply.doris.result }, codedit: { status: processReply.codedit.status, result: processReply.codedit.result } } }), api);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Process current certificate" })).toHaveLength(0);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Part I line 1 interval" })).toHaveLength(0);
  expect(JSON.stringify(tree.toJSON())).toContain("Pneumonia");
  expect(JSON.stringify(tree.toJSON())).not.toContain("must-not-render");
  await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
  await pickViaPicker("Y55");
  await act(async () => { byLabel(tree, "Save final cause").props.onPress(); await flush(); });
  expect(api.processDoris).not.toHaveBeenCalled();
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", { conclusive_cod: "Y55", remark: "" }, "coding");
  await act(async () => tree.unmount());
});

it("offers the coder-only not-codeable action with the served reason codes", async () => {
  const api = apiFor();
  const onDone = jest.fn();
  const { tree } = renderPanel(makeWorkspace(), api, onDone);
  for (const reason of ["Narration language", "Narration does not match", "No information", "Form is empty", "Other"]) {
    expect(() => byLabel(tree, `Not-codeable reason: ${reason}`)).not.toThrow();
  }
  await act(async () => byLabel(tree, "Not-codeable reason: No information").props.onPress());
  await act(async () => { byLabel(tree, "Submit not-codeable report").props.onPress(); await flush(); });
  expect(api.saveNotCodeable).toHaveBeenCalledWith("sid-1", { reason: "no_info", other: "" });
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("normalizes nested DORIS guidance errors and validates consumed response fields", async () => {
  const identity: WorkspaceIdentity = { vaSid: "sid with spaces", mode: "coding" };
  const request = jest.fn(async () => { throw new ApiError(422, "ERROR", undefined, undefined, { schema_version: 1, error: { code: "INVALID_INPUT", message: "WHO option request was invalid." } }); });
  await expect(dorisGuidance(request, identity, "postcoordination-options", { stem_code: "CA40", axis_id: "axis-1", parent_uri: "urn:parent" }, parseDorisOptions)).rejects.toMatchObject({ code: "INVALID_INPUT", message: "WHO option request was invalid." });
  expect(request).toHaveBeenCalledWith("/api/v1/doris-clinical/postcoordination-options/sid%20with%20spaces", expect.objectContaining({ method: "POST" }));
  expect(() => parseDorisOptions({ schema_version: 1, items: [{}], truncated: false })).toThrow("Invalid DORIS response: items[0].code");
});

it("parses and serializes ISO 8601 intervals like the web editor", () => {
  expect(parseInterval("P76Y")).toEqual({ value: "76", unit: "Y", representable: true });
  expect(parseInterval("PT23H")).toEqual({ value: "23", unit: "H", representable: true });
  expect(parseInterval("PT5M")).toEqual({ value: "5", unit: "MI", representable: true });
  expect(parseInterval("P")).toMatchObject({ unit: "unknown", representable: true });
  expect(parseInterval("P1Y2M").representable).toBe(false);
  expect(parseInterval(undefined).representable).toBe(false);
  expect(serializeInterval("76", "Y")).toEqual({ value: "P76Y", error: "" });
  expect(serializeInterval("23", "H")).toEqual({ value: "PT23H", error: "" });
  expect(serializeInterval("5", "MI")).toEqual({ value: "PT5M", error: "" });
  expect(serializeInterval("", "")).toEqual({ value: "", error: "" });
  expect(serializeInterval("x", "Y").error).not.toBe("");
  expect(serializeInterval("2", "").error).not.toBe("");
});

it("starts with three Part I lines and processes with trailing empty lines", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace(), api);
  expect(() => byLabel(tree, "Remove Part I line 3")).not.toThrow();
  expect(() => byLabel(tree, "Remove Part I line 4")).toThrow();
  expect(byLabel(tree, "Remove Part I line 1").props.disabled).toBe(true);
  expect(byLabel(tree, "Move Part I line 3 down").props.disabled).toBe(true);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(api.processDoris).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(tree.toJSON())).not.toContain("Complete each Part I line");
  await act(async () => byLabel(tree, "Remove Part I line 3").props.onPress());
  expect(() => byLabel(tree, "Remove Part I line 3")).toThrow();
  await act(async () => tree.unmount());
});

it("writes Estimated age as an ISO duration from number and unit, and shows unrepresentable values", async () => {
  const seed: JsonObject = { ...certificate, AdministrativeData: { Sex: 1 } };
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
  await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
  await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(api.processDoris).toHaveBeenCalledWith("sid-1", "coder", expect.any(Number), expect.objectContaining({ AdministrativeData: { Sex: 1, EstimatedAge: "P76Y" } }));
  await act(async () => tree.unmount());

  const odd = renderPanel(makeWorkspace({ seed: { ...certificate, AdministrativeData: { Sex: 1, EstimatedAge: "P1Y2M" } } }), apiFor());
  expect(JSON.stringify(odd.tree.toJSON())).toContain("Existing value: P1Y2M");
  await act(async () => odd.tree.unmount());
});

it("shows an empty Estimated age input with a placeholder when none is stored", async () => {
  const { tree } = renderPanel(makeWorkspace({ seed: { ...certificate, AdministrativeData: { Sex: 1 } } }), apiFor());
  const input = byLabel(tree, "Estimated age");
  expect(input.props.value).toBe("");
  expect(input.props.placeholder).toBe("Age");
  expect(JSON.stringify(tree.toJSON())).toContain("Age unit");
  await act(async () => tree.unmount());
});

it("adds uncoded text from the picker to a line and removes a condition chip", async () => {
  const seed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }] };
  const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
  await act(async () => byLabel(tree, "Open search Part I line 1").props.onPress());
  expect(mockFrame.props.init).toMatchObject({ title: "Immediate cause", allowUncoded: true });
  await act(async () => mockFrame.props.onMessage({ t: "uncoded", text: "Fever" }, jest.fn()));
  expect(JSON.stringify(tree.toJSON())).toContain("Fever ×");
  await act(async () => byLabel(tree, "Remove condition 2").props.onPress());
  expect(JSON.stringify(tree.toJSON())).not.toContain("Fever ×");
  await act(async () => tree.unmount());
});

it("adds a picker-verified code to the searched line with the line interval", async () => {
  const seed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }, { Conditions: [] }] };
  const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
  await act(async () => byLabel(tree, "Open search Part I line 2").props.onPress());
  expect(mockFrame.props.init).toMatchObject({ title: "Due to", accent: "#B45309" });
  await pickViaPicker("Y55");
  expect(JSON.stringify(tree.toJSON())).toContain("Y55 — Selected cause ×");
  await act(async () => tree.unmount());
});

function allText(tree: ReactTestRenderer): string {
  const out: string[] = [];
  const walk = (node: any) => { if (typeof node === "string") out.push(node); else if (node?.children) node.children.forEach(walk); };
  walk(tree.toJSON());
  return out.join("|");
}

const whoSeed: JsonObject = {
  ...certificate,
  AdministrativeData: { Sex: 2, DateBirth: "1990-05-06" },
  MannerOfDeath: { MannerOfDeath: 0 },
};

const fullSeed: JsonObject = { ...whoSeed, MannerOfDeath: { MannerOfDeath: 2 }, Surgery: { WasPerformed: 1, Reason: "Appendectomy" }, Autopsy: { WasRequested: 1 } };

it("uses the WHO headings, in WHO order, with Part 2 and each WHO card as its own tile", async () => {
  const { tree } = renderPanel(makeWorkspace({ seed: fullSeed }), apiFor());
  const text = allText(tree);
  const order = ["Administrative Data", "Frame A: Medical data", "Part 1: Cause of death", "Part 2: Other significant conditions contributing to death", "Significant conditions contributing to death", "Manner of death", "Fetal or infant death *", "Information on pregnancy", "Surgery", "Autopsy", "*fields are not mandatory"];
  const positions = order.map((heading) => text.indexOf(heading));
  expect(positions.every((position) => position >= 0)).toBe(true);
  expect([...positions].sort((a, b) => a - b)).toEqual(positions);
  // Part 2 is one heading; the other cards are not nested under it as extra "Part 2" headings.
  expect(text.match(/Part 2:/g)).toHaveLength(1);
  for (const gone of ["Certificate context", "Part II", "Not set", "Time unit"]) expect(text).not.toContain(gone);
  for (const label of ["Stillborn?", "If death within 24h specify number of hours survived", "Birth weight (in grams)", "Number of completed weeks of pregnancy", "Age of mother (years)", "If yes please specify date of surgery*", "If yes please specify reason for surgery (disease or condition)*", "Was an autopsy requested?*", "If yes were the findings used in the certification?*", "If external cause or poisoning:*", "Place of occurrence of the external cause:*"]) expect(text).toContain(label);
  await act(async () => tree.unmount());
});

it("prefixes Part I lines with A to E and labels the interval fields with one Onset to death label", async () => {
  const { tree } = renderPanel(makeWorkspace({ seed: { ...certificate, Part1: [1, 2, 3, 4, 5].map((n) => ({ Conditions: [{ Text: `Cause ${n}`, Interval: "P1D" }] })) } }), apiFor());
  for (const letter of ["A", "B", "C", "D", "E"]) expect(() => byLabel(tree, `Line ${letter}`)).not.toThrow();
  const text = allText(tree);
  expect(text).toContain("Immediate cause");
  expect(text).toContain("Due to");
  expect(text).not.toMatch(/Due to \d|Immediate cause \d/);
  expect(text).toContain("Onset to death");
  expect(text).not.toContain("Time unit");
  expect(byLabel(tree, "Part I line 1 interval").props.placeholder).toBe("Interval");
  await act(async () => tree.unmount());
});

it("shows a stored MannerOfDeath 0 as the Disease radio, keeps numeric fields numeric and omits blanks", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
  const selected = tree.root.findAll((n) => typeof n.props.testID === "string" && n.props.testID.startsWith("question-doris_manner_of_death-") && n.props.accessibilityState?.selected === true);
  expect([...new Set(selected.map((n) => n.props.accessibilityLabel))]).toEqual(["Manner of death: Disease"]);
  const weeks = byLabel(tree, "Number of completed weeks of pregnancy");
  expect(weeks.props.keyboardType).toBe("numeric");
  await act(async () => weeks.props.onChangeText("3x6"));
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(((api.processDoris as jest.Mock).mock.calls[0][3] as JsonObject).FetalOrInfantDeath).toEqual({ PregnancyWeeks: 36 });
  await act(async () => weeks.props.onChangeText(""));
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(((api.processDoris as jest.Mock).mock.calls[1][3] as JsonObject).FetalOrInfantDeath).toBeUndefined();
  await act(async () => tree.unmount());
});

it("greys the pregnancy follow-ups until the first answer is Yes", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed: { ...whoSeed, MaternalDeath: { WasPregnant: 0 } } }), api);
  const followUp = () => tree.root.findAll((n) => n.props.testID === "question-doris_time_from_pregnancy-choice-1" && n.props.accessibilityRole === "radio")[0];
  expect(followUp().props.accessibilityState.disabled).toBe(true);
  await act(async () => tree.root.findAll((n) => n.props.testID === "question-doris_was_pregnant-choice-1")[0].props.onPress());
  expect(followUp().props.accessibilityState.disabled).toBe(false);
  await act(async () => followUp().props.onPress());
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(((api.processDoris as jest.Mock).mock.calls[0][3] as JsonObject).MaternalDeath).toEqual({ WasPregnant: 1, TimeFromPregnancy: 1 });
  await act(async () => tree.unmount());
});

it("shows the interview provenance text beside every prefilled field", async () => {
  const workspace = makeWorkspace({ seed: fullSeed });
  workspace.doris!.prefill_provenance = {
    "AdministrativeData.DateBirth": { sources: ["Id10020"] },
    "MannerOfDeath.MannerOfDeath": { sources: ["Id10077"], note: "injury" },
    "Surgery.Reason": { sources: ["Id10200", "Id10201"] },
  };
  const { tree } = renderPanel(workspace, apiFor());
  const text = allText(tree);
  expect(text).toContain("from interview (Id10020)");
  expect(text).toContain("from interview (Id10077; injury)");
  expect(text).toContain("from interview (Id10200, Id10201)");
  await act(async () => tree.unmount());
});

it("renders the date fields as calendar fields and writes ISO dates", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ seed: fullSeed }), api);
  expect(byLabel(tree, "Date of birth").props.accessibilityValue).toEqual({ text: "1990-05-06" });
  expect(() => byLabel(tree, "Date of death")).not.toThrow();
  expect(() => byLabel(tree, "Date of injury")).not.toThrow();
  expect(() => byLabel(tree, "If yes please specify date of surgery*")).not.toThrow();
  await act(async () => tree.unmount());
});

it("restyles the not-codeable reasons as radio rows with their served ids", async () => {
  const { tree } = renderPanel(makeWorkspace(), apiFor());
  const row = tree.root.findAll((n) => n.props.testID === "question-doris_not_codeable-choice-no_info" && n.props.accessibilityRole === "radio")[0];
  expect(row.findAll((n) => [n.props.style].flat(3).some((s: any) => s?.width === 22 && s?.borderWidth === 2 && s?.borderRadius === 9999)).length).toBeGreaterThan(0);
  await act(async () => tree.unmount());
});

it("sends ICDVersion even when the served seed holds only prefilled answers", async () => {
  const api = apiFor();
  const seed: JsonObject = { AdministrativeData: { Sex: 1 }, Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40.Z", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }] };
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(api.processDoris).toHaveBeenCalledWith("sid-1", "coder", expect.any(Number), expect.objectContaining({ ICDVersion: "ICD11" }));
  await act(async () => tree.unmount());
});

// Policy docs/policy/doris-certificate-rules.md ("Hiding clears the control ... old values are never resurrected")
// and the Flask editor (doris_clinical.js applyRules -> clearControls) both blank a hidden section the moment it hides.
const choose = (tree: ReactTestRenderer, name: string, value: number) => act(async () => tree.root.findAll((n) => n.props.testID === `question-${name}-choice-${value}` && n.props.accessibilityRole === "radio")[0].props.onPress());
const sentCertificate = async (tree: ReactTestRenderer, api: WorkspaceApi): Promise<JsonObject> => {
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  const calls = (api.processDoris as jest.Mock).mock.calls;
  return calls[calls.length - 1][3] as JsonObject;
};

it("blanks MaternalDeath when sex goes Female to Male and back, as the web editor does", async () => {
  const api = apiFor();
  const seed: JsonObject = { ...whoSeed, MaternalDeath: { WasPregnant: 1, TimeFromPregnancy: 1 } };
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  expect((await sentCertificate(tree, api)).MaternalDeath).toEqual({ WasPregnant: 1, TimeFromPregnancy: 1 });
  await choose(tree, "doris_sex", 1);
  expect(allText(tree)).toContain("not applicable when the selected sex is male");
  await choose(tree, "doris_sex", 2);
  expect((await sentCertificate(tree, api)).MaternalDeath).toBeUndefined();
  await act(async () => tree.unmount());
});

it("blanks surgery date and reason when Surgery goes Yes to No and back to Yes", async () => {
  const api = apiFor();
  const seed: JsonObject = { ...whoSeed, Surgery: { WasPerformed: 1, Date: "2025-01-02", Reason: "Appendicitis" } };
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  expect((await sentCertificate(tree, api)).Surgery).toEqual({ WasPerformed: 1, Date: "2025-01-02", Reason: "Appendicitis" });
  await choose(tree, "doris_surgery_performed", 0);
  await choose(tree, "doris_surgery_performed", 1);
  expect((await sentCertificate(tree, api)).Surgery).toEqual({ WasPerformed: 1 });
  await act(async () => tree.unmount());
});

it("blanks FetalOrInfantDeath when the age unit moves to Years and back to Months", async () => {
  const api = apiFor();
  const seed: JsonObject = { ...whoSeed, AdministrativeData: { Sex: 2, EstimatedAge: "P6M" }, FetalOrInfantDeath: { BirthWeight: 3000 } };
  const { tree } = renderPanel(makeWorkspace({ seed }), api);
  expect((await sentCertificate(tree, api)).FetalOrInfantDeath).toEqual({ BirthWeight: 3000 });
  await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
  await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
  await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
  await act(async () => byLabel(tree, "Estimated age unit: Months").props.onPress());
  expect((await sentCertificate(tree, api)).FetalOrInfantDeath).toBeUndefined();
  await act(async () => tree.unmount());
});

it("drops the open ICD picker and its typed query when the app goes to the background", async () => {
  let onChange: ((state: string) => void) | undefined;
  const spy = jest.spyOn(AppState, "addEventListener").mockImplementation((_event, listener) => { onChange = listener as (state: string) => void; return { remove: () => undefined } as never; });
  mockFrame.props = null;
  const api = apiFor();
  const request: JsonRequester = jest.fn(async () => ({}));
  const element = (workspace: WorkspacePayload) => <DorisPanel workspace={workspace} identity={identity} api={api} request={request} onSaved={async () => undefined} onDone={jest.fn()} />;
  let tree!: ReactTestRenderer;
  act(() => { tree = create(element(makeWorkspace({ seed: { ...certificate } }))); });
  await act(async () => byLabel(tree, "Open search Part I line 1").props.onPress());
  expect(mockFrame.props).not.toBeNull();
  await act(async () => { onChange?.("background"); });
  expect(onChange).toBeDefined();
  // Returning reloads the workspace; the editor restarts but must not reopen the picker.
  mockFrame.props = null;
  await act(async () => { onChange?.("active"); tree.update(element(makeWorkspace({ seed: { ...certificate } }))); });
  expect(byLabel(tree, "Process current certificate")).toBeTruthy();
  expect(mockFrame.props).toBeNull();
  spy.mockImplementation(() => ({ remove: () => undefined }) as never);
  await act(async () => tree.unmount());
});

it("ignores an uncoded picker message in final-cause mode and keeps the picker open", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  await act(async () => byLabel(tree, "Confirm Step 1 underlying cause open search").props.onPress());
  expect(mockFrame.props.init.allowUncoded).toBe(false);
  expect(tree.root.findAllByType(Modal)).toHaveLength(1);
  await act(async () => mockFrame.props.onMessage({ t: "uncoded", text: "Fever" }, jest.fn()));
  expect(tree.root.findAllByType(Modal)).toHaveLength(1);
  // Control: a close message does dismiss it.
  await act(async () => mockFrame.props.onMessage({ t: "close" }, jest.fn()));
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  await act(async () => tree.unmount());
});

function processedCertificate(api: WorkspaceApi, call = 0): JsonObject {
  return (api.processDoris as jest.Mock).mock.calls[call][3] as JsonObject;
}

describe("clear and precision controls", () => {
  const withProvenance = (seed: JsonObject, provenance: JsonObject = {}) => {
    const workspace = makeWorkspace({ seed });
    workspace.doris!.prefill_provenance = provenance;
    return workspace;
  };
  const process = async (tree: ReactTestRenderer) => { await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); }); };
  const has = (tree: ReactTestRenderer, label: string) => tree.root.findAllByProps({ accessibilityLabel: label }).length > 0;

  it("clears a choice group to unset, only while it has a value, and drops its interview badge", async () => {
    const api = apiFor();
    const { tree } = renderPanel(withProvenance({ ...whoSeed, MannerOfDeath: { MannerOfDeath: 1 } }, { "MannerOfDeath.MannerOfDeath": { sources: ["Id10077"] } }), api);
    expect(has(tree, "Clear Stillborn?")).toBe(false);
    expect(has(tree, "Clear Sex")).toBe(true);
    expect(allText(tree)).toContain("from interview (Id10077)");
    await act(async () => byLabel(tree, "Clear Manner of death").props.onPress());
    expect(has(tree, "Clear Manner of death")).toBe(false);
    expect(allText(tree)).not.toContain("from interview (Id10077)");
    expect(has(tree, "If external cause or poisoning:*")).toBe(false);
    await process(tree);
    expect(processedCertificate(api).MannerOfDeath).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("clears a date with a precision but keeps the chosen precision", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...whoSeed, AdministrativeData: { Sex: 1, DateBirth: "1997" } } }), api);
    expect(byLabel(tree, "Date of birth precision").props.accessibilityValue).toEqual({ text: "Year" });
    expect(tree.root.findByProps({ accessibilityLabel: "Date of birth", placeholder: "Year" }).props.value).toBe("1997");
    await act(async () => byLabel(tree, "Clear Date of birth").props.onPress());
    expect(has(tree, "Clear Date of birth")).toBe(false);
    expect(byLabel(tree, "Date of birth precision").props.accessibilityValue).toEqual({ text: "Year" });
    expect(tree.root.findByProps({ accessibilityLabel: "Date of birth", placeholder: "Year" }).props.value).toBe("");
    await act(async () => tree.unmount());
  });

  it("stores a year-month date of injury and a year-only date of surgery in the certificate", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...fullSeed, MannerOfDeath: { MannerOfDeath: 1 } } }), api);
    for (const [label, name] of [["Date of injury", "Year-Month"], ["If yes please specify date of surgery*", "Year"]]) {
      await act(async () => byLabel(tree, `${label} precision`).props.onPress());
      await act(async () => byLabel(tree, `${label} precision: ${name}`).props.onPress());
    }
    await act(async () => tree.root.findByProps({ accessibilityLabel: "If yes please specify date of surgery*", placeholder: "Year" }).props.onChangeText("2025"));
    expect(has(tree, "Date of death precision")).toBe(false);
    await process(tree);
    expect((processedCertificate(api).Surgery as JsonObject).Date).toBe("2025");
    await act(async () => tree.unmount());
  });

  it("keeps a prefilled partial date of death as stored, in a text field, until replaced", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...whoSeed, AdministrativeData: { DateDeath: "2020-05" } } }), api);
    const text = () => tree.root.findByProps({ accessibilityLabel: "Date of death", placeholder: "YYYY-MM-DD" });
    expect(text().props.value).toBe("2020-05");
    await act(async () => text().props.onChangeText("2020-05-1"));
    await act(async () => text().props.onChangeText("2020-05-14"));
    await process(tree);
    expect((processedCertificate(api).AdministrativeData as JsonObject).DateDeath).toBe("2020-05-14");
    await act(async () => tree.unmount());
  });

  it("clears number and multi-line text inputs from the single ✕ in the label row", async () => {
    const api = apiFor();
    const seed = { ...whoSeed, FetalOrInfantDeath: { BirthWeight: 3200, PerinatalDescription: "Mother had fever" } };
    const { tree } = renderPanel(makeWorkspace({ seed }), api);
    await act(async () => byLabel(tree, "Clear Birth weight (in grams)").props.onPress());
    expect(has(tree, "Clear Birth weight (in grams)")).toBe(false);
    await act(async () => byLabel(tree, "Clear If death was perinatal, please state conditions of mother that affected the fetus and newborn").props.onPress());
    await process(tree);
    expect(processedCertificate(api).FetalOrInfantDeath).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("keeps the Administrative Data card after its last answered field is cleared", async () => {
    const seed = { ...whoSeed, AdministrativeData: { Sex: 1, EstimatedAge: "P5Y", DateBirth: "1997", DateDeath: "2020-05-14" } };
    const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
    expect(has(tree, "Clear Sex")).toBe(true);
    for (const label of ["Clear Sex", "Clear Estimated age", "Clear Date of birth", "Clear Date of death"]) await act(async () => byLabel(tree, label).props.onPress());
    expect(has(tree, "Clear Date of death")).toBe(false);
    expect(allText(tree)).toContain("Administrative Data");
    expect(has(tree, "Date of birth")).toBe(true);
    expect(has(tree, "Estimated age")).toBe(true);
    expect(allText(tree)).not.toContain("Administrative data was not supplied");
    await act(async () => byLabel(tree, "Sex: Female").props.onPress());
    expect(has(tree, "Clear Sex")).toBe(true);
    await act(async () => tree.unmount());
  });
});

describe("search box auto-open", () => {
  beforeEach(() => { jest.useFakeTimers(); });
  afterEach(() => { jest.useRealTimers(); });
  const seed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }] };
  const type = async (tree: ReactTestRenderer, text: string) => act(async () => byLabel(tree, "Search Part I line 1 condition").props.onChangeText(text));
  const wait = async (ms: number) => act(async () => { jest.advanceTimersByTime(ms); });

  it("opens the picker on the typed term 500 ms after 3 characters and clears the box", async () => {
    mockFrame.props = null;
    const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
    await type(tree, "pne");
    await wait(499);
    expect(mockFrame.props).toBeNull();
    await wait(1);
    expect(mockFrame.props.init).toMatchObject({ title: "Immediate cause", query: "pne" });
    expect(byLabel(tree, "Search Part I line 1 condition").props.value).toBe("");
    await act(async () => tree.unmount());
  });

  it("restarts the pause on each keystroke and ignores 1-2 characters and whitespace", async () => {
    mockFrame.props = null;
    const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
    await type(tree, "pn");
    await wait(2000);
    await type(tree, "   ");
    await wait(2000);
    await type(tree, " pn ");
    await wait(2000);
    expect(mockFrame.props).toBeNull();
    await type(tree, "pne");
    await wait(400);
    await type(tree, "pneu");
    await wait(400);
    expect(mockFrame.props).toBeNull();
    await wait(100);
    expect(mockFrame.props.init.query).toBe("pneu");
    await act(async () => tree.unmount());
  });

  it("clearing the box cancels the pending open; Enter still opens at once and the timer does not fire after", async () => {
    mockFrame.props = null;
    const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
    await type(tree, "pneu");
    await type(tree, "");
    await wait(2000);
    expect(mockFrame.props).toBeNull();
    await type(tree, "fev");
    await act(async () => byLabel(tree, "Search Part I line 1 condition").props.onSubmitEditing());
    expect(mockFrame.props.init.query).toBe("fev");
    mockFrame.props = null;
    await wait(2000);
    expect(mockFrame.props).toBeNull();
    await act(async () => tree.unmount());
  });

  it("does not fire after unmount", async () => {
    mockFrame.props = null;
    const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
    await type(tree, "pneu");
    await act(async () => tree.unmount());
    await wait(2000);
    expect(mockFrame.props).toBeNull();
  });
});

describe("EstimatedAge from the dates", () => {
  const dated: JsonObject = { ...certificate, AdministrativeData: { Sex: 1, DateBirth: "1996-08-12", DateDeath: "2025-06-12" } };

  it("fills a blank age from both dates on load for a prefill seed, and sends it", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated, prefill: { "AdministrativeData.DateBirth": { sources: ["Id10020"] } } }), api);
    expect((await sentCertificate(tree, api)).AdministrativeData).toEqual({ Sex: 1, DateBirth: "1996-08-12", DateDeath: "2025-06-12", EstimatedAge: "P28Y" });
  });

  it("does not derive on load for a saved certificate, so the save never shows an age it lacks", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    expect((await sentCertificate(tree, api)).AdministrativeData).not.toHaveProperty("EstimatedAge");
  });

  it("does not derive from partial dates", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...certificate, AdministrativeData: { Sex: 1, DateBirth: "1996", DateDeath: "2025-06-12" } } }), api);
    expect((await sentCertificate(tree, api)).AdministrativeData).not.toHaveProperty("EstimatedAge");
  });

  it("never overwrites a stored age, and a cleared age stays empty until a date changes", async () => {
    const typed = apiFor();
    const kept = renderPanel(makeWorkspace({ seed: { ...dated, AdministrativeData: { ...dated.AdministrativeData as JsonObject, EstimatedAge: "P40Y" } } }), typed);
    expect((await sentCertificate(kept.tree, typed)).AdministrativeData).toMatchObject({ EstimatedAge: "P40Y" });
    await act(async () => kept.tree.unmount());

    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...dated, AdministrativeData: { ...dated.AdministrativeData as JsonObject, EstimatedAge: "P28Y" } } }), api);
    await act(async () => byLabel(tree, "Clear Estimated age").props.onPress());
    expect((await sentCertificate(tree, api)).AdministrativeData).not.toHaveProperty("EstimatedAge");
    // A later date change refills the cleared age.
    await act(async () => tree.root.findByProps({ label: "Date of death" }).props.onChange("2025-08-12"));
    expect((await sentCertificate(tree, api)).AdministrativeData).toMatchObject({ DateDeath: "2025-08-12", EstimatedAge: "P29Y" });
  });

  it("does not refill over a number typed without a unit when a date changes", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
    await act(async () => tree.root.findByProps({ label: "Date of death" }).props.onChange("2025-08-12"));
    expect(byLabel(tree, "Estimated age").props.value).toBe("76");
    expect((await sentCertificate(tree, api)).AdministrativeData).not.toHaveProperty("EstimatedAge");
  });

  it("does not refill over a unit picked without a number when a date changes", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
    await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
    await act(async () => tree.root.findByProps({ label: "Date of death" }).props.onChange("2025-08-12"));
    expect((await sentCertificate(tree, api)).AdministrativeData).not.toHaveProperty("EstimatedAge");
  });
});

describe("Step 1 result card and final cause picker (digitva-l5fw)", () => {
  const quickButton = (tree: ReactTestRenderer, prefix: string) => tree.root.findAll((n) => typeof n.props.label === "string" && n.props.label.startsWith(prefix) && typeof n.props.onPress === "function")[0];

  it("shows one 'No problems found' for an empty CoDEdit run and collapses blank-line runs in the DORIS report", async () => {
    const api = apiFor({ processDoris: jest.fn(async (): Promise<DorisProcessReply> => ({ ...processReply, doris: { status: "completed" as const, result: { ...processReply.doris.result, report: "Line one\n\n\n\nLine two" } }, codedit: { status: "completed" as const, result: { report: "", tabularReport: "" } } })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    const text = allText(tree);
    expect(text).toContain("Line one\n\nLine two");
    expect(text).not.toContain("\n\n\n");
    expect(text.split("No problems found in the certificate.").length - 1).toBe(1);
    expect(text).not.toContain("No issues found");
    await act(async () => tree.unmount());
  });

  it("does not show 'No problems found' when CoDEdit reported something", async () => {
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), apiFor());
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).not.toContain("No problems found in the certificate.");
    await act(async () => tree.unmount());
  });

  it("quick-adds the DORIS result through WHO, clears it with the cross, and opens its ICD-11 details", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "CA40");
    expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40", "https://who.int/Y55");
    expect(allText(tree)).toContain("Selected cause");
    expect(byLabel(tree, "Save Step 1").props.disabled).toBe(false);
    await act(async () => byLabel(tree, "Clear chosen cause CA40").props.onPress());
    expect(allText(tree)).not.toContain("Selected cause");
    expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
    await act(async () => tree.root.findAllByProps({ accessibilityLabel: "Details for CA40" })[0].props.onPress());
    expect(allText(tree)).toContain("WHO URI: |https://who.int/Y55");
    await act(async () => tree.unmount());
  });

  it("shows the WHO ICD-11 citation and labels the VA definition as a DigitVA addition", async () => {
    const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => ({ icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Definition</p>" })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    expect(allText(tree)).toContain("https://icd.who.int/browse11");
    expect(allText(tree)).toContain("CC BY-ND 3.0 IGO");
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(tree.root.findAllByProps({ testID: "digitva-addition" })).toHaveLength(0);
    await act(async () => tree.root.findAllByProps({ accessibilityLabel: "Details for CA40" })[0].props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("DigitVA addition — not from WHO");
    await act(async () => tree.unmount());
  });

  it("shows the associated VA code under the chosen cause, with its case definition behind a toggle", async () => {
    const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => ({ icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Case <b>text</b></p>" })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).not.toContain("Associated VA codes");
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(api.getVaDefinitionForIcd).toHaveBeenCalledWith("CA40");
    expect(allText(tree)).toContain("Associated VA codes: VAs-01.01 Sepsis");
    expect(allText(tree)).not.toContain("Case text");
    await act(async () => byLabel(tree, "Case definition").props.onPress());
    expect(allText(tree)).toContain("Case text");
    await act(async () => tree.unmount());
  });

  it("refuses a quick-add the WHO codeinfo does not confirm, without choosing it", async () => {
    const api = apiFor({ getDorisCodeInfo: jest.fn(async () => { throw new Error("not found"); }) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("WHO ICD-11 did not confirm that code");
    expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
    await act(async () => tree.unmount());
  });

  it("step 2 shows the Step 1 assigned causes and quick-adds Step 1 and SmartVA codes; a multi-code SmartVA opens search", async () => {
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = {
      ...base,
      assessments: { ...base.assessments, initial: { immediate_cod: "Pneumonia", antecedent_cod: "CA40", other_conditions: ["Asthma"] } },
      smartva: { age: "28.0", gender: "Female", key_symptoms: ["Fever", null, null], causes: [{ rank: 1, cause: "Pneumonia", icd10: "J18", icd11: "CA40/CA41", likelihood: "0.8" }, { rank: 2, cause: "", icd10: null, icd11: null, likelihood: null }, { rank: 3, cause: null, icd10: null, icd11: null, likelihood: null }], symptoms: ["fever", "cough"] },
    } as unknown as WorkspacePayload;
    const api = apiFor();
    const { tree } = renderPanel(workspace, api);
    const text = allText(tree);
    expect(text).toContain("Your Step 1 assigned causes");
    expect(text).toContain("Step 1 underlying cause: CA40");
    expect(text).toContain("Age: |28|");
    expect(text).not.toContain("28.0");
    expect(text).toContain("Cause of Death: |Pneumonia");
    expect(text).toContain("ICD-11 mapping: CA40/CA41");
    expect(text).not.toContain("Secondary");
    expect(text).toContain("Fever");
    expect(text).toContain("Use Step 1 underlying cause: CA40");
    expect(text).toContain("Search SmartVA result: CA40 / CA41");
    expect(text).toContain("Or search ICD-11 for your own code");
    await act(async () => quickButton(tree, "Use Step 1 underlying cause").props.onPress());
    await act(async () => flush());
    expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40", "https://who.int/Y55");
    expect(byLabel(tree, "Save final cause").props.disabled).toBe(false);
    await act(async () => tree.unmount());
  });

  it("a single SmartVA ICD-11 target is a one-tap quick-add", async () => {
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = { ...base, smartva: { age: "40", gender: "Male", key_symptoms: [null, null, null], causes: [{ rank: 1, cause: "Stroke", icd10: "I64", icd11: "8B20", likelihood: null }], symptoms: [] } } as unknown as WorkspacePayload;
    const { tree } = renderPanel(workspace, apiFor());
    expect(allText(tree)).toContain("Use SmartVA result: 8B20");
    await act(async () => tree.unmount());
  });

  it("unmasked Step 2 has no Step 1 card and quick-adds the DORIS result", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ step: "final" }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).not.toContain("Your Step 1 assigned causes");
    expect(quickButton(tree, "Use DORIS result")).toBeDefined();
    await act(async () => tree.unmount());
  });

  it("a reviewer's masked Step 2 reads the reviewer's own Step 1, not the coder's row", async () => {
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = {
      ...base,
      assessments: { ...base.assessments, initial: { immediate_cod: "CODER-IMM", antecedent_cod: "CODER-ANT" }, reviewer_initial: { immediate_cod: "REVIEWER-IMM", antecedent_cod: "REVIEWER-ANT" } },
      smartva: null,
    } as unknown as WorkspacePayload;
    const reviewer = { vaSid: "sid-1", mode: "reviewing" } as WorkspaceIdentity;
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<DorisPanel workspace={workspace} identity={reviewer} api={apiFor()} request={jest.fn(async () => ({}))} onSaved={async () => undefined} onDone={jest.fn()} />); });
    const text = allText(tree);
    expect(text).toContain("REVIEWER-ANT");
    expect(text).not.toContain("CODER-ANT");
    expect(quickButton(tree, "Use Step 1 underlying cause: REVIEWER-ANT")).toBeDefined();
    await act(async () => tree.unmount());
  });
});

describe("unsaved draft across remounts (digitva-yeg3.20)", () => {
  const removePart2 = (tree: ReactTestRenderer) => tree.root.findAllByProps({ accessibilityLabel: "Remove Part II" });

  it("restores an edited certificate when the panel mounts again for the same case and session", async () => {
    const api = apiFor();
    const request: JsonRequester = jest.fn(async () => ({}));
    const first = renderPanel(makeWorkspace(), api, jest.fn(), request);
    expect(removePart2(first.tree).length).toBeGreaterThan(0);
    await act(async () => removePart2(first.tree)[0].props.onPress());
    expect(removePart2(first.tree)).toHaveLength(0);
    await act(async () => first.tree.unmount());

    const again = renderPanel(makeWorkspace(), api, jest.fn(), request);
    expect(byLabel(again.tree, "Process current certificate")).toBeTruthy();
    expect(removePart2(again.tree)).toHaveLength(0);
    expect(JSON.stringify(again.tree.toJSON())).toContain("Process it again before saving");
    await act(async () => again.tree.unmount());

    // Another session (requester) never sees it.
    const other = renderPanel(makeWorkspace(), api);
    expect(removePart2(other.tree).length).toBeGreaterThan(0);
    await act(async () => other.tree.unmount());
  });

  it("forgets the draft after a successful save", async () => {
    const api = apiFor({ processDoris: jest.fn(async (_sid: string, _role: string, revision: number) => ({ ...processReply, client_revision: revision })) as never });
    const request: JsonRequester = jest.fn(async () => ({}));
    const first = renderPanel(makeWorkspace(), api, jest.fn(), request);
    await act(async () => removePart2(first.tree)[0].props.onPress());
    await act(async () => { byLabel(first.tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(first.tree, "Confirm Step 1 underlying cause open search").props.onPress());
    await pickViaPicker("Y55");
    await act(async () => { byLabel(first.tree, "Save Step 1").props.onPress(); await flushAll(); });
    expect(api.saveInitial).toHaveBeenCalledTimes(1);
    await act(async () => first.tree.unmount());

    const again = renderPanel(makeWorkspace(), api, jest.fn(), request);
    expect(removePart2(again.tree).length).toBeGreaterThan(0);
    await act(async () => again.tree.unmount());
  });

  it("keeps the draft when a save fails", async () => {
    const api = apiFor({
      processDoris: jest.fn(async (_sid: string, _role: string, revision: number) => ({ ...processReply, client_revision: revision })) as never,
      saveInitial: jest.fn(async () => { throw new Error("Network down"); }),
    });
    const request: JsonRequester = jest.fn(async () => ({}));
    const first = renderPanel(makeWorkspace(), api, jest.fn(), request);
    await act(async () => removePart2(first.tree)[0].props.onPress());
    await act(async () => { byLabel(first.tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(first.tree, "Confirm Step 1 underlying cause open search").props.onPress());
    await pickViaPicker("Y55");
    await act(async () => { byLabel(first.tree, "Save Step 1").props.onPress(); await flushAll(); });
    expect(JSON.stringify(first.tree.toJSON())).toContain("Network down");
    await act(async () => first.tree.unmount());

    const again = renderPanel(makeWorkspace(), api, jest.fn(), request);
    expect(byLabel(again.tree, "Process current certificate")).toBeTruthy();
    expect(removePart2(again.tree)).toHaveLength(0);
    await act(async () => again.tree.unmount());
  });
});

describe("final COD remark (digitva-p9j0)", () => {
  const withSavedRemark = (workspace: WorkspacePayload, remark: string): WorkspacePayload => ({ ...workspace, assessments: { ...workspace.assessments, final: { conclusive_cod: "A00", remark } as never } });
  const setRemark = (tree: ReactTestRenderer, value: string) => {
    expect(tree.root.findAllByProps({ accessibilityLabel: "COD remark" }).length).toBeGreaterThan(0);
    act(() => byLabel(tree, "COD remark").props.onChangeText(value));
  };

  it("sends the remark with the certificate final save", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ step: "final" }), api);
    setRemark(tree, "checked twice");
    expect(byLabel(tree, "COD remark").props.value).toBe("checked twice");
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
    await pickViaPicker("Y55");
    await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
    expect((api.saveFinal as jest.Mock).mock.calls[0][1]).toMatchObject({ conclusive_cod: "Y55", remark: "checked twice" });
    await act(async () => tree.unmount());
  });

  it("sends the remark with the masked final save", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ step: "final", masked: true }), api);
    setRemark(tree, "masked note");
    await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
    await pickViaPicker("Y55");
    await act(async () => { byLabel(tree, "Save final cause").props.onPress(); await flush(); });
    expect(api.saveFinal).toHaveBeenCalledWith("sid-1", { conclusive_cod: "Y55", remark: "masked note" }, "coding");
    await act(async () => tree.unmount());
  });

  it("prefills the saved final remark, masked and certificate", async () => {
    for (const masked of [false, true]) {
      const { tree } = renderPanel(withSavedRemark(makeWorkspace({ step: "final", masked }), "earlier remark"), apiFor());
      expect(tree.root.findAllByProps({ accessibilityLabel: "COD remark" }).length).toBeGreaterThan(0);
      expect(byLabel(tree, "COD remark").props.value).toBe("earlier remark");
      await act(async () => tree.unmount());
    }
  });

  it("has no remark box on the initial save", async () => {
    const { tree } = renderPanel(makeWorkspace(), apiFor());
    expect(tree.root.findAllByProps({ accessibilityLabel: "Process current certificate" }).length).toBeGreaterThan(0);
    expect(tree.root.findAllByProps({ accessibilityLabel: "COD remark" })).toHaveLength(0);
    await act(async () => tree.unmount());
  });
});

test("the DORIS reply keeps the server's notes about what was sent to WHO", () => {
  const { parseDorisProcess } = jest.requireActual("../src/workspace/contracts");
  const base = { schema_version: 1, client_revision: 0, icd_release: "2026-01", certificate: {}, certificate_digest: "d", result_digest: "r",
    doris: { status: "completed", result: null }, codedit: { status: "completed", result: null }, process_token: "t",
    who_notes: ["The date of birth is year-only. It was left out of the WHO check; your entry is kept.", 7] };
  const parsed = parseDorisProcess(base);
  expect(parsed.who_notes).toEqual(["The date of birth is year-only. It was left out of the WHO check; your entry is kept."]);
});
