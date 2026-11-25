import React from "react";
import { Modal, TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The shared single-choice dropdown (src/ui/Select.tsx). */

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

import { Select } from "../src/ui/Select";

const options = [{ value: "a", label: "CMO Office › Alpha" }, { value: "b", label: "CMO Office › Beta" }, { value: "c", label: "Gamma" }];

async function render(props: Partial<React.ComponentProps<typeof Select>> = {}) {
  const all = { label: "Unit", placeholder: "Pick one", options, value: "", onChange: jest.fn(), searchable: true, ...props };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<Select {...all} />); });
  return { tree, props: all };
}
const find = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];
const press = (tree: ReactTestRenderer, label: string) => act(async () => find(tree, label).props.onPress());
const menuOpen = (tree: ReactTestRenderer) => tree.root.findByType(Modal).props.visible;

test("shows the placeholder, then the selected label", async () => {
  const { tree } = await render();
  expect(find(tree, "Unit").props.accessibilityRole).toBe("button");
  expect(JSON.stringify(tree.toJSON())).toContain("Pick one");
  await act(async () => tree.update(<Select label="Unit" placeholder="Pick one" options={options} value="c" onChange={jest.fn()} />));
  expect(find(tree, "Unit: Gamma")).toBeDefined();
});

test("opens, filters by a case-insensitive substring, shows no-match, and a pick reports the value and closes", async () => {
  const { tree, props } = await render({ value: "c", searchLabel: "Search" });
  await press(tree, "Unit: Gamma");
  expect(menuOpen(tree)).toBe(true);
  expect(find(tree, "Gamma").props.accessibilityState).toEqual({ checked: true });
  const search = tree.root.findByType(TextInput);
  await act(async () => search.props.onChangeText("beta"));
  expect(find(tree, "CMO Office › Beta")).toBeDefined();
  expect(find(tree, "CMO Office › Alpha")).toBeUndefined();
  await act(async () => search.props.onChangeText("zzz"));
  expect(JSON.stringify(tree.toJSON())).toContain("pickerNoMatch");
  await act(async () => search.props.onChangeText("beta"));
  await press(tree, "CMO Office › Beta");
  expect(props.onChange).toHaveBeenCalledWith("b");
  expect(menuOpen(tree)).toBe(false);
});

test("a menu that is not searchable has no search box and closes on the backdrop", async () => {
  const { tree } = await render({ searchable: false });
  await press(tree, "Unit");
  expect(tree.root.findAllByType(TextInput)).toHaveLength(0);
  await press(tree, "closeList");
  expect(menuOpen(tree)).toBe(false);
});
