import { createElement, useEffect, useMemo, useState, type ReactNode } from "react";
import { Text, View } from "react-native";

import {
  getDmCoderDaily, getDmDemographics, getDmSiteSubmissions,
  type DmCoderDaily, type DmDemographics, type DmFilterOptions, type DmSiteSubmissions,
} from "../../data/api";
import { countApiParams, exportApiParams, matchGender, type Filters } from "../../data/query";
import { t, type StringKey } from "../../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";
import type { JsonRequester } from "../../workspace/api";
import { browserErrorText } from "../common";
import { StatPressable, TextAction } from "../stats/controls";
import { workflowLabel } from "./DataFilters";

const SITE_ROWS = 10;

interface BarRow {
  key: string;
  label: string;
  value: number;
  detail?: string;
  onPick?: () => void;
}

/** Rows as proportional bars; the number and its detail are always written out. A row with *onPick* is a button that filters the list. */
function Bars({ rows }: { rows: BarRow[] }) {
  const { ui } = useTheme();
  const top = rows.reduce((max, row) => Math.max(max, row.value), 0);
  return (
    <View>
      {rows.map((row) => {
        const body = (
          <View style={{ gap: 2, paddingVertical: spacing.xxs }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.sm }}>
              <Text style={{ flexShrink: 1, fontSize: fontSize.body, color: ui.foreground }}>{row.label}</Text>
              <Text style={{ fontSize: fontSize.body, fontWeight: "600", color: ui.foreground }}>{row.value.toLocaleString()}</Text>
            </View>
            <View importantForAccessibility="no-hide-descendants" accessibilityElementsHidden style={{ height: 6, borderRadius: radius.sm, backgroundColor: ui.secondary, overflow: "hidden" }}>
              <View style={{ width: `${top > 0 ? Math.max(row.value > 0 ? 1 : 0, Math.round((100 * row.value) / top)) : 0}%`, height: 6, backgroundColor: ui.primary }} />
            </View>
            {row.detail ? <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{row.detail}</Text> : null}
          </View>
        );
        const spoken = `${row.label}: ${row.value}${row.detail ? `, ${row.detail}` : ""}`;
        return row.onPick ? (
          <StatPressable key={row.key} label={t("dataPanelFilterBy", { row: spoken })} onPress={row.onPick}>{body}</StatPressable>
        ) : (
          <View key={row.key} accessible accessibilityLabel={spoken}>{body}</View>
        );
      })}
    </View>
  );
}

function Panel({ title, state, children }: { title: string; state: "loading" | "failed" | "empty" | "ready"; children?: ReactNode }) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xs, flexGrow: 1, flexBasis: 280, minWidth: 0 }}>
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{title}</Text>
      {state === "loading" ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("loading")}</Text> : null}
      {state === "failed" ? <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{t("dataPanelFailed")}</Text> : null}
      {state === "empty" ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("dataPanelEmpty")}</Text> : null}
      {state === "ready" ? children : null}
    </View>
  );
}

/** One fetch per panel, redone when the filters or *reload* change; a failure is local to its panel. */
function useFetched<T>(request: JsonRequester, load: (request: JsonRequester) => Promise<T>, key: string, reload: number) {
  const [state, setState] = useState<{ key: string; data?: T; failed?: string } | null>(null);
  useEffect(() => {
    let active = true;
    load(request)
      .then((data) => {
        if (active) setState({ key, data });
      })
      .catch((caught) => {
        if (active) setState({ key, failed: browserErrorText(caught) });
      });
    return () => {
      active = false;
    };
    // load is rebuilt each render; key stands for everything it closes over.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, key, reload]);
  const current = state?.key === key ? state : null;
  return { data: current?.data, failed: Boolean(current?.failed), loading: !current };
}

/** Submissions by site (or by unit for a project with a tree). A row sets the site or unit filter. */
function SitePanel({ request, filters, tree, reload, onFilter }: { request: JsonRequester; filters: Filters; tree: boolean; reload: number; onFilter: (patch: Partial<Filters>) => void }) {
  const params = { ...countApiParams(filters), ...(tree ? { group_by: "org_unit" } : {}) };
  const key = JSON.stringify(params);
  const { data, failed, loading } = useFetched<DmSiteSubmissions>(request, (r) => getDmSiteSubmissions(r, params), key, reload);
  const [all, setAll] = useState(false);
  const rows: BarRow[] = useMemo(() => {
    if (!data) return [];
    const sorted = data.group_by === "org_unit"
      ? data.stats.map((unit): BarRow => ({ key: unit.org_unit_id, label: `${unit.org_unit_code} ${unit.org_unit_name}`.trim(), value: unit.total_submissions, onPick: () => onFilter({ org_unit: unit.org_unit_id }) }))
      : data.stats.map((site): BarRow => ({
        key: `${site.project_id}:${site.site_id}`, label: site.site_id, value: site.total_submissions,
        detail: t("dataSiteDetail", { week: site.this_week_submissions, today: site.today_submissions }),
        onPick: () => onFilter({ site: site.site_id }),
      }));
    return sorted.sort((a, b) => b.value - a.value);
  }, [data, onFilter]);
  const shown = all ? rows : rows.slice(0, SITE_ROWS);
  return (
    <Panel title={t("dataPanelSites")} state={failed ? "failed" : loading ? "loading" : rows.length ? "ready" : "empty"}>
      <Bars rows={shown} />
      {rows.length > SITE_ROWS ? <TextAction small label={t(all ? "dataShowFewer" : "dataShowAll", { count: rows.length })} onPress={() => setAll((current) => !current)} /> : null}
    </Panel>
  );
}

function DemographicsPanel({ request, filters, genders, reload, onFilter }: { request: JsonRequester; filters: Filters; genders: string[]; reload: number; onFilter: (patch: Partial<Filters>) => void }) {
  const params = countApiParams(filters);
  const key = JSON.stringify(params);
  const { data, failed, loading } = useFetched<DmDemographics>(request, (r) => getDmDemographics(r, params), key, reload);
  const bands = (data?.age_bands ?? []).filter((row) => row.count > 0);
  const sexes = (data?.sex ?? []).filter((row) => row.count > 0);
  return (
    <Panel title={t("dataPanelDemographics")} state={failed ? "failed" : loading ? "loading" : bands.length || sexes.length ? "ready" : "empty"}>
      <Text style={{ ...typography.subhead, fontWeight: "600" }}>{t("dataFilterAge")}</Text>
      <Bars rows={bands.map((row) => ({
        key: row.band ?? "unknown",
        label: t(`dataAge_${row.band ?? "unknown"}` as StringKey),
        value: row.count,
        onPick: row.band ? () => onFilter({ age_group: row.band! }) : undefined,
      }))} />
      <Text style={{ ...typography.subhead, fontWeight: "600" }}>{t("dataFilterGender")}</Text>
      <Bars rows={sexes.map((row) => {
        const gender = matchGender(genders, row.sex);
        return { key: row.sex ?? "unknown", label: row.sex ?? t("dataAge_unknown"), value: row.count, onPick: gender ? () => onFilter({ gender }) : undefined };
      })} />
    </Panel>
  );
}

function WorkflowPanel({ counts, onFilter }: { counts: Record<string, number> | null; onFilter: (patch: Partial<Filters>) => void }) {
  const rows = Object.entries(counts ?? {}).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);
  return (
    <Panel title={t("dataPanelWorkflow")} state={counts === null ? "loading" : rows.length ? "ready" : "empty"}>
      <Bars rows={rows.map(([state, count]) => ({ key: state, label: workflowLabel(state), value: count, onPick: () => onFilter({ workflow: state }) }))} />
    </Panel>
  );
}

/** Finalisations per coder over the last seven days. A name narrows the list to that coder (kept out of the URL). */
function CoderPanel({ request, filters, reload, onCoder }: { request: JsonRequester; filters: Filters; reload: number; onCoder: (name: string) => void }) {
  const { ui } = useTheme();
  const params = exportApiParams(filters);
  const key = JSON.stringify(params);
  const { data, failed, loading } = useFetched<DmCoderDaily>(request, (r) => getDmCoderDaily(r, params), key, reload);
  const cell = { padding: `${spacing.xxs}px ${spacing.xs}px`, borderBottom: `1px solid ${ui.border}`, textAlign: "right", fontSize: fontSize.body, color: ui.foreground } as const;
  return (
    <Panel title={t("dataPanelCoders")} state={failed ? "failed" : loading ? "loading" : data?.rows.length ? "ready" : "empty"}>
      {data ? (
        <>
          <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataCodersWindow", { days: data.window_days, zone: data.timezone })}</Text>
          {createElement(
            "div",
            { role: "region", tabIndex: 0, "aria-label": t("dataPanelCoders"), style: { overflowX: "auto", maxWidth: "100%" } },
            createElement(
              "table",
              { style: { borderCollapse: "collapse", fontFamily: controls.fontFamily } },
              createElement("thead", null, createElement(
                "tr",
                null,
                createElement("th", { scope: "col", style: { ...cell, textAlign: "left", fontWeight: 600 } }, t("dataColCoder")),
                ...data.dates.map((date) => createElement("th", { key: date.iso, scope: "col", style: { ...cell, fontWeight: 600, whiteSpace: "nowrap" } }, date.label)),
                createElement("th", { scope: "col", style: { ...cell, fontWeight: 600 } }, t("dataColTotal")),
                createElement("th", { scope: "col", style: { ...cell, fontWeight: 600 } }, t("dataColCumulative")),
              )),
              createElement("tbody", null, ...data.rows.map((row, index) => {
                const name = row.coder_name || t("dataCoderUnknown");
                return createElement(
                  "tr",
                  { key: `${name}:${index}` },
                  createElement("th", { scope: "row", style: { ...cell, textAlign: "left", fontWeight: 400 } }, row.coder_name
                    ? <StatPressable label={t("dataCoderSearch", { name })} onPress={() => onCoder(name)} style={{ minHeight: 32, justifyContent: "center" }}><Text style={{ fontSize: fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{name}</Text></StatPressable>
                    : name),
                  ...data.dates.map((date) => createElement("td", { key: date.iso, style: cell }, String(row.daily?.[date.iso] ?? 0))),
                  createElement("td", { style: { ...cell, fontWeight: 600 } }, String(row.window_total ?? 0)),
                  createElement("td", { style: { ...cell, fontWeight: 600 } }, String(row.cumulative_total ?? 0)),
                );
              })),
            ),
          )}
        </>
      ) : null}
    </Panel>
  );
}

/**
 * The side panels of a data manager (they would answer 403 to a viewer, so the screen never mounts them for one):
 * submissions by site or unit, age and sex, workflow distribution and the coders' last seven days. Each fetches on
 * its own and shows its own failure. Every row is a filter or a search on the list.
 */
export function DataPanels({ request, filters, options, treeProjects, workflowCounts, reload, onFilter, onCoder }: {
  request: JsonRequester;
  filters: Filters;
  options: DmFilterOptions | null;
  /** Project ids that have an organization tree: a single such project groups its sites by unit. */
  treeProjects: string[];
  workflowCounts: Record<string, number> | null;
  reload: number;
  onFilter: (patch: Partial<Filters>) => void;
  /** A coder's name was clicked: the screen keeps it as a removable list filter outside the URL. */
  onCoder: (name: string) => void;
}) {
  const single = filters.project && !filters.project.includes(",") ? filters.project : "";
  const tree = Boolean(single && treeProjects.includes(single));
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.lg, alignItems: "flex-start" }}>
      <SitePanel request={request} filters={filters} tree={tree} reload={reload} onFilter={onFilter} />
      <DemographicsPanel request={request} filters={filters} genders={options?.genders ?? []} reload={reload} onFilter={onFilter} />
      <WorkflowPanel counts={workflowCounts} onFilter={onFilter} />
      <CoderPanel request={request} filters={filters} reload={reload} onCoder={onCoder} />
    </View>
  );
}
