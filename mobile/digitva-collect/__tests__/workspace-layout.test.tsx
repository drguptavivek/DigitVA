import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

import { CategoryPanel } from "../src/workspace/CategoryPanel.web";
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout.web";
import type { WorkspacePayload } from "../src/workspace/contracts";

test("browser category panel keeps the HTMX query/response table and flip colours", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CategoryPanel category={{
    code: "symptoms",
    label: "General symptoms",
    render_mode: "table_sections",
    summary_items: [],
    subcategories: [{
      code: "duration",
      label: "duration_of_illness",
      render_mode: "table_sections",
      items: [
        { label: "Fever", value: "Yes", flip: false, info: true },
        { label: "Cough", value: "Yes", flip: true, info: false },
      ],
    }],
    }} />);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("Query");
  expect(output).toContain("Response");
  expect(output).toContain("Fever");
  expect(output).toContain("Cough");
  expect(output).toContain('"children":["i"]');
  expect(output.match(/"children":\["Yes"\]/g)).toHaveLength(2);
  expect(output).toContain("#bc2938");
  expect(output).toContain("#3f9366");
});

test("browser disease history groups explicit answers without using flip or hiding other values", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CategoryPanel category={{
      code: "vahealthhistorydetails",
      label: "Disease / Co-morbidity",
      render_mode: "table_sections",
      summary_items: [],
      subcategories: [{ code: "medical_history", label: "Medical history", render_mode: "table_sections", items: [
        { label: "Malaria", value: "Yes", flip: true, info: false },
        { label: "Stroke", value: "Yes", flip: false, info: false },
        { label: "Diabetes", value: "No", flip: true, info: false },
        { label: "Tuberculosis", value: "Unknown", flip: false, info: false },
        { label: "Structured answer", value: ["Yes"], flip: false, info: false },
      ] }],
    }} />);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("Diagnosed by Health Professional");
  expect(output).toContain("fa-clipboard-check");
  expect(output).toContain("Absent");
  expect(output).toContain("fa-clipboard");
  expect(output).toContain("#b44b52");
  expect(output).toContain("#477b5b");
  expect(output).toContain("Malaria\\nStroke");
  expect(output).toContain("Diabetes");
  expect(output).toContain("Tuberculosis");
  expect(output).toContain("Other responses");
  expect(output).toContain("Structured answer");
  expect(output).toContain("flexWrap");
});

test("COD workflow keeps medical history in the regular query/response table", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CategoryPanel category={{
      code: "vacodassessment",
      label: "COD assessment",
      render_mode: "workflow_panel",
      summary_items: [],
      subcategories: [{ code: "medical_history", label: "Medical history", render_mode: "table_sections", items: [
        { label: "Malaria", value: "Yes", flip: false, info: false },
      ] }],
    }} />);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("Query");
  expect(output).toContain("Response");
  expect(output).toContain("Malaria");
  expect(output).toContain('"children":["Yes"]');
  expect(output).not.toContain("Diagnosed by Health Professional");
});

test.each(["table_sections", "default"])("browser %s sections suppress global summaries and keep attachment paths bounded", async (renderMode) => {
  const renderMedia = jest.fn((path: string) => <Text>media:{path}</Text>);
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CategoryPanel renderMedia={renderMedia} category={{
      code: "symptoms", label: "Symptoms", render_mode: renderMode, summary_items: ["global summary must stay hidden"],
      subcategories: [{ code: "files", label: "Files", render_mode: "table_sections", items: [
        { label: "Allowed", value: "/api/v1/attachments/abc.pdf", flip: false, info: false },
        { label: "Rejected", value: "/api/v1/attachments/https://evil.example/x", flip: false, info: false },
      ] }],
    }} />);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).not.toContain("global summary must stay hidden");
  expect(renderMedia).toHaveBeenCalledWith("/api/v1/attachments/abc.pdf");
  expect(renderMedia).not.toHaveBeenCalledWith("/api/v1/attachments/https://evil.example/x");
  expect(output).toContain("/api/v1/attachments/https://evil.example/x");
});

const layoutWorkspace: WorkspacePayload = {
  case: { va_sid: "sid-1", instance_name: "form-1", form_type_code: "WHO", project_code: "P1", site_code: "S1", age: 46, gender: "male", is_demo_project: false, project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress", narrative_qa_enabled: false, social_autopsy_enabled: false },
  categories: [
    { code: "one", label: "One", nav_label: "One", render_mode: "table_sections", icon_name: "fa-user", count: 1, attachment_count: 2 } as WorkspacePayload["categories"][number],
    { code: "two", label: "Two", nav_label: "Two", render_mode: "table_sections", icon_name: "fa-heart", count: 0 },
  ],
  default_category: "one", step: "initial", blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
};

test("browser layout keeps notes mounted and exposes functional category navigation", async () => {
  const onSelectCategory = jest.fn();
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={layoutWorkspace} categories={layoutWorkspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={onSelectCategory} onExit={jest.fn()} notes={<Text>unsaved note</Text>}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("unsaved note");
  expect(output).toContain("Open Notes");
  expect(output).toContain("VA Coding");
  expect(output).toContain("/vaindex");
  expect(output).toContain("/coding");
  expect(output).toContain("/help");
  expect(output).toContain("fa-user");
  expect(output).toContain("attachments");
  const next = renderer.root.findAllByType("button" as never).find((node) => node.props.children === "Next");
  expect(next).toBeDefined();
  await act(async () => next?.props.onClick());
  expect(onSelectCategory).toHaveBeenCalledWith("two");
});
