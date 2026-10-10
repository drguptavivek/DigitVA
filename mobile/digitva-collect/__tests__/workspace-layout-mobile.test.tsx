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

function renderLayout(nextBlockedReason?: string): { renderer: ReactTestRenderer; select: jest.Mock; previous: jest.Mock } {
  const select = jest.fn();
  const previous = jest.fn();
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(<WorkspaceLayout
      identity={{ vaSid: "sid-mobile", mode: "coding" }}
      workspace={workspace}
      categories={workspace.categories}
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

test("phone layout keeps a 44px category icon rail and direct selection labels", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer, select } = renderLayout();
  const output = JSON.stringify(renderer.toJSON());

  expect(output).toContain("Case category shortcuts");
  expect(output).toContain("masked-form-7");
  expect(output).toContain("Age ");
  expect(output).toContain('"46"');
  expect(output).toContain("Male");
  expect(output).toContain("Open category names");
  expect(output).toContain('"minHeight":48');

  const category = renderer.root.findAll((node) => node.props.accessibilityLabel === "One, 3 responses, 2 attachments")[0];
  expect(category).toBeDefined();
  act(() => category.props.onPress());
  expect(select).toHaveBeenCalledWith("one");
});

test("phone category drawer exposes names/counts and closes through its accessible control", () => {
  dimensions.mockReturnValue({ width: 390, height: 844, scale: 1, fontScale: 1 });
  const { renderer } = renderLayout();
  const trigger = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-trigger")[0];
  act(() => trigger.props.onPress());
  let output = JSON.stringify(renderer.toJSON());
  expect(output).toContain('"role":"dialog"');
  expect(output).toContain("Case categories");
  expect(output).toContain("Two");
  expect(output).toContain('"children":["2"]');

  const close = renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-close")[0];
  act(() => close.props.onPress());
  output = JSON.stringify(renderer.toJSON());
  expect(renderer.root.findAll((node) => node.props.nativeID === "digitva-category-drawer-close")).toHaveLength(0);
  expect(output).toContain("Open category names");
});

test("phone Notes opens as a persistent sheet and blocked Next leaves Previous and rail exploration available", () => {
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
