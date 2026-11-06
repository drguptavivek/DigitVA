import React from "react";
import { Platform, ScrollView, Text, TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { QueueScreen } from "../src/workspace/QueueScreen";
import { WorkflowHistory } from "../src/workspace/WorkflowHistory";
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout";
import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { humanizeKey } from "../src/workspace/humanizeKey";
import type { WorkspaceApi } from "../src/workspace/api";

const originalOS = Object.getOwnPropertyDescriptor(Platform, "OS");
afterEach(() => { if (originalOS) Object.defineProperty(Platform, "OS", originalOS); });
const setOS = (os: string) => Object.defineProperty(Platform, "OS", { configurable: true, value: os });

const coderRow = { va_sid: "s1", va_uniqueid_masked: "PHC01-000025", va_form_id: "F1", project_id: "P1", site_id: "P1-S1", va_submission_date: "2026-10-01", va_data_collector: null, va_deceased_age: 83, va_deceased_gender: "female" };
const makeApi = () => ({
  getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, has_random_mode: true, has_pick_mode: true }),
  getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: [{ project_id: "P1", project_name: "One" }, { project_id: "P2", project_name: "Two" }], last_project_id: null }),
  getCodingAllocation: jest.fn().mockResolvedValue(null),
  getCodingAvailable: jest.fn().mockResolvedValue({ forms: [coderRow], count: 1, limit: 50, offset: 0, has_more: false }),
  getCodingHistory: jest.fn().mockResolvedValue({ history: [], count: 0, limit: 50, offset: 0, has_more: false }),
}) as unknown as WorkspaceApi;

async function queue() {
  let r!: ReactTestRenderer;
  await act(async () => { r = create(<QueueScreen api={makeApi()} mode="coding" onOpen={jest.fn()} onExit={jest.fn()} />); });
  for (let i = 0; i < 6; i++) await act(async () => { await Promise.resolve(); });
  return r;
}
const labelled = (r: ReactTestRenderer, label: string) => r.root.findAll((n) => n.props.accessibilityLabel === label || n.props.label === label);

describe("coding queue presentation", () => {
  test("phone: no Back button or Help pill, segmented tabs, a Project picker row, a tinted filter field", async () => {
    setOS("ios");
    const r = await queue();
    expect(labelled(r, "Available").length).toBeGreaterThan(0); // subject present before asserting absence
    expect(labelled(r, "Back")).toHaveLength(0);
    expect(r.root.findAll((n) => n.props.testID === "contextual-help-coding")).toHaveLength(0);
    expect(r.root.findAll((n) => n.props.accessibilityRole === "radiogroup" && n.props.accessibilityLabel === "Cases").length).toBeGreaterThan(0);
    expect(r.root.findAll((n) => n.type === Text && n.props.children === "Project").length).toBeGreaterThan(0);
    expect(r.root.findAll((n) => n.type === TextInput && n.props.accessibilityLabel === "Filter cases").length).toBeGreaterThan(0);
  });

  test("web: Back button and Help banner stay, tabs stay buttons", async () => {
    setOS("web");
    const r = await queue();
    expect(labelled(r, "Back").length).toBeGreaterThan(0);
    expect(r.root.findAll((n) => n.props.testID === "contextual-help-coding").length).toBeGreaterThan(0);
    expect(r.root.findAll((n) => n.props.accessibilityRole === "radiogroup" && n.props.accessibilityLabel === "Cases")).toHaveLength(0);
    expect(labelled(r, "History").length).toBeGreaterThan(0);
  });
});

const events = { events: [{ event_id: "e1", previous_state: "coder_finalized", current_state: "reviewer_eligible", event_created_at: "2026-10-22T15:41:00.123456+00:00", actor_role: "coder", transition_reason: "reviewer_eligible_after_recode_window" }], next_cursor: null } as never;
function sync(element: React.ReactElement) {
  let r!: ReactTestRenderer;
  act(() => { r = create(element); });
  return r;
}
const history = () => sync(<WorkflowHistory events={events} cursor={null} loading={false} error="" onOlder={jest.fn()} onLatest={jest.fn()} onRetry={jest.fn()} />);

describe("workflow history", () => {
  test("phone humanises states and reasons and formats the timestamp", () => {
    setOS("ios");
    const text = JSON.stringify(history().toJSON());
    expect(text).toContain("Coder finalized");
    expect(text).toContain("Reviewer eligible");
    expect(text).toContain("Reviewer eligible after recode window");
    expect(text).not.toContain("123456");
  });
  test("web keeps the raw states, timestamp and reason", () => {
    setOS("web");
    const text = JSON.stringify(history().toJSON());
    expect(text).toContain("coder_finalized");
    expect(text).toContain("2026-10-22T15:41:00.123456+00:00");
    expect(text).toContain("reviewer_eligible_after_recode_window");
  });
  test("humanizeKey leaves real labels alone", () => {
    expect(humanizeKey("risk_factors")).toBe("Risk factors");
    expect(humanizeKey("final_cod_submitted")).toBe("Final COD submitted");
    expect(humanizeKey("smartva_pending")).toBe("SmartVA pending");
    expect(humanizeKey("vacoder")).toBe("Coder");
    expect(humanizeKey("General")).toBe("General");
    expect(humanizeKey("Demographic / Risk Factors")).toBe("Demographic / Risk Factors");
  });
});

describe("case view", () => {
  test("phone layout has no Exit button and marks the selected tab with an underline", async () => {
    let r!: ReactTestRenderer;
    await act(async () => {
      r = create(<WorkspaceLayout identity={{} as never} workspace={{ case: { instance_name: "f" } } as never}
        categories={[{ code: "a", label: "A", nav_label: "A" }, { code: "b", label: "B", nav_label: "B" }] as never[]}
        selectedCode="b" categoryLoading={false} onSelectCategory={() => undefined} onExit={() => undefined}><Text>x</Text></WorkspaceLayout>);
    });
    expect(r.root.findAll((n) => n.type === ScrollView && n.props.accessibilityLabel === "Case categories").length).toBeGreaterThan(0);
    expect(labelled(r, "Exit")).toHaveLength(0);
    const tabs = r.root.findAll((n) => n.props.accessibilityState && "selected" in n.props.accessibilityState && n.props.onLayout);
    const underline = (sel: boolean) => tabs.find((n) => n.props.accessibilityState.selected === sel)!.props.style.borderBottomColor;
    expect(underline(false)).toBe("transparent");
    expect(underline(true)).not.toBe("transparent");
  });

  test("category panel humanises raw section keys and drops the heading above the symptoms card", () => {
    const category = { code: "c", label: "Demographic / Risk Factors", summary_items: ["High blood pressure"], subcategories: [{ code: "g", label: "risk_factors", items: [] }] } as never;
    const text = JSON.stringify(sync(<CategoryPanel category={category} />).toJSON());
    expect(text).toContain("Risk factors");
    expect(text).toContain("Symptoms on VA Interview");
    expect(text).toContain("High blood pressure");
    expect(text).not.toContain("Demographic / Risk Factors\"]");
  });
});
