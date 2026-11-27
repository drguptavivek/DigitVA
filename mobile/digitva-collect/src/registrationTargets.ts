import type { AccessProject, IntakeContextEntry } from "./api";
import type { Target } from "./sync";

/**
 * The places a death can be registered from *contexts* (register_death intake entries): a project without a unit tree gives
 * one target per site, one with a tree gives one per active, selectable unit. *projects* supply each context's `has_tree`.
 * Shared by the phone's Register screen and the web Add a Death form so both offer the same choices.
 */
export function registrationTargets(contexts: IntakeContextEntry[], projects: AccessProject[]): Target[] {
  return contexts.flatMap((entry) => {
    const project = projects.find((item) => item.project_id === entry.project_id);
    const units = (entry.org_units ?? []).filter((unit) => unit.is_active !== false && unit.selectable !== false);
    if (!project?.has_tree) return [{
      key: `${entry.project_id}:${entry.site_id}`,
      label: entry.site_name ?? entry.site_id,
      projectId: entry.project_id,
      siteId: entry.site_id,
      siteName: entry.site_name ?? entry.site_id,
    }];
    return units.map((unit) => ({
      key: `${entry.project_id}:${entry.site_id}:${unit.org_unit_id}`,
      label: `${entry.site_name ?? entry.site_id} · ${unit.unit_name ?? unit.org_unit_id}`,
      projectId: entry.project_id,
      siteId: entry.site_id,
      orgUnitId: unit.org_unit_id,
      siteName: entry.site_name ?? entry.site_id,
      unitName: unit.unit_name ?? unit.org_unit_id,
    }));
  });
}
