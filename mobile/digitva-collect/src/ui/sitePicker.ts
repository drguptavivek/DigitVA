/**
 * The site/unit picker's model (pure): rows of unit names, grouped under a site header only when the user
 * reaches more than one real site; internal placeholder names are never shown.
 */
import { isInternalPlaceholderUnit } from "./placeholderUnit";
import { matchesSearch } from "./caseSearch";

export interface PickerTarget {
  key: string;
  label: string;
  projectId: string;
  siteId: string;
  orgUnitId?: string;
  siteName?: string;
  unitName?: string;
}

export interface PickerRow { target: PickerTarget; label: string }
export interface PickerGroup { siteId: string; title?: string; rows: PickerRow[] }
export interface PickerModel { groups: PickerGroup[]; /** Site headers are shown. */ headers: boolean; /** Rows before search. */ total: number }

/** Whether the target can be shown by name: its unit (or, with no tree, its site) is not an internal placeholder. */
const nameable = (target: PickerTarget) =>
  target.unitName === undefined ? !isInternalPlaceholderUnit(target.siteName ?? target.siteId) : !isInternalPlaceholderUnit(target.unitName);

/** The row's text: the unit name; with no unit tree the site name. */
export function rowLabel(target: PickerTarget): string {
  if (!nameable(target)) return target.label;
  return target.unitName ?? target.siteName ?? target.label;
}

/** Everything the row can be found by: its unit, its site and the raw label. */
const searchable = (target: PickerTarget, label: string) => [label, target.unitName, target.siteName, target.label];

/**
 * Rows for *targets* filtered by *query*. Placeholder-named targets are dropped while any real one exists;
 * if everything is a placeholder, the raw labels are shown rather than an empty picker.
 */
export function pickerModel(targets: PickerTarget[], query = ""): PickerModel {
  const named = targets.filter(nameable);
  const pool = named.length > 0 ? named : targets;
  const headers = new Set(pool.map((target) => target.siteId)).size > 1;
  const groups: PickerGroup[] = [];
  for (const target of pool) {
    const label = rowLabel(target);
    if (!matchesSearch(searchable(target, label), query)) continue;
    let group = groups.find((item) => item.siteId === target.siteId);
    if (!group) {
      group = { siteId: target.siteId, title: headers && !isInternalPlaceholderUnit(target.siteName) ? target.siteName : undefined, rows: [] };
      groups.push(group);
    }
    group.rows.push({ target, label });
  }
  return { groups, headers, total: pool.length };
}

/** The remembered choice among *targets* (same site and unit), if still offered. */
export function recentTarget(targets: PickerTarget[], recent: { siteId: string; orgUnitId?: string } | undefined): PickerTarget | undefined {
  if (!recent) return undefined;
  return targets.find((target) => target.siteId === recent.siteId && (target.orgUnitId ?? undefined) === (recent.orgUnitId ?? undefined));
}
