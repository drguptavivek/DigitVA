import { useMemo } from "react";

import { t } from "../i18n";
import { orgUnitChains, type LabelUnit } from "./orgUnitLabel";
import { isInternalPlaceholderUnit } from "./placeholderUnit";
import { Select } from "./Select";

type PickUnit = LabelUnit & { is_active?: boolean; selectable?: boolean };
/** A caller-keyed option: *value* is what onChange reports (e.g. a site+unit target key), *suffix* tells apart two options on one unit. */
export type OrgUnitChoice = { value: string; org_unit_id: string; suffix?: string };

/**
 * A searchable org-unit dropdown (web and native, via Select). Each option is the unit name with its ancestors (nearest first) as a muted
 * second line, so a search for any ancestor finds its descendants. *units* are all of one project's known units (for the ancestor lookup).
 * Without *choices* the active, selectable, non-placeholder units are offered and *value* is an org_unit_id; with *choices*
 * those are offered as given and *value* is a choice's value.
 */
export function OrgUnitSelect({ label = t("chooseUnit"), placeholder = t("chooseUnit"), searchLabel = t("filterUnitSearch"), units, choices, value, onChange, testID }: {
  label?: string;
  placeholder?: string;
  searchLabel?: string;
  units: PickUnit[];
  choices?: OrgUnitChoice[];
  value: string;
  onChange: (value: string) => void;
  testID?: string;
}) {
  const options = useMemo(() => {
    const chains = orgUnitChains(units);
    const offered: OrgUnitChoice[] = choices ?? units
      .filter((u) => u.selectable !== false && u.is_active !== false && !isInternalPlaceholderUnit(u.unit_name))
      .map((u) => ({ value: u.org_unit_id, org_unit_id: u.org_unit_id }));
    return offered
      .map((choice) => {
        const chain = chains.get(choice.org_unit_id);
        const name = chain?.name ?? choice.org_unit_id;
        const detail = [chain?.trail, choice.suffix].filter(Boolean).join(" · ");
        return { value: choice.value, label: name, detail: detail || undefined, key: `${chain?.sortKey ?? name}\u0002${choice.suffix ?? ""}` };
      })
      .sort((a, b) => a.key.localeCompare(b.key))
      .map(({ value: v, label: l, detail }) => ({ value: v, label: l, detail }));
  }, [units, choices]);
  return <Select label={label} placeholder={placeholder} searchLabel={searchLabel} searchable options={options} value={value} onChange={onChange} testID={testID} />;
}
