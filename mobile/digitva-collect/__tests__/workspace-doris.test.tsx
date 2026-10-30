import React from "react";
import { AppState, Modal, Platform } from "react-native";
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

import * as viewState from "../src/workspace/viewState";
import { activateBrowserDraft, clearBrowserDraft, DORIS_DRAFT_KEY, draftContext, readCodDraft, readPendingNote, saveCodDraft, savePendingNote } from "../src/workspace/doris/browserDraft";
import { ApiError } from "../src/api";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import type { DorisProcessReply, JsonObject, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";
import { DorisPanel } from "../src/workspace/doris/DorisPanel";
import { AssociatedVaCodes } from "../src/workspace/doris/CodeDetailsSheet";
import { dorisGuidance, parseDorisOptions } from "../src/workspace/doris/guidance";
import { UNKNOWN_UNIT, parseInterval, serializeInterval } from "../src/workspace/doris/interval";

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

function renderPanel(workspace: WorkspacePayload, api: WorkspaceApi, onDone = jest.fn(), request: JsonRequester = jest.fn(async () => ({})), demo = false) {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<DorisPanel workspace={workspace} identity={identity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} demo={demo} />); });
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
  let text = allText(tree);
  expect(text).toContain("Underlying cause: 5A14 Diabetes mellitus, type unspecified");
  expect(text).toContain("+ BA41.Z Acute myocardial infarction, unspecified (manifestation)");
  expect(text).toContain("|5A14/BA41.Z|");
  // Stem, URI and the "/" explanation sit behind the collapsed Details toggle.
  expect(text).not.toContain("Computed stem");
  expect(text).not.toContain("joins the stem code DORIS chose");
  await act(async () => byLabel(tree, "Show DORIS code details").props.onPress());
  text = allText(tree);
  expect(text).toContain("Computed stem: |5A14");
  expect(text).toContain("Computed URI: |http://id.who.int/icd/release/11/mms/1");
  expect(text).toContain("joins the stem code DORIS chose");
  expect(byLabel(tree, "Hide DORIS code details").props.accessibilityState).toEqual({ expanded: true });
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
  // The public demo's exact messages (app/static/js/doris_interval.js).
  expect(serializeInterval("1e3", "Y").error).toBe("Enter a non-negative decimal number without an exponent.");
  expect(serializeInterval("", "Y").error).toBe("Enter a non-negative decimal number without an exponent.");
  expect(serializeInterval("2", "").error).toBe("Choose a time unit.");
  expect(serializeInterval("2", UNKNOWN_UNIT).error).toBe("Remove the interval value or choose a time unit.");
  expect(serializeInterval("", UNKNOWN_UNIT)).toEqual({ value: "", error: "" });
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
  expect(JSON.stringify(tree.toJSON())).toContain("Fever");
  await act(async () => byLabel(tree, "Remove Fever").props.onPress());
  expect(JSON.stringify(tree.toJSON())).not.toContain("Fever");
  await act(async () => tree.unmount());
});

it("adds a picker-verified code to the searched line with the line interval", async () => {
  const seed: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }, { Conditions: [] }] };
  const { tree } = renderPanel(makeWorkspace({ seed }), apiFor());
  await act(async () => byLabel(tree, "Open search Part I line 2").props.onPress());
  expect(mockFrame.props.init).toMatchObject({ title: "Due to", accent: "#B45309" });
  await pickViaPicker("Y55");
  expect(JSON.stringify(tree.toJSON())).toContain("Y55 — Selected cause");
  expect(byLabel(tree, "Remove Y55")).toBeDefined();
  await act(async () => tree.unmount());
});

function allText(tree: ReactTestRenderer): string {
  const out: string[] = [];
  const walk = (node: any) => { if (typeof node === "string") out.push(node); else if (node?.children) node.children.forEach(walk); };
  walk(tree.toJSON());
  return out.join("|");
}

function hostNodesWithTestId(tree: ReactTestRenderer, testID: string): ReactTestInstance[] {
  return tree.root.findAll((node) => typeof node.type === "string" && node.props.testID === testID);
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

  it("does not refill over a number typed without a unit, and Process is blocked until the unit is chosen", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
    await act(async () => tree.root.findByProps({ label: "Date of death" }).props.onChange("2025-08-12"));
    expect(byLabel(tree, "Estimated age").props.value).toBe("76");
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).toContain("Estimated age: Choose a time unit.");
    expect(api.processDoris).not.toHaveBeenCalled();
  });

  it("blocks Process when a unit is picked without a number, and does not refill when a date changes", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
    await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
    await act(async () => tree.root.findByProps({ label: "Date of death" }).props.onChange("2025-08-12"));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).toContain("Estimated age: Enter a non-negative decimal number without an exponent.");
    expect(api.processDoris).not.toHaveBeenCalled();
  });

  it("blocks Process with the demo's message for a value under Unknown, and for an exponent", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: dated }), api);
    await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
    await act(async () => byLabel(tree, "Estimated age unit: Unknown").props.onPress());
    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).toContain("Estimated age: Remove the interval value or choose a time unit.");
    expect(api.processDoris).not.toHaveBeenCalled();

    await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
    await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("1e3"));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).toContain("Estimated age: Enter a non-negative decimal number without an exponent.");
    expect(api.processDoris).not.toHaveBeenCalled();

    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
    expect((await sentCertificate(tree, api)).AdministrativeData).toMatchObject({ EstimatedAge: "P76Y" });
  });
});

it("shows the server's DORIS error message and each field path, not a generic line", async () => {
  const error = new ApiError(422, "INVALID_INPUT", undefined, undefined, { schema_version: 1, error: { code: "INVALID_INPUT", message: "The DORIS certificate is invalid.", fields: [{ path: "Part1[0].Conditions[0].Interval", message: "Interval must be an ISO 8601 duration." }] } });
  const api = apiFor({ processDoris: jest.fn(async () => { throw error; }) });
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(api.processDoris).toHaveBeenCalledTimes(1);
  expect(allText(tree)).toContain("The DORIS certificate is invalid. Check: Part1[0].Conditions[0].Interval — Interval must be an ISO 8601 duration.");
  await act(async () => tree.unmount());
});

describe("Step 1 result card and final cause picker (digitva-l5fw)", () => {
  const quickButton = (tree: ReactTestRenderer, prefix: string) => tree.root.findAll((n) => typeof n.props.label === "string" && n.props.label.startsWith(prefix) && typeof n.props.onPress === "function")[0];

  it("expands the details with every report box and logs no React warning", async () => {
    const errors = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const api = apiFor({ processDoris: jest.fn(async (): Promise<DorisProcessReply> => ({ ...processReply, doris: { status: "completed" as const, result: { ...processReply.doris.result, report: "DORIS report" } }, codedit: { status: "completed" as const, result: { report: "CoDEdit report", tabularReport: "CoDEdit table" } } })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Show DORIS code details").props.onPress());
    const text = allText(tree);
    expect(text).toContain("DORIS report");
    expect(text).toContain("CoDEdit report");
    expect(text).toContain("CoDEdit table");
    expect(errors.mock.calls.map((call) => String(call[0]))).toEqual([]);
    errors.mockRestore();
    await act(async () => tree.unmount());
  });

  it("shows one 'No problems found' for an empty CoDEdit run and collapses blank-line runs in the DORIS report", async () => {
    const api = apiFor({ processDoris: jest.fn(async (): Promise<DorisProcessReply> => ({ ...processReply, doris: { status: "completed" as const, result: { ...processReply.doris.result, report: "Line one\n\n\n\nLine two" } }, codedit: { status: "completed" as const, result: { report: "", tabularReport: "" } } })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    // The DORIS report sits behind the collapsed Details toggle, as the public demo keeps it.
    expect(allText(tree)).not.toContain("Line one");
    await act(async () => byLabel(tree, "Show DORIS code details").props.onPress());
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
    expect(hostNodesWithTestId(tree, "digitva-addition")).toHaveLength(1);
    await act(async () => tree.root.findAllByProps({ accessibilityLabel: "Details for CA40" })[0].props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("DigitVA addition — not from WHO");
    await act(async () => tree.unmount());
  });

  it("shows the associated VA code and its plain-text case definition under the chosen cause", async () => {
    const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => ({ icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Case <b>text</b></p>" })) });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    // A suggestion carries no banner of its own: the mapping shows once the coder chooses it.
    expect(allText(tree)).not.toContain("Associated VA codes");
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(api.getVaDefinitionForIcd).toHaveBeenCalledWith("CA40");
    expect(api.getVaDefinitionForIcd).toHaveBeenCalledTimes(1);
    expect(allText(tree)).toContain("Associated VA codes: VAs-01.01 Sepsis");
    expect(allText(tree)).toContain("Case text");
    expect(hostNodesWithTestId(tree, "associated-va-codes")).toHaveLength(0);
    expect(hostNodesWithTestId(tree, "va-definition-note")).toHaveLength(1);
    expect(allText(tree)).toContain("DigitVA addition — not from WHO");
    await act(async () => tree.unmount());
  });

  it("shows VA mapping directly under concrete suggestions in Step 1 and masked Step 2, without duplicate selected notes", async () => {
    const definition = { icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Severe chest pain…</p>" };
    const initialApi = apiFor({ getVaDefinitionForIcd: jest.fn(async () => definition) });
    const initial = renderPanel(makeWorkspace({ seed: whoSeed }), initialApi);
    await act(async () => { byLabel(initial.tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => flush());
    expect(hostNodesWithTestId(initial.tree, "va-definition-note")).toHaveLength(0);
    expect(hostNodesWithTestId(initial.tree, "associated-va-codes")).toHaveLength(0);
    await act(async () => quickButton(initial.tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(hostNodesWithTestId(initial.tree, "associated-va-codes")).toHaveLength(0);
    expect(hostNodesWithTestId(initial.tree, "va-definition-note")).toHaveLength(1);
    expect(allText(initial.tree)).toContain("Case definition");
    expect(allText(initial.tree)).toContain("Severe chest pain…");
    expect(allText(initial.tree).match(/Associated VA codes:/g)).toHaveLength(1);
    await act(async () => initial.tree.unmount());

    const maskedBase = makeWorkspace({ step: "final", masked: true });
    const maskedWorkspace = { ...maskedBase, assessments: { ...maskedBase.assessments, initial: { immediate_cod: "Pneumonia", antecedent_cod: "CA40" } } } as WorkspacePayload;
    const maskedApi = apiFor({ getVaDefinitionForIcd: jest.fn(async () => definition) });
    const masked = renderPanel(maskedWorkspace, maskedApi);
    await act(async () => flush());
    expect(allText(masked.tree)).toContain("DORIS suggests: |CA40");
    // The information card keeps the one banner until the same code is chosen; quick choices carry none.
    expect(hostNodesWithTestId(masked.tree, "associated-va-codes")).toHaveLength(1);
    expect(hostNodesWithTestId(masked.tree, "va-definition-note")).toHaveLength(0);
    await act(async () => quickButton(masked.tree, "Use Step 1 underlying cause").props.onPress());
    await act(async () => flush());
    expect(hostNodesWithTestId(masked.tree, "associated-va-codes")).toHaveLength(0);
    expect(hostNodesWithTestId(masked.tree, "va-definition-note")).toHaveLength(1);
    await act(async () => masked.tree.unmount());
  });

  it("labels the chosen cause and swaps the matching quick choice for plain text (Step 1)", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).not.toContain("Your choice");
    expect(quickButton(tree, "Use DORIS result")).toBeDefined();
    await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("Your choice: CA40 — Selected cause");
    expect(allText(tree)).toContain("Your choice matches the DORIS result.");
    expect(quickButton(tree, "Use DORIS result")).toBeUndefined();
    await act(async () => byLabel(tree, "Clear chosen cause CA40").props.onPress());
    expect(allText(tree)).not.toContain("Your choice");
    expect(quickButton(tree, "Use DORIS result")).toBeDefined();
    await act(async () => tree.unmount());
  });

  it("masked Step 2 shows one banner for the chosen cause and marks the matching Step 1 choice, keeping SmartVA a button", async () => {
    const definition = { icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Case definition</p>" };
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = {
      ...base,
      assessments: { ...base.assessments, initial: { immediate_cod: "Pneumonia", antecedent_cod: "CA40" } },
      smartva: { age: "40", gender: "Male", key_symptoms: [null, null, null], causes: [{ rank: 1, cause: "Stroke", icd10: "I64", icd11: "8B20", likelihood: null }], symptoms: [] },
    } as unknown as WorkspacePayload;
    const { tree } = renderPanel(workspace, apiFor({ getVaDefinitionForIcd: jest.fn(async () => definition) }));
    await act(async () => flush());
    expect(allText(tree)).not.toContain("Your choice");
    await act(async () => quickButton(tree, "Use Step 1 underlying cause").props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("Your choice: CA40 — Selected cause");
    expect(allText(tree)).toContain("Your choice matches your Step 1 underlying cause.");
    expect(quickButton(tree, "Use Step 1 underlying cause")).toBeUndefined();
    expect(quickButton(tree, "Use SmartVA result")).toBeDefined();
    // One banner for the chosen cause; the Step 1 information card and the suggestions add none.
    expect(hostNodesWithTestId(tree, "va-definition-note")).toHaveLength(1);
    expect(hostNodesWithTestId(tree, "associated-va-codes")).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("keeps the DORIS button when only the stem is chosen, and swaps it only for the primary code", async () => {
    const api = apiFor({ processDoris: jest.fn(async () => ({ ...processReply, doris: { status: "completed", result: { code: "CA40.1", stemCode: "CA40", title: "Pneumonia" } } })) as WorkspaceApi["processDoris"] });
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Confirm Step 1 underlying cause open search").props.onPress());
    await pickViaPicker("CA40");
    await act(async () => flush());
    expect(allText(tree)).toContain("Your choice: CA40 — Selected cause");
    expect(allText(tree)).not.toContain("Your choice matches the DORIS result.");
    expect(quickButton(tree, "Use DORIS result: CA40.1")).toBeDefined();
    await act(async () => quickButton(tree, "Use DORIS result: CA40.1").props.onPress());
    await act(async () => flush());
    expect(allText(tree)).toContain("Your choice: CA40.1");
    expect(allText(tree)).toContain("Your choice matches the DORIS result.");
    expect(quickButton(tree, "Use DORIS result")).toBeUndefined();
    await act(async () => tree.unmount());
  });

  it("retries a rejected VA mapping lookup instead of caching the transient failure", async () => {
    const definition = { icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Case definition</p>" };
    let attempts = 0;
    const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("temporary mapping failure");
      return definition;
    }) });
    const first = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(first.tree, "Process current certificate").props.onPress(); await flushAll(); });
    await act(async () => { quickButton(first.tree, "Use DORIS result").props.onPress(); await flushAll(); });
    expect(allText(first.tree)).not.toContain("Associated VA codes");
    await act(async () => first.tree.unmount());
    const second = renderPanel(makeWorkspace({ seed: whoSeed }), api);
    await act(async () => { byLabel(second.tree, "Process current certificate").props.onPress(); await flushAll(); });
    await act(async () => { quickButton(second.tree, "Use DORIS result").props.onPress(); await flushAll(); });
    expect(attempts).toBe(2);
    expect(allText(second.tree)).toContain("Associated VA codes: VAs-01.01 Sepsis");
    await act(async () => second.tree.unmount());
  });

  it("does not render a late mapping result for the previous code", async () => {
    let resolveOld!: (value: any) => void;
    const oldDefinition = { icd_code: "CA40", classification: "icd11", va_code: "VAs-old", title: "Old cause", definition_html: "<p>Old definition</p>" };
    const newDefinition = { icd_code: "CA41", classification: "icd11", va_code: "VAs-new", title: "New cause", definition_html: "<p>New definition</p>" };
    const api = apiFor({ getVaDefinitionForIcd: jest.fn((code: string) => code === "CA40" ? new Promise((resolve) => { resolveOld = resolve; }) : Promise.resolve(newDefinition)) });
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<AssociatedVaCodes api={api} code="CA40" />); await flushAll(); });
    await act(async () => { tree.update(<AssociatedVaCodes api={api} code="CA41" />); await flushAll(); });
    expect(allText(tree)).toContain("VAs-new");
    expect(allText(tree)).not.toContain("VAs-old");
    await act(async () => { resolveOld(oldDefinition); await flushAll(); });
    expect(allText(tree)).toContain("VAs-new");
    expect(allText(tree)).not.toContain("VAs-old");
    await act(async () => tree.unmount());
  });

  describe("VA cause bucket display", () => {
    const withBucket = { icd_code: "CA40", classification: "icd11", va_code: "VAs-01.01", title: "Sepsis", definition_html: "<p>Case <b>text</b></p>", bucket_code: "vas_01_01", bucket_label: "Sepsis", bucket_section: "Infectious diseases", has_definition: true };
    const labelOnly = { icd_code: "5A00", classification: "icd11", va_code: "VAs-98", title: "Other and unspecified NCD", definition_html: "", bucket_code: "vas_98", bucket_label: "Other and unspecified NCD", bucket_section: "Non-communicable diseases", has_definition: false };
    const show = async (lookup: unknown, props: Partial<React.ComponentProps<typeof AssociatedVaCodes>> = {}) => {
      const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => lookup) as unknown as WorkspaceApi["getVaDefinitionForIcd"] });
      let tree!: ReactTestRenderer;
      await act(async () => { tree = create(<AssociatedVaCodes api={api} code="CA40" showDefinition {...props} />); await flushAll(); });
      return tree;
    };

    it("shows the section, the VA cause and the plain-text definition for a bucket with one", async () => {
      const tree = await show(withBucket);
      const text = allText(tree);
      expect(text).toContain("Infectious diseases");
      expect(text).toContain("VA cause: Sepsis (VAs-01.01)");
      expect(text).toContain("Case definition");
      expect(text).toContain("Case text");
      expect(text).not.toContain("Associated VA codes");
      await act(async () => tree.unmount());
    });

    it("shows a label-only bucket with no definition paragraph", async () => {
      const tree = await show(labelOnly);
      const text = allText(tree);
      expect(text).toContain("Non-communicable diseases");
      expect(text).toContain("VA cause: Other and unspecified NCD (VAs-98)");
      expect(text).not.toContain("Case definition");
      expect(text).not.toContain("No definition text");
      await act(async () => tree.unmount());
    });

    it("says not mapped for an unmapped code, and stays silent when the lookup fails", async () => {
      const unmapped = await show(null);
      expect(allText(unmapped)).toContain("VA cause: not mapped");
      expect(allText(unmapped)).not.toContain("Case definition");
      await act(async () => unmapped.unmount());
      const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => { throw new Error("offline"); }) });
      let failed!: ReactTestRenderer;
      await act(async () => { failed = create(<AssociatedVaCodes api={api} code="CA40" showDefinition />); await flushAll(); });
      expect(allText(failed)).not.toContain("VA cause");
      await act(async () => failed.unmount());
    });

    it("shows the bucket label alone on the Step 1 card, and keeps the old wording for a server without buckets", async () => {
      const card = await show(withBucket, { showDefinition: false });
      expect(allText(card)).toContain("VA cause: Sepsis (VAs-01.01)");
      expect(allText(card)).not.toContain("Case definition");
      await act(async () => card.unmount());
      const { bucket_code, bucket_label, bucket_section, has_definition, ...old } = withBucket;
      const legacy = await show(old);
      expect(allText(legacy)).toContain("Associated VA codes: VAs-01.01 Sepsis");
      expect(allText(legacy)).toContain("Case text");
      await act(async () => legacy.unmount());
    });

    it("shows the same lines in the ICD-11 details sheet", async () => {
      const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => labelOnly) });
      const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
      await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
      await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
      await act(async () => flush());
      await act(async () => tree.root.findAllByProps({ accessibilityLabel: "Details for CA40" })[0].props.onPress());
      await act(async () => flush());
      // Once under the chosen cause and once in the sheet.
      const text = allText(tree);
      expect(text.match(/Non-communicable diseases/g)).toHaveLength(2);
      expect(text.match(/VA cause: Other and unspecified NCD \(VAs-98\)/g)).toHaveLength(2);
      expect(text).not.toContain("No definition text");
      await act(async () => tree.unmount());
    });

    it("never disables Process or Save for an unmapped code", async () => {
      const api = apiFor({ getVaDefinitionForIcd: jest.fn(async () => null) });
      const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), api);
      await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
      await act(async () => quickButton(tree, "Use DORIS result").props.onPress());
      await act(async () => flush());
      expect(allText(tree)).toContain("VA cause: not mapped");
      expect(byLabel(tree, "Process current certificate").props.disabled).toBeFalsy();
      expect(byLabel(tree, "Save Step 1").props.disabled).toBeFalsy();
      await act(async () => tree.unmount());
    });
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
    expect(text).toContain("28 years · Female");
    expect(text).not.toContain("28.0");
    expect(text).toContain("SmartVA Analysis|28 years · Female|1|Pneumonia");
    expect(text).toContain("ICD-10 J18 · ICD-11 CA40/CA41");
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

  describe("age restriction confirmation and causing-condition-unknown", () => {
    const ageError = () => new ApiError(422, "AGE_RESTRICTION_CONFIRMATION_REQUIRED", undefined, undefined, { error: "Age restriction", code: "AGE_RESTRICTION_CONFIRMATION_REQUIRED", age_restriction: { code: "Y55", age_group_selectable: "adults", restriction_note: "Not for children." } });
    const confirmButton = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label)[0];
    const reachSave = async (tree: ReactTestRenderer) => {
      await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
      await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
      await pickViaPicker("Y55");
    };

    it("asks on 422, resends with age_restriction_confirmed on confirm, and leaves the form on cancel", async () => {
      const saveFinal = jest.fn().mockRejectedValueOnce(ageError()).mockRejectedValueOnce(ageError()).mockResolvedValueOnce({ va_sid: "sid-1", final_assessment_id: "final-1" });
      const api = apiFor({ saveFinal });
      const { tree, onDone } = renderPanel(makeWorkspace({ step: "final" }), api);
      await reachSave(tree);
      await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
      const dialog = JSON.stringify(tree.toJSON());
      expect(dialog).toContain("Y55 is usually used only for adults.");
      expect(dialog).toContain("Not for children.");
      await act(async () => confirmButton(tree, "Cancel").props.onPress());
      expect(saveFinal).toHaveBeenCalledTimes(1);
      expect(onDone).not.toHaveBeenCalled();
      expect(byLabel(tree, "Save final COD").props.disabled).toBe(false);
      await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
      await act(async () => { confirmButton(tree, "Save anyway").props.onPress(); await flushAll(); });
      expect(saveFinal).toHaveBeenCalledTimes(3);
      expect(saveFinal.mock.calls[0][1]).not.toHaveProperty("age_restriction_confirmed");
      expect(saveFinal.mock.calls[2][1]).toMatchObject({ conclusive_cod: "Y55", age_restriction_confirmed: true });
      expect(onDone).toHaveBeenCalledTimes(1);
      await act(async () => tree.unmount());
    });

    it("keeps the existing error for a sex refusal", async () => {
      const saveFinal = jest.fn().mockRejectedValue(new ApiError(422, "final_blocked", undefined, undefined, { messages: ["Y55 is not valid for this sex."] }));
      const { tree } = renderPanel(makeWorkspace({ step: "final" }), apiFor({ saveFinal }));
      await reachSave(tree);
      await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
      expect(JSON.stringify(tree.toJSON())).toContain("Y55 is not valid for this sex.");
      expect(confirmButton(tree, "Save anyway")).toBeUndefined();
      await act(async () => tree.unmount());
    });

    const reachStep1Save = async (tree: ReactTestRenderer) => {
      await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
      await act(async () => byLabel(tree, "Confirm Step 1 underlying cause open search").props.onPress());
      await pickViaPicker("Y55");
    };

    it("Step 1: asks on 422, leaves the form on cancel, resends with age_restriction_confirmed on confirm", async () => {
      const saveInitial = jest.fn().mockRejectedValueOnce(ageError()).mockRejectedValueOnce(ageError()).mockResolvedValueOnce({ va_sid: "sid-1", initial_assessment_id: "initial-1" });
      const { tree } = renderPanel(makeWorkspace(), apiFor({ saveInitial }));
      await reachStep1Save(tree);
      await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flushAll(); });
      expect(JSON.stringify(tree.toJSON())).toContain("Not for children.");
      await act(async () => confirmButton(tree, "Cancel").props.onPress());
      expect(saveInitial).toHaveBeenCalledTimes(1);
      expect(byLabel(tree, "Save Step 1").props.disabled).toBe(false);
      await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flushAll(); });
      await act(async () => { confirmButton(tree, "Save anyway").props.onPress(); await flushAll(); });
      expect(saveInitial).toHaveBeenCalledTimes(3);
      expect(saveInitial.mock.calls[0][1]).not.toHaveProperty("age_restriction_confirmed");
      expect(saveInitial.mock.calls[2][1]).toMatchObject({ antecedent_cod: "Y55", age_restriction_confirmed: true });
      expect(saveInitial.mock.calls[2][1]).not.toHaveProperty("causing_condition_unknown");
      await act(async () => tree.unmount());
    });

    it("Step 1: a sex refusal stays an error with no confirm dialog", async () => {
      const saveInitial = jest.fn().mockRejectedValue(new ApiError(422, "final_blocked", undefined, undefined, { messages: ["Y55 is not valid for this sex."] }));
      const { tree } = renderPanel(makeWorkspace(), apiFor({ saveInitial }));
      await reachStep1Save(tree);
      await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flushAll(); });
      expect(JSON.stringify(tree.toJSON())).toContain("Y55 is not valid for this sex.");
      expect(confirmButton(tree, "Save anyway")).toBeUndefined();
      await act(async () => tree.unmount());
    });

    it("tolerates a 422 without the age_restriction object", async () => {
      const saveFinal = jest.fn().mockRejectedValueOnce(new ApiError(422, "AGE_RESTRICTION_CONFIRMATION_REQUIRED", undefined, undefined, { error: "x" }));
      const { tree } = renderPanel(makeWorkspace({ step: "final" }), apiFor({ saveFinal }));
      await reachSave(tree);
      await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
      expect(JSON.stringify(tree.toJSON())).toContain("Y55 is usually used only for certain age groups.");
      expect(confirmButton(tree, "Save anyway")).toBeDefined();
      await act(async () => tree.unmount());
    });

    it("masked final save: confirms and sends causing_condition_unknown from the picker", async () => {
      const saveFinal = jest.fn().mockRejectedValueOnce(ageError()).mockResolvedValueOnce({ va_sid: "sid-1", final_assessment_id: "final-1" });
      const { tree } = renderPanel(makeWorkspace({ step: "final", masked: true }), apiFor({ saveFinal }));
      await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
      const reply = jest.fn();
      await act(async () => { mockFrame.props.onMessage({ t: "req", id: 2, path: "selection-check", body: { schema_version: 1, code: "Y55", uri: "https://who.int/Y55" } }, reply); await flushAll(); });
      await act(async () => { mockFrame.props.onMessage({ t: "select", choice: { code: "Y55", uri: "https://who.int/Y55", causing_condition_unknown: true } }, reply); await flushAll(); });
      await act(async () => { byLabel(tree, "Save final cause").props.onPress(); await flushAll(); });
      expect(saveFinal.mock.calls[0][1]).toMatchObject({ conclusive_cod: "Y55", causing_condition_unknown: true });
      await act(async () => { confirmButton(tree, "Save anyway").props.onPress(); await flushAll(); });
      expect(saveFinal.mock.calls[1][1]).toMatchObject({ causing_condition_unknown: true, age_restriction_confirmed: true });
      await act(async () => tree.unmount());
    });
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

describe("DORIS parity with the public demo: reopened titles and notes, Part 2, Sex label, Details", () => {
  const stemTitle = { code: "5A14", title: "Diabetes mellitus, type unspecified", role: "stem", uri: null };
  const cluster = { code: "5A14/BA41.Z", stemCode: "5A14" };

  it("shows a reopened run's stored UCOD titles while hiding year-only technical notes", async () => {
    const api = apiFor();
    const saved = {
      certificate,
      doris: { status: "completed", result: cluster },
      codedit: { status: "completed", result: { report: "", tabularReport: "" } },
      final_choice: "",
      ucod_parts: [stemTitle, { code: "BA41.Z", title: "Acute myocardial infarction, unspecified", role: "postcoordinated", uri: null }],
      who_notes: ["Year-only dates left out of the WHO check: date of death. Your entries are kept."],
    } as unknown as JsonObject;
    const { tree } = renderPanel(makeWorkspace({ processing: saved }), api);
    const text = allText(tree);
    expect(text).toContain("Underlying cause: 5A14 Diabetes mellitus, type unspecified");
    expect(text).not.toContain("Year-only dates left out of the WHO check:");
    expect(text).not.toContain("Computed UCOD:");
    await act(async () => tree.unmount());
  });

  it("hides the earlier stored year-only wording but keeps actionable WHO/internal errors", async () => {
    const liveApi = apiFor({ processDoris: jest.fn(async () => ({ ...processReply, who_notes: ["Year-only dates left out of the WHO check: date of death. Your entries are kept.", "WHO internal engine failure: retry the certificate."] })) });
    const live = renderPanel(makeWorkspace(), liveApi);
    await act(async () => { byLabel(live.tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(live.tree)).not.toContain("Year-only dates left out of the WHO check:");
    expect(allText(live.tree)).toContain("WHO internal engine failure: retry the certificate.");
    await act(async () => live.tree.unmount());

    const saved = {
      certificate,
      doris: { status: "completed", result: { code: "CA40", stemCode: "CA40" } },
      codedit: { status: "completed", result: {} },
      who_notes: [
        "The date of birth is year-only. It was left out of the WHO check; your entry is kept.",
        "WHO internal engine failure: retry the certificate.",
      ],
    } as unknown as JsonObject;
    const { tree } = renderPanel(makeWorkspace({ processing: saved }), apiFor());
    const text = allText(tree);
    expect(text).not.toContain("The date of birth is year-only.");
    expect(text).toContain("WHO internal engine failure: retry the certificate.");
    await act(async () => tree.unmount());
  });

  it("titles the Step 1 suggestion from its stored stem part, with no WHO lookup", async () => {
    const api = apiFor();
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = { ...base, doris: { ...base.doris, step1_processing: { doris: { status: "completed", result: cluster }, codedit: { status: "completed", result: {} }, ucod_parts: [stemTitle] } } } as unknown as WorkspacePayload;
    const { tree } = renderPanel(workspace, api);
    await act(async () => flush());
    expect(allText(tree)).toContain("DORIS suggests: |5A14/BA41.Z| — Diabetes mellitus, type unspecified");
    expect(api.getDorisCodeInfo).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("looks up a Step 1 suggestion's title by its stem, never by the full computed UCOD", async () => {
    const api = apiFor();
    const base = makeWorkspace({ step: "final", masked: true });
    const workspace = { ...base, doris: { ...base.doris, step1_processing: { doris: { status: "completed", result: cluster }, codedit: { status: "completed", result: {} } } } } as unknown as WorkspacePayload;
    const { tree } = renderPanel(workspace, api);
    await act(async () => flush());
    expect(api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "5A14");
    expect(api.getDorisCodeInfo).not.toHaveBeenCalledWith("sid-1", "5A14/BA41.Z");
    expect(allText(tree)).toContain("DORIS suggests: |5A14/BA41.Z| — Selected cause");
    await act(async () => tree.unmount());
  });

  it("drops an empty Part 2 from the processed certificate, and keeps Part 2 when it has a condition", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ...certificate, Part2: { Conditions: [] } } }), api);
    const sent = await sentCertificate(tree, api);
    expect(sent.Part1).toHaveLength(1);
    expect(sent).not.toHaveProperty("Part2");
    await act(async () => tree.unmount());

    const withPart2 = apiFor();
    const kept = renderPanel(makeWorkspace(), withPart2);
    expect((await sentCertificate(kept.tree, withPart2)).Part2).toEqual({ Conditions: [{ Text: "Diabetes", Code: "5A11", LinearizationURI: "https://who.int/5A11" }] });
    await act(async () => kept.tree.unmount());
  });

  it("labels Sex code 9 Unknown, not Undetermined", () => {
    const { tree } = renderPanel(makeWorkspace({ seed: { ...certificate, AdministrativeData: { Sex: 1 } } }), apiFor());
    expect(allText(tree)).toContain("Sex|Not stated|Male|Female|Unknown|Date of birth");
    // Estimated age follows the two dates it is derived from.
    expect(allText(tree)).toMatch(/Date of birth\|.*Date of death\|.*Estimated age\|/);
    expect(allText(tree)).not.toContain("Undetermined");
  });

  it("keeps the CoDEdit readable and tabular reports behind Details, with the WHO check visible", async () => {
    const reply: DorisProcessReply = {
      ...processReply,
      codedit: { status: "completed", result: { issueIds: "BER-CE-9", report: "RE_W_IV_CodeURIMismatch", tabularReport: "0,RE_W_IV_CodeURIMismatch,BER-CE-9;5A11/GB61.Z;;;" } },
    };
    const { tree } = renderPanel(makeWorkspace(), apiFor({ processDoris: jest.fn(async () => reply) }));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect(allText(tree)).toContain("The selected code - 5A11/GB61.Z - and URI correspond to different ICD entities");
    expect(allText(tree)).not.toContain("RE_W_IV_CodeURIMismatch");
    await act(async () => byLabel(tree, "Show DORIS code details").props.onPress());
    expect(allText(tree)).toContain("RE_W_IV_CodeURIMismatch");
    expect(allText(tree)).toContain("0,RE_W_IV_CodeURIMismatch,BER-CE-9");
    await act(async () => tree.unmount());
  });
});

describe("web reload recovery", () => {
  const values = new Map<string, string>();
  const store = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  };
  let platform: PropertyDescriptor | undefined;
  beforeEach(() => {
    platform = Object.getOwnPropertyDescriptor(Platform, "OS");
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    jest.spyOn(viewState, "browserSessionStore").mockReturnValue(store);
    clearBrowserDraft();
    values.clear();
  });
  afterEach(() => {
    clearBrowserDraft();
    jest.restoreAllMocks();
    if (platform) Object.defineProperty(Platform, "OS", platform);
  });
  function authorizedWorkspace(): WorkspacePayload {
    const workspace = makeWorkspace({ step: "final", seed: { ...certificate, AdministrativeData: { Sex: 1, DateBirth: "2000-01-01" } } });
    workspace.case.doris_draft_context = "opaque-user-allocation-context";
    workspace.case.payload_version_id = "payload-1";
    workspace.doris!.reset_certificate = { AdministrativeData: { Sex: 2, DateBirth: "2001-01-01" } };
    workspace.smartva = { cause: "Server SmartVA" };
    activateBrowserDraft(draftContext(workspace, identity));
    return workspace;
  }

  it("reload restores COD/remark/selection, uses fresh demographics and requires reprocessing", async () => {
    const workspace = authorizedWorkspace();
    const first = renderPanel(workspace, apiFor());
    await act(async () => byLabel(first.tree, "Part I line 1 interval").props.onChangeText("3"));
    await act(async () => byLabel(first.tree, "COD remark").props.onChangeText("Retained remark"));
    // Store a selected cause as the real picker does, without retaining its process proof.
    const context = draftContext(workspace, identity)!;
    const saved = readCodDraft(context, "final")!;
    saveCodDraft(context, { ...saved, selectedCause: { code: "CA40", title: "Chosen pneumonia", uri: "https://who.int/CA40" } });
    await act(async () => first.tree.unmount());
    const freshWorkspace = { ...workspace, doris: { ...workspace.doris!, initial_certificate: { ...certificate, AdministrativeData: { Sex: 2, DateBirth: "2002-01-01" } } } };
    const api = apiFor();
    const second = renderPanel(freshWorkspace, api);
    expect(byLabel(second.tree, "COD remark").props.value).toBe("Retained remark");
    expect(byLabel(second.tree, "Part I line 1 interval").props.value).toBe("3");
    expect(allText(second.tree)).toContain("Chosen pneumonia");
    expect(byLabel(second.tree, "Save final COD").props.disabled).toBe(true);
    expect(allText(second.tree)).not.toContain("DORIS and CoDEdit");
    await act(async () => { byLabel(second.tree, "Process current certificate").props.onPress(); await flush(); });
    const sent = (api.processDoris as jest.Mock).mock.calls[0][3];
    expect(sent.AdministrativeData).toEqual({ Sex: 2, DateBirth: "2002-01-01" });
    expect(sent.Part1[0].Conditions[0].Interval).toBe("P3D");
    expect(values.get(DORIS_DRAFT_KEY)).not.toContain("DateBirth");
    await act(async () => second.tree.unmount());
  });

  it("failed final submission keeps recovery data and successful submission clears it", async () => {
    const workspace = authorizedWorkspace();
    const api = apiFor({ saveFinal: jest.fn().mockRejectedValueOnce(new Error("Network failed")).mockResolvedValueOnce({ va_sid: "sid-1", final_assessment_id: "final-1" }) });
    const { tree, onDone } = renderPanel(workspace, api);
    await act(async () => byLabel(tree, "COD remark").props.onChangeText("Keep on failure"));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
    await pickViaPicker("CA40");
    await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
    expect(onDone).not.toHaveBeenCalled();
    expect(readCodDraft(draftContext(workspace, identity), "final")?.remark).toBe("Keep on failure");
    await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(values.has(DORIS_DRAFT_KEY)).toBe(false);
    await act(async () => tree.unmount());
  });

  it.each(["remark", "certificate"])("late final-save success preserves newer same-case %s edits", async (field) => {
    const workspace = authorizedWorkspace();
    let complete!: (value: Awaited<ReturnType<WorkspaceApi["saveFinal"]>>) => void;
    const api = apiFor({ saveFinal: jest.fn(() => new Promise((resolve) => { complete = resolve; })) as WorkspaceApi["saveFinal"] });
    const { tree, onDone } = renderPanel(workspace, api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
    await pickViaPicker("CA40");
    await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flush(); });
    await act(async () => field === "remark"
      ? byLabel(tree, "COD remark").props.onChangeText("Newer unsaved remark")
      : byLabel(tree, "Part I line 1 interval").props.onChangeText("4"));
    const before = values.get(DORIS_DRAFT_KEY);
    expect(before).toContain(field === "remark" ? "Newer unsaved remark" : "P4D");
    await act(async () => { complete({ va_sid: "sid-1", final_assessment_id: "saved" }); await flushAll(); });
    expect(onDone).not.toHaveBeenCalled();
    expect(values.get(DORIS_DRAFT_KEY)).toBe(before);
    await act(async () => tree.unmount());
  });

  it("late final-save success cannot clear another case's draft", async () => {
    const workspace = authorizedWorkspace();
    let complete!: (value: Awaited<ReturnType<WorkspaceApi["saveFinal"]>>) => void;
    const api = apiFor({ saveFinal: jest.fn(() => new Promise((resolve) => { complete = resolve; })) as WorkspaceApi["saveFinal"] });
    const { tree, onDone, request } = renderPanel(workspace, api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
    await pickViaPicker("CA40");
    await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flush(); });
    const nextIdentity = { ...identity, vaSid: "sid-2" };
    const next = { ...workspace, case: { ...workspace.case, va_sid: "sid-2", doris_draft_context: "case-two-context" } };
    activateBrowserDraft(draftContext(next, nextIdentity));
    await act(async () => tree.update(<DorisPanel workspace={next} identity={nextIdentity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} />));
    await act(async () => byLabel(tree, "COD remark").props.onChangeText("Second case draft"));
    const before = values.get(DORIS_DRAFT_KEY);
    await act(async () => { complete({ va_sid: "sid-1", final_assessment_id: "saved" }); await flushAll(); });
    expect(onDone).not.toHaveBeenCalled();
    expect(values.get(DORIS_DRAFT_KEY)).toBe(before);
    expect(byLabel(tree, "COD remark").props.value).toBe("Second case draft");
    await act(async () => tree.unmount());
  });

  it.each([false, true])("stale ICD-11 403 preserves current edits (new case: %s)", async (navigate) => {
    const workspace = authorizedWorkspace();
    let fail!: (error: unknown) => void;
    const api = apiFor({ getDorisCodeInfo: jest.fn(() => new Promise((_resolve, reject) => { fail = reject; })) as WorkspaceApi["getDorisCodeInfo"] });
    const { tree, onDone, request } = renderPanel(workspace, api);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    const quick = tree.root.findAll((node) => typeof node.props.label === "string" && node.props.label.startsWith("Use DORIS result") && typeof node.props.onPress === "function")[0];
    await act(async () => { quick.props.onPress(); await flush(); });
    if (navigate) {
      const nextIdentity = { ...identity, vaSid: "sid-2" };
      const next = { ...workspace, case: { ...workspace.case, va_sid: "sid-2", doris_draft_context: "case-two-context" } };
      activateBrowserDraft(draftContext(next, nextIdentity));
      await act(async () => tree.update(<DorisPanel workspace={next} identity={nextIdentity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} />));
    }
    await act(async () => byLabel(tree, "COD remark").props.onChangeText("Newer draft"));
    const before = values.get(DORIS_DRAFT_KEY);
    await act(async () => { fail(new ApiError(403, "no_allocation")); await flushAll(); });
    expect(onDone).not.toHaveBeenCalled();
    expect(values.get(DORIS_DRAFT_KEY)).toBe(before);
    expect(byLabel(tree, "COD remark").props.value).toBe("Newer draft");
    await act(async () => tree.unmount());
  });

  it.each(["certificate edit", "remark edit", "close", "navigation"])("stale picker-page 403 cannot clear the current draft after %s", async (change) => {
    const workspace = authorizedWorkspace();
    let fail!: (error: unknown) => void;
    const api = apiFor({ searchDorisTerms: jest.fn(() => new Promise((_resolve, reject) => { fail = reject; })) as WorkspaceApi["searchDorisTerms"] });
    const { tree, onDone, request } = renderPanel(workspace, api);
    await act(async () => byLabel(tree, "COD remark").props.onChangeText("Keep this draft"));
    await act(async () => byLabel(tree, "Search Part I line 1 condition").props.onSubmitEditing());
    const oldFrame = mockFrame.props;
    const reply = jest.fn();
    await act(async () => { oldFrame.onMessage({ t: "req", id: 77, path: "terms", body: { query: "pneu" } }, reply); await flush(); });
    expect(api.searchDorisTerms).toHaveBeenCalledTimes(1);
    if (change === "certificate edit") await act(async () => byLabel(tree, "Part I line 1 interval").props.onChangeText("4"));
    else if (change === "remark edit") await act(async () => byLabel(tree, "COD remark").props.onChangeText("Newer remark"));
    else if (change === "close") await act(async () => oldFrame.onMessage({ t: "close" }, reply));
    else {
      const nextIdentity = { ...identity, vaSid: "sid-2" };
      const next = { ...workspace, case: { ...workspace.case, va_sid: "sid-2", doris_draft_context: "case-two-context" } };
      activateBrowserDraft(draftContext(next, nextIdentity));
      await act(async () => tree.update(<DorisPanel workspace={next} identity={nextIdentity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} />));
      await act(async () => byLabel(tree, "COD remark").props.onChangeText("New form draft"));
    }
    const before = values.get(DORIS_DRAFT_KEY);
    expect(before).toBeDefined();
    await act(async () => { fail(new ApiError(403, "no_allocation")); await flushAll(); });
    expect(onDone).not.toHaveBeenCalled();
    expect(values.get(DORIS_DRAFT_KEY)).toBe(before);
    expect(tree.root.findAllByProps({ accessibilityLabel: "COD remark" }).length).toBeGreaterThan(0);
    expect(reply).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("reset clears causes and processing while retaining remarks, pending note and server SmartVA", async () => {
    const workspace = authorizedWorkspace();
    savePendingNote(draftContext(workspace, identity), "Keep pending note");
    const { tree } = renderPanel(workspace, apiFor());
    await act(async () => byLabel(tree, "COD remark").props.onChangeText("Keep remark"));
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    await act(async () => byLabel(tree, "Reset DORIS from interview").props.onPress());
    expect(byLabel(tree, "COD remark").props.value).toBe("Keep remark");
    expect(byLabel(tree, "Save final COD").props.disabled).toBe(true);
    expect(allText(tree)).not.toContain("Pneumonia");
    expect(readPendingNote(draftContext(workspace, identity))).toBe("Keep pending note");
    expect(readCodDraft(draftContext(workspace, identity), "final")?.certificate.Part1).toEqual([{ Conditions: [] }, { Conditions: [] }, { Conditions: [] }]);
    expect(workspace.smartva).toEqual({ cause: "Server SmartVA" });
    await act(async () => tree.unmount());
  });
});

/** Merged style of a host node (arrays flattened). */
function flatStyle(node: ReactTestInstance): Record<string, any> {
  const raw = node.props.style;
  return Object.assign({}, ...[typeof raw === "function" ? raw({ pressed: false }) : raw].flat(3).filter(Boolean));
}
const hostAncestors = (node: ReactTestInstance) => { const out: ReactTestInstance[] = []; for (let n = node.parent; n; n = n.parent) if (typeof n.type === "string") out.push(n); return out; };
const hostText = (node: ReactTestInstance): string => node.findAll((n) => typeof n.type === "string").flatMap((n) => n.children.filter((c): c is string => typeof c === "string")).join("");

describe("form layout stays in flow (digitva-4x2y)", () => {
  const prefilled: JsonObject = { ...certificate, AdministrativeData: { Sex: 2, EstimatedAge: "P62Y", DateBirth: "1964-05-06", DateDeath: "2026-10-01" } };
  const provenance: JsonObject = { "AdministrativeData.EstimatedAge": { sources: ["Id10019"] }, "AdministrativeData.DateDeath": { sources: ["Id10023"] } };

  it("keeps every administrative field inside its card: nothing in a column cell grows or has a flex-basis (a height there)", async () => {
    const { tree } = renderPanel(makeWorkspace({ seed: prefilled, prefill: provenance }), apiFor());
    const title = tree.root.findAll((n) => typeof n.type === "string" && n.children.includes("Administrative Data"))[0];
    const card = hostAncestors(title).find((n) => flatStyle(n).borderWidth === 1)!;
    for (const label of ["Estimated age", "Estimated age unit", "Date of birth precision", "Date of birth", "Date of death", "Clear Date of death"]) {
      expect(card.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === label).length).toBeGreaterThan(0);
    }
    // Root cause of the controls drawn far below their labels: RN's Yoga (legacy stretch errata) fills the height a column offers
    // to a child with flexGrow/flex, and reads flexBasis as a height. So such a child must sit in a row (where both are widths).
    let grown = 0;
    for (const node of card.findAll((n) => typeof n.type === "string")) {
      const style = flatStyle(node);
      if (!(style.flexGrow > 0 || style.flex > 0 || style.flexBasis !== undefined)) continue;
      grown += 1;
      expect(flatStyle(hostAncestors(node)[0]).flexDirection).toBe("row");
    }
    expect(grown).toBeGreaterThan(0);
    // Absolute positions and transforms never carry a field.
    for (const node of card.findAll((n) => typeof n.type === "string")) {
      expect(flatStyle(node).position).toBeUndefined();
      expect(flatStyle(node).transform).toBeUndefined();
    }
    // The date of death is a plain date: its field sits in a row beside nothing, not bare in the column cell.
    const dateButton = card.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === "Date of death")[0];
    const sized = hostAncestors(dateButton).find((n) => flatStyle(n).flexBasis === 150)!;
    expect(flatStyle(hostAncestors(sized)[0]).flexDirection).toBe("row");
    await act(async () => tree.unmount());
  });

  it("puts the chip's remove × in the chip's own row, with a 44px reach and a labelled button", async () => {
    const { tree } = renderPanel(makeWorkspace({ seed: { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Pneumonia, organism unspecified", Code: "CA40.Z", LinearizationURI: "https://who.int/CA40.Z" }] }] } }), apiFor());
    const chip = hostNodesWithTestId(tree, "condition-chip")[0];
    expect(flatStyle(chip)).toMatchObject({ flexDirection: "row" });
    expect(flatStyle(chip).flexWrap).toBeUndefined();
    expect(hostText(chip)).toContain("CA40.Z — Pneumonia, organism unspecified");
    const remove = chip.findAll((n) => n.props.accessibilityLabel === "Remove CA40.Z" && typeof n.type === "string")[0];
    expect(remove.parent && remove.parent.parent === chip || hostAncestors(remove)[0] === chip).toBe(true);
    const w = flatStyle(remove);
    const slop = remove.props.hitSlop;
    expect(w.width + 2 * slop).toBeGreaterThanOrEqual(44);
    expect(w.height + 2 * slop).toBeGreaterThanOrEqual(44);
    await act(async () => tree.unmount());
  });

  it("shows the ⓘ on the same row as the DORIS result choice", async () => {
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), apiFor());
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    const row = hostNodesWithTestId(tree, "quick-choice-row")[0];
    expect(flatStyle(row)).toMatchObject({ flexDirection: "row" });
    expect(flatStyle(row).flexWrap).toBeUndefined();
    expect(row.findAll((n) => typeof n.props.label === "string" && n.props.label.startsWith("Use DORIS result")).length).toBeGreaterThan(0);
    expect(row.findAll((n) => n.props.accessibilityLabel === "Details for CA40").length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
  });

  it("does not truncate the line title and keeps the move and remove controls", async () => {
    const { tree } = renderPanel(makeWorkspace({ seed: whoSeed }), apiFor());
    const titles = tree.root.findAll((n) => typeof n.type === "string" && n.children.includes("Immediate cause"));
    expect(titles.length).toBeGreaterThan(0);
    for (const t of titles) expect(t.props.numberOfLines).toBeUndefined();
    const header = hostAncestors(titles[0]).find((n) => flatStyle(n).justifyContent === "space-between")!;
    for (const label of ["Move Part I line 1 down", "Remove Part I line 1"]) {
      const button = header.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === label)[0];
      expect(flatStyle(button).minWidth + 2 * button.props.hitSlop).toBeGreaterThanOrEqual(44);
      expect(flatStyle(button).minHeight + 2 * button.props.hitSlop).toBeGreaterThanOrEqual(44);
    }
    await act(async () => tree.unmount());
  });
});

describe("demo mode (Collect Plus Try DORIS)", () => {
  const rendered = (demo: boolean, seed: JsonObject = certificate) => renderPanel(makeWorkspace({ seed }), apiFor(), jest.fn(), jest.fn(async () => ({})), demo);
  const hasLabel = (tree: ReactTestRenderer, label: string) => tree.root.findAllByProps({ accessibilityLabel: label }).length > 0;

  it("hides Save Step 1 and Report not codeable, and words Reset as a return to the loaded example", async () => {
    const { tree } = rendered(true);
    // The panel is there and live (Process is offered) before the absences are asserted.
    expect(hasLabel(tree, "Process current certificate")).toBe(true);
    expect(hasLabel(tree, "Reset to the loaded example")).toBe(true);
    for (const label of ["Save Step 1", "Submit not-codeable report", "Reset DORIS from interview"]) expect(hasLabel(tree, label)).toBe(false);
    expect(allText(tree)).not.toContain("Report not codeable");
    await act(async () => tree.unmount());
  });

  it("leaves offline coding and the web as they were: the same panel without the prop keeps all three", async () => {
    const { tree } = rendered(false);
    expect(hasLabel(tree, "Process current certificate")).toBe(true);
    for (const label of ["Save Step 1", "Submit not-codeable report", "Reset DORIS from interview"]) expect(hasLabel(tree, label)).toBe(true);
    expect(allText(tree)).toContain("Report not codeable");
    expect(hasLabel(tree, "Reset to the loaded example")).toBe(false);
    await act(async () => tree.unmount());
  });

  it("offers the administrative fields on a blank certificate, and they reach the processed certificate", async () => {
    const api = apiFor();
    const { tree } = renderPanel(makeWorkspace({ seed: { ICDVersion: "ICD11", Part1: certificate.Part1 } }), api, jest.fn(), jest.fn(async () => ({})), true);
    // No AdministrativeData in the seed (like the blank demo certificate); demo mode still offers the card.
    expect(allText(tree)).not.toContain("Administrative data was not supplied");
    await act(async () => tree.root.findAllByProps({ testID: "question-doris_sex-choice-2" }).find((node) => node.props.accessibilityRole === "radio")!.props.onPress());
    await act(async () => byLabel(tree, "Estimated age").props.onChangeText("76"));
    await act(async () => byLabel(tree, "Estimated age unit").props.onPress());
    await act(async () => byLabel(tree, "Estimated age unit: Years").props.onPress());
    // The native date fields open the system picker, so the test checks they are offered rather than typing into them.
    for (const label of ["Date of birth", "Date of death"]) expect(tree.root.findAllByProps({ accessibilityLabel: label }).length).toBeGreaterThan(0);
    await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
    expect((api.processDoris as jest.Mock).mock.calls[0][3].AdministrativeData).toEqual({ Sex: 2, EstimatedAge: "P76Y" });
    await act(async () => tree.unmount());
  });

  it("Reset restores the whole loaded example, causes included", async () => {
    const { tree } = rendered(true);
    await act(async () => byLabel(tree, "Part I line 1 interval").props.onChangeText("3"));
    await act(async () => byLabel(tree, "Reset to the loaded example").props.onPress());
    expect(allText(tree)).toContain("Pneumonia");
    expect(allText(tree)).toContain("Certificate reset to the loaded example.");
    await act(async () => tree.unmount());
  });
});
