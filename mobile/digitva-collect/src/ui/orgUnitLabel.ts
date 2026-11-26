import { isInternalPlaceholderUnit } from "./placeholderUnit";

/** The fields of an org unit the label needs; AccessUnit and IntakeContextEntry.org_units both fit. */
export type LabelUnit = { org_unit_id: string; unit_code?: string; unit_name?: string; level_code?: string; path?: string };
/** A unit's name, its ancestor trail (nearest first, "" for a root), the combined label and the root-first sort key. */
export type UnitChain = { name: string; trail: string; label: string; sortKey: string };

const SEPARATOR = " < ";

const nameOf = (unit: LabelUnit) => unit.unit_name || unit.unit_code || unit.org_unit_id;

/**
 * Chains for every unit of one project, built once: name "PHC 1", trail "CHC 01 < BK HOSPITAL" (ancestors found by path
 * prefix within *units*, nearest parent first). An unknown ancestor is left out, never shown as a code; placeholder-named
 * ancestors are skipped. label is "name < trail" (for search and accessibility). sortKey is the root-first names, so
 * siblings sort together under their parent.
 */
export function orgUnitChains(units: LabelUnit[]): Map<string, UnitChain> {
  const byPath = new Map(units.filter((u) => u.path).map((u) => [u.path, u]));
  const chains = new Map<string, UnitChain>();
  for (const unit of units) {
    const parts = (unit.path ?? "").split(".").filter(Boolean);
    const ancestors = parts.slice(0, -1)
      .map((_, i) => byPath.get(parts.slice(0, i + 1).join(".")))
      .filter((u): u is LabelUnit => Boolean(u) && !isInternalPlaceholderUnit(u!.unit_name));
    const name = nameOf(unit);
    const trail = ancestors.map(nameOf).reverse().join(SEPARATOR);
    chains.set(unit.org_unit_id, {
      name,
      trail,
      label: trail ? `${name}${SEPARATOR}${trail}` : name,
      sortKey: [...ancestors, unit].map(nameOf).join("\u0001"),
    });
  }
  return chains;
}

/** One unit's chain label (see orgUnitChains); for many units build orgUnitChains once instead. */
export function orgUnitChainLabel(unit: LabelUnit, units: LabelUnit[]): string {
  return orgUnitChains([...units, unit]).get(unit.org_unit_id)!.label;
}
