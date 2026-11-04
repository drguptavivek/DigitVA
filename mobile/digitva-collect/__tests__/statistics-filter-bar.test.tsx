import React from "react";
import { Modal, ScrollView } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The Statistics top line, Filters panel and applied chips (src/web/stats/FilterBar.tsx). */

let mockWidth = 1024;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: mockWidth, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, values: Record<string, string | number> = {}) => [key, ...Object.values(values)].join(":"),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
}));

import { FilterBar } from "../src/web/stats/FilterBar";

const projects = [
  { project_id: "P1", project_name: "Alpha", mode: "organization" as const },
  { project_id: "P2", project_name: "Beta", mode: "organization" as const },
  { project_id: "P3", project_name: "Gamma", mode: "sites" as const },
];
const overdue = { key: "overdue", label: "Overdue", options: [{ value: "", label: "All" }, { value: "1", label: "Overdue only" }], value: "", onChange: jest.fn() };

async function render(props: Partial<React.ComponentProps<typeof FilterBar>> = {}) {
  const all = {
    projects: projects as never, chosen: [], onProjects: jest.fn(), period: "all" as const, onPeriod: jest.fn(), selects: [], tab: "deaths" as const,
    onTab: jest.fn(), onClearAll: jest.fn(), ...props,
  };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<FilterBar {...all} />); });
  return { tree, props: all };
}
const pressable = (tree: ReactTestRenderer, label: string) => tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
const press = (tree: ReactTestRenderer, label: string) => act(async () => pressable(tree, label).props.onPress());
/** The Filters panel's modal (the Project menu's comes first in the tree). */
const panel = (tree: ReactTestRenderer) => tree.root.findAllByType(Modal).at(-1)!;
const modalOpen = (tree: ReactTestRenderer) => panel(tree).props.visible;
const clicks = (tree: ReactTestRenderer, label: string) => tree.root.findAll((node) => node.props["data-label"] === label)[0];

test("the Filters button opens the panel; Done, Close, outside tap and Escape close it", async () => {
  const { tree } = await render();
  expect(modalOpen(tree)).toBe(false);
  for (const close of [
    () => act(async () => clicks(tree, "statsProjectDone").props.onClick()),
    () => act(async () => clicks(tree, "supervisionClose").props.onClick()),
    () => press(tree, "closeList"),
    () => act(async () => panel(tree).props.onRequestClose()),
  ]) {
    await press(tree, "statsFilters");
    expect(modalOpen(tree)).toBe(true);
    await close();
    expect(modalOpen(tree)).toBe(false);
  }
  await act(async () => tree.unmount());
});

test("the button counts applied filters, not projects, and chips remove them one by one", async () => {
  const onProjects = jest.fn();
  const onPeriod = jest.fn();
  const onChange = jest.fn();
  const { tree } = await render({ chosen: ["P1", "P2"], period: "12m", selects: [{ ...overdue, value: "1", onChange }], onProjects, onPeriod });
  expect(pressable(tree, "statsFiltersActive:2")).toBeDefined();
  expect(pressable(tree, "filterProject: projectSelectCount:2")).toBeDefined();
  expect(tree.root.findAll((node) => String(node.props.accessibilityLabel).startsWith("removeFilter:filterProject"))).toHaveLength(0);
  await press(tree, "removeFilter:statsPeriod: statsPeriod12m");
  expect(onPeriod).toHaveBeenCalledWith("all");
  await press(tree, "removeFilter:Overdue: Overdue only");
  expect(onChange).toHaveBeenCalledWith("");
  await act(async () => tree.unmount());
});

test("no applied filter shows no chips and no count", async () => {
  const { tree } = await render();
  expect(pressable(tree, "statsFilters")).toBeDefined();
  expect(tree.root.findAll((node) => String(node.props.accessibilityLabel).startsWith("removeFilter"))).toHaveLength(0);
  expect(pressable(tree, "clearAll")).toBeUndefined();
  await act(async () => tree.unmount());
});

test("projects are chosen in the top-line Project menu, at once and several at a time, not in the panel", async () => {
  const { tree, props } = await render({ chosen: ["P1"] });
  await press(tree, "filterProject: Alpha");
  const menu = tree.root.findAllByType(Modal)[0];
  expect(menu.props.visible).toBe(true);
  expect(pressable(tree, "Beta").props.accessibilityRole).toBe("checkbox");
  await press(tree, "Beta");
  expect(props.onProjects).toHaveBeenCalledWith(["P1", "P2"]);
  expect(tree.root.findAllByType(Modal)[0].props.visible).toBe(true);
  await press(tree, "filterAllProjects");
  expect(props.onProjects).toHaveBeenLastCalledWith([]);
  await act(async () => tree.root.findAllByType(Modal)[0].props.onRequestClose());
  expect(pressable(tree, "Beta")).toBeUndefined();
  await press(tree, "statsFilters");
  expect(pressable(tree, "Beta")).toBeUndefined();
});

test("Clear all resets the panel's filters in one call", async () => {
  const { tree, props } = await render({ period: "12m" });
  await press(tree, "statsFiltersActive:1");
  await act(async () => clicks(tree, "clearAll").props.onClick());
  expect(props.onClearAll).toHaveBeenCalledTimes(1);
  await press(tree, "clearAll");
  expect(props.onClearAll).toHaveBeenCalledTimes(2);
  expect(modalOpen(tree)).toBe(true);
  await act(async () => tree.unmount());
});

test("tabs sit on the top line and change the tab", async () => {
  const { tree, props } = await render();
  await press(tree, "statsTabInterviews");
  expect(props.onTab).toHaveBeenCalledWith("interviews");
  await act(async () => tree.unmount());
});

const tabList = (tree: ReactTestRenderer) => tree.root.findAllByType(ScrollView)[0];
/** The narrow layout stacks the controls line above the tabs (column-reverse); the wide one keeps one row. */
const controlsAboveTabs = (tree: ReactTestRenderer) => {
  const direction = tabList(tree).parent!.props.style.flexDirection;
  expect(["row", "column-reverse"]).toContain(direction);
  return direction === "column-reverse";
};

test("the tabs are one horizontal row that never wraps", async () => {
  const { tree } = await render();
  const list = tabList(tree);
  expect(list.props.horizontal).toBe(true);
  expect(JSON.stringify([list.props.style, list.props.contentContainerStyle])).not.toContain("flexWrap");
  expect(tree.root.findAll((node) => node.props.accessibilityRole === "tab" && typeof node.props.onPress === "function")).toHaveLength(5);
  await act(async () => tree.unmount());
});

test("Project and Filters sit above the tabs under 900 px and on the tab line from 900 px", async () => {
  for (const [width, above] of [[375, true], [768, true], [899, true], [900, false], [1366, false]] as const) {
    mockWidth = width;
    const { tree } = await render();
    expect(controlsAboveTabs(tree)).toBe(above);
    await act(async () => tree.unmount());
  }
  mockWidth = 1024;
});
