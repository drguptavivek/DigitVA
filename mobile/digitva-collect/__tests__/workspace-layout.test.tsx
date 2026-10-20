import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Dimensions, StyleSheet, Text } from "react-native";

import { CategoryPanel } from "../src/workspace/CategoryPanel.web";
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout.web";
import type { WorkspacePayload } from "../src/workspace/contracts";

// Desktop width so the section rail (hidden under 768px) is rendered.
beforeAll(() => Dimensions.set({ window: { width: 1280, height: 900, scale: 1, fontScale: 1 } }));

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
  expect(output).toContain("Informational response: Yes");
  expect(output.match(/"children":\["Yes"\]/g)).toHaveLength(2);
  expect(output).toContain("#1D4ED8");
  expect(output).toContain("#2f7a50");
  const yesBadges = renderer.root.findAllByType(Text).filter((node) => node.props.children === "Yes");
  expect(yesBadges).toHaveLength(2);
  const informational = yesBadges.find((node) => node.props.accessibilityLabel === "Informational response: Yes");
  const answer = yesBadges.find((node) => node.props.accessibilityLabel === undefined);
  expect(informational).toBeDefined();
  expect(answer).toBeDefined();
  expect(StyleSheet.flatten(informational?.props.style)).toMatchObject({ paddingVertical: 8, paddingHorizontal: 16, fontSize: 16, lineHeight: 24 });
  expect(StyleSheet.flatten(answer?.props.style)).toMatchObject({ paddingVertical: 8, paddingHorizontal: 16, fontSize: 16, lineHeight: 24, display: "inline-block" });
});

test("browser disease history groups explicit answers without using flip or hiding other values", async () => {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<CategoryPanel category={{
      code: "vahealthhistorydetails",
      label: "Disease / Co-morbidity",
      render_mode: "health_history_summary",
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
  expect(output).toContain("Medical History (Responses)");
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
  expect(output).not.toContain("VA Coding");
  expect(output).not.toContain("digitva_logo");
  expect(output).toContain("fa-user");
  expect(output).toContain("attachments");
  const next = renderer.root.findAllByType("button" as never).find((node) => node.props.children === "Next");
  expect(next).toBeDefined();
  await act(async () => next?.props.onClick());
  expect(onSelectCategory).toHaveBeenCalledWith("two");
});

test("browser layout keeps the rail scrollable without an overlay scrollbar and shows demo case metadata", async () => {
  const demoWorkspace: WorkspacePayload = { ...layoutWorkspace, case: { ...layoutWorkspace.case, age: 74, gender: "female", is_demo_project: true } };
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={demoWorkspace} categories={demoWorkspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain('"74"');
  expect(output).toContain("Female");
  expect(output).toContain("DEMO");
  expect(renderer.root.findAll((node) => node.props.accessibilityLabel === "Age 74, Female, DEMO").length).toBeGreaterThan(0);
  const rail = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-rail")[0];
  expect(StyleSheet.flatten(rail.props.style)).toMatchObject({ maxHeight: "calc(100dvh - 72px)", scrollbarWidth: "none", msOverflowStyle: "none" });
});

test("browser layout exposes the matching WHO ICD browser only for a valid classification", async () => {
  const icd11Workspace: WorkspacePayload = { ...layoutWorkspace, case: { ...layoutWorkspace.case, icd_classification: "icd11" } };
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={icd11Workspace} categories={icd11Workspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  act(() => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0].props.onPress());
  const browserLink = renderer.root.findAllByType("a" as never).find((node) => node.props.title === "Open ICD-11 Browser");
  expect(browserLink?.props.href).toBe("https://icd.who.int/browse/2026-01/mms/en");
  expect(browserLink?.props.target).toBe("_blank");
  expect(browserLink?.props.rel).toBe("noopener noreferrer");

  const missingClassification = { ...layoutWorkspace, case: { ...layoutWorkspace.case, icd_classification: undefined } } as unknown as WorkspacePayload;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={missingClassification} categories={missingClassification.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  act(() => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0].props.onPress());
  expect(renderer.root.findAllByType("a" as never).some((node) => String(node.props.title ?? "").includes("ICD"))).toBe(false);
});

test("the sections drawer locks body scrolling while open and restores it on close and unmount", async () => {
  // Node test environment: a minimal document double covers what the layout touches.
  const fakeDocument = { body: { style: { overflow: "auto" } }, getElementById: () => null, addEventListener: () => undefined, removeEventListener: () => undefined, querySelector: () => null, head: { appendChild: () => undefined }, createElement: () => ({ style: {}, setAttribute: () => undefined }) };
  (globalThis as any).document = fakeDocument;
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={layoutWorkspace} categories={layoutWorkspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  expect(fakeDocument.body.style.overflow).toBe("auto");
  const byId = (id: string) => renderer.root.findAll((node) => node.props.nativeID === id)[0];
  act(() => byId("digitva-category-drawer-trigger").props.onPress());
  expect(byId("digitva-category-drawer")).toBeDefined();
  expect(fakeDocument.body.style.overflow).toBe("hidden");
  act(() => byId("digitva-category-drawer-close").props.onPress());
  expect(fakeDocument.body.style.overflow).toBe("auto");
  act(() => byId("digitva-category-drawer-trigger").props.onPress());
  expect(fakeDocument.body.style.overflow).toBe("hidden");
  act(() => renderer.unmount());
  expect(fakeDocument.body.style.overflow).toBe("auto");
  delete (globalThis as any).document;
});

test("desktop layout keeps a compact case strip visible beside the Case Info trigger (digitva-yeg3.21)", async () => {
  const demoWorkspace: WorkspacePayload = { ...layoutWorkspace, case: { ...layoutWorkspace.case, age: 74, gender: "female", is_demo_project: true } };
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<WorkspaceLayout identity={{ vaSid: "sid-1", mode: "coding" }} workspace={demoWorkspace} categories={demoWorkspace.categories} selectedCode="one" categoryLoading={false} onSelectCategory={jest.fn()} onExit={jest.fn()}><Text>category content</Text></WorkspaceLayout>);
    await Promise.resolve();
  });
  const strip = renderer.root.findAll((node) => node.props.nativeID === "digitva-case-strip")[0];
  expect(strip).toBeDefined();
  const stripText = JSON.stringify(strip.findAllByType(Text).map((node) => node.props.children));
  expect(stripText).toContain("form-1");
  expect(stripText).toContain("74 y");
  expect(stripText).toContain("Female");
  expect(stripText).toContain("P1/S1");
  expect(stripText).toContain("DEMO");
  // The flyout stays closed and its trigger stays available for the rest of the details.
  expect(renderer.root.findAll((node) => node.props.id === "digitva-case-info-trigger").length).toBeGreaterThan(0);
  const panel = renderer.root.findAll((node) => node.props.nativeID === "digitva-case-info-panel")[0];
  expect(StyleSheet.flatten(panel.props.style)).toMatchObject({ display: "none" });
});
