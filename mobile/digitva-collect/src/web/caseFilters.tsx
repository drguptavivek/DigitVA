import { useCallback, useEffect, useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import type { AccessProject, IntakeContextEntry } from "../api";
import { t } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button } from "../ui";

/** Filters the "Advanced filters" sheet applies on both VA Interview tabs. Empty string = not set. */
export type AdvancedFilters = {
  dodFrom: string;
  dodTo: string;
  reportedFrom: string;
  reportedTo: string;
  sex: "" | "male" | "female" | "other";
  ageBand: "" | AgeBand;
  ageMin: string;
  ageMax: string;
};

export type AgeBand = "lt1" | "1-14" | "15-49" | "50-69" | "70+";

export const EMPTY_ADVANCED: AdvancedFilters = {
  dodFrom: "", dodTo: "", reportedFrom: "", reportedTo: "", sex: "", ageBand: "", ageMin: "", ageMax: "",
};

const AGE_BANDS: { key: AgeBand; min: number; max: number }[] = [
  { key: "lt1", min: 0, max: 0 },
  { key: "1-14", min: 1, max: 14 },
  { key: "15-49", min: 15, max: 49 },
  { key: "50-69", min: 50, max: 69 },
  { key: "70+", min: 70, max: Infinity },
];

/** The row fields the advanced filters read; both case rows and draft rows carry them. */
export type AdvancedFilterRow = {
  deceased_sex?: string | null;
  age_years?: number | null;
  date_of_death?: string | null;
  created_at?: string | null;
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function validDate(value: string): string | undefined {
  return ISO_DATE.test(value) ? value : undefined;
}

function wholeNumber(value: string): number | undefined {
  if (!/^\d{1,3}$/.test(value.trim())) return undefined;
  return Number(value.trim());
}

/** Local calendar date of an ISO timestamp, so "reported on" matches what the row shows. */
function localDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  if (ISO_DATE.test(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return formatLocal(parsed);
}

function formatLocal(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function inRange(value: string | undefined, from: string, to: string): boolean {
  const lo = validDate(from);
  const hi = validDate(to);
  if (!lo && !hi) return true;
  if (!value) return false;
  return (!lo || value >= lo) && (!hi || value <= hi);
}

/** Age bounds from the band and the min/max fields together (both must hold). */
function ageBounds(filters: AdvancedFilters): { min: number; max: number } | undefined {
  const band = AGE_BANDS.find((entry) => entry.key === filters.ageBand);
  const min = wholeNumber(filters.ageMin);
  const max = wholeNumber(filters.ageMax);
  if (!band && min === undefined && max === undefined) return undefined;
  return {
    min: Math.max(band?.min ?? 0, min ?? 0),
    max: Math.min(band?.max ?? Infinity, max ?? Infinity),
  };
}

/** Whether a row passes every advanced filter. A row missing the field a filter needs does not pass it. */
export function matchesAdvanced(row: AdvancedFilterRow, filters: AdvancedFilters): boolean {
  if (!inRange(row.date_of_death ?? undefined, filters.dodFrom, filters.dodTo)) return false;
  if (!inRange(localDate(row.created_at), filters.reportedFrom, filters.reportedTo)) return false;
  if (filters.sex) {
    const sex = (row.deceased_sex ?? "").toLowerCase();
    const bucket = sex === "male" || sex === "female" ? sex : "other";
    if (bucket !== filters.sex) return false;
  }
  const bounds = ageBounds(filters);
  if (bounds) {
    if (typeof row.age_years !== "number") return false;
    if (row.age_years < bounds.min || row.age_years > bounds.max) return false;
  }
  return true;
}

type AppliedChip = { key: string; label: string; clear: Partial<AdvancedFilters> };

function rangeText(from: string, to: string): string {
  return `${validDate(from) ?? "…"} – ${validDate(to) ?? "…"}`;
}

function ageBandLabel(band: AgeBand): string {
  return band === "lt1" ? t("ageUnder1") : band;
}

/** One removable chip per active advanced filter; its length is the badge count. */
export function appliedAdvancedChips(filters: AdvancedFilters, reportedLabel: string): AppliedChip[] {
  const chips: AppliedChip[] = [];
  if (validDate(filters.dodFrom) || validDate(filters.dodTo)) {
    chips.push({ key: "dod", label: `${t("filterDateOfDeath")}: ${rangeText(filters.dodFrom, filters.dodTo)}`, clear: { dodFrom: "", dodTo: "" } });
  }
  if (validDate(filters.reportedFrom) || validDate(filters.reportedTo)) {
    chips.push({ key: "reported", label: `${reportedLabel}: ${rangeText(filters.reportedFrom, filters.reportedTo)}`, clear: { reportedFrom: "", reportedTo: "" } });
  }
  if (filters.sex) {
    chips.push({ key: "sex", label: `${t("filterSex")}: ${sexFilterLabel(filters.sex)}`, clear: { sex: "" } });
  }
  if (filters.ageBand) {
    chips.push({ key: "ageBand", label: `${t("filterAge")}: ${ageBandLabel(filters.ageBand)}`, clear: { ageBand: "" } });
  }
  const min = wholeNumber(filters.ageMin);
  const max = wholeNumber(filters.ageMax);
  if (min !== undefined || max !== undefined) {
    chips.push({ key: "ageRange", label: `${t("filterAge")}: ${min ?? "…"} – ${max ?? "…"}`, clear: { ageMin: "", ageMax: "" } });
  }
  return chips;
}

function sexFilterLabel(sex: AdvancedFilters["sex"]): string {
  if (sex === "male") return t("sexMale");
  if (sex === "female") return t("sexFemale");
  return t("sexOtherUnknown");
}

function useFilterStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    filterCard: { gap: spacing.xs, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    searchRow: { flexDirection: "row", gap: spacing.xs, alignItems: "center" },
    searchInput: {
      flex: 1, minWidth: 0, minHeight: 40, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface,
      paddingHorizontal: spacing.sm, paddingVertical: spacing.xxs, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily,
    },
    chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    // Row 2: status chips left, toggles right; on a phone the right part wraps under the left.
    statusRow: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: spacing.xs },
    statusLeft: { flexShrink: 1, minWidth: 0 },
    statusRight: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
    segment: { flexDirection: "row", borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, overflow: "hidden" },
    segmentOption: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm },
    segmentOptionOn: { backgroundColor: colors.accent },
    chip: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    chipOn: { borderColor: colors.accent, backgroundColor: colors.accent },
    chipText: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    chipTextOn: { color: colors.onAccent },
    groupLabel: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    advancedButton: {
      flexDirection: "row", alignItems: "center", gap: spacing.xxs, minHeight: 40, paddingHorizontal: spacing.sm,
      borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    },
    advancedText: { ...typography.subhead, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    badge: { minWidth: 20, height: 20, paddingHorizontal: 6, borderRadius: radius.full, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center" },
    badgeText: { ...typography.caption, fontWeight: "700", color: colors.onAccent, fontFamily: controls.fontFamily },
    appliedChip: {
      flexDirection: "row", alignItems: "center", gap: spacing.xxs, paddingVertical: spacing.xxs, paddingLeft: spacing.sm, paddingRight: spacing.xs,
      borderRadius: radius.full, borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.accentSoft,
    },
    appliedChipText: { ...typography.caption, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    linkText: { ...typography.caption, fontWeight: "600", color: colors.accent, fontFamily: controls.fontFamily },
    note: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    backdropSheet: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
    backdropSide: { flex: 1, flexDirection: "row", justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" },
    sheet: {
      maxHeight: "85%", width: "100%", backgroundColor: colors.background, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
      borderWidth: 1, borderColor: colors.border,
    },
    side: { height: "100%", width: 380, maxWidth: "100%", backgroundColor: colors.background, borderLeftWidth: 1, borderColor: colors.border },
    sheetHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.sm, borderBottomWidth: 1, borderColor: colors.border },
    sheetTitle: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    sheetBody: { padding: spacing.sm, gap: spacing.md },
    section: { gap: spacing.xs },
    sectionTitle: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily, textTransform: "uppercase" },
    group: { gap: spacing.xs, padding: spacing.sm, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
    pair: { flexDirection: "row", gap: spacing.xs },
    pairField: { flex: 1, minWidth: 0, gap: spacing.xxs },
    fieldLabel: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    sheetFooter: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.xs, padding: spacing.sm, borderTopWidth: 1, borderColor: colors.border },
  }), [colors]);
}

type ChipOption<K extends string> = { key: K; label: string };

function ChipGroup<K extends string>({ options, value, onChange, a11yLabel }: {
  options: ChipOption<K>[];
  value: K;
  onChange: (key: K) => void;
  a11yLabel: (label: string) => string;
}) {
  const s = useFilterStyles();
  return (
    <View style={s.chipRow}>
      {options.map((option) => {
        const on = option.key === value;
        return (
          <Pressable
            key={option.key}
            accessibilityRole="button"
            accessibilityLabel={a11yLabel(option.label)}
            accessibilityState={{ selected: on }}
            hitSlop={spacing.xs}
            onPress={() => onChange(option.key)}
            style={[s.chip, on && s.chipOn]}
          >
            <Text style={[s.chipText, on && s.chipTextOn]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Native browser date field (web only screen); the value is an ISO date or "". */
function DateField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const { colors } = useTheme();
  const s = useFilterStyles();
  return (
    <View style={s.pairField}>
      <Text style={s.fieldLabel}>{label}</Text>
      <input
        type="date"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        style={{
          minHeight: 40, boxSizing: "border-box", width: "100%", border: `1px solid ${colors.border}`, borderRadius: radius.md,
          padding: "0 8px", fontSize: 16, color: colors.text, background: colors.surface, fontFamily: controls.fontFamily,
        }}
      />
    </View>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const { colors } = useTheme();
  const s = useFilterStyles();
  return (
    <View style={s.pairField}>
      <Text style={s.fieldLabel}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        inputMode="numeric"
        maxLength={3}
        value={value}
        onChangeText={(next) => onChange(next.replace(/\D/g, ""))}
        placeholderTextColor={colors.textMuted}
        style={[s.searchInput, { flex: undefined }]}
      />
    </View>
  );
}

/** The area option meaning "any of my own areas" (the units of my field grants). */
export const WITHIN_AREA = "__within_area__";

export type ProjectOption = { value: string; label: string };

/** Project and area are applied with the sheet but filtered outside `matchesAdvanced` (project on the server). */
export type PlaceFilters = { project?: string; unit?: string };

function areaLabel(unit: string): string {
  return unit === WITHIN_AREA ? t("filterWithinArea") : unit;
}

/**
 * Advanced filters: a bottom sheet on a phone, a side panel on a wide screen
 * (iOS HIG grouped sections). Project and Area come first, then Dates, Sex,
 * Age. Edits stay local until Apply; Clear all empties the form without applying.
 */
function AdvancedFiltersSheet({ open, value, place, projects, units, reportedLabel, onApply, onClose }: {
  open: boolean;
  value: AdvancedFilters;
  place: PlaceFilters;
  projects: ProjectOption[];
  units: string[];
  reportedLabel: string;
  onApply: (next: AdvancedFilters, place: PlaceFilters) => void;
  onClose: () => void;
}) {
  const s = useFilterStyles();
  const { width } = useWindowDimensions();
  const [draft, setDraft] = useState(value);
  const [draftPlace, setDraftPlace] = useState(place);
  useEffect(() => {
    if (open) {
      setDraft(value);
      setDraftPlace(place);
    }
  }, [open, value, place.project, place.unit]);
  const set = (patch: Partial<AdvancedFilters>) => setDraft((previous) => ({ ...previous, ...patch }));
  const wide = width >= 768;
  return (
    <Modal visible={open} transparent animationType={wide ? "fade" : "slide"} onRequestClose={onClose}>
      <View style={wide ? s.backdropSide : s.backdropSheet}>
        <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={onClose} style={StyleSheet.absoluteFill} />
        <View style={wide ? s.side : s.sheet} accessibilityViewIsModal>
          <View style={s.sheetHeader}>
            <Text style={s.sheetTitle} accessibilityRole="header">{t("advancedFilters")}</Text>
            <Button kind="secondary" size="sm" label={t("supervisionClose")} onPress={onClose} />
          </View>
          <ScrollView contentContainerStyle={s.sheetBody}>
            {projects.length > 1 ? (
              <View style={s.section}>
                <Text style={s.sectionTitle}>{t("filterProject")}</Text>
                <View style={s.group}>
                  <ChipGroup
                    options={[{ key: "", label: t("filterAllProjects") }, ...projects.map((project) => ({ key: project.value, label: project.label }))]}
                    value={draftPlace.project ?? ""}
                    onChange={(key) => setDraftPlace((previous) => ({ ...previous, project: key || undefined }))}
                    a11yLabel={(label) => t("filterProjectLabel", { label })}
                  />
                </View>
              </View>
            ) : null}
            {units.length > 1 ? (
              <View style={s.section}>
                <Text style={s.sectionTitle}>{t("filterArea")}</Text>
                <View style={s.group}>
                  <ChipGroup
                    options={[
                      { key: "", label: t("filterAll") },
                      { key: WITHIN_AREA, label: t("filterWithinArea") },
                      ...units.map((unit) => ({ key: unit, label: unit })),
                    ]}
                    value={draftPlace.unit ?? ""}
                    onChange={(key) => setDraftPlace((previous) => ({ ...previous, unit: key || undefined }))}
                    a11yLabel={(label) => t("filterAreaLabel", { label })}
                  />
                </View>
              </View>
            ) : null}
            <View style={s.section}>
              <Text style={s.sectionTitle}>{t("filterDates")}</Text>
              <View style={s.group}>
                <Text style={s.groupLabel}>{t("filterDateOfDeath")}</Text>
                <View style={s.pair}>
                  <DateField label={`${t("filterDateOfDeath")} ${t("filterFrom")}`} value={draft.dodFrom} onChange={(dodFrom) => set({ dodFrom })} />
                  <DateField label={`${t("filterDateOfDeath")} ${t("filterTo")}`} value={draft.dodTo} onChange={(dodTo) => set({ dodTo })} />
                </View>
                <Text style={s.groupLabel}>{reportedLabel}</Text>
                <View style={s.pair}>
                  <DateField label={`${reportedLabel} ${t("filterFrom")}`} value={draft.reportedFrom} onChange={(reportedFrom) => set({ reportedFrom })} />
                  <DateField label={`${reportedLabel} ${t("filterTo")}`} value={draft.reportedTo} onChange={(reportedTo) => set({ reportedTo })} />
                </View>
              </View>
            </View>
            <View style={s.section}>
              <Text style={s.sectionTitle}>{t("filterSex")}</Text>
              <View style={s.group}>
                <ChipGroup<AdvancedFilters["sex"]>
                  options={[
                    { key: "", label: t("filterAll") },
                    { key: "male", label: t("sexMale") },
                    { key: "female", label: t("sexFemale") },
                    { key: "other", label: t("sexOtherUnknown") },
                  ]}
                  value={draft.sex}
                  onChange={(sex) => set({ sex })}
                  a11yLabel={(label) => t("filterSexLabel", { label })}
                />
              </View>
            </View>
            <View style={s.section}>
              <Text style={s.sectionTitle}>{t("filterAge")}</Text>
              <View style={s.group}>
                <ChipGroup<AdvancedFilters["ageBand"]>
                  options={[{ key: "", label: t("filterAll") }, ...AGE_BANDS.map((band) => ({ key: band.key, label: ageBandLabel(band.key) }))]}
                  value={draft.ageBand}
                  onChange={(ageBand) => set({ ageBand })}
                  a11yLabel={(label) => t("filterAgeLabel", { label })}
                />
                <View style={s.pair}>
                  <NumberField label={t("filterAgeMin")} value={draft.ageMin} onChange={(ageMin) => set({ ageMin })} />
                  <NumberField label={t("filterAgeMax")} value={draft.ageMax} onChange={(ageMax) => set({ ageMax })} />
                </View>
              </View>
            </View>
          </ScrollView>
          <View style={s.sheetFooter}>
            <Button kind="secondary" label={t("clearAll")} onPress={() => { setDraft(EMPTY_ADVANCED); setDraftPlace({}); }} />
            <Button label={t("applyFilters")} onPress={() => onApply(draft, draftPlace)} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

export type StatusChip<K extends string> = { key: K; label: string };

/** A two-way segmented toggle on the right of the status row (Mine | All, Last 30 days | All). */
export type FilterToggle = {
  key: string;
  on: boolean;
  onLabel: string;
  offLabel: string;
  a11yLabel: (label: string) => string;
  onChange: (on: boolean) => void;
};

function SegmentedToggle({ toggle }: { toggle: FilterToggle }) {
  const s = useFilterStyles();
  return (
    <View style={s.segment}>
      {([[true, toggle.onLabel], [false, toggle.offLabel]] as const).map(([value, label]) => {
        const selected = toggle.on === value;
        return (
          <Pressable
            key={String(value)}
            accessibilityRole="button"
            accessibilityLabel={toggle.a11yLabel(label)}
            accessibilityState={{ selected }}
            hitSlop={spacing.xxs}
            onPress={() => toggle.onChange(value)}
            style={[s.segmentOption, selected && s.segmentOptionOn]}
          >
            <Text style={[s.chipText, selected && s.chipTextOn]}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * The filter bar every case list shares. Row 1: search and the Advanced
 * filters button (its badge counts every applied sheet filter). Row 2: status
 * chips on the left, the optional toggles on the right. Project and Area live
 * in the sheet; applied sheet filters show as removable chips with Clear all.
 */
export function CaseFilterBar<K extends string>(props: {
  search: string;
  onSearch: (value: string) => void;
  statusChips: StatusChip<K>[];
  status: K;
  allStatus: K;
  onStatus: (key: K) => void;
  toggles?: FilterToggle[];
  projects: ProjectOption[];
  project?: string;
  onProject: (value: string | undefined) => void;
  units: string[];
  unit?: string;
  onUnit: (value: string | undefined) => void;
  advanced: AdvancedFilters;
  onAdvanced: (value: AdvancedFilters) => void;
  reportedLabel: string;
  onClearAll: () => void;
}) {
  const s = useFilterStyles();
  const { colors } = useTheme();
  const [sheetOpen, setSheetOpen] = useState(false);
  const projectLabel = props.projects.find((project) => project.value === props.project)?.label ?? props.project;
  const chips = [
    ...(props.project ? [{ key: "project", label: `${t("filterProject")}: ${projectLabel}`, clear: () => props.onProject(undefined) }] : []),
    ...(props.unit ? [{ key: "unit", label: `${t("filterArea")}: ${areaLabel(props.unit)}`, clear: () => props.onUnit(undefined) }] : []),
    ...appliedAdvancedChips(props.advanced, props.reportedLabel)
      .map((chip) => ({ key: chip.key, label: chip.label, clear: () => props.onAdvanced({ ...props.advanced, ...chip.clear }) })),
  ];
  const anyActive = props.search.trim().length > 0 || props.status !== props.allStatus || chips.length > 0;
  return (
    <View style={s.filterCard}>
      <View style={s.searchRow}>
        <TextInput
          accessibilityLabel={t("searchCases")}
          placeholder={t("searchCasesPlaceholder")}
          placeholderTextColor={colors.textMuted}
          value={props.search}
          onChangeText={props.onSearch}
          style={s.searchInput}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={chips.length ? t("advancedFiltersActive", { count: chips.length }) : t("advancedFilters")}
          accessibilityState={{ expanded: sheetOpen }}
          onPress={() => setSheetOpen(true)}
          style={s.advancedButton}
        >
          <Text style={s.advancedText}>{t("advancedFilters")}</Text>
          {chips.length ? <View style={s.badge}><Text style={s.badgeText}>{chips.length}</Text></View> : null}
        </Pressable>
      </View>
      <View style={s.statusRow} testID="case-filter-status-row">
        <View style={s.statusLeft} testID="case-filter-status-left">
          <ChipGroup options={props.statusChips} value={props.status} onChange={props.onStatus} a11yLabel={(label) => t("filterStatusLabel", { label })} />
        </View>
        {props.toggles?.length ? (
          <View style={s.statusRight} testID="case-filter-status-right">
            {props.toggles.map((toggle) => <SegmentedToggle key={toggle.key} toggle={toggle} />)}
          </View>
        ) : null}
      </View>
      {anyActive ? (
        <View style={s.chipRow}>
          {chips.map((chip) => (
            <Pressable
              key={chip.key}
              accessibilityRole="button"
              accessibilityLabel={t("removeFilter", { label: chip.label })}
              hitSlop={spacing.xs}
              onPress={chip.clear}
              style={s.appliedChip}
            >
              <Text style={s.appliedChipText}>{chip.label}</Text>
              <Text style={s.appliedChipText} aria-hidden>×</Text>
            </Pressable>
          ))}
          <Pressable accessibilityRole="button" accessibilityLabel={t("clearAll")} hitSlop={spacing.xs} onPress={props.onClearAll}>
            <Text style={s.linkText}>{t("clearAll")}</Text>
          </Pressable>
        </View>
      ) : null}
      <AdvancedFiltersSheet
        open={sheetOpen}
        value={props.advanced}
        place={{ project: props.project, unit: props.unit }}
        projects={props.projects}
        units={props.units}
        reportedLabel={props.reportedLabel}
        onApply={(next, place) => {
          setSheetOpen(false);
          props.onAdvanced(next);
          if (place.project !== props.project) props.onProject(place.project);
          if (place.unit !== props.unit) props.onUnit(place.unit);
        }}
        onClose={() => setSheetOpen(false)}
      />
    </View>
  );
}

/** Whether an ISO timestamp falls within the last *days* days (local calendar dates, today included). */
export function withinLastDays(value: string | null | undefined, days: number, now: Date = new Date()): boolean {
  const day = localDate(value);
  return Boolean(day) && day! >= formatLocal(new Date(now.getFullYear(), now.getMonth(), now.getDate() - (days - 1)));
}

/** A placeholder unit the server names for a sites-mode project; never shown. */
export function isInternalPlaceholderUnit(name: string | null | undefined): boolean {
  return !name || /^sites_in_project_/i.test(name.trim());
}

type UnitInfo = { code: string; name: string; path: string; breadcrumb: string };
export type OrgLookup = { byId: Map<string, UnitInfo>; byName: Map<string, UnitInfo> };
/** One row's unit for the area filter: its id and the name the row carries. */
export type RowUnit = { id?: string | null; name?: string | null };

/**
 * The Area filter of a case list: unit lookup (with breadcrumbs for search),
 * the options (units holding a listed row, and their ancestors), and the
 * matcher for a chosen option (that unit's subtree, or any of the user's own
 * field areas for "Within area"). *projects* is the access summary,
 * *context* adds units it does not list; *project* narrows the options.
 */
export function useAreaFilter(projects: AccessProject[] | undefined, context: IntakeContextEntry[] | undefined,
                              rows: RowUnit[], project?: string) {
  const orgLookup = useMemo<OrgLookup>(() => {
    const byId = new Map<string, UnitInfo>();
    const byName = new Map<string, UnitInfo>();
    const codeToName = new Map<string, string>();
    for (const proj of projects ?? []) {
      for (const u of proj.units ?? []) if (u.unit_code && u.unit_name) codeToName.set(u.unit_code, u.unit_name);
    }
    for (const entry of context ?? []) {
      for (const u of entry.org_units ?? []) if (u.unit_code && u.unit_name) codeToName.set(u.unit_code, u.unit_name);
    }
    const breadcrumb = (path: string, name: string) => {
      const parts = path.split(".").filter(Boolean);
      return parts.length <= 1 ? name : parts.map((code) => codeToName.get(code) ?? code).join(" › ");
    };
    const add = (id: string, info: Omit<UnitInfo, "breadcrumb">) => {
      const full = { ...info, breadcrumb: breadcrumb(info.path, info.name) };
      byId.set(id, full);
      byName.set(info.name, full);
    };
    for (const proj of projects ?? []) {
      for (const u of proj.units ?? []) add(u.org_unit_id, { code: u.unit_code, name: u.unit_name, path: u.path });
    }
    for (const entry of context ?? []) {
      for (const u of entry.org_units ?? []) {
        if (byId.has(u.org_unit_id)) continue;
        const name = u.unit_name ?? u.unit_code ?? u.org_unit_id;
        add(u.org_unit_id, { code: u.unit_code ?? name, name, path: u.path ?? u.unit_code ?? name });
      }
    }
    return { byId, byName };
  }, [projects, context]);

  /** The units of the user's own field grants (and units they may report deaths in). */
  const withinAreaNames = useMemo(() => {
    const names = new Set<string>();
    for (const proj of projects ?? []) {
      for (const g of proj.grants ?? []) {
        if (g.active && ["interviewer", "death_reporter", "interview_supervisor"].includes(g.role) &&
            g.unit_name && !isInternalPlaceholderUnit(g.unit_name)) names.add(g.unit_name);
      }
      for (const u of proj.units ?? []) {
        if ((u as { can_register_death?: boolean }).can_register_death && u.unit_name && !isInternalPlaceholderUnit(u.unit_name)) names.add(u.unit_name);
      }
    }
    return names;
  }, [projects]);

  const rowUnits = useMemo(() => rows.map((row) => {
    const info = (row.id ? orgLookup.byId.get(row.id) : undefined) ?? (row.name ? orgLookup.byName.get(row.name.trim()) : undefined);
    return { name: (info?.name ?? row.name ?? "").trim(), path: info?.path };
  }), [orgLookup, rows]);

  const unitOptions = useMemo(() => {
    const names = new Set<string>();
    const paths = rowUnits.map((row) => row.path).filter((path): path is string => Boolean(path));
    for (const proj of projects ?? []) {
      if (project && proj.project_id !== project) continue;
      for (const u of proj.units ?? []) {
        if (u.selectable !== false && u.unit_name && !isInternalPlaceholderUnit(u.unit_name) && u.path &&
            paths.some((p) => p === u.path || p.startsWith(`${u.path}.`))) names.add(u.unit_name);
      }
    }
    for (const row of rowUnits) if (row.name && !isInternalPlaceholderUnit(row.name)) names.add(row.name);
    return Array.from(names);
  }, [projects, project, rowUnits]);

  /** Whether a row's unit sits in the chosen area: that unit or its subtree, or any of the user's own areas. */
  const unitMatches = useCallback((unit: string | undefined, orgUnitId: string | null | undefined, unitName: string) => {
    if (!unit) return true;
    const rowInfo = (orgUnitId ? orgLookup.byId.get(orgUnitId) : undefined) ?? orgLookup.byName.get(unitName);
    const areas = unit === WITHIN_AREA
      ? (withinAreaNames.size > 0 ? Array.from(withinAreaNames) : unitOptions.slice(0, 1))
      : [unit];
    return areas.some((areaName) => {
      if (unitName === areaName) return true;
      const areaInfo = orgLookup.byName.get(areaName);
      return Boolean(rowInfo?.path && areaInfo?.path && (rowInfo.path === areaInfo.path || rowInfo.path.startsWith(`${areaInfo.path}.`)));
    });
  }, [orgLookup, unitOptions, withinAreaNames]);

  return { orgLookup, unitOptions, unitMatches };
}
