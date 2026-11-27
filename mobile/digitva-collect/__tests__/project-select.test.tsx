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

import { anchorMenu, ProjectSelect } from "../src/ui/ProjectSelect";

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

test("the menu is attached to the button at every width", async () => {
  const wide = await render();
  await press(wide.tree, "filterProject: filterAllProjects");
  const menu = wide.tree.root.findAll((node) => node.props.accessibilityViewIsModal === true)[0];
  expect(menu.props.style).toEqual(expect.arrayContaining([expect.objectContaining({ top: 58, right: 124, width: 280, maxHeight: 400 })]));
  await act(async () => wide.tree.unmount());

  mockWidth = 400;
  const narrow = await render();
  await press(narrow.tree, "filterProject: filterAllProjects");
  expect(narrow.tree.root.findByType(Modal).props.animationType).toBe("none");
  const narrowMenu = narrow.tree.root.findAll((node) => node.props.accessibilityViewIsModal === true)[0];
  expect(narrowMenu.props.style).toEqual(expect.arrayContaining([expect.objectContaining({ top: 58, width: 280 })]));
  await act(async () => narrow.tree.unmount());
});

describe("anchorMenu", () => {
  const win = { width: 1000, height: 800 };
  const right = { side: "right", menuWidth: 280 } as const;

  test("opens below the field when there is room", () => {
    expect(anchorMenu({ x: 700, y: 10, w: 200, h: 44 }, win, right)).toEqual({ top: 58, right: 100, width: 280, maxHeight: 400 });
  });

  test("opens above a field near the bottom, capped by the space above", () => {
    const menu = anchorMenu({ x: 100, y: 700, w: 200, h: 44 }, win, { side: "left", menuWidth: 360 });
    expect(menu).toEqual({ bottom: 104, left: 100, width: 360, maxHeight: 400 });
    expect(anchorMenu({ x: 100, y: 300, w: 200, h: 44 }, { width: 1000, height: 500 }, { side: "left", menuWidth: 360 }))
      .toEqual({ bottom: 204, left: 100, width: 360, maxHeight: 288 });
  });

  test("a mid-screen field opens below while there is room for about five rows, even with more room above", () => {
    // 375x812 phone, unit field at 390-434: 374 below, 386 above. Opening up would cover the fields just used.
    const menu = anchorMenu({ x: 8, y: 390, w: 359, h: 44 }, { width: 375, height: 812 }, { side: "left", menuWidth: 360 });
    expect(menu.top).toBe(438);
    expect(menu.bottom).toBeUndefined();
    expect(menu.maxHeight).toBe(366);
  });

  test("caps maxHeight by the space on the chosen side", () => {
    expect(anchorMenu({ x: 0, y: 100, w: 200, h: 44 }, { width: 1000, height: 400 }, right).maxHeight).toBe(244);
  });

  test("is at least as wide as the field and clamped inside the window", () => {
    expect(anchorMenu({ x: 8, y: 10, w: 500, h: 44 }, win, right).width).toBe(500);
    const narrow = anchorMenu({ x: 8, y: 10, w: 310, h: 44 }, { width: 320, height: 800 }, right);
    expect(narrow.width).toBe(304);
    expect(narrow.right).toBe(8);
    expect(anchorMenu({ x: 900, y: 10, w: 90, h: 44 }, win, { side: "left", menuWidth: 360 }).left).toBe(632);
  });
});

test("on the phone one project stays plain text, with no button or menu", async () => {
  const one = await render({ projects: [projects[0]], fieldRow: true });
  expect(JSON.stringify(one.tree.toJSON())).toContain("filterProject: Alpha");
  expect(one.tree.root.findAll((node) => typeof node.props.onPress === "function")).toHaveLength(0);
  expect(one.tree.root.findAllByType(Modal)).toHaveLength(0);
  await act(async () => one.tree.unmount());
});

test("on the web one project is still a dropdown listing just that project; no project renders nothing", async () => {
  const { Platform } = require("react-native");
  const os = Platform.OS;
  Platform.OS = "web";
  try {
    await webOneProject();
  } finally {
    Platform.OS = os;
  }
});

async function webOneProject() {
  const onChange = jest.fn();
  const one = await render({ projects: [projects[0]], onChange });
  await press(one.tree, "filterProject: Alpha");
  expect(one.tree.root.findByType(Modal).props.visible).toBe(true);
  expect(one.tree.root.findAll((node) => node.props.accessibilityLabel === "filterAllProjects")).toHaveLength(0);
  expect(find(one.tree, "Alpha").props.accessibilityState.checked).toBe(true);
  await press(one.tree, "Alpha");
  expect(one.tree.root.findByType(Modal).props.visible).toBe(false);
  expect(onChange).not.toHaveBeenCalled();
  await act(async () => one.tree.unmount());
  const none = await render({ projects: [] });
  expect(none.tree.toJSON()).toBeNull();
  await act(async () => none.tree.unmount());
}

test("a disabled field does not open", async () => {
  const { tree } = await render({ disabled: true });
  expect(find(tree, "filterProject: filterAllProjects").props.accessibilityState).toEqual({ expanded: false, disabled: true });
  expect(find(tree, "filterProject: filterAllProjects").props.disabled).toBe(true);
  await act(async () => tree.unmount());
});
