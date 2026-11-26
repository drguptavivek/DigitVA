import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The direct-interview place picker: org-unit names with ancestor lines, one value per site+unit, the no-tree fallback. */

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => <button data-label={label} disabled={disabled} onClick={onPress} />,
}));

import { DirectInterviewPanel, directInterviewTargets } from "../src/web/DirectInterviewPanel";

const unit = (id: string, name: string, path: string, level_code: string) => ({ org_unit_id: id, unit_code: path.split(".").pop(), unit_name: name, level_code, path });
const district = unit("d", "Agra", "AG", "D");
const phc = unit("p", "Rampur", "AG.RP", "P");
const phc2 = unit("p2", "Sadar", "AG.SD", "P");
const entry = (site_id: string, site_name: string, org_units: object[]) =>
  ({ project_id: "P1", project_name: "Alpha", site_id, site_name, web_intake_mode: "direct", org_units });

async function render(context: any[], onStart = jest.fn()) {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<DirectInterviewPanel targets={directInterviewTargets(context)} context={context} projectFixed onStart={onStart} />);
  });
  return { tree, onStart };
}
const press = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
const options = (tree: ReactTestRenderer) =>
  [...new Set(tree.root.findAll((n) => n.props.accessibilityRole === "radio").map((n) => n.props.accessibilityLabel as string))];
const start = (tree: ReactTestRenderer) => tree.root.findAll((n) => n.props["data-label"] === "startInterview")[0];

test("options are unit names with their ancestors and a pick starts with the unit", async () => {
  const { tree, onStart } = await render([entry("S1", "Site One", [{ ...district, selectable: false }, phc, phc2])]);
  await act(async () => press(tree, "interviewPlace").props.onPress());
  expect(options(tree)).toEqual(["Rampur, Agra", "Sadar, Agra"]);
  await act(async () => press(tree, "Sadar, Agra").props.onPress());
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S1", orgUnitId: "p2" }));
});

test("one unit under two sites gives two options told apart by site", async () => {
  const { tree, onStart } = await render([
    entry("S1", "Site One", [phc, phc2]),
    entry("S2", "Site Two", [phc, phc2]),
  ]);
  await act(async () => press(tree, "interviewPlace").props.onPress());
  expect(options(tree)).toEqual([
    "Rampur, Site One", "Rampur, Site Two",
    "Sadar, Site One", "Sadar, Site Two",
  ]);
  await act(async () => press(tree, "Rampur, Site Two").props.onPress());
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S2", orgUnitId: "p" }));
});

test("a project without units keeps the site field", async () => {
  const { tree } = await render([entry("S1", "Site One", []), entry("S2", "Site Two", [])]);
  await act(async () => press(tree, "interviewPlace: choosePlace").props.onPress());
  expect(press(tree, "Site One")).toBeDefined();
  expect(press(tree, "Site Two")).toBeDefined();
});
