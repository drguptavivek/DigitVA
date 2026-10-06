import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable: MockPressable, Text: MockText, View: MockView } = require("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled, accessibilityLabel }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string }) => React.createElement(MockPressable, { accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, disabled, onPress }, React.createElement(MockText, null, label)),
    errorText: (error: unknown) => error instanceof Error ? error.message : "Generic error",
    styles: new Proxy({}, { get: () => undefined }),
  };
});

import { ApiError } from "../src/api";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import type { DorisProcessReply, DorisTerm, JsonObject, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";
import { DorisPanel } from "../src/workspace/doris/DorisPanel";
import { dorisGuidance, parseDorisOptions } from "../src/workspace/doris/guidance";

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

function makeWorkspace(options: { step?: "initial" | "final"; masked?: boolean; seed?: JsonObject; processing?: JsonObject } = {}): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: options.masked ? "masked_doris" : "unmasked_doris", icd_classification: "icd11", workflow_state: options.step === "final" ? "initial_coded" : "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [], default_category: "vacodassessment", step: options.step ?? "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: null,
    doris: {
      initial_certificate: options.seed ?? certificate,
      prefill_provenance: {},
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

it("invalidates the process proof and final choice after a certificate edit", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  expect(JSON.stringify(tree.toJSON())).toContain("DORIS and CoDEdit");
  await act(async () => byLabel(tree, "Part I line 1 condition text 1").props.onChangeText("Updated pneumonia"));
  expect(JSON.stringify(tree.toJSON())).not.toContain("DORIS and CoDEdit");
  expect(byLabel(tree, "Save Step 1").props.disabled).toBe(true);
  expect(api.processDoris).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("discards an in-flight process reply after an edit", async () => {
  let finish!: (reply: DorisProcessReply) => void;
  const api = apiFor({ processDoris: jest.fn(() => new Promise((resolve) => { finish = resolve; })) });
  const { tree } = renderPanel(makeWorkspace(), api);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  await act(async () => byLabel(tree, "Part I line 1 condition text 1").props.onChangeText("Changed while processing"));
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
  const search = byLabel(tree, "Confirm Step 1 underlying cause search");
  await act(async () => search.props.onChangeText("Y55"));
  await act(async () => { byLabel(tree, "Confirm Step 1 underlying cause search").props.onSubmitEditing(); await flush(); });
  await act(async () => { byLabel(tree, "Use Y55").props.onPress(); await flush(); });
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

it("requires WHO postcoordination choices before checking the expression URI", async () => {
  const term: DorisTerm = { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", release: "2025-01", matching_text: "Pneumonia", postcoordination: true, postcoordination_availability: 2, related_maternal: false, related_perinatal: false, has_coding_note: false };
  const api = apiFor({ searchDorisTerms: jest.fn(async () => ({ schema_version: 1 as const, items: [term], truncated: false, next_cursor: null })) });
  const request = jest.fn(async (path: string) => path.endsWith("/postcoordination/sid-1")
    ? { schema_version: 1, stem: { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40", has_children: false }, axes: [{ id: "axis-1", label: "Laterality", required: true, allow_multiple_values: "NotAllowed", options: [{ code: "R", title: "Right", uri: "urn:right", has_children: false }], subtree_uris: ["urn:axis"], truncated: false }], other_postcoordination: null, truncated: false }
    : { schema_version: 1, selected: { code: "CA40", title: "Pneumonia", uri: "https://who.int/CA40" }, ancestors: [], siblings: [], children: [], related_maternal: [], related_perinatal: [], truncated: false });
  const { tree } = renderPanel(makeWorkspace(), api, jest.fn(), request);
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flush(); });
  await act(async () => byLabel(tree, "Confirm Step 1 underlying cause search").props.onChangeText("Pneumonia"));
  await act(async () => byLabel(tree, "Confirm Step 1 underlying cause search").props.onSubmitEditing());
  await act(async () => { byLabel(tree, "Inspect WHO code").props.onPress(); await flush(); });
  expect(request).toHaveBeenCalledWith("/api/v1/doris-clinical/postcoordination/sid-1", expect.anything());
  expect(request).toHaveBeenCalledWith("/api/v1/doris-clinical/hierarchy/sid-1", expect.anything());
  expect(api.checkDorisSelection).not.toHaveBeenCalled();
  await act(async () => byLabel(tree, "Select Laterality R").props.onPress());
  await act(async () => { byLabel(tree, "Use complete WHO expression").props.onPress(); await flush(); });
  expect(api.getDorisCodeInfo).toHaveBeenCalledWith("sid-1", "CA40/R");
  expect(api.checkDorisSelection).toHaveBeenCalledWith("sid-1", "CA40/R", "https://who.int/Y55");
  await act(async () => tree.unmount());
});

it("keeps masked Step 2 readonly and sends only its final choice", async () => {
  const api = apiFor();
  const { tree } = renderPanel(makeWorkspace({ step: "final", masked: true, processing: { certificate: { secret: "must-not-render" }, process_token: "must-not-render-either", doris: { status: processReply.doris.status, result: processReply.doris.result }, codedit: { status: processReply.codedit.status, result: processReply.codedit.result } } }), api);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Process current certificate" })).toHaveLength(0);
  expect(tree.root.findAllByProps({ accessibilityLabel: "Part I line 1 condition text 1" })).toHaveLength(0);
  expect(JSON.stringify(tree.toJSON())).toContain("Pneumonia");
  expect(JSON.stringify(tree.toJSON())).not.toContain("must-not-render");
  await act(async () => byLabel(tree, "Choose and confirm the final underlying cause search").props.onChangeText("Y55"));
  await act(async () => { byLabel(tree, "Choose and confirm the final underlying cause search").props.onSubmitEditing(); await flush(); });
  await act(async () => { byLabel(tree, "Use Y55").props.onPress(); await flush(); });
  await act(async () => { byLabel(tree, "Save final cause").props.onPress(); await flush(); });
  expect(api.processDoris).not.toHaveBeenCalled();
  expect(api.saveFinal).toHaveBeenCalledWith("sid-1", { conclusive_cod: "Y55" }, "coding");
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
