/**
 * Characterization (digitva-r8nh.24): where DorisPanel writes the unsaved certificate to its three draft stores
 * (the in-memory map, the per-tab browser draft and a native draftStore), in what order, and which browser clear
 * each save path uses: a Step 1 save clears only the COD draft, every other end of the case clears the case's
 * browser draft. Runs as the web client so the browser draft context is real.
 */
import React from "react";
import { Platform } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { ConfirmDialog } from "../src/ConfirmDialog";

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
jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme("light") };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({ WhoVaQuestionControls: { SingleChoice: () => null, MultipleChoice: () => null } }));
const mockFrame: { props: any } = { props: null };
jest.mock("../src/workspace/doris/picker/IcdPicker", () => ({ IcdPicker: (props: any) => { mockFrame.props = props; return null; } }));

/** Every draft write, in order: the browser draft calls (with their context) and the native store's. */
const mockLog: unknown[][] = [];
jest.mock("../src/workspace/doris/browserDraft", () => {
  const actual = jest.requireActual("../src/workspace/doris/browserDraft");
  const spy = (name: string) => (...args: unknown[]) => { mockLog.push([name, ...args]); return actual[name](...args); };
  return { ...actual, saveCodDraft: spy("saveCodDraft"), clearCodDraft: spy("clearCodDraft"), clearCaseBrowserDraft: spy("clearCaseBrowserDraft") };
});

import * as viewState from "../src/workspace/viewState";
import { ApiError } from "../src/api";
import { draftContext } from "../src/workspace/doris/browserDraft";
import type { JsonRequester, WorkspaceApi } from "../src/workspace/api";
import type { DorisProcessReply, JsonObject, WorkspaceIdentity, WorkspacePayload } from "../src/workspace/contracts";
import { DorisPanel, type CodDraftStore } from "../src/workspace/doris/DorisPanel";

const identity: WorkspaceIdentity = { vaSid: "sid-1", mode: "coding" };
const certificate: JsonObject = {
  ICDVersion: "ICD11",
  Part1: [{ Conditions: [{ Text: "Pneumonia", Code: "CA40", LinearizationURI: "https://who.int/CA40", Interval: "P2D" }] }],
};
const processReply: DorisProcessReply = {
  schema_version: 1, client_revision: 0, icd_release: "2025-01", certificate,
  certificate_digest: "certificate-digest", result_digest: "result-digest",
  doris: { status: "completed", result: { code: "CA40", stemCode: "CA40", title: "Pneumonia" } },
  codedit: { status: "completed", result: { report: "Independent coding check" } },
  process_token: "opaque-process-token",
};

function makeWorkspace(options: { step?: "initial" | "final"; masked?: boolean } = {}): WorkspacePayload {
  return {
    case: { va_sid: "sid-1", instance_name: "Case 1", form_type_code: "VA", project_mode: options.masked ? "masked_doris" : "unmasked_doris", icd_classification: "icd11", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false, doris_draft_context: "draft-context", payload_version_id: "payload-1" },
    categories: [], default_category: "vacodassessment", step: options.step ?? "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: null,
    doris: {
      initial_certificate: certificate, prefill_provenance: {}, saved_processing: null,
      step1_certificate: options.masked ? certificate : null,
      step1_processing: options.masked ? { doris: { status: processReply.doris.status, result: processReply.doris.result }, codedit: { status: processReply.codedit.status, result: processReply.codedit.result }, process_token: "private-step1-token" } : null,
    },
    narrative_qa: null, social_autopsy: null,
  } as unknown as WorkspacePayload;
}

function apiFor(overrides: Partial<WorkspaceApi> = {}): WorkspaceApi {
  return {
    processDoris: jest.fn(async () => processReply),
    searchDorisTerms: jest.fn(async (_sid: string, query: string) => ({
      schema_version: 1 as const,
      items: [{ code: query || "Y55", title: "Selected cause", uri: "https://who.int/Y55", release: "2025-01", matching_text: "Selected cause", postcoordination: false, postcoordination_availability: 0, related_maternal: false, related_perinatal: false, has_coding_note: false }],
      truncated: false, next_cursor: null,
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

const store = (): CodDraftStore => ({
  read: jest.fn(() => undefined),
  save: (cod) => { mockLog.push(["store.save", cod]); },
  clear: () => { mockLog.push(["store.clear"]); },
});

const byLabel = (tree: ReactTestRenderer, label: string) => tree.root.findByProps({ accessibilityLabel: label });

function allText(tree: ReactTestRenderer): string {
  const out: string[] = [];
  const walk = (node: any) => { if (typeof node === "string") out.push(node); else if (node?.children) node.children.forEach(walk); };
  walk(tree.toJSON());
  return out.join("|");
}

async function flushAll() {
  for (let tick = 0; tick < 8; tick += 1) await Promise.resolve();
}

async function pickViaPicker(code: string, uri = "https://who.int/Y55") {
  const reply = jest.fn();
  await act(async () => { mockFrame.props.onMessage({ t: "req", id: 1, path: "terms", body: { schema_version: 1, query: code, limit: 20, cursor: null } }, reply); await flushAll(); });
  await act(async () => { mockFrame.props.onMessage({ t: "req", id: 2, path: "selection-check", body: { schema_version: 1, code, uri } }, reply); await flushAll(); });
  await act(async () => { mockFrame.props.onMessage({ t: "select", choice: { code, uri } }, reply); await flushAll(); });
}

function renderPanel(workspace: WorkspacePayload, api: WorkspaceApi, draftStore: CodDraftStore, request: JsonRequester, onDone = jest.fn()) {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<DorisPanel workspace={workspace} identity={identity} api={api} request={request} onSaved={async () => undefined} onDone={onDone} draftStore={draftStore} />); });
  return { tree, onDone };
}

/** Processes the certificate and picks the Step 1 (or final) cause, then empties the log. */
async function readyToSave(tree: ReactTestRenderer, step: "initial" | "final") {
  await act(async () => { byLabel(tree, "Process current certificate").props.onPress(); await flushAll(); });
  const search = step === "initial" ? "Confirm Step 1 underlying cause open search" : "Choose and confirm the final underlying cause open search";
  await act(async () => byLabel(tree, search).props.onPress());
  await pickViaPicker("Y55");
  mockLog.length = 0;
}

const names = () => mockLog.map((entry) => entry[0]);

const values = new Map<string, string>();
const session = {
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
  jest.spyOn(viewState, "browserSessionStore").mockReturnValue(session);
  values.clear();
  mockLog.length = 0;
});
afterEach(() => {
  jest.restoreAllMocks();
  if (platform) Object.defineProperty(Platform, "OS", platform);
});

it("writes nothing on open, then an edit writes the browser draft before the native store, the same COD to both", async () => {
  const workspace = makeWorkspace();
  const { tree } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  expect(mockLog).toEqual([]);
  await act(async () => byLabel(tree, "Part I line 1 interval").props.onChangeText("3"));
  expect(names()).toEqual(["saveCodDraft", "store.save"]);
  const [[, context, browserCod], [, storeCod]] = mockLog as [[string, unknown, Record<string, unknown>], [string, unknown]];
  expect(context).toEqual(draftContext(workspace, identity));
  expect(context).toBeDefined();
  expect(storeCod).toBe(browserCod);
  expect(Object.keys(browserCod).sort()).toEqual(["certificate", "remark", "selectedCause", "step"]);
  expect(browserCod).toMatchObject({ step: "initial", selectedCause: null, remark: "" });
  await act(async () => tree.unmount());
});

it("keeps an edit in memory for the same requester and step, and a Step 1 save forgets it", async () => {
  const workspace = makeWorkspace();
  const request: JsonRequester = jest.fn(async () => ({}));
  const first = renderPanel(workspace, apiFor(), store(), request);
  await act(async () => byLabel(first.tree, "Part I line 1 interval").props.onChangeText("3"));
  await act(async () => first.tree.unmount());
  const second = renderPanel(workspace, apiFor(), store(), request);
  expect(allText(second.tree)).toContain("Certificate changed. Process it again before saving.");
  await readyToSave(second.tree, "initial");
  await act(async () => { byLabel(second.tree, "Save Step 1").props.onPress(); await flushAll(); });
  await act(async () => second.tree.unmount());
  const third = renderPanel(workspace, apiFor(), store(), request);
  expect(allText(third.tree)).not.toContain("Certificate changed. Process it again before saving.");
  await act(async () => third.tree.unmount());
});

it("a Step 1 save clears the COD browser draft (not the case's) and then the native store", async () => {
  const workspace = makeWorkspace();
  const { tree } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  await readyToSave(tree, "initial");
  await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flushAll(); });
  expect(mockLog).toEqual([["clearCodDraft", draftContext(workspace, identity)], ["store.clear"]]);
  await act(async () => tree.unmount());
});

it("a final save clears the case's browser draft and then the native store", async () => {
  const workspace = makeWorkspace({ step: "final" });
  const { tree, onDone } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  await readyToSave(tree, "final");
  await act(async () => { byLabel(tree, "Save final COD").props.onPress(); await flushAll(); });
  expect(mockLog).toEqual([["clearCaseBrowserDraft", draftContext(workspace, identity)], ["store.clear"]]);
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("a masked final save clears the case's browser draft and then the native store", async () => {
  const workspace = makeWorkspace({ step: "final", masked: true });
  const { tree, onDone } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  await act(async () => byLabel(tree, "Choose and confirm the final underlying cause open search").props.onPress());
  await pickViaPicker("Y55");
  mockLog.length = 0;
  await act(async () => { byLabel(tree, "Save final cause").props.onPress(); await flushAll(); });
  expect(mockLog).toEqual([["clearCaseBrowserDraft", draftContext(workspace, identity)], ["store.clear"]]);
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("a not-codeable report clears the case's browser draft and then the native store", async () => {
  const workspace = makeWorkspace();
  const { tree, onDone } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  await act(async () => byLabel(tree, "Not-codeable reason: No information").props.onPress());
  mockLog.length = 0;
  await act(async () => { byLabel(tree, "Submit not-codeable report").props.onPress(); await flushAll(); });
  expect(mockLog).toEqual([["clearCaseBrowserDraft", draftContext(workspace, identity)], ["store.clear"]]);
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("a lost allocation (403 on save) clears the case's browser draft and then the native store", async () => {
  const workspace = makeWorkspace();
  const api = apiFor({ saveInitial: jest.fn(async () => { throw new ApiError(403, "no_allocation"); }) });
  const { tree, onDone } = renderPanel(workspace, api, store(), jest.fn(async () => ({})));
  await readyToSave(tree, "initial");
  await act(async () => { byLabel(tree, "Save Step 1").props.onPress(); await flushAll(); });
  expect(mockLog).toEqual([["clearCaseBrowserDraft", draftContext(workspace, identity)], ["store.clear"]]);
  expect(onDone).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("a reset writes the reset COD to the browser draft and then the native store", async () => {
  const workspace = makeWorkspace({ step: "final" });
  const { tree } = renderPanel(workspace, apiFor(), store(), jest.fn(async () => ({})));
  await act(async () => byLabel(tree, "COD remark").props.onChangeText("Keep remark"));
  mockLog.length = 0;
  await act(async () => byLabel(tree, "Reset DORIS from interview").props.onPress());
  await act(async () => tree.root.findByType(ConfirmDialog).props.onConfirm());
  const resetWrites = mockLog.slice(0, 2);
  expect(resetWrites.map((entry) => entry[0])).toEqual(["saveCodDraft", "store.save"]);
  expect(resetWrites[0][1]).toEqual(draftContext(workspace, identity));
  expect(resetWrites[1][1]).toBe(resetWrites[0][2]);
  expect(resetWrites[0][2]).toMatchObject({ step: "final", selectedCause: null, remark: "Keep remark" });
  // The reset writes inside its state update, then the edit effect writes the same state again.
  expect(names()).toEqual(["saveCodDraft", "store.save", "saveCodDraft", "store.save"]);
  await act(async () => tree.unmount());
});
