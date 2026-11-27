import type { AccessProject } from "../api";
import type { Target } from "../sync";
import type { SelectOption } from "../ui/Select";
import { orgUnitChains } from "../ui/orgUnitLabel";
import { pickerModel } from "../ui/sitePicker";

/**
 * The "Site and unit" options for the web Add a Death form, one per registration *target* (value = target key). A unit shows its
 * name with its ancestors as the muted detail; a no-tree project shows the site name. The detail also names the site when the
 * same unit is offered under more than one site, and the project when the targets span more than one project. Placeholder
 * names are dropped as on the phone. Sorted root-first by unit names, then project.
 */
export function placeOptions(targets: Target[], projects: AccessProject[]): SelectOption[] {
  const chains = new Map(projects.map((p) => [p.project_id, orgUnitChains(p.units ?? [])]));
  const projectName = (id: string) => projects.find((p) => p.project_id === id)?.project_name ?? id;
  const rows = pickerModel(targets).groups.flatMap((group) => group.rows.map((row) => row.target));
  const manyProjects = new Set(rows.map((t) => t.projectId)).size > 1;
  const unitSites = new Map<string, Set<string>>();
  for (const t of rows) if (t.orgUnitId) unitSites.set(`${t.projectId}:${t.orgUnitId}`, (unitSites.get(`${t.projectId}:${t.orgUnitId}`) ?? new Set()).add(t.siteId));
  return rows
    .map((t) => {
      const chain = t.orgUnitId ? chains.get(t.projectId)?.get(t.orgUnitId) : undefined;
      const label = chain?.name ?? t.unitName ?? t.siteName ?? t.label;
      const sameUnitElsewhere = t.orgUnitId ? (unitSites.get(`${t.projectId}:${t.orgUnitId}`)?.size ?? 0) > 1 : false;
      const detail = [chain?.trail, sameUnitElsewhere ? t.siteName ?? t.siteId : undefined, manyProjects ? projectName(t.projectId) : undefined].filter(Boolean).join(" · ");
      return { value: t.key, label, detail: detail || undefined, key: chain?.sortKey ?? label, order: `${t.projectId}\u0001${t.siteId}` };
    })
    .sort((a, b) => a.key.localeCompare(b.key) || a.order.localeCompare(b.order))
    .map(({ value, label, detail }) => ({ value, label, detail }));
}

/** The list filter one queue place choice sends; `projectId` also names the project when the queue shows All projects. */
export type QueuePlace = { projectId: string; siteId?: string; orgUnitId?: string };

/**
 * The Code or Review queue's "Site and unit" choices in *projectIds*, from the server's reach for *action*
 * (`actions.code` / `actions.review` on /me/access; absent there means no choice). Never a place outside that reach:
 * - project-wide reach: every listed site (no tree) or every active, selectable unit (tree);
 * - site reach: those sites (the server's `site_id` filter), tree or not;
 * - unit reach (tree): the active, selectable units under a reached unit.
 * Labelled and sorted as placeOptions (unit lineage as the detail, the project when several). The server re-checks
 * reach on every list call; the filter only narrows it.
 */
export function queuePlaceOptions(projects: AccessProject[], action: "code" | "review", projectIds: string[]): { options: SelectOption[]; places: Map<string, QueuePlace> } {
  const targets: Target[] = [];
  const places = new Map<string, QueuePlace>();
  for (const project of projects) {
    const reach = project.actions[action];
    if (!reach || !projectIds.includes(project.project_id)) continue;
    const projectId = project.project_id;
    const wholeSites = reach.project && !project.has_tree;
    for (const site of project.sites) {
      if (!wholeSites && !reach.site_ids.includes(site.site_id)) continue;
      const key = `${projectId}:${site.site_id}`;
      targets.push({ key, label: site.site_name, projectId, siteId: site.site_id, siteName: site.site_name });
      places.set(key, { projectId, siteId: site.site_id });
    }
    if (!project.has_tree) continue;
    const units = project.units ?? [];
    const roots = units.filter((unit) => reach.org_unit_ids.includes(unit.org_unit_id));
    for (const unit of units) {
      if (!unit.selectable || unit.is_active === false) continue;
      if (!reach.project && !roots.some((root) => unit.path === root.path || unit.path.startsWith(`${root.path}.`))) continue;
      const key = `${projectId}::${unit.org_unit_id}`;
      targets.push({ key, label: unit.unit_name, projectId, siteId: "", orgUnitId: unit.org_unit_id, unitName: unit.unit_name });
      places.set(key, { projectId, orgUnitId: unit.org_unit_id });
    }
  }
  return { options: placeOptions(targets, projects), places };
}
