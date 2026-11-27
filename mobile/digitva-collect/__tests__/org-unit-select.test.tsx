import React from "react";
import { Modal, TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The shared org-unit dropdown (src/ui/OrgUnitSelect.tsx) and its label (src/ui/orgUnitLabel.ts). */

let mockWidth = 1024;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: mockWidth, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

import { OrgUnitSelect } from "../src/ui/OrgUnitSelect";
import { orgUnitChainLabel, orgUnitChains } from "../src/ui/orgUnitLabel";

const u = (id: string, name: string, path: string, level_code: string, extra: object = {}) =>
  ({ org_unit_id: id, unit_code: path.split(".").pop(), unit_name: name, level_code, path, ...extra });
const units = [
  u("d", "Agra", "AG", "D"), u("b", "Sadar", "AG.SD", "B"), u("p", "Rampur", "AG.SD.RP", "P"),
  u("d2", "Mathura", "MT", "D"), u("b2", "Sadar", "MT.SD", "B"), u("p2", "Rampur", "MT.SD.RP", "P"),
];

async function render(props: Partial<React.ComponentProps<typeof OrgUnitSelect>> = {}) {
  const all = { units, value: "", onChange: jest.fn(), ...props };
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<OrgUnitSelect {...all} />); });
  await act(async () => tree.root.findAll((n) => n.props.accessibilityLabel === "chooseUnit" && typeof n.props.onPress === "function")[0].props.onPress());
  return tree;
}
const labels = (tree: ReactTestRenderer) =>
  [...new Set(tree.root.findAll((n) => n.props.accessibilityRole === "radio").map((n) => n.props.accessibilityLabel as string))];

test("label is the unit name then its ancestors, nearest first, with no level text", () => {
  expect(orgUnitChainLabel(units[2], units)).toBe("Rampur < Sadar < Agra");
  expect(orgUnitChains(units).get("p")).toMatchObject({ name: "Rampur", trail: "Sadar < Agra" });
  expect(orgUnitChains(units).get("d")).toMatchObject({ name: "Agra", trail: "", label: "Agra" });
});

test("an ancestor missing from the list is skipped", () => {
  expect(orgUnitChainLabel(units[2], [units[0], units[2]])).toBe("Rampur < Agra");
});

test("a placeholder ancestor is skipped and a placeholder unit is not offered", async () => {
  const withPlaceholder = [u("s", "sites_in_project_X", "SP", "D"), u("c", "Clinic", "SP.CL", "P"), u("c2", "sites_in_project_Y", "SP.PH", "P")];
  expect(orgUnitChainLabel(withPlaceholder[1], withPlaceholder)).toBe("Clinic");
  const tree = await render({ units: withPlaceholder });
  expect(labels(tree)).toEqual(["Clinic"]);
});

test("same-named units under different parents are told apart by the second line, grouped by parent", async () => {
  const tree = await render();
  const rows = labels(tree);
  expect(rows).toEqual([
    "Agra", "Sadar, Agra", "Rampur, Sadar < Agra",
    "Mathura", "Sadar, Mathura", "Rampur, Sadar < Mathura",
  ]);
  expect(new Set(rows).size).toBe(rows.length);
  expect(rows.some((l) => l.includes("("))).toBe(false);
});

test("inactive and non-selectable units are not offered", async () => {
  const tree = await render({ units: [units[0], { ...units[1], is_active: false }, { ...units[2], selectable: false }, units[3]] });
  expect(labels(tree)).toEqual(["Agra", "Mathura"]);
});

test("searching an ancestor finds its descendants and reports the picked id", async () => {
  const onChange = jest.fn();
  const tree = await render({ value: "", onChange });
  await act(async () => tree.root.findByType(TextInput).props.onChangeText("mathura"));
  const rows = labels(tree);
  expect(rows).toEqual(["Mathura", "Sadar, Mathura", "Rampur, Sadar < Mathura"]);
  await act(async () => tree.root.findAll((n) => n.props.accessibilityLabel === rows[2] && typeof n.props.onPress === "function")[0].props.onPress());
  expect(onChange).toHaveBeenCalledWith("p2");
  expect(tree.root.findByType(Modal).props.visible).toBe(false);
});

test("caller-keyed choices: one unit under two sites gets two values, the site named on the second line", async () => {
  const onChange = jest.fn();
  const tree = await render({ onChange, choices: [
    { value: "proj:S2:p", org_unit_id: "p", suffix: "Site Two" },
    { value: "proj:S1:p", org_unit_id: "p", suffix: "Site One" },
  ] });
  const rows = labels(tree);
  expect(rows).toEqual(["Rampur, Sadar < Agra · Site One", "Rampur, Sadar < Agra · Site Two"]);
  await act(async () => tree.root.findAll((n) => n.props.accessibilityLabel === rows[1] && typeof n.props.onPress === "function")[0].props.onPress());
  expect(onChange).toHaveBeenCalledWith("proj:S2:p");
});

test("a narrow window still opens the menu attached to the field", async () => {
  mockWidth = 375;
  try {
    const tree = await render();
    expect(tree.root.findByType(Modal).props.animationType).toBe("none");
    expect(tree.root.findByType(Modal).props.visible).toBe(true);
  } finally { mockWidth = 1024; }
});
