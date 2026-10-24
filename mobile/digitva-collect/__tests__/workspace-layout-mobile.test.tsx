import React from "react";

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: jest.fn(), configurable: true });
  return actual;
});

import * as ReactNative from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout.web";
import type { WorkspacePayload } from "../src/workspace/contracts";

const dimensions = ReactNative.useWindowDimensions as jest.MockedFunction<typeof ReactNative.useWindowDimensions>;

const workspace: WorkspacePayload = {
  case: {
    va_sid: "sid-mobile",
    instance_name: "masked-form-7",
    form_type_code: "WHO",
    project_code: "P1",
    site_code: "S1",
    age: 46,
    gender: "male",
    is_demo_project: false,
    project_mode: "masked_simple",
    icd_classification: "icd10",
    workflow_state: "coding_in_progress",
    narrative_qa_enabled: false,
    social_autopsy_enabled: false,
  },
  categories: [
    { code: "one", label: "One", nav_label: "One", render_mode: "table_sections", icon_name: "fa-user", count: 3, attachment_count: 2 },
    { code: "two", label: "Two", nav_label: "Two", render_mode: "table_sections", icon_name: "fa-heart", count: 2 },
    { code: "three", label: "Three", nav_label: "Three", render_mode: "table_sections", icon_name: "fa-file", count: 1 },
  ],
  default_category: "one",
  step: "initial",
  blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null,
  other_conditions_options: null,
  doris: null,
  narrative_qa: null,
  social_autopsy: null,
};

function renderLayout(nextBlockedReason?: string, ws: WorkspacePayload = workspace): { renderer: ReactTestRenderer; select: jest.Mock; previous: jest.Mock } {
  const select = jest.fn();
  const previous = jest.fn();
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(<WorkspaceLayout
      identity={{ vaSid: "sid-mobile", mode: "coding" }}
      workspace={ws}
      categories={ws.categories}
      selectedCode="two"
      categoryLoading={false}
      onSelectCategory={select}
      onExit={previous}
      nextBlockedReason={nextBlockedReason}
      notes={<Text>draft note survives navigation</Text>}
    ><Text>category content</Text></WorkspaceLayout>);
  });
  return { renderer, select, previous };
}

afterEach(() => dimensions.mockReset());

test("phone layout hides the rail and shows a hamburger with the current section name", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const output = JSON.stringify(renderer.toJSON());

  expect(output).not.toContain("Case category shortcuts");
  expect(output).toContain("Open sections menu");
  expect(output).toContain("masked-form-7");
  expect(output).toContain("Age ");
  expect(output).toContain("Male");
  const bar = renderer.root.findAll((node) => node.props.numberOfLines === 1 && node.props.children === "Two");
  expect(bar.length).toBeGreaterThan(0);
});

const withDistrict = (survey_district?: string | null): WorkspacePayload =>
  ({ ...workspace, case: { ...workspace.case, ...(survey_district === undefined ? {} : { survey_district }) } });
const infoNode = (r: ReactTestRenderer) => r.root.findAll((n) => typeof n.props.accessibilityLabel === "string" && n.props.accessibilityLabel.startsWith("Age 46, Male") && n.props.numberOfLines === 1)[0];

test("phone sections bar pins age, sex and survey district on one ellipsized line", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const node = infoNode(renderLayout(undefined, withDistrict("Raisen")).renderer);
  expect(node.props.accessibilityLabel).toBe("Age 46, Male, Survey district Raisen");
  expect(node.props.children).toBe("46 y · Male · Raisen");
  expect(node.props.numberOfLines).toBe(1);
});

test("phone bar appends the state after the district, and shows the state alone without one", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const both = { ...workspace, case: { ...workspace.case, survey_district: "Raisen", survey_state: "Madhya Pradesh" } };
  const node = infoNode(renderLayout(undefined, both).renderer);
  expect(node.props.children).toBe("46 y · Male · Raisen, Madhya Pradesh");
  expect(node.props.accessibilityLabel).toBe("Age 46, Male, Survey district Raisen, Survey state Madhya Pradesh");
  const stateOnly = { ...workspace, case: { ...workspace.case, survey_state: "Madhya Pradesh" } };
  expect(infoNode(renderLayout(undefined, stateOnly).renderer).props.children).toBe("46 y · Male · Madhya Pradesh");
});

test.each([[undefined], [null], ["  "]])("phone bar omits the district part when it is %p", (district) => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout(undefined, withDistrict(district));
  const node = infoNode(renderer);
  expect(node.props.children).toBe("46 y · Male");
  expect(node.props.accessibilityLabel).toBe("Age 46, Male");
  expect(JSON.stringify(renderer.toJSON())).not.toContain("Survey district");
});

test("wide layout shows the survey district in the VA Form Details strip", () => {
  dimensions.mockReturnValue({ width: 1280, height: 900, scale: 1, fontScale: 1 });
  expect(JSON.stringify(renderLayout(undefined, withDistrict("Raisen")).renderer.toJSON())).toContain("Raisen");
  expect(JSON.stringify(renderLayout(undefined, withDistrict(null)).renderer.toJSON())).not.toContain("Survey district");
});

test("wide layout shows the survey state in the VA Form Details strip", () => {
  dimensions.mockReturnValue({ width: 1280, height: 900, scale: 1, fontScale: 1 });
  const withState = { ...workspace, case: { ...workspace.case, survey_state: "Madhya Pradesh" } };
  expect(JSON.stringify(renderLayout(undefined, withState).renderer.toJSON())).toContain("Survey state");
});

test("the layout draws no app header of its own: the shared AppHeader owns the logo, links and account menu", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const json = JSON.stringify(renderer.toJSON());
  expect(json).toContain("Open sections menu");
  expect(json).not.toContain("Account menu");
  expect(json).not.toContain("digitva_logo");
  expect(renderer.root.findAll((node) => node.type === ("header" as never))).toHaveLength(0);
});

test("phone sections bar is sticky, solid and below the drawer", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const trigger = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0];
  const bar = trigger.parent!;
  const style = ReactNative.StyleSheet.flatten(bar.props.style) as Record<string, unknown>;
  expect(style).toMatchObject({ position: "sticky", top: 0 });
  expect(style.backgroundColor).toEqual(expect.any(String));
  expect(style.zIndex).toBeLessThan(50);
});

test("phone sections drawer lists every section, selects and closes", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer, select } = renderLayout();
  const drawerNodes = () => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer");
  expect(drawerNodes()).toHaveLength(0);
  const trigger = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0];
  act(() => trigger.props.onPress());
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain('"role":"dialog"');
  expect(output).toContain("Case categories");
  for (const label of ["One, 3 responses, 2 attachments", "Two, 2 responses", "Three, 1 responses"]) expect(output).toContain(label);

  const category = renderer.root.findAll((node) => node.props.accessibilityLabel === "One, 3 responses, 2 attachments").find((node) => typeof node.props.onPress === "function");
  act(() => category?.props.onPress());
  expect(select).toHaveBeenCalledWith("one");
  expect(drawerNodes()).toHaveLength(0);
});

test("phone drawer closes from its close control and backdrop", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const open = () => act(() => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0].props.onPress());
  const isOpen = () => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer").length > 0;
  open();
  act(() => renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-close")[0].props.onPress());
  expect(isOpen()).toBe(false);
  open();
  const backdrop = renderer.root.findAll((node) => node.props.accessibilityLabel === "Close category names" && node.props.nativeID !== "digitva-category-drawer-close" && typeof node.props.onPress === "function")[0];
  act(() => backdrop.props.onPress());
  expect(isOpen()).toBe(false);
});

test("tablet width keeps the icon rail and has no hamburger", () => {
  dimensions.mockReturnValue({ width: 800, height: 1000, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("Case category shortcuts");
  expect(output).not.toContain("Open sections menu");
});

test("phone Notes opens as a persistent sheet and blocked Next leaves Previous available", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer, select } = renderLayout("Complete the current assessment before continuing.");
  const notesTrigger = renderer.root.findAll((node) => node.props.nativeID === "digitva-notes-trigger")[0];
  act(() => notesTrigger.props.onPress());
  let output = JSON.stringify(renderer.toJSON());
  expect(output).toContain("draft note survives navigation");
  expect(output).toContain('"maxHeight":"82%"');
  expect(output).toContain('"aria-modal":true');

  const buttons = renderer.root.findAllByType("button" as never);
  const next = buttons.find((node) => node.props.children === "Next");
  const previous = buttons.find((node) => node.props.children === "Previous");
  expect(next?.props.disabled).toBe(true);
  expect(next?.props["aria-label"]).toContain("Complete the current assessment");
  expect(previous?.props.disabled).toBe(false);
  act(() => previous?.props.onClick());
  expect(select).toHaveBeenCalledWith("one");
});

test("desktop layout expands the familiar category hierarchy and keeps hints/details visible", () => {
  dimensions.mockReturnValue({ width: 1280, height: 900, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const output = JSON.stringify(renderer.toJSON());

  expect(output).toContain("masked-form-7");
  expect(output).toContain("VA Form Details");
  expect(output).toContain("Hints");
  expect(output).toContain("SmartVA");
  expect(output).toContain("Two");
  expect(output).toContain("Case category shortcuts");
});

test("desktop rail opens the same names/counts drawer without replacing the rail", () => {
  dimensions.mockReturnValue({ width: 1280, height: 900, scale: 1, fontScale: 1 });
  const { renderer, select } = renderLayout();
  const trigger = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0];
  act(() => trigger.props.onPress());
  const output = JSON.stringify(renderer.toJSON());
  expect(output).toContain('"role":"complementary"');
  expect(output).not.toContain('"aria-modal":true');
  const category = renderer.root.findAll((node) => node.props.accessibilityLabel === "One, 3 responses, 2 attachments").find((node) => typeof node.props.onPress === "function");
  expect(category).toBeDefined();
  act(() => category?.props.onPress());
  expect(select).toHaveBeenCalledWith("one");
});

test("the open Notes panel sits above the sticky app header (z 40), so its close button is clickable", () => {
  // Training 2026-10-24: the header covered the panel's top 56 px and the × could not be clicked.
  dimensions.mockReturnValue({ width: 1280, height: 900, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  act(() => renderer.root.findAll((node) => node.props.nativeID === "digitva-notes-trigger")[0].props.onPress());
  const output = JSON.stringify(renderer.toJSON());
  const z = [...output.matchAll(/"zIndex":(\d+)/g)].map((m) => Number(m[1]));
  expect(z).toContain(45);
  const close = renderer.root.findAll((node) => node.props.nativeID === "digitva-notes-close")[0];
  expect(close).toBeTruthy();
  act(() => close.props.onPress());
  expect(JSON.stringify(renderer.toJSON())).toContain('"display":"none"');
});
