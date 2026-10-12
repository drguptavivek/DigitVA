import React from "react";
import { act, create } from "react-test-renderer";
import { Dimensions, Text } from "react-native";

import { palette } from "../src/theme";
import { webPalette } from "../src/workspace/webPalette";
import { CategoryPanel } from "../src/workspace/CategoryPanel.web";
import { WorkflowHistory } from "../src/workspace/WorkflowHistory";
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout.web";
import type { WorkspacePayload } from "../src/workspace/contracts";

const mockTheme: { mode: "light" | "dark" } = { mode: "dark" };
jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme(mockTheme.mode) };
});

beforeAll(() => Dimensions.set({ window: { width: 1280, height: 900, scale: 1, fontScale: 1 } }));

const workspace = {
  case: { va_sid: "sid-1", instance_name: "form-1", form_type_code: "WHO", project_code: "P1", site_code: "S1", age: 46, gender: "male", is_demo_project: false, project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
  categories: [{ code: "one", label: "One", nav_label: "One", render_mode: "table_sections", icon_name: "fa-user", count: 1 }],
  default_category: "one", step: "initial", blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
} as unknown as WorkspacePayload;

const category = {
  code: "c", label: "Cat", render_mode: "health_history_summary", summary_items: [],
  subcategories: [{ code: "s", label: "Sub", render_mode: "table_sections", items: [
    { label: "Malaria", value: "Yes", flip: false, info: false },
    { label: "Stroke", value: "No", flip: false, info: false },
  ] }],
};

async function json(node: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(node); await Promise.resolve(); });
  return JSON.stringify(tree.toJSON());
}

test.each(["light", "dark"] as const)("browser workspace follows the %s theme", async (mode) => {
  mockTheme.mode = mode;
  const panel = await json(<CategoryPanel category={category as never} />);
  const table = await json(<CategoryPanel category={{ ...category, render_mode: "table_sections" } as never} />);
  const layout = await json(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={workspace} categories={workspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>content</Text></WorkspaceLayout>);
  const history = await json(<WorkflowHistory events={null} cursor={null} loading={false} error="boom" onOlder={jest.fn()} onLatest={jest.fn()} onRetry={jest.fn()} />);
  const w = webPalette[mode];
  const other = webPalette[mode === "dark" ? "light" : "dark"];
  expect(layout).toContain(`"backgroundColor":"${w.page}"`);
  expect(layout).toContain(`"backgroundColor":"${w.card}"`);
  expect(layout).not.toContain(`"backgroundColor":"${other.page}"`);
  expect(table).toContain(`"color":"${w.text}"`);
  expect(table).toContain(`"backgroundColor":"${w.header}"`);
  expect(panel).toContain(`"backgroundColor":"${w.yesPanel}"`);
  expect(panel).not.toContain(`"backgroundColor":"${other.yesPanel}"`);
  // The legacy static `styles` export is light; a themed screen must use the active palette surface.
  expect(history).toContain(`"color":"${palette[mode].danger}"`);
  expect(history).not.toContain(`"color":"${palette[mode === "dark" ? "light" : "dark"].danger}"`);
});
