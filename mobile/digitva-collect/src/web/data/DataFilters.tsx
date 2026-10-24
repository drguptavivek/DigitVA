import { createElement } from "react";
import { Text, View } from "react-native";

import type { DmFilterOptions } from "../../data/api";
import {
  activeFilters, AGE_GROUPS, clearFilters, ODK_STATUSES, ODK_SYNC_VALUES, SMARTVA_VALUES, WORKFLOW_GROUPS, WORKFLOW_STATES,
  matchGender, withFilters, type DataQuery, type FilterKey, type Filters,
} from "../../data/query";
import { t, type StringKey } from "../../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { SelectRow, StatPressable, TextAction } from "../stats/controls";

/** The server lists "female" and "Female" apart; the picker offers each spelling once (the first), plus the one in the URL. */
function genderChoices(genders: string[], current: string): string[] {
  const seen = new Set<string>();
  return [...genders, ...(current ? [current] : [])].filter((value) => {
    const key = value.trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** The label of a workflow state or group, in the current language. */
export const workflowLabel = (state: string): string => t(`dataWf_${state}` as StringKey);

const FILTER_NAMES: Record<FilterKey, StringKey> = {
  search: "dataFilterSearch", project: "dataFilterProject", site: "dataFilterSite", date_from: "dataFilterDateFrom", date_to: "dataFilterDateTo",
  odk_status: "dataFilterOdkStatus", smartva: "dataFilterSmartva", age_group: "dataFilterAge", gender: "dataFilterGender",
  odk_sync: "dataFilterSync", workflow: "dataFilterWorkflow", visit_note: "dataFilterVisitNote", org_unit: "dataFilterOrgUnit",
};

/** What a chip says for one active filter: "Workflow: Coded". */
export function chipText(key: FilterKey, value: string): string {
  const name = t(FILTER_NAMES[key]);
  if (key === "visit_note") return name;
  if (key === "org_unit") return name;
  if (key === "workflow") return `${name}: ${workflowLabel(value)}`;
  if (key === "odk_status") return `${name}: ${t(`dataOdk_${value}` as StringKey)}`;
  if (key === "smartva") return `${name}: ${t(`dataSmartva_${value}` as StringKey)}`;
  if (key === "age_group") return `${name}: ${t(`dataAge_${value}` as StringKey)}`;
  if (key === "odk_sync") return `${name}: ${t(`dataSync_${value}` as StringKey)}`;
  if (key === "gender") return `${name}: ${value.charAt(0).toUpperCase()}${value.slice(1)}`;
  return `${name}: ${value}`;
}

/** The active filters as removable chips and a Clear; nothing when no filter is on. */
export function FilterChips({ query, onQuery }: { query: DataQuery; onQuery: (next: DataQuery) => void }) {
  const { ui } = useTheme();
  const active = activeFilters(query.filters);
  if (!active.length) return null;
  return (
    <View accessibilityRole="toolbar" accessibilityLabel={t("dataChipsLabel")} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs }}>
      {active.map(({ key, value }) => {
        const text = chipText(key, value);
        return (
          <StatPressable
            key={key}
            label={t("dataChipRemove", { filter: text })}
            onPress={() => onQuery(withFilters(query, { [key]: key === "odk_sync" ? "in_sync" : "" }))}
            style={{ minHeight: 32, justifyContent: "center", paddingHorizontal: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: ui.input, backgroundColor: ui.secondary }}
          >
            <Text style={{ fontSize: fontSize.caption, color: ui.foreground }}>{`${text}  ✕`}</Text>
          </StatPressable>
        );
      })}
      <TextAction small label={t("dataClearFilters")} onPress={() => onQuery(clearFilters(query))} />
    </View>
  );
}

function CheckList({ label, options, selected, onChange }: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{label}</Text>
      {createElement(
        "div",
        { role: "group", "aria-label": label, style: { maxHeight: 132, overflowY: "auto", border: `1px solid ${ui.input}`, borderRadius: radius.md, padding: spacing.xs } },
        ...options.map((option) => createElement(
          "label",
          { key: option.value, style: { display: "flex", alignItems: "center", gap: spacing.xs, minHeight: 32, fontSize: fontSize.body, color: ui.foreground, fontFamily: controls.fontFamily } },
          createElement("input", {
            type: "checkbox",
            checked: selected.includes(option.value),
            onChange: () => onChange(selected.includes(option.value) ? selected.filter((one) => one !== option.value) : [...selected, option.value]),
          }),
          option.label,
        )),
      )}
    </View>
  );
}

export function DateInput({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{label}</Text>
      {createElement("input", {
        type: "date",
        "aria-label": label,
        value,
        onChange: (event: { target: { value: string } }) => onChange(event.target.value),
        style: { boxSizing: "border-box", minHeight: 44, padding: `0 ${spacing.sm}px`, fontSize: fontSize.body, fontFamily: controls.fontFamily, color: ui.foreground, background: ui.background, border: `1px solid ${ui.input}`, borderRadius: radius.md },
      })}
    </View>
  );
}

/** Everything the list can be narrowed by except the search box. Each change goes straight to the URL. */
export function FilterPanel({ query, options, onQuery }: { query: DataQuery; options: DmFilterOptions | null; onQuery: (next: DataQuery) => void }) {
  const { ui } = useTheme();
  const filters: Filters = query.filters;
  const set = (patch: Partial<Filters>) => onQuery(withFilters(query, patch));
  const list = (value: string) => value.split(",").filter(Boolean);
  const selectedProjects = list(filters.project);
  const sites = (options?.sites ?? []).filter((site) => !selectedProjects.length || selectedProjects.includes(site.project_id));
  const several = (options?.projects.length ?? 0) > 1;
  const genders = options?.genders ?? [];
  const genderNow = matchGender(genders, filters.gender) || filters.gender;
  const all = { value: "", label: t("dataAll") };
  const choices = (values: readonly string[], prefix: string) => [all, ...values.map((value) => ({ value, label: t(`${prefix}${value}` as StringKey) }))];
  return (
    <View style={{ gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: ui.border, borderRadius: radius.lg }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        {several ? (
          <View style={{ flexGrow: 1, flexBasis: 220 }}>
            <CheckList label={t("dataFilterProject")} options={(options?.projects ?? []).map((value) => ({ value, label: value }))} selected={selectedProjects} onChange={(next) => set({ project: next.join(",") })} />
          </View>
        ) : null}
        <View style={{ flexGrow: 1, flexBasis: 220 }}>
          <CheckList
            label={t("dataFilterSite")}
            options={sites.map((site) => ({ value: site.site_id, label: several && !selectedProjects.length ? `${site.project_id} / ${site.site_id}` : site.site_id }))}
            selected={list(filters.site)}
            onChange={(next) => set({ site: next.join(",") })}
          />
        </View>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        <DateInput label={t("dataFilterDateFrom")} value={filters.date_from} onChange={(next) => set({ date_from: next })} />
        <DateInput label={t("dataFilterDateTo")} value={filters.date_to} onChange={(next) => set({ date_to: next })} />
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow label={t("dataFilterWorkflow")} value={filters.workflow} onChange={(next) => set({ workflow: next })} options={[
            all,
            ...WORKFLOW_GROUPS.map((value) => ({ value: value as string, label: workflowLabel(value) })),
            ...WORKFLOW_STATES.map((value) => ({ value: value as string, label: workflowLabel(value) })),
          ]} />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow label={t("dataFilterOdkStatus")} value={filters.odk_status} onChange={(next) => set({ odk_status: next })} options={choices(ODK_STATUSES, "dataOdk_")} />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow label={t("dataFilterSmartva")} value={filters.smartva} onChange={(next) => set({ smartva: next })} options={choices(SMARTVA_VALUES, "dataSmartva_")} />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow label={t("dataFilterAge")} value={filters.age_group} onChange={(next) => set({ age_group: next })} options={choices(AGE_GROUPS, "dataAge_")} />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow
            label={t("dataFilterGender")}
            value={genderNow}
            onChange={(next) => set({ gender: next })}
            options={[all, ...genderChoices(genders, genderNow).map((value) => ({ value, label: value.charAt(0).toUpperCase() + value.slice(1) }))]}
          />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow label={t("dataFilterSync")} value={filters.odk_sync} onChange={(next) => set({ odk_sync: next })} options={ODK_SYNC_VALUES.map((value) => ({ value: value as string, label: t(`dataSync_${value}` as StringKey) }))} />
        </View>
      </View>
    </View>
  );
}
