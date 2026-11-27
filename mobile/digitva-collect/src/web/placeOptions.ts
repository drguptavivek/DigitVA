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
