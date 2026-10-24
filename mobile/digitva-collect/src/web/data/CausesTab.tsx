import { createElement, useEffect, useMemo, useState, type ReactNode } from "react";
import { Text, View } from "react-native";

import { ClientApiError } from "../../client/api";
import { codExportUrl, getCodAggregates, getCodSchemes, type CodAggregates, type CodScheme, type DmFilterOptions } from "../../data/api";
import {
  ageKey, ageSexTotals, CAUSES_ERROR_CODES, causesApiParams, groupsFor, scopeSections, topCausesFor,
  type CauseNode, type CausesQuery, type ScopeSection,
} from "../../data/causes";
import { t, type StringKey } from "../../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";
import type { JsonRequester } from "../../workspace/api";
import { browserErrorText } from "../common";
import { ChoiceRow, SelectRow, StatPressable, TextAction } from "../stats/controls";
import { formatPercent } from "../stats/pipeline";
import { DateInput } from "./DataFilters";

/** A refusal the tab words itself (400 with a known code); anything else gets the app's generic text. */
export function causesErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.status === 400 && (CAUSES_ERROR_CODES as readonly string[]).includes(error.code ?? "")) {
    return t(`causesErr_${error.code}` as StringKey);
  }
  return browserErrorText(error);
}

const capital = (value: string) => `${value.charAt(0).toUpperCase()}${value.slice(1)}`;

/** Share bars, the same drawing as the Statistics causes: label and "n · %" written out, the bar proportional to the share. */
function BarList({ rows }: { rows: { key: string; label: string; count: number; percent: number; rank?: number }[] }) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      {rows.map((row) => (
        <View key={row.key} accessible accessibilityLabel={t("causesCauseRow", { label: row.label, count: row.count, percent: formatPercent(row.percent) })} style={{ gap: spacing.xxs }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.sm }}>
            <Text style={{ flex: 1, fontSize: fontSize.body, color: ui.foreground }}>{row.rank ? `${row.rank}. ${row.label}` : row.label}</Text>
            <Text style={{ fontSize: fontSize.body, color: ui.foreground }}>{`${row.count.toLocaleString()} · ${formatPercent(row.percent)}%`}</Text>
          </View>
          <View style={{ height: 6, borderRadius: radius.sm, backgroundColor: ui.secondary, overflow: "hidden" }}>
            <View style={{ width: `${Math.max(1, Math.min(100, row.percent))}%`, height: 6, backgroundColor: ui.primary }} />
          </View>
        </View>
      ))}
    </View>
  );
}

function Heading({ children }: { children: string }) {
  const { ui } = useTheme();
  return <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{children}</Text>;
}

function Empty() {
  const { ui } = useTheme();
  return <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("causesEmpty")}</Text>;
}

function Region({ label, children }: { label: string; children: ReactNode }) {
  return createElement("div", { role: "region", tabIndex: 0, "aria-label": label, style: { overflowX: "auto", maxWidth: "100%" } }, children);
}

function useCellStyle() {
  const { ui } = useTheme();
  return {
    head: { padding: `${spacing.xxs}px ${spacing.xs}px`, borderBottom: `1px solid ${ui.border}`, textAlign: "right", fontSize: fontSize.body, fontWeight: 600, color: ui.mutedForeground, whiteSpace: "nowrap" } as const,
    cell: { padding: `${spacing.xxs}px ${spacing.xs}px`, borderBottom: `1px solid ${ui.border}`, textAlign: "right", fontSize: fontSize.body, color: ui.foreground, whiteSpace: "nowrap" } as const,
  };
}

const LEFT = { textAlign: "left" } as const;

function AgeSexTable({ rows }: { rows: CodAggregates["summary"]["age_sex_distribution"] }) {
  const { ui } = useTheme();
  const { head, cell } = useCellStyle();
  const totals = ageSexTotals(rows);
  const th = (label: StringKey, extra = {}) => createElement("th", { scope: "col", style: { ...head, ...extra } }, t(label));
  const bold = { ...cell, fontWeight: 600 };
  return (
    <Region label={t("causesAgeSexHeading")}>
      {createElement(
        "table",
        { style: { borderCollapse: "collapse", fontFamily: controls.fontFamily, minWidth: 320 } },
        createElement("thead", null, createElement("tr", null, th("causesColAgeBand", LEFT), th("causesColMale"), th("causesColFemale"), th("causesColUnknown"), th("causesColTotal"))),
        createElement(
          "tbody",
          null,
          ...rows.map((row) => createElement(
            "tr",
            { key: row.age_band },
            createElement("th", { scope: "row", style: { ...cell, ...LEFT, fontWeight: 400 } }, row.age_band),
            createElement("td", { style: cell }, String(row.male_count ?? 0)),
            createElement("td", { style: cell }, String(row.female_count ?? 0)),
            createElement("td", { style: cell }, String(row.unknown_count ?? 0)),
            createElement("td", { style: cell }, `${row.total_count ?? 0} · ${formatPercent(row.total_percent ?? 0)}%`),
          )),
          createElement(
            "tr",
            { key: "total", style: { background: ui.secondary } },
            createElement("th", { scope: "row", style: { ...bold, ...LEFT } }, t("causesColTotal")),
            createElement("td", { style: bold }, String(totals.male)),
            createElement("td", { style: bold }, String(totals.female)),
            createElement("td", { style: bold }, String(totals.unknown)),
            createElement("td", { style: bold }, String(totals.total)),
          ),
        ),
      )}
    </Region>
  );
}

/** One age scope: its category > subcategory > disease rows, collapsed to categories until opened. */
function ScopeTable({ section, open, toggle }: { section: ScopeSection; open: Set<string>; toggle: (key: string) => void }) {
  const { ui } = useTheme();
  const { head, cell } = useCellStyle();
  const rows: ReactNode[] = [];
  const walk = (node: CauseNode) => {
    const key = `${section.key}|${node.key}`;
    const expanded = open.has(key);
    const pct = section.total ? ` · ${formatPercent((100 * node.total) / section.total)}%` : "";
    rows.push(createElement(
      "tr",
      { key },
      createElement(
        "th",
        { scope: "row", style: { ...cell, ...LEFT, whiteSpace: "normal", fontWeight: node.level === 0 ? 600 : 400, paddingLeft: spacing.xs + node.level * spacing.md } },
        node.children.length ? (
          <StatPressable label={t(expanded ? "causesCollapse" : "causesExpand", { label: node.label })} selected={expanded} onPress={() => toggle(key)} style={{ minHeight: 32, justifyContent: "center" }}>
            <Text style={{ fontSize: fontSize.body, fontWeight: node.level === 0 ? "600" : "400", color: ui.primary }}>{`${expanded ? "▾" : "▸"} ${node.label}`}</Text>
          </StatPressable>
        ) : node.label,
      ),
      createElement("td", { style: cell }, String(node.male)),
      createElement("td", { style: cell }, String(node.female)),
      createElement("td", { style: cell }, String(node.unknown)),
      createElement("td", { style: { ...cell, fontWeight: 600 } }, `${node.total}${pct}`),
    ));
    if (expanded) node.children.forEach(walk);
  };
  section.tree.forEach(walk);
  const th = (label: StringKey, extra = {}) => createElement("th", { scope: "col", style: { ...head, ...extra } }, t(label));
  return (
    <Region label={section.label}>
      {createElement(
        "table",
        { style: { borderCollapse: "collapse", fontFamily: controls.fontFamily, minWidth: 360, width: "100%" } },
        createElement("thead", null, createElement("tr", null, th("causesColGrouping", LEFT), th("causesColMale"), th("causesColFemale"), th("causesColUnknown"), th("causesColTotal"))),
        createElement("tbody", null, ...rows),
      )}
    </Region>
  );
}

const DROPPED_CATEGORIES = ["not_included_in_scheme", "not_eligible_for_coding", "icd11_not_included_in_scheme", "icd11_scheme_has_no_icd11_rows"] as const;

/** Deaths whose ICD matched no category, per age scope, behind a disclosure. */
function Dropped({ sections }: { sections: ScopeSection[] }) {
  const { ui } = useTheme();
  const { head, cell } = useCellStyle();
  const [shown, setShown] = useState(false);
  const count = sections.reduce((sum, section) => sum + section.unmatched, 0);
  if (!count) return null;
  return (
    <View style={{ gap: spacing.xs }}>
      <Heading>{t("causesDroppedHeading")}</Heading>
      <TextAction label={t(shown ? "causesDroppedHide" : "causesDroppedShow", { count })} onPress={() => setShown((now) => !now)} />
      {shown ? sections.filter((section) => section.unmatched).map((section) => (
        <View key={section.key} style={{ gap: spacing.xs }}>
          <Text style={{ ...typography.subhead, fontWeight: "600", color: ui.foreground }}>{section.label}</Text>
          {DROPPED_CATEGORIES.map((category) => {
            const rows = section.dropped.filter((row) => row.category === category);
            if (!rows.length && category.startsWith("icd11_")) return null;
            const title = t(`causesDropped_${category}` as StringKey);
            return (
              <View key={category} style={{ gap: spacing.xxs }}>
                <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{title}</Text>
                {rows.length ? (
                  <Region label={title}>
                    {createElement(
                      "table",
                      { style: { borderCollapse: "collapse", fontFamily: controls.fontFamily } },
                      createElement("thead", null, createElement("tr", null, createElement("th", { scope: "col", style: { ...head, ...LEFT } }, t("causesColIcd")), createElement("th", { scope: "col", style: head }, t("causesColCount")))),
                      createElement("tbody", null, ...rows.map((row, index) => createElement(
                        "tr",
                        { key: `${row.icd_code}:${index}` },
                        createElement("th", { scope: "row", style: { ...cell, ...LEFT, fontWeight: 400 } }, row.icd_code || "–"),
                        createElement("td", { style: cell }, String(row.unmatched_count ?? 0)),
                      ))),
                    )}
                  </Region>
                ) : <Text style={{ fontSize: fontSize.body, color: ui.mutedForeground }}>{t("causesDroppedNone")}</Text>}
              </View>
            );
          })}
        </View>
      )) : null}
    </View>
  );
}

/** A form id typed by hand (there is no list of forms to pick from); committed on Enter or blur so each key press is not a request. */
function FormInput({ value, onCommit }: { value: string; onCommit: (next: string) => void }) {
  const { ui } = useTheme();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft.trim() !== value && onCommit(draft.trim());
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("causesForm")}</Text>
      {createElement("input", {
        type: "text", "aria-label": t("causesForm"), value: draft, maxLength: 64,
        onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
        onBlur: commit,
        onKeyDown: (event: { key: string }) => event.key === "Enter" && commit(),
        style: { boxSizing: "border-box", minHeight: 44, width: 150, padding: `0 ${spacing.sm}px`, fontSize: fontSize.body, fontFamily: controls.fontFamily, color: ui.foreground, background: ui.background, border: `1px solid ${ui.input}`, borderRadius: radius.md },
      })}
    </View>
  );
}

/**
 * Data > Causes: the Expo successor of /data-management/cod-buckets for a data manager or admin, over
 * /api/v1/cod-buckets/*. The URL holds the filters (scheme, project, site, form, sex, dates) and the age choice; the
 * top-ten bars are the main element. The heatmap, treemap and age pyramid of the Flask page are not drawn here.
 */
export function CausesTab({ request, query, options, onQuery }: {
  request: JsonRequester;
  query: CausesQuery;
  options: DmFilterOptions | null;
  onQuery: (next: CausesQuery) => void;
}) {
  const { ui } = useTheme();
  const [schemes, setSchemes] = useState<CodScheme[]>([]);
  const [state, setState] = useState<{ key: string; data?: CodAggregates; error?: string } | null>(null);
  const [reload, setReload] = useState(0);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const params = causesApiParams(query);
  const key = JSON.stringify(params);

  useEffect(() => {
    let active = true;
    getCodSchemes(request).then((reply) => active && setSchemes(reply.data)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [request]);

  useEffect(() => {
    let active = true;
    getCodAggregates(request, JSON.parse(key))
      .then((data) => active && setState({ key, data }))
      .catch((caught) => active && setState({ key, error: causesErrorText(caught) }));
    return () => {
      active = false;
    };
  }, [request, key, reload]);

  const current = state?.key === key ? state : null;
  const data = current?.data;
  const sections = useMemo(() => (data ? scopeSections(data) : []), [data]);
  const age = data ? ageKey(query.age, data.summary.age_filters ?? []) : "all";
  const set = (patch: Partial<CausesQuery>) => onQuery({ ...query, ...patch });
  const all = { value: "", label: t("dataAll") };
  const sites = (options?.sites ?? []).filter((site) => !query.project || site.project_id === query.project);
  const schemeNow = query.scheme_code || data?.filters?.scheme_code || "";
  const genderNow = options?.genders.find((value) => value.toLowerCase() === query.gender.toLowerCase()) ?? query.gender;
  const scope = [
    query.project, query.site, query.form_id, query.date_from || query.date_to ? `${query.date_from || "…"} → ${query.date_to || "…"}` : "", query.gender && capital(query.gender),
  ].filter(Boolean).join(" / ") || t("causesScopeAll");
  const toggle = (rowKey: string) => setOpen((now) => {
    const next = new Set(now);
    if (!next.delete(rowKey)) next.add(rowKey);
    return next;
  });
  const top = data ? topCausesFor(data.summary, age) : [];
  const groups = data ? groupsFor(data.summary, age) : [];

  return (
    <View style={{ gap: spacing.lg }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, alignItems: "flex-end" }}>
        <View style={{ flexGrow: 1, flexBasis: 200 }}>
          <SelectRow
            label={t("causesScheme")}
            value={schemeNow}
            onChange={(next) => set({ scheme_code: next })}
            options={[
              ...(schemeNow && !schemes.some((scheme) => scheme.scheme_code === schemeNow) ? [{ value: schemeNow, label: schemeNow }] : []),
              ...schemes.map((scheme) => ({ value: scheme.scheme_code, label: scheme.scheme_name })),
            ]}
          />
        </View>
        {(options?.projects.length ?? 0) > 1 ? (
          <View style={{ flexGrow: 1, flexBasis: 160 }}>
            <SelectRow label={t("dataFilterProject")} value={query.project} onChange={(next) => set({ project: next, site: "" })} options={[all, ...(options?.projects ?? []).map((value) => ({ value, label: value }))]} />
          </View>
        ) : null}
        <View style={{ flexGrow: 1, flexBasis: 160 }}>
          <SelectRow label={t("dataFilterSite")} value={query.site} onChange={(next) => set({ site: next })} options={[all, ...[...new Set(sites.map((site) => site.site_id))].map((value) => ({ value, label: value }))]} />
        </View>
        <View style={{ flexGrow: 1, flexBasis: 140 }}>
          <SelectRow label={t("dataFilterGender")} value={genderNow} onChange={(next) => set({ gender: next })} options={[all, ...(options?.genders ?? []).map((value) => ({ value, label: capital(value) }))]} />
        </View>
        <FormInput value={query.form_id} onCommit={(next) => set({ form_id: next })} />
        <DateInput label={t("dataFilterDateFrom")} value={query.date_from} onChange={(next) => set({ date_from: next })} />
        <DateInput label={t("dataFilterDateTo")} value={query.date_to} onChange={(next) => set({ date_to: next })} />
      </View>

      {!current ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("loading")}</Text> : null}
      {current?.error ? (
        <View style={{ gap: spacing.xs }}>
          <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{current.error}</Text>
          <TextAction label={t("statsRetry")} onPress={() => setReload((count) => count + 1)} />
        </View>
      ) : null}

      {data ? (
        <>
          <Text accessibilityLiveRegion="polite" style={{ ...typography.subhead, color: ui.mutedForeground }}>
            {t("causesSummary", { coded: (data.summary.matched_total ?? 0).toLocaleString(), scheme: data.summary.scheme_used, scope })}
          </Text>
          {(data.summary.age_filters?.length ?? 0) > 1 ? (
            <ChoiceRow label={t("causesAgeFilter")} value={age} onChange={(next) => set({ age: next === "all" ? "" : next })} options={data.summary.age_filters.map((filter) => ({ value: filter.key, label: filter.label }))} />
          ) : null}

          <View style={{ gap: spacing.xs }}>
            <Heading>{t("causesTopHeading")}</Heading>
            {top.length ? <BarList rows={top.map((row) => ({ key: String(row.rank), label: row.display_label, count: row.coded_count, percent: row.percent, rank: row.rank }))} /> : <Empty />}
          </View>

          <View style={{ gap: spacing.xs }}>
            <Heading>{t("causesGroupsHeading")}</Heading>
            {groups.length ? <BarList rows={groups.map((row) => ({ key: row.label, label: row.label, count: row.coded_count, percent: row.percent }))} /> : <Empty />}
          </View>

          <View style={{ gap: spacing.xs }}>
            <Heading>{t("causesAgeSexHeading")}</Heading>
            {data.summary.age_sex_distribution?.length ? <AgeSexTable rows={data.summary.age_sex_distribution} /> : <Empty />}
          </View>

          <View style={{ gap: spacing.sm }}>
            <Heading>{t("causesCategoriesHeading")}</Heading>
            {sections.length ? sections.map((section) => (
              <View key={section.key} style={{ gap: spacing.xxs }}>
                <Text style={{ ...typography.subhead, fontWeight: "600", color: ui.foreground }}>{section.label}</Text>
                <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("causesScopeTotal", { total: section.total.toLocaleString() })}</Text>
                {section.tree.length ? <ScopeTable section={section} open={open} toggle={toggle} /> : null}
                {section.unmatched ? <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("causesUnmatched", { count: section.unmatched })}</Text> : null}
              </View>
            )) : <Empty />}
          </View>

          <Dropped sections={sections} />
        </>
      ) : null}

      <View style={{ gap: spacing.xxs }}>
        {createElement("a", { href: codExportUrl(params), style: { display: "inline-flex", alignItems: "center", minHeight: 44, alignSelf: "flex-start", fontSize: fontSize.body, color: ui.primary, fontFamily: controls.fontFamily } }, t("causesExport"))}
        <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("causesExportNote")}</Text>
      </View>
    </View>
  );
}
