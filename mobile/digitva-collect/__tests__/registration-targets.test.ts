import { registrationTargets } from "../src/registrationTargets";
import { intakeContextFromAccess } from "../src/api";
import { placeOptions } from "../src/web/placeOptions";

const unit = (id: string, name: string, path: string, over: Record<string, unknown> = {}) =>
  ({ org_unit_id: id, unit_name: name, path, selectable: true, is_active: true, roles: [], ...over });
const project = (id: string, hasTree: boolean, units: unknown[], sites: string[]) => ({
  project_id: id, project_name: `Name ${id}`, has_tree: hasTree, grants: [], sites: [], units,
  actions: { interview: [], register_death: sites.map((site_id) => ({ site_id, site_name: `Site ${site_id}`, web_intake_mode: "death_register", org_units: [] })) },
});
const access = { projects: [
  project("T", true, [unit("r", "Root", "R", { selectable: false }), unit("a", "Alpha", "R.A"), unit("g", "Gone", "R.G", { is_active: false })], ["S1", "S2"]),
  project("N", false, [], ["S3"]),
], training: null } as never;

it("gives one target per site without a tree and one per active selectable unit with one", () => {
  const a = access as { projects: never[] };
  const targets = registrationTargets(intakeContextFromAccess(access, "register_death"), a.projects);
  expect(targets.map((t) => t.key)).toEqual(["T:S1:a", "T:S2:a", "N:S3"]);
  expect(targets[0]).toMatchObject({ label: "Site S1 · Alpha", orgUnitId: "a", unitName: "Alpha", siteName: "Site S1" });
  expect(targets[2]).toEqual({ key: "N:S3", label: "Site S3", projectId: "N", siteId: "S3", siteName: "Site S3" });
});

it("names the site for a unit under several sites and the project when targets span projects", () => {
  const a = access as { projects: never[] };
  const targets = registrationTargets(intakeContextFromAccess(access, "register_death"), a.projects);
  expect(placeOptions(targets, a.projects)).toEqual([
    { value: "T:S1:a", label: "Alpha", detail: "Root · Site S1 · Name T" },
    { value: "T:S2:a", label: "Alpha", detail: "Root · Site S2 · Name T" },
    { value: "N:S3", label: "Site S3", detail: "Name N" },
  ]);
});
