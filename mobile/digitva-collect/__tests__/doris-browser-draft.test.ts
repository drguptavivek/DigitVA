jest.mock("react-native", () => ({ Platform: { OS: "web" } }));
const mockStore = new Map<string, string>();
jest.mock("../src/workspace/viewState", () => ({ browserSessionStore: () => ({
  getItem: (key: string) => mockStore.get(key) ?? null,
  setItem: (key: string, value: string) => mockStore.set(key, value),
  removeItem: (key: string) => mockStore.delete(key),
}) }));

import { activateBrowserDraft, clearBrowserDraft, clearCaseBrowserDraft, clearCodDraft, DORIS_DRAFT_KEY, readCodDraft, readPendingNote, saveCodDraft, savePendingNote } from "../src/workspace/doris/browserDraft";
import type { JsonObject } from "../src/workspace/contracts";
const context = { fingerprint: "opaque-actor-allocation", vaSid: "case1", mode: "coding", payloadVersion: "payload1", projectMode: "unmasked_doris" };
const certificate: JsonObject = {
  AdministrativeData: { DateBirth: "1990-01-01", Name: "Must not persist" },
  Part1: [{ Conditions: [{ Text: "Condition one", Code: "CA40", LinearizationURI: "uri", Interval: "P2D", Secret: "no" }, { Text: "Uncoded clinical cause" }] }, { Conditions: [] }],
  Part2: { Conditions: [{ Text: "Contributory condition" }] },
  processing: { token: "must-not-persist" },
};
const cod = { step: "final", certificate, selectedCause: { code: "CA40", title: "Condition one", uri: "uri" }, remark: "Coder's free text remark" };

beforeEach(() => { clearBrowserDraft(); mockStore.clear(); activateBrowserDraft(context); });

test("recovers nested COD lines, selection, intervals and remark without demographics or proof", () => {
  saveCodDraft(context, cod);
  const restored = readCodDraft(context, "final")!;
  expect(restored.selectedCause).toEqual(cod.selectedCause);
  expect(restored.remark).toBe(cod.remark);
  expect(restored.certificate).toEqual({ Part1: [{ Conditions: [{ Text: "Condition one", Code: "CA40", LinearizationURI: "uri", Interval: "P2D" }, { Text: "Uncoded clinical cause" }] }, { Conditions: [] }], Part2: { Conditions: [{ Text: "Contributory condition" }] } });
  const serialized = mockStore.get(DORIS_DRAFT_KEY)!;
  expect(serialized).not.toMatch(/DateBirth|AdministrativeData|Name|Secret|processing|token/);
});

test("Step 1 clearing preserves pending note and Step 2 never restores Step 1 causes", () => {
  saveCodDraft(context, { ...cod, step: "initial" });
  savePendingNote(context, "Unsaved note");
  expect(readCodDraft(context, "final")).toBeUndefined();
  clearCodDraft(context);
  expect(readCodDraft(context, "initial")).toBeUndefined();
  expect(readPendingNote(context)).toBe("Unsaved note");
});

test.each(["fingerprint", "vaSid", "payloadVersion", "mode", "projectMode"] as const)("new %s invalidates the preceding form", (field) => {
  saveCodDraft(context, cod);
  const next = { ...context, [field]: "different" };
  activateBrowserDraft(next);
  expect(readCodDraft(next, "final")).toBeUndefined();
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
});

test("late old-context writes cannot replace a new form or resurrect a submitted draft", () => {
  saveCodDraft(context, cod);
  const next = { ...context, fingerprint: "new", vaSid: "case2" };
  activateBrowserDraft(next);
  savePendingNote(next, "new form note");
  saveCodDraft(context, cod);
  expect(readPendingNote(next)).toBe("new form note");
  clearBrowserDraft();
  saveCodDraft(next, cod);
  savePendingNote(next, "late note");
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
});

test.each(["{broken", JSON.stringify({ schemaVersion: 99 }), "x".repeat(200001)])("corrupt or oversized storage is discarded", (raw) => {
  mockStore.set(DORIS_DRAFT_KEY, raw);
  expect(readCodDraft(context, "final")).toBeUndefined();
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
});

test("bounded condition lists and oversize text are not persisted", () => {
  saveCodDraft(context, { ...cod, certificate: { Part1: [{ Conditions: Array(31).fill({ Text: "x" }) }] } });
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
  saveCodDraft(context, { ...cod, certificate: { Part1: [{ Conditions: [{ Text: "x".repeat(10001) }] }] } });
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
});

 test("case-scoped cleanup cannot clear a different active context", () => {
  const next = { ...context, fingerprint: "next-form", vaSid: "case2" };
  activateBrowserDraft(next);
  savePendingNote(next, "New form note");
  clearCaseBrowserDraft(context);
  expect(readPendingNote(next)).toBe("New form note");
  clearCaseBrowserDraft(next);
  expect(mockStore.has(DORIS_DRAFT_KEY)).toBe(false);
});
