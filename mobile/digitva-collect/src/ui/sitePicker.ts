/**
 * The site/unit picker's model (pure): rows of unit names, grouped under a site header only when the user
 * reaches more than one real site; internal placeholder names are never shown.
 */
import { isInternalPlaceholderUnit } from "./placeholderUnit";
import { matchesSearch } from "./caseSearch";
import { orgUnitChains, type LabelUnit } from "./orgUnitLabel";

export interface PickerTarget {
  key: string;
  label: string;
  projectId: string;
  siteId: string;
  orgUnitId?: string;
  siteName?: string;
  unitName?: string;
}

/** *detail*: the unit's ancestors, nearest first, shown as a muted second line. */
export interface PickerRow { target: PickerTarget; label: string; detail?: string }
export interface PickerGroup { siteId: string; title?: string; rows: PickerRow[] }
export interface PickerModel { groups: PickerGroup[]; /** Site headers are shown. */ headers: boolean; /** Rows before search. */ total: number }

/** Whether the target can be shown by name: its unit (or, with no tree, its site) is not an internal placeholder. */
const nameable = (target: PickerTarget) =>
  target.unitName === undefined ? !isInternalPlaceholderUnit(target.siteName ?? target.siteId) : !isInternalPlaceholderUnit(target.unitName);

/** A target's ancestor trail ("Parent < Grandparent"; "" for a root), if its unit is known in its own project's tree. */
export type ChainOf = (target: PickerTarget) => string | undefined;

/**
 * A ChainOf over several projects' unit trees. Chains are built once here (callers memoise the result), and a target
 * is resolved only inside its own project, so equal unit paths in two projects never mix.
 */
export function chainLookup(projects: Array<{ projectId: string; units?: LabelUnit[] }>): ChainOf {
  const byProject = new Map(projects.filter((p) => p.units?.length).map((p) => [p.projectId, orgUnitChains(p.units!)]));
  return (target) => (target.orgUnitId ? byProject.get(target.projectId)?.get(target.orgUnitId)?.trail : undefined);
}

/** The row's text: the unit name; with no unit tree the site name. */
export function rowLabel(target: PickerTarget): string {
  if (!nameable(target)) return target.label;
  return target.unitName ?? target.siteName ?? target.label;
}

/** Everything the row can be found by: its unit, its ancestors, its site and the raw label. */
const searchable = (target: PickerTarget, label: string, detail?: string) => [label, detail, target.unitName, target.siteName, target.label];

/**
 * Rows for *targets* filtered by *query*. Placeholder-named targets are dropped while any real one exists;
 * if everything is a placeholder, the raw labels are shown rather than an empty picker.
 */
export function pickerModel(targets: PickerTarget[], query = "", chainOf?: ChainOf): PickerModel {
  const named = targets.filter(nameable);
  const pool = named.length > 0 ? named : targets;
  const headers = new Set(pool.map((target) => target.siteId)).size > 1;
  const groups: PickerGroup[] = [];
  for (const target of pool) {
    const label = rowLabel(target);
    const detail = (target.unitName !== undefined ? chainOf?.(target) : undefined) || undefined;
    if (!matchesSearch(searchable(target, label, detail), query)) continue;
    let group = groups.find((item) => item.siteId === target.siteId);
    if (!group) {
      group = { siteId: target.siteId, title: headers && !isInternalPlaceholderUnit(target.siteName) ? target.siteName : undefined, rows: [] };
      groups.push(group);
    }
    group.rows.push({ target, label, detail });
  }
  return { groups, headers, total: pool.length };
}

/** The remembered choice among *targets* (same site and unit), if still offered. */
export function recentTarget(targets: PickerTarget[], recent: { siteId: string; orgUnitId?: string } | undefined): PickerTarget | undefined {
  if (!recent) return undefined;
  return targets.find((target) => target.siteId === recent.siteId && (target.orgUnitId ?? undefined) === (recent.orgUnitId ?? undefined));
}
