/**
 * The Code and Review queues' "Sort and filter" choices (docs/policy/case-list-views.md "Code and Review queue sort and
 * filter"): their model, the server parameters they become, the applied-filter chips and the panel (a right side panel
 * on a wide screen, a bottom sheet on a phone). Every choice is a server parameter; nothing here filters loaded rows.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { radius, spacing, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { Select, type SelectOption } from "../ui/Select";
import { ChipGroup, FilterPanel, useFilterStyles } from "../web/caseFilters";
import type { QueueAgeGroup, QueueFilterParams, QueueSort } from "./api";
import { languageLabel } from "./codingLanguages";
import { DateField } from "./doris/DateField";
import { formatCardDate } from "./caseLabel";

/** The panel's choices other than project and place (those are the screen's own state). "" / [] = not set. */
export type QueueFilters = {
  sort?: QueueSort;
  state: string[];
  sex?: "female" | "male";
  ageGroup: QueueAgeGroup[];
  language: string[];
  interviewedFrom: string;
  interviewedTo: string;
  interviewer: string;
  /** My coded cases only: the cases the Recode button is offered on. */
  recodeable: boolean;
};

const DATE_FIELD = { flexBasis: 200, flexGrow: 1 } as const;
export const EMPTY_FILTERS: QueueFilters = { state: [], ageGroup: [], language: [], interviewedFrom: "", interviewedTo: "", interviewer: "", recodeable: false };

export const QUEUE_SORTS: QueueSort[] = ["interviewed_asc", "interviewed_desc", "age_asc", "age_desc"];
export const AGE_GROUPS: QueueAgeGroup[] = ["neonate", "child", "adult"];
const STATE_LABELS: Record<string, StringKey> = { coded: "queuePillCoded", recoded: "queuePillRecoded", not_codeable: "queuePillNotCodeable" };

/**
 * The state pills a list filters on (owner 2026-11-27): My coded cases and Available to review only. Coding Available
 * and Reviewed by me show one pill on every row, so they have none, and the server refuses any `state` there.
 */
export function queueStates(mode: "coding" | "reviewing", history: boolean): string[] {
  if (mode === "coding") return history ? ["coded", "recoded", "not_codeable"] : [];
  return history ? [] : ["coded", "recoded"];
}

/** The caller's coding languages from a stats answer (`languages.mine`); undefined while no stats are in. */
export function myLanguages(stats: { languages?: unknown } | undefined): string[] | undefined {
  if (!stats) return undefined;
  const mine = stats.languages && typeof stats.languages === "object" ? (stats.languages as { mine?: unknown }).mine : undefined;
  return Array.isArray(mine) ? mine.filter((code): code is string => typeof code === "string") : [];
}

/**
 * What the shown list accepts: its *states*, the user's *languages* (undefined: not known yet, the chosen ones are kept,
 * they came from the same user's list) and whether the Interviewer field is offered.
 */
export type FilterReach = { states: string[]; languages?: string[]; interviewer: boolean; recodeable: boolean };

/** *filters* without the values the shown list does not accept, so a tab or project change never sends one (a 400). */
export function fitFilters(filters: QueueFilters, reach: FilterReach): QueueFilters {
  const languages = reach.languages;
  return {
    ...filters,
    state: filters.state.filter((state) => reach.states.includes(state)),
    language: languages ? filters.language.filter((code) => languages.includes(code)) : filters.language,
    interviewer: reach.interviewer ? filters.interviewer : "",
    recodeable: reach.recodeable && filters.recodeable,
  };
}

/** The server parameters of *filters* and the search *q*: only the set ones, so an unfiltered list asks exactly as before. */
export function filterParams(filters: QueueFilters, q = ""): QueueFilterParams {
  const interviewer = filters.interviewer.trim();
  return {
    ...(filters.sort ? { sort: filters.sort } : {}),
    ...(filters.state.length ? { state: filters.state } : {}),
    ...(filters.sex ? { sex: filters.sex } : {}),
    ...(filters.ageGroup.length ? { ageGroup: filters.ageGroup } : {}),
    ...(filters.language.length ? { language: filters.language } : {}),
    ...(filters.interviewedFrom ? { interviewedFrom: filters.interviewedFrom } : {}),
    ...(filters.interviewedTo ? { interviewedTo: filters.interviewedTo } : {}),
    ...(interviewer ? { interviewer } : {}),
    ...(filters.recodeable ? { recodeable: "1" as const } : {}),
    ...(q ? { q } : {}),
  };
}

const toggled = <T,>(values: T[], value: T): T[] => (values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);

export type FilterChip = { key: string; label: string; clear: () => void };

/** One removable chip per applied filter (sort is not a filter: it has no chip and no count). *apply* sets the next filters. */
export function filterChips(filters: QueueFilters, apply: (next: QueueFilters) => void): FilterChip[] {
  const chips: FilterChip[] = [];
  for (const state of filters.state) chips.push({ key: `state:${state}`, label: t(STATE_LABELS[state] ?? "queuePillCoded"), clear: () => apply({ ...filters, state: toggled(filters.state, state) }) });
  if (filters.sex) chips.push({ key: "sex", label: t(filters.sex === "female" ? "sexFemale" : "sexMale"), clear: () => apply({ ...filters, sex: undefined }) });
  for (const group of filters.ageGroup) chips.push({ key: `age:${group}`, label: t(`queueAgeShort_${group}`), clear: () => apply({ ...filters, ageGroup: toggled(filters.ageGroup, group) }) });
  for (const code of filters.language) chips.push({ key: `language:${code}`, label: languageLabel(code), clear: () => apply({ ...filters, language: toggled(filters.language, code) }) });
  const from = formatCardDate(filters.interviewedFrom) ?? filters.interviewedFrom;
  const to = formatCardDate(filters.interviewedTo) ?? filters.interviewedTo;
  if (from || to) {
    const label = from && to ? t("queueChipInterviewed", { from, to }) : from ? t("queueChipInterviewedFrom", { date: from }) : t("queueChipInterviewedTo", { date: to });
    chips.push({ key: "interviewed", label, clear: () => apply({ ...filters, interviewedFrom: "", interviewedTo: "" }) });
  }
  if (filters.interviewer.trim()) chips.push({ key: "interviewer", label: t("queueInterviewer", { name: filters.interviewer.trim() }), clear: () => apply({ ...filters, interviewer: "" }) });
  if (filters.recodeable) chips.push({ key: "recodeable", label: t("queueRecodeableOnly"), clear: () => apply({ ...filters, recodeable: false }) });
  return chips;
}

/** No coding languages: the queues show nothing to code or review, so say so and offer the languages editor (text alone without one). */
export function NoLanguages({ onChoose }: { onChoose?: () => void }) {
  const styles = useUiStyles();
  const { colors } = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.xs }} testID="no-languages">
      <Text style={styles.muted}>{t("queueNoLanguages")}</Text>
      {onChoose ? (
        <Pressable accessibilityRole="button" accessibilityLabel={t("queueChooseLanguages")} onPress={onChoose} hitSlop={12}
          style={{ minHeight: 44, justifyContent: "center" }} testID="choose-languages">
          <Text style={[styles.muted, { color: colors.accent, fontWeight: "600" }]}>{t("queueChooseLanguages")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** Multi-select chips; *all* (when given) is the first chip, selected while nothing is chosen, and clears the choice. */
function MultiChips<K extends string>({ section, options, values, onChange, all }: {
  section: string;
  options: { key: K; label: string }[];
  values: K[];
  onChange: (next: K[]) => void;
  all?: string;
}) {
  const s = useFilterStyles();
  const chip = (key: string, label: string, on: boolean, press: () => void) => (
    <Pressable key={key} accessibilityRole="button" accessibilityLabel={t("queueChoiceLabel", { section, label })} accessibilityState={{ selected: on }}
      hitSlop={spacing.xs} onPress={press} style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </Pressable>
  );
  return (
    <View style={s.chipRow}>
      {all ? chip("", all, values.length === 0, () => onChange([])) : null}
      {options.map((option) => chip(option.key, option.label, values.includes(option.key), () => onChange(toggled(values, option.key))))}
    </View>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const s = useFilterStyles();
  return (
    <View style={s.section}>
      <Text style={s.sectionTitle} accessibilityRole="header">{title}</Text>
      <View style={s.group}>{children}</View>
    </View>
  );
}

/**
 * The Sort and filter panel. Edits stay a draft until "Show N cases" (or Clear all, which empties the draft); N is
 * *countCases* for the draft, asked 300 ms after the last edit while the panel is open (a stale answer is dropped;
 * none known shows "Show cases"). Project is *projectControl*, the screen's own picker (it applies at once and clears
 * the draft place). Sections without choices are left out: Site and unit without *placeOptions*, Workflow state on a
 * list without *states*, Language while the user's *languages* are not known, Interviewer unless *interviewer*. A user
 * with no languages gets the No languages line and the editor (*onEditLanguages*) in Language instead of chips.
 */
export function QueueFilterPanel({ open, onClose, value, place, projectId, projectControl, placeOptions, states, languages, onEditLanguages, interviewer, recodeable, phone, countKey, countCases, onApply }: {
  open: boolean;
  onClose: () => void;
  value: QueueFilters;
  place: string;
  projectId?: string;
  projectControl: ReactNode;
  placeOptions?: SelectOption[];
  states: string[];
  languages?: string[];
  onEditLanguages?: () => void;
  interviewer: boolean;
  /** Offer the Recodeable only toggle (Coding, My coded cases). */
  recodeable: boolean;
  phone: boolean;
  /** Changes when the list the count is for changes (mode, project, tab, search). */
  countKey: string;
  countCases: (draft: QueueFilters, place: string) => Promise<number | undefined>;
  onApply: (next: QueueFilters, place: string) => void;
}) {
  const s = useFilterStyles();
  const { colors } = useTheme();
  const [draft, setDraft] = useState(value);
  const [draftPlace, setDraftPlace] = useState(place);
  const [count, setCount] = useState<number | undefined>(undefined);
  const counter = useRef(countCases);
  counter.current = countCases;
  useEffect(() => {
    if (!open) return;
    setDraft(value);
    setDraftPlace(place);
  }, [open]);
  // The project applies at once (the global picker); the draft place belonged to the project before.
  const shownProject = useRef(projectId);
  useEffect(() => {
    if (shownProject.current === projectId) return;
    shownProject.current = projectId;
    setDraftPlace("");
  }, [projectId]);
  const draftKey = JSON.stringify([draft, draftPlace, countKey]);
  useEffect(() => {
    if (!open) return undefined;
    let live = true;
    setCount(undefined);
    const timer = setTimeout(() => {
      void counter.current(draft, draftPlace).then((n) => { if (live) setCount(n); }, () => undefined);
    }, 300);
    return () => { live = false; clearTimeout(timer); };
  }, [open, draftKey]);
  if (!open) return null;
  const set = (patch: Partial<QueueFilters>) => setDraft((previous) => ({ ...previous, ...patch }));
  const backwards = Boolean(draft.interviewedFrom && draft.interviewedTo && draft.interviewedFrom > draft.interviewedTo);
  return (
    <FilterPanel open title={t("queuePanelTitle")} onClose={onClose} footer={(
      <>
        <Button kind="secondary" label={t("clearAll")} onPress={() => { setDraft(EMPTY_FILTERS); setDraftPlace(""); }} />
        <Button label={count === undefined ? t("queueShowCasesUnknown") : count === 1 ? t("queueShowCasesOne") : t("queueShowCases", { n: count })} disabled={backwards}
          onPress={() => { onApply(draft, draftPlace); onClose(); }} />
      </>
    )}>
      <Section title={t("queueSectionSort")}>
        {QUEUE_SORTS.map((sort) => {
          const on = draft.sort === sort;
          return (
            <Pressable key={sort} accessibilityRole="radio" accessibilityLabel={t(`queueSort_${sort}`)} accessibilityState={{ checked: on }}
              onPress={() => set({ sort })} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44 }}>
              <View style={{ width: 20, height: 20, borderRadius: radius.full, borderWidth: 2, borderColor: on ? colors.accent : colors.border, alignItems: "center", justifyContent: "center" }}>
                {on ? <View style={{ width: 10, height: 10, borderRadius: radius.full, backgroundColor: colors.accent }} /> : null}
              </View>
              <Text style={s.advancedText}>{t(`queueSort_${sort}`)}</Text>
            </Pressable>
          );
        })}
      </Section>
      {projectControl ? <Section title={t("filterProject")}>{projectControl}</Section> : null}
      {placeOptions?.length ? (
        <Section title={t("chooseSite")}>
          <Select label={t("chooseSite")} placeholder={t("filterAllAreas")} searchLabel={t("filterUnitSearch")} searchable
            options={[{ value: "", label: t("filterAllAreas") }, ...placeOptions]} value={draftPlace} onChange={setDraftPlace} />
        </Section>
      ) : null}
      {states.length ? (
        <Section title={t("queueSectionState")}>
          <MultiChips section={t("queueSectionState")} options={states.map((state) => ({ key: state, label: t(STATE_LABELS[state] ?? "queuePillCoded") }))}
            values={draft.state} onChange={(state) => set({ state })} />
          {recodeable ? (
            <View style={s.chipRow}>
              <Pressable accessibilityRole="button" accessibilityLabel={t("queueRecodeableOnly")} accessibilityState={{ selected: draft.recodeable }}
                hitSlop={spacing.xs} onPress={() => set({ recodeable: !draft.recodeable })} style={[s.chip, draft.recodeable && s.chipOn]}>
                <Text style={[s.chipText, draft.recodeable && s.chipTextOn]}>{t("queueRecodeableOnly")}</Text>
              </Pressable>
            </View>
          ) : null}
        </Section>
      ) : null}
      <Section title={t("filterSex")}>
        <ChipGroup<"" | "female" | "male">
          options={[{ key: "", label: t("filterAll") }, { key: "female", label: t("sexFemale") }, { key: "male", label: t("sexMale") }]}
          value={draft.sex ?? ""} onChange={(sex) => set({ sex: sex || undefined })} a11yLabel={(label) => t("filterSexLabel", { label })} />
      </Section>
      <Section title={t("queueSectionAge")}>
        <MultiChips section={t("queueSectionAge")} options={AGE_GROUPS.map((group) => ({ key: group, label: t(phone ? `queueAgeShort_${group}` : `queueAge_${group}`) }))}
          values={draft.ageGroup} onChange={(ageGroup) => set({ ageGroup })} />
      </Section>
      {languages?.length === 0 ? (
        <Section title={t("queueSectionLanguage")}>
          <NoLanguages onChoose={onEditLanguages ? () => { onClose(); onEditLanguages(); } : undefined} />
        </Section>
      ) : languages ? (
        <Section title={t("queueSectionLanguage")}>
          <MultiChips section={t("queueSectionLanguage")} all={t(phone ? "queueAllMine" : "queueAllMyLanguages")}
            options={languages.map((code) => ({ key: code, label: languageLabel(code) }))} values={draft.language} onChange={(language) => set({ language })} />
        </Section>
      ) : null}
      <Section title={t("queueSectionInterviewed")}>
        {/* A date field needs ~200px (input plus calendar button): the pair wraps in a narrow panel. */}
        <View style={[s.pair, { flexWrap: "wrap" }]}>
          <View style={[s.pairField, DATE_FIELD]}>
            <Text style={s.fieldLabel}>{t("queueInterviewedFrom")}</Text>
            <DateField label={`${t("queueSectionInterviewed")} ${t("queueInterviewedFrom")}`} value={draft.interviewedFrom} onChange={(interviewedFrom) => set({ interviewedFrom })} />
          </View>
          <View style={[s.pairField, DATE_FIELD]}>
            <Text style={s.fieldLabel}>{t("queueInterviewedTo")}</Text>
            <DateField label={`${t("queueSectionInterviewed")} ${t("queueInterviewedTo")}`} value={draft.interviewedTo} onChange={(interviewedTo) => set({ interviewedTo })} />
          </View>
        </View>
        {/* The phone's date picker has no clear of its own. */}
        {draft.interviewedFrom || draft.interviewedTo ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t("queueClearDates")} hitSlop={spacing.xs} onPress={() => set({ interviewedFrom: "", interviewedTo: "" })}
            style={{ minHeight: 44, justifyContent: "center", alignSelf: "flex-start" }}>
            <Text style={s.linkText}>{t("queueClearDates")}</Text>
          </Pressable>
        ) : null}
      </Section>
      {interviewer ? (
        <Section title={t("queueSectionInterviewer")}>
          <TextInput accessibilityLabel={t("queueSectionInterviewer")} placeholder={t("queueInterviewerPlaceholder")} placeholderTextColor={colors.textMuted}
            maxLength={128} value={draft.interviewer} onChangeText={(next) => set({ interviewer: next })} style={[s.searchInput, { flex: undefined }]} />
        </Section>
      ) : null}
    </FilterPanel>
  );
}
