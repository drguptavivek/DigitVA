import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

/** The direct-interview place picker: org-unit names with ancestor lines, one value per site+unit, the no-tree fallback. */

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  FieldLabel: ({ label }: { label: string }) => <span data-field-label={label} />,
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => <button data-label={label} disabled={disabled} onClick={onPress} />,
}));

import { DirectInterviewPanel } from "../src/web/DirectInterviewPanel";
import { registrationTargets } from "../src/registrationTargets";

const unit = (id: string, name: string, path: string, level_code: string) => ({ org_unit_id: id, unit_code: path.split(".").pop(), unit_name: name, level_code, path });
const district = unit("d", "Agra", "AG", "D");
const phc = unit("p", "Rampur", "AG.RP", "P");
const phc2 = unit("p2", "Sadar", "AG.SD", "P");
const entry = (site_id: string, site_name: string, org_units: object[], project_id = "P1", project_name = "Alpha") =>
  ({ project_id, project_name, site_id, site_name, web_intake_mode: "direct", org_units });
const project = (project_id: string, project_name: string, has_tree: boolean, units: object[] = []) => ({ project_id, project_name, has_tree, units });

async function render(context: any[], projects: any[], onStart = jest.fn()) {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<DirectInterviewPanel targets={registrationTargets(context, projects)} projects={projects} onStart={onStart} />);
  });
  return { tree, onStart };
}
const press = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
const options = (tree: ReactTestRenderer) =>
  [...new Set(tree.root.findAll((n) => n.props.accessibilityRole === "radio").map((n) => n.props.accessibilityLabel as string))];
const start = (tree: ReactTestRenderer) => tree.root.findAll((n) => n.props["data-label"] === "startInterview")[0];
const fields = (tree: ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.props.accessibilityLabel === "string" && n.props.accessibilityLabel.startsWith("chooseSite") && typeof n.props.onPress === "function");

test("one dropdown labelled Site and unit; options are unit names with ancestors and a pick starts with the unit", async () => {
  const { tree, onStart } = await render(
    [entry("S1", "Site One", [{ ...district, selectable: false }, phc, phc2])],
    [project("P1", "Alpha", true, [district, phc, phc2])],
  );
  expect(fields(tree)).toHaveLength(1);
  expect(start(tree).props.disabled).toBe(true);
  await act(async () => press(tree, "chooseSite").props.onPress());
  expect(options(tree)).toEqual(["Rampur, Agra", "Sadar, Agra"]);
  await act(async () => press(tree, "Sadar, Agra").props.onPress());
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S1", orgUnitId: "p2" }));
});

test("one unit under two sites gives two options told apart by site", async () => {
  const { tree, onStart } = await render(
    [entry("S1", "Site One", [phc, phc2]), entry("S2", "Site Two", [phc, phc2])],
    [project("P1", "Alpha", true, [phc, phc2])],
  );
  await act(async () => press(tree, "chooseSite").props.onPress());
  expect(options(tree).filter((label) => label.startsWith("Rampur"))).toEqual(["Rampur, Site One", "Rampur, Site Two"]);
  await act(async () => press(tree, "Rampur, Site Two").props.onPress());
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S2", orgUnitId: "p" }));
});

test("a project without a tree lists its sites", async () => {
  const { tree, onStart } = await render([entry("S1", "Site One", []), entry("S2", "Site Two", [])], [project("P1", "Alpha", false)]);
  await act(async () => press(tree, "chooseSite").props.onPress());
  expect(options(tree)).toEqual(["Site One", "Site Two"]);
  await act(async () => press(tree, "Site Two").props.onPress());
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S2" }));
});

test("places from several projects name their project", async () => {
  const { tree } = await render(
    [entry("S1", "Site One", []), entry("S2", "Beta Site", [], "P2", "Beta")],
    [project("P1", "Alpha", false), project("P2", "Beta", false)],
  );
  await act(async () => press(tree, "chooseSite").props.onPress());
  expect(options(tree)).toEqual(["Beta Site, Beta", "Site One, Alpha"]);
});

test("a single option is chosen automatically, a tree project with one unit keeps its unit id", async () => {
  const { tree, onStart } = await render([entry("S1", "Site One", [phc])], [project("P1", "Alpha", true, [phc])]);
  expect(fields(tree)[0].props.accessibilityLabel).toBe("chooseSite: Rampur");
  expect(start(tree).props.disabled).toBe(false);
  await act(async () => start(tree).props.onClick());
  expect(onStart).toHaveBeenCalledWith(expect.objectContaining({ projectId: "P1", siteId: "S1", orgUnitId: "p" }));
});
