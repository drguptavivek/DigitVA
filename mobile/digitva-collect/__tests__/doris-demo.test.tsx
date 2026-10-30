/**
 * The Collect Plus "Try DORIS" demo: the six synthetic examples load (WHO's recorded `observed` results never reach
 * the screen), the demo API reaches no store and no network, the route is gated to Collect Plus on Android, and a
 * device-wide ICD-11 / DORIS switch that is off is told so and linked to Settings.
 */
import { readFileSync } from "fs";
import { join } from "path";
import React from "react";
import { Platform } from "react-native";
import { act, create } from "react-test-renderer";

const mockPlus = jest.fn(() => true);
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus() }));

const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Redirect: ({ href }: { href: string }) => ReactActual.createElement("redirect", { href }),
    useRouter: () => mockRouter,
  };
});

// Everything a demo must never touch: the interviewer store, drafts, the accounts, the network.
const mockForbidden = jest.fn();
jest.mock("../src/drafts", () => new Proxy({}, { get: () => mockForbidden }));
jest.mock("../src/interviewerDb", () => new Proxy({}, { get: () => mockForbidden }));
jest.mock("../src/auth", () => new Proxy({}, { get: () => mockForbidden }));
jest.mock("../src/AppState", () => ({ useAppState: () => mockForbidden() }));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, data: string) => require("node:crypto").createHash("sha256").update(data, "utf8").digest("hex"),
  randomUUID: () => require("node:crypto").randomUUID(),
}));
const mockFetch = jest.fn(() => { throw new Error("network_forbidden"); });
const realFetch = global.fetch;

let mockEnabled = true;
jest.mock("../src/icd11DorisPreference", () => ({
  isIcd11DorisEnabled: async () => mockEnabled,
  useIcd11DorisPreference: () => ({ ready: true, answered: true, enabled: mockEnabled }),
}));
const mockInit = jest.fn(async () => ({ ok: true as const, ms: 0, copyMs: 0, initMs: 0, cached: true }));
type ProgressListener = (event: { phase: string; percent?: number }) => void;
let mockProgressListener: ProgressListener | undefined;
const mockEngine = { init: () => mockInit(), onProgress: (listener: ProgressListener) => { mockProgressListener = listener; return () => undefined; } };
jest.mock("../src/offlineEngine", () => ({ offlineEngine: () => mockEngine }));
let mockPanelProps: Record<string, any> | undefined;
jest.mock("../src/workspace/doris/DorisPanel", () => ({ DorisPanel: (props: Record<string, any>) => { mockPanelProps = props; return null; } }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { View } = jest.requireActual("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => ReactActual.createElement("button", { accessibilityRole: "button", accessibilityLabel: label, onPress }),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement(View, null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
  };
});

import DorisDemoRoute from "../app/doris-demo";
import DorisDemoWeb from "../src/nativeRoutes/dorisDemo.web";
import DorisDemo from "../src/nativeRoutes/dorisDemo.native";
import { ApiError } from "../src/api";
import type { JsonObject } from "../src/workspace/contracts";
import type { EngineResult, OfflineEngine } from "../src/offlineEngine";
import { createGuidanceRequester } from "../src/workspace/offlineDoris";
import {
  createDorisDemoApi, createDorisDemoEditor, demoCertificate, demoVaSid, demoWorkspace, DORIS_DEMO_BLANK, DORIS_DEMO_EXAMPLES,
} from "../src/workspace/dorisDemo";

const resource = JSON.parse(readFileSync(join(__dirname, "..", "..", "..", "resource", "doris_help_examples.json"), "utf8"));
const NEONATAL_WARNING = "Manual check is recommended for perinatal conditions";

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });
async function render(element: React.ReactElement) {
  let root!: ReturnType<typeof create>;
  await act(async () => { root = create(element); });
  return root;
}
const press = async (root: ReturnType<typeof create>, label: string) => {
  const button = root.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
  expect(button).toBeDefined();
  await act(async () => { button.props.onPress(); });
};
const dump = (root: ReturnType<typeof create>) => JSON.stringify(root.toJSON());

beforeEach(() => {
  setOs("android");
  mockPlus.mockReturnValue(true);
  mockEnabled = true;
  mockPanelProps = undefined;
  mockProgressListener = undefined;
  mockInit.mockClear();
  mockForbidden.mockClear();
  mockRouter.push.mockClear();
  mockRouter.back.mockClear();
  global.fetch = mockFetch as unknown as typeof fetch;
  mockFetch.mockClear();
});
afterEach(() => {
  global.fetch = realFetch;
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

describe("the examples", () => {
  it("bundles WHO's six examples as an unchanged copy of the resource file", () => {
    const copy = JSON.parse(readFileSync(join(__dirname, "..", "assets", "doris-help-examples.json"), "utf8"));
    expect(copy).toEqual(resource);
    expect(DORIS_DEMO_EXAMPLES.map((example) => example.id)).toEqual(resource.examples.map((example: { id: string }) => example.id));
    expect(DORIS_DEMO_EXAMPLES).toHaveLength(6);
  });

  it.each(resource.examples.map((example: { id: string }) => example.id) as string[])("loads %s on the certificate WHO published, without its observed result", (id: string) => {
    const source = resource.examples.find((example: { id: string }) => example.id === id);
    expect(source.observed).toBeDefined();
    const workspace = demoWorkspace(id, 3);
    expect(workspace.doris?.initial_certificate).toEqual(source.certificate);
    expect(workspace.step).toBe("initial");
    expect(workspace.case.va_sid).toBe(demoVaSid(id, 3));
    expect(workspace.doris?.saved_processing).toBeNull();
    // A copy: editing the loaded certificate never changes the bundled example.
    expect(workspace.doris?.initial_certificate).not.toBe(DORIS_DEMO_EXAMPLES.find((example) => example.id === id)?.certificate);
    for (const example of DORIS_DEMO_EXAMPLES) expect(Object.keys(example).sort()).toEqual(["certificate", "id", "label", "purpose"]);
    expect(JSON.stringify([DORIS_DEMO_EXAMPLES, workspace])).not.toContain("observed");
  });

  it("starts the blank certificate with only its version, and every load gets its own case id", () => {
    expect(demoCertificate(DORIS_DEMO_BLANK)).toEqual({ ICDVersion: "ICD11" });
    expect(demoVaSid("adult", 1)).not.toBe(demoVaSid("adult", 2));
  });
});

describe("the demo API", () => {
  const editor = {
    onProcess: jest.fn(async () => ({ processed: true })),
    onTerms: jest.fn(async () => ({ items: [] })),
    onCodeInfo: jest.fn(async () => ({ item: {} })),
    onSelectionCheck: jest.fn(async () => ({ item: {} })),
  };
  let allowed = async () => undefined as void;
  const api = () => createDorisDemoApi(editor as never, () => allowed());
  beforeEach(() => { Object.values(editor).forEach((fn) => fn.mockClear()); allowed = async () => undefined; });

  it("runs the DORIS calls on the engine and nothing else", async () => {
    const certificate = { ICDVersion: "ICD11" };
    await expect(api().processDoris("demo-adult-0", "coder", 4, certificate)).resolves.toEqual({ processed: true });
    expect(editor.onProcess).toHaveBeenCalledWith(4, certificate);
    await api().searchDorisTerms("demo-adult-0", "fever", { limit: 5 });
    await api().getDorisCodeInfo("demo-adult-0", "BA41.Z");
    await api().checkDorisSelection("demo-adult-0", "BA41.Z", "uri");
    expect(editor.onTerms).toHaveBeenCalledWith("fever", 5, undefined);
    expect(editor.onCodeInfo).toHaveBeenCalledWith("BA41.Z");
    expect(editor.onSelectionCheck).toHaveBeenCalledWith("BA41.Z", "uri");
    await expect(api().getVaDefinitionForIcd("BA41.Z")).resolves.toBeNull();
    // Subject present (the calls above ran), now absence: no store, no account, no network.
    expect(mockForbidden).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("saves nothing: a save says so, and case, queue and server calls are absent", async () => {
    const demo = api();
    for (const save of [() => demo.saveInitial("v", {}), () => demo.saveFinal("v", {}), () => demo.saveNotCodeable("v", {})]) {
      const error = await save().catch((caught) => caught);
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).payload?.messages).toEqual(["dorisDemoNoSave"]);
    }
    for (const call of [
      () => demo.getWorkspace("v", "coding"), () => demo.allocateCoding(), () => demo.codeOwnSubmission("v"), () => demo.recode("v"),
      () => demo.releaseCoding(), () => demo.getCodingAvailable(), () => demo.getCodingHistory(), () => demo.searchIcd("v", "icd11", "x"),
      () => demo.saveNote("v", "coding", "x"), () => demo.getWorkflowEvents("v"), () => demo.runSmartva("v"),
    ]) {
      await expect(call()).rejects.toThrow("doris_demo_unavailable");
    }
    expect(editor.onProcess).not.toHaveBeenCalled();
    expect(mockForbidden).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("refuses the DORIS calls once the device-wide switch is off", async () => {
    allowed = async () => { throw new Error("icd11_doris_disabled"); };
    await expect(api().processDoris("v", "coder", 1, {})).rejects.toThrow("icd11_doris_disabled");
    await expect(api().searchDorisTerms("v", "fever")).rejects.toThrow("icd11_doris_disabled");
    expect(editor.onProcess).not.toHaveBeenCalled();
    expect(editor.onTerms).not.toHaveBeenCalled();
  });
});

/** A fake engine under the REAL demo editor: a certificate with one coded cause processes; every call is recorded. */
const MMS = "http://id.who.int/icd/release/11/2026-01/mms";
const BA41 = `${MMS}/1334938734/unspecified`;
const ok = (data: unknown): EngineResult => ({ ok: true, data, status: 200, ms: 1, nativeMs: 1 });
function fakeEngine() {
  const calls: string[] = [];
  const answer = (op: string, data: unknown) => async () => { calls.push(op); return ok(data); };
  const engine = {
    available: async () => true,
    init: async () => ({ ok: true as const, ms: 0, copyMs: 0, initMs: 0, cached: true }),
    updateWhoFiles: async () => ({ ok: true as const, ms: 0, copyMs: 0, initMs: 0, cached: true }),
    call: answer("call", {}),
    search: answer("search", { destinationEntities: [{ theCode: "BA41.Z", id: `${MMS}/1334938734`, title: "Acute myocardial infarction" }] }),
    codeinfo: answer("codeinfo", { code: "BA41.Z", stemId: BA41 }),
    entity: answer("entity", { title: { "@value": "Acute myocardial infarction" } }),
    foundationEntity: answer("foundationEntity", {}),
    doris: answer("doris", { code: "BA41.Z", stemCode: "BA41.Z", uri: BA41, stemURI: BA41, report: "r", tabularReport: "t", reject: false, error: null, warning: null }),
    codedit: answer("codedit", { report: "r", tabularReport: "t", issueIds: "" }),
    onProgress: () => () => undefined,
  } as unknown as OfflineEngine;
  return { engine, calls };
}
const CAUSE = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "AMI", Code: "BA41.Z", LinearizationURI: BA41 }] }] };

describe("the demo editor, requester and API over the real offline editor", () => {
  const off = async () => { throw new Error("icd11_doris_disabled"); };
  const on = async () => undefined;

  it("processes a certificate, searches and checks a code with no network call", async () => {
    const { engine, calls } = fakeEngine();
    const editor = createDorisDemoEditor(engine);
    const api = createDorisDemoApi(editor, on);
    const reply = await api.processDoris("demo-adult-0", "coder", 0, CAUSE);
    expect(reply.doris.status).toBe("completed");
    expect(reply.process_token).toMatch(/^local-/);
    await expect(api.searchDorisTerms("demo-adult-0", "myocardial")).resolves.toMatchObject({ items: expect.any(Array) });
    await api.getDorisCodeInfo("demo-adult-0", "BA41.Z");
    await api.checkDorisSelection("demo-adult-0", "BA41.Z", BA41);
    // The engine was reached (subject present) and nothing else was.
    expect(calls).toEqual(expect.arrayContaining(["doris", "codedit", "search", "codeinfo"]));
    expect(mockFetch).not.toHaveBeenCalled();
    expect(mockForbidden).not.toHaveBeenCalled();
  });

  it("the editor's store refuses to save or read a coding", async () => {
    const { engine } = fakeEngine();
    const editor = createDorisDemoEditor(engine);
    const reply = await editor.onProcess(0, CAUSE);
    const input = {
      clientDraftId: "demo-draft",
      body: { doris_certificate: CAUSE, doris_result: reply.doris as unknown as JsonObject, codedit_result: reply.codedit as unknown as JsonObject, doris_process_token: reply.process_token, antecedent_cod: "BA41.Z" },
      reply, deviceUuid: null, coderProfileUpdatedAt: null,
    };
    // save() reads the existing row first, so the refusal comes from the demo store's get; nothing is written.
    await expect(editor.save(input)).rejects.toThrow("doris_demo_unavailable");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("answers icd11_doris_disabled to all four DORIS calls with the switch off, and runs no engine call", async () => {
    const { engine, calls } = fakeEngine();
    const api = createDorisDemoApi(createDorisDemoEditor(engine), off);
    await expect(api.processDoris("v", "coder", 0, CAUSE)).rejects.toThrow("icd11_doris_disabled");
    await expect(api.searchDorisTerms("v", "fever")).rejects.toThrow("icd11_doris_disabled");
    await expect(api.getDorisCodeInfo("v", "BA41.Z")).rejects.toThrow("icd11_doris_disabled");
    await expect(api.checkDorisSelection("v", "BA41.Z", BA41)).rejects.toThrow("icd11_doris_disabled");
    expect(calls).toEqual([]);
  });

  it("the guidance requester refuses every non-guidance path and checks the switch before a guidance one", async () => {
    const { engine, calls } = fakeEngine();
    const editor = createDorisDemoEditor(engine);
    const allowed = jest.fn(on);
    const vaSid = demoVaSid("adult", 1);
    const request = createGuidanceRequester(editor, vaSid, allowed);
    for (const [path, init] of [
      ["/api/v1/workspace/" + vaSid, { method: "GET" }],
      ["/api/v1/doris-clinical/hierarchy/" + vaSid, { method: "GET" }],
      ["/api/v1/doris-clinical/hierarchy/other-case", { method: "POST", json: {} }],
      ["/api/v1/doris-clinical/save/" + vaSid, { method: "POST", json: {} }],
      ["https://example.org/api/v1/doris-clinical/hierarchy/" + vaSid, { method: "POST", json: {} }],
    ] as const) {
      await expect(request(path, init as never)).rejects.toThrow("offline_server_unavailable");
    }
    expect(allowed).not.toHaveBeenCalled();
    // A guidance path for this case asks the switch (whatever the engine then answers).
    await request("/api/v1/doris-clinical/hierarchy/" + encodeURIComponent(vaSid), { method: "POST", json: { schema_version: 1, code: "BA41.Z" } } as never).catch(() => undefined);
    expect(allowed).toHaveBeenCalledTimes(1);
    // A guidance path for this case reaches the switch check first: off, it is refused before the engine is touched.
    calls.length = 0;
    const closed = createGuidanceRequester(editor, vaSid, off);
    await expect(closed("/api/v1/doris-clinical/hierarchy/" + encodeURIComponent(vaSid), { method: "POST", json: {} } as never)).rejects.toThrow("icd11_doris_disabled");
    expect(calls).toEqual([]);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("the route", () => {
  it("opens the demo in Collect Plus on Android, with no account and no sign-in", async () => {
    const root = await render(<DorisDemoRoute />);
    expect(dump(root)).toContain("dorisDemoIntro");
    expect(mockForbidden).not.toHaveBeenCalled();
  });

  it.each([["plain Collect on Android", "android", false], ["Collect Plus on iOS", "ios", true], ["the web", "web", true]])("sends %s home", async (_name, os, plus) => {
    setOs(os);
    mockPlus.mockReturnValue(plus);
    const root = await render(<DorisDemoRoute />);
    expect(root.toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    expect(mockInit).not.toHaveBeenCalled();
  });

  it("the shared entry and the web twin only redirect home", async () => {
    // Jest resolves the bare path to the .native screen, as Metro does on the phone; the shared file is named in full.
    const DorisDemoBase = jest.requireActual("../src/nativeRoutes/dorisDemo.tsx").default;
    expect((await render(<DorisDemoBase />)).toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
    expect((await render(<DorisDemoWeb />)).toJSON()).toMatchObject({ type: "redirect", props: { href: "/" } });
  });
});

describe("the screen", () => {
  it("shows engine progress, then opens the editor on a blank certificate", async () => {
    let finish!: () => void;
    mockInit.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: false }); }));
    const root = await render(<DorisDemo />);
    expect(dump(root)).toContain("dorisDemoStarting");
    expect(mockPanelProps).toBeUndefined();
    await act(async () => { mockProgressListener?.({ phase: "copy", percent: 40 }); });
    expect(dump(root)).toContain("copy 40%");
    await act(async () => { finish(); });
    expect(mockPanelProps?.workspace.doris.initial_certificate).toEqual({ ICDVersion: "ICD11" });
    expect(mockPanelProps?.identity).toEqual({ vaSid: demoVaSid(DORIS_DEMO_BLANK, 0), mode: "coding" });
    expect(mockPanelProps?.api).toBeDefined();
    expect(mockPanelProps?.demo).toBe(true);
  });

  it("loads a chosen example afresh and shows its purpose but not WHO's observed result", async () => {
    const neonatal = resource.examples.find((example: { id: string }) => example.id === "neonatal");
    expect(neonatal.observed.doris.warning).toContain(NEONATAL_WARNING);
    const root = await render(<DorisDemo />);
    await press(root, neonatal.label);
    expect(mockPanelProps?.workspace.doris.initial_certificate).toEqual(neonatal.certificate);
    expect(dump(root)).toContain(neonatal.purpose);
    expect(dump(root)).not.toContain(NEONATAL_WARNING);
    const first = mockPanelProps?.identity.vaSid;
    await press(root, neonatal.label);
    expect(mockPanelProps?.identity.vaSid).not.toBe(first);
  });

  it("reports an engine that could not start and offers another try", async () => {
    mockInit.mockResolvedValueOnce({ ok: false, error: "unavailable", ms: 0 } as never);
    const root = await render(<DorisDemo />);
    expect(dump(root)).toContain("dorisDemoEngineFailed");
    expect(mockPanelProps).toBeUndefined();
    await press(root, "dorisDemoRetry");
    expect(mockInit).toHaveBeenCalledTimes(2);
    expect(mockPanelProps).toBeDefined();
  });

  it("says coding is off and links to Settings, without starting the engine", async () => {
    mockEnabled = false;
    const root = await render(<DorisDemo />);
    expect(dump(root)).toContain("dorisDemoDisabledBody");
    await press(root, "icd11DorisOpenSettings");
    expect(mockRouter.push).toHaveBeenCalledWith("/settings");
    expect(mockInit).not.toHaveBeenCalled();
    expect(mockPanelProps).toBeUndefined();
  });

  it("waits for Continue when the switch was turned on while the demo was open", async () => {
    mockEnabled = false;
    const root = await render(<DorisDemo />);
    mockEnabled = true;
    await act(async () => { root.update(<DorisDemo />); });
    expect(dump(root)).toContain("icd11DorisContinueBody");
    expect(mockInit).not.toHaveBeenCalled();
    await press(root, "icd11DorisContinue");
    expect(mockInit).toHaveBeenCalledTimes(1);
  });
});
