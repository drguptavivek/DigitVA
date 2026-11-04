import React from "react";
import { Modal, View } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The shared top-line Project control (src/ui/ProjectSelect.tsx). */

let mockWidth = 1024;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: mockWidth, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));

import { ProjectSelect } from "../src/ui/ProjectSelect";

const projects = [{ id: "P1", name: "Alpha" }, { id: "P2", name: "Beta" }, { id: "P3", name: "Gamma" }];
const focus = jest.fn();
const measureInWindow = jest.fn((done: (x: number, y: number, w: number, h: number) => void) => done(700, 10, 200, 44));
// The Jest View is a class component, so a ref to the button is its instance: give it the host methods the control calls.
const viewPrototype = (View as unknown as { prototype: Record<string, unknown> }).prototype;
beforeAll(() => Object.assign(viewPrototype, { focus, measureInWindow }));
afterAll(() => { delete viewPrototype.focus; delete viewPrototype.measureInWindow; });

async function render(props: Partial<React.ComponentProps<typeof ProjectSelect>> = {}) {
  const all = { projects, value: [] as string[], onChange: jest.fn(), ...props };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<ProjectSelect {...all} />); });
  return { tree, props: all };
}
const find = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
const press = (tree: ReactTestRenderer, label: string) => act(async () => find(tree, label).props.onPress());
const menuOpen = (tree: ReactTestRenderer) => tree.root.findByType(Modal).props.visible;

beforeEach(() => {
  mockWidth = 1024;
  focus.mockClear();
});

test("single choice: the field names the choice, rows are radios, a press reports [] or [id] and closes", async () => {
  const { tree, props } = await render({ value: ["P2"] });
  const field = find(tree, "filterProject: Beta");
  expect(field.props.accessibilityRole).toBe("button");
  expect(field.props.accessibilityState).toEqual({ expanded: false, disabled: false });
  await press(tree, "filterProject: Beta");
  expect(menuOpen(tree)).toBe(true);
  expect(find(tree, "filterProject: Beta").props.accessibilityState.expanded).toBe(true);
  expect(find(tree, "Beta").props.accessibilityRole).toBe("radio");
  expect(find(tree, "Beta").props.accessibilityState).toEqual({ checked: true });
  expect(find(tree, "filterAllProjects").props.accessibilityState).toEqual({ checked: false });
  await press(tree, "Gamma");
  expect(props.onChange).toHaveBeenLastCalledWith(["P3"]);
  expect(menuOpen(tree)).toBe(false);
  expect(focus).toHaveBeenCalled();
  await press(tree, "filterProject: Beta");
  await press(tree, "filterAllProjects");
  expect(props.onChange).toHaveBeenLastCalledWith([]);
  await act(async () => tree.unmount());
});

test("multiple: rows are checkboxes, presses toggle without closing, from All a press narrows to that project", async () => {
  const { tree, props } = await render({ multiple: true });
  expect(find(tree, "filterProject: filterAllProjects")).toBeDefined();
  await press(tree, "filterProject: filterAllProjects");
  expect(find(tree, "Alpha").props.accessibilityRole).toBe("checkbox");
  // All checks every project.
  expect(find(tree, "Alpha").props.accessibilityState).toEqual({ checked: true });
  await press(tree, "Beta");
  expect(props.onChange).toHaveBeenLastCalledWith(["P2"]);
  expect(menuOpen(tree)).toBe(true);
  await act(async () => tree.update(<ProjectSelect projects={projects} value={["P1", "P2"]} onChange={props.onChange} multiple />));
  expect(find(tree, "filterProject: projectSelectCount:2")).toBeDefined();
  await press(tree, "Gamma");
  // Every project is All.
  expect(props.onChange).toHaveBeenLastCalledWith([]);
  await press(tree, "Alpha");
  expect(props.onChange).toHaveBeenLastCalledWith(["P2"]);
  await act(async () => tree.unmount());
});

test("Escape (onRequestClose) and a press outside close the menu without a choice", async () => {
  const { tree, props } = await render();
  await press(tree, "filterProject: filterAllProjects");
  await act(async () => tree.root.findByType(Modal).props.onRequestClose());
  expect(menuOpen(tree)).toBe(false);
  await press(tree, "filterProject: filterAllProjects");
  await press(tree, "closeList");
  expect(menuOpen(tree)).toBe(false);
  expect(props.onChange).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

test("wide screens anchor the menu below the button; narrow ones use a bottom sheet", async () => {
  const wide = await render();
  await press(wide.tree, "filterProject: filterAllProjects");
  const menu = wide.tree.root.findAll((node) => node.props.accessibilityViewIsModal === true)[0];
  expect(menu.props.style).toEqual(expect.arrayContaining([expect.objectContaining({ top: 58, right: 124 })]));
  await act(async () => wide.tree.unmount());

  mockWidth = 400;
  const narrow = await render();
  await press(narrow.tree, "filterProject: filterAllProjects");
  expect(narrow.tree.root.findByType(Modal).props.animationType).toBe("slide");
  await act(async () => narrow.tree.unmount());
});

test("one project is plain text; no project renders nothing", async () => {
  const one = await render({ projects: [projects[0]] });
  expect(JSON.stringify(one.tree.toJSON())).toContain("filterProject: Alpha");
  expect(one.tree.root.findAll((node) => node.props.accessibilityRole === "button")).toHaveLength(0);
  await act(async () => one.tree.unmount());
  const none = await render({ projects: [] });
  expect(none.tree.toJSON()).toBeNull();
  await act(async () => none.tree.unmount());
});

test("a disabled field does not open", async () => {
  const { tree } = await render({ disabled: true });
  expect(find(tree, "filterProject: filterAllProjects").props.accessibilityState).toEqual({ expanded: false, disabled: true });
  expect(find(tree, "filterProject: filterAllProjects").props.disabled).toBe(true);
  await act(async () => tree.unmount());
});
