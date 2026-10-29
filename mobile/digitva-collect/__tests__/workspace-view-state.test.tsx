import React from "react";
import { act, create } from "react-test-renderer";
import { AppState } from "react-native";

import { CaseWorkspaceScreen } from "../src/workspace/CaseWorkspaceScreen";
import type { WorkspaceApi } from "../src/workspace/api";
import { canRestoreScroll, clearScroll, parseQueueParams, readScroll, resolveSection, saveScroll, serializeQueueParams } from "../src/workspace/viewState";

let layoutProps: any;
jest.mock("../src/workspace/WorkspaceLayout", () => ({
  WorkspaceLayout: (props: any) => { layoutProps = props; return props.children ?? null; },
}));
jest.mock("../src/workspace/CategoryPanel", () => ({ CategoryPanel: () => null, CategoryValue: () => null }));
jest.mock("../src/workspace/PrivateNotePanel", () => ({ PrivateNotePanel: () => null }));
jest.mock("../src/workspace/QualityPanels", () => ({ QualityPanels: () => null }));
jest.mock("../src/workspace/SmartvaStatusPanel", () => ({ SmartvaStatusPanel: () => null }));
const mockCodPanel: { props: { onSaved?: (blockedMessage?: string) => Promise<void> } | null } = { props: null };
jest.mock("../src/workspace/SimpleCodPanel", () => ({ SimpleCodPanel: (props: any) => { mockCodPanel.props = props; return null; } }));
jest.mock("../src/ui", () => {
  const { Text, View } = require("react-native");
  const React = require("react");
  return {
    Button: () => null,
    Screen: ({ children }: any) => React.createElement(View, null, children),
    errorText: () => "error",
    useUiStyles: () => new Proxy({}, { get: () => undefined }),
    Text,
  };
});

class FakeStore {
  map = new Map<string, string>();
  get length() { return this.map.size; }
  key(i: number) { return [...this.map.keys()][i] ?? null; }
  getItem(k: string) { return this.map.get(k) ?? null; }
  setItem(k: string, v: string) { this.map.set(k, v); }
  removeItem(k: string) { this.map.delete(k); }
}

const cats = [{ code: "a" }, { code: "b" }, { code: "c" }];

test("resolveSection accepts offered codes only", () => {
  expect(resolveSection(cats, "b")).toBe("b");
  expect(resolveSection(cats, ["c", "a"])).toBe("c");
  expect(resolveSection(cats, "zzz")).toBeUndefined();
  expect(resolveSection(cats, "../x")).toBeUndefined();
  expect(resolveSection(cats, undefined)).toBeUndefined();
});

test("scroll offsets round-trip per section and clear per case", () => {
  const store = new FakeStore();
  saveScroll(store, "coding", "sid1", "a", 812.4);
  saveScroll(store, "coding", "sid1", "b", 5);
  saveScroll(store, "coding", "sid2", "a", 9);
  expect(readScroll(store, "coding", "sid1", "a")).toBe(812);
  expect(readScroll(store, "coding", "sid1", "zz")).toBe(0);
  clearScroll(store, "coding", "sid1");
  expect(readScroll(store, "coding", "sid1", "a")).toBe(0);
  expect(readScroll(store, "coding", "sid1", "b")).toBe(0);
  expect(readScroll(store, "coding", "sid2", "a")).toBe(9);
});

test("scroll helpers survive missing or throwing storage and junk values", () => {
  const throwing = { getItem() { throw new Error("no"); }, setItem() { throw new Error("no"); }, removeItem() { throw new Error("no"); }, key() { throw new Error("no"); }, length: 1 };
  expect(readScroll(undefined, "coding", "s", "a")).toBe(0);
  expect(readScroll(throwing as any, "coding", "s", "a")).toBe(0);
  expect(() => saveScroll(throwing as any, "coding", "s", "a", 3)).not.toThrow();
  expect(() => clearScroll(throwing as any, "coding", "s")).not.toThrow();
  const store = new FakeStore();
  store.setItem("digitva.scroll.v1:coding:s:a", "abc");
  expect(readScroll(store, "coding", "s", "a")).toBe(0);
  store.setItem("digitva.scroll.v1:coding:s:a", "-40");
  expect(readScroll(store, "coding", "s", "a")).toBe(0);
});

test("restore waits until the content is tall enough", () => {
  expect(canRestoreScroll(800, 900, 700)).toBe(false);
  expect(canRestoreScroll(800, 1500, 700)).toBe(true);
  expect(canRestoreScroll(0, 5000, 700)).toBe(false);
});

test("queue params parse valid values and ignore invalid ones", () => {
  expect(parseQueueParams({ project: "UNSW01", tab: "history", offset: "100" })).toEqual({ projectId: "UNSW01", allProjects: false, showHistory: true, offset: 100 });
  expect(parseQueueParams({ project: "all" })).toEqual({ projectId: undefined, allProjects: true, showHistory: false, offset: 0 });
  expect(parseQueueParams({})).toEqual({ projectId: undefined, allProjects: false, showHistory: false, offset: 0 });
  expect(parseQueueParams({ project: "a b;<x>", tab: "bogus", offset: "-5" })).toEqual({ projectId: undefined, allProjects: false, showHistory: false, offset: 0 });
  expect(parseQueueParams({ offset: "7" }).offset).toBe(0);
  expect(parseQueueParams({ offset: "99999999999" }).offset).toBe(0);
  expect(parseQueueParams({ project: ["P1", "P2"] }).projectId).toBe("P1");
});

test("queue params serialise to a URL-safe record that parses back", () => {
  const view = { projectId: "P1", showHistory: true, offset: 50 };
  expect(serializeQueueParams(view)).toEqual({ project: "P1", tab: "history", offset: "50" });
  expect(serializeQueueParams({ showHistory: false, offset: 0 })).toEqual({ project: "all", tab: undefined, offset: undefined });
  const back = parseQueueParams(serializeQueueParams(view));
  expect(back).toMatchObject({ projectId: "P1", showHistory: true, offset: 50 });
});

beforeEach(() => { AppState.currentState = "active"; layoutProps = undefined; });

function apiFor(): WorkspaceApi {
  const payload = {
    case: { va_sid: "sid-1", instance_name: "Case", form_type_code: "VA", project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    categories: [
      { code: "a", label: "A", nav_label: "A", render_mode: "default" },
      { code: "b", label: "B", nav_label: "B", render_mode: "default" },
      { code: "vacodassessment", label: "COD", nav_label: "COD", render_mode: "workflow_panel" },
    ],
    default_category: "a", step: "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: [], doris: null, narrative_qa: null, social_autopsy: null,
  };
  return {
    getWorkspace: jest.fn(async () => payload),
    getCategory: jest.fn(async (_sid: string, code: string) => ({ code, label: code, render_mode: "default", summary_items: [], subcategories: [] })),
    getNote: jest.fn(async () => ({ va_sid: "sid-1", content: null, updated_at: null })),
  } as unknown as WorkspaceApi;
}

async function mount(section: string | undefined, onSectionChange = jest.fn()) {
  const api = apiFor();
  await act(async () => {
    create(<CaseWorkspaceScreen identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} section={section} onSectionChange={onSectionChange} />);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  });
  return { api, onSectionChange };
}

test("a known section in the URL opens that section without rewriting the URL", async () => {
  const { api, onSectionChange } = await mount("b");
  expect(api.getCategory).toHaveBeenCalledWith("sid-1", "b", "coding");
  expect(layoutProps.selectedCode).toBe("b");
  expect(onSectionChange).not.toHaveBeenCalled();
});

test.each([["nope"], [undefined]])("unknown or missing section %p opens the default section", async (section) => {
  const { api } = await mount(section as string | undefined);
  expect(api.getCategory).toHaveBeenCalledWith("sid-1", "a", "coding");
});

test("picking a section (rail or pager) reports it once per pick", async () => {
  const { onSectionChange } = await mount(undefined);
  await act(async () => { layoutProps.onSelectCategory("vacodassessment"); await Promise.resolve(); });
  await act(async () => { layoutProps.onSelectCategory("b"); await Promise.resolve(); });
  expect(onSectionChange.mock.calls).toEqual([["vacodassessment"], ["b"]]);
  expect(layoutProps.selectedCode).toBe("b");
});

test("queue params belong to queue URLs only", () => {
  const { ownsQueueParams, hasQueueParams } = require("../src/workspace/viewState");
  expect(ownsQueueParams("")).toBe(true);
  expect(ownsQueueParams("?project=SADEMO&tab=history")).toBe(true);
  expect(ownsQueueParams("?vaSid=abc&mode=coding")).toBe(false);
  expect(hasQueueParams({ project: "SADEMO" })).toBe(true);
  expect(hasQueueParams({ offset: "50" })).toBe(true);
  expect(hasQueueParams({})).toBe(false);
});

test("saving Step 1 reloads the workspace on the COD section the coder is in, not the first section", async () => {
  const { api } = await mount("vacodassessment");
  expect(layoutProps.selectedCode).toBe("vacodassessment");
  await act(async () => { await mockCodPanel.props?.onSaved?.(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
  expect(api.getWorkspace).toHaveBeenCalledTimes(2);
  expect(layoutProps.selectedCode).toBe("vacodassessment");
  expect((api.getCategory as jest.Mock).mock.calls.at(-1)?.[1]).toBe("vacodassessment");
});

test("saving DORIS Step 1 lands on the COD section showing Step 2, not the first section", async () => {
  const cod = { code: "vacodassessment", label: "COD", nav_label: "COD", render_mode: "workflow_panel" };
  const base = {
    case: { va_sid: "sid-1", instance_name: "Case", form_type_code: "VA", project_mode: "masked_doris", icd_classification: "icd11", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
    default_category: "a", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null, reviewer_initial: null, reviewer_final: null },
    smartva: null, other_conditions_options: [], doris: null, narrative_qa: null, social_autopsy: null,
  };
  // The server keeps vacodassessment in the nav (always_include) and only the step changes.
  const before = { ...base, step: "initial", categories: [{ code: "a", label: "A", nav_label: "A", render_mode: "default" }, cod] };
  const after = { ...base, step: "final", categories: [{ code: "a", label: "A", nav_label: "A", render_mode: "default" }, cod] };
  let served = before;
  const api = {
    getWorkspace: jest.fn(async () => served),
    getCategory: jest.fn(async (_sid: string, code: string) => ({ code, label: code, render_mode: "default", summary_items: [], subcategories: [] })),
    getNote: jest.fn(async () => ({ va_sid: "sid-1", content: null, updated_at: null })),
  } as unknown as WorkspaceApi;
  let panel!: { workspace: { step: string }; onSaved: () => Promise<void> };
  await act(async () => {
    create(<CaseWorkspaceScreen
      identity={{ vaSid: "sid-1", mode: "coding" }} api={api} onExit={jest.fn()} section="vacodassessment"
      renderDoris={(workspace, onSaved) => { panel = { workspace, onSaved }; return null; }}
    />);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  });
  expect(layoutProps.selectedCode).toBe("vacodassessment");
  expect(panel.workspace.step).toBe("initial");
  served = after;
  await act(async () => { await panel.onSaved(); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
  expect(panel.workspace.step).toBe("final");
  expect(layoutProps.selectedCode).toBe("vacodassessment");
  expect((api.getCategory as jest.Mock).mock.calls.at(-1)?.[1]).toBe("vacodassessment");
});
