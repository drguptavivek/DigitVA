import { useLocalSearchParams, useRouter } from "expo-router";
import { createElement, useCallback, useEffect, useMemo, useState } from "react";
import { Text, useWindowDimensions, View } from "react-native";

import { useAppState } from "../AppState";
import { ClientApiError } from "../client/api";
import { ConfirmDialog } from "../ConfirmDialog";
import {
  acceptUpstreamChange, cancelRevisionRequest, dmExportUrl, EXPORT_KINDS, getDmFilterOptions, getDmKpi, getDmSubmissions,
  getUpstreamChangeDetails, refreshDmAnalytics, rejectUpstreamChange,
  type DmFilterOptions, type DmKpi, type DmSubmissionRow, type DmSubmissionsPage, type ExportKind, type UpstreamChangeDetails,
} from "../data/api";
import { causesPatch, parseCausesQuery, type CausesQuery } from "../data/causes";
import {
  columnsFor, countApiParams, exportApiParams, isStaleResult, listApiParams, PAGE_SIZES, paramsPatch, parseDataQuery, visibleColumns, withCoder, withFilters,
  type ColumnKey, type DataQuery, type Filters,
} from "../data/query";
import { t, type StringKey } from "../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../theme";
import { Button } from "../ui";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { browserErrorText, WebShell } from "./common";
import { DataCards } from "./data/DataCards";
import { CausesTab } from "./data/CausesTab";
import { FilterChips, FilterPanel } from "./data/DataFilters";
import { DataPanels } from "./data/DataPanels";
import { columnLabel, DataCardList, DataTable, type RowAction } from "./data/DataTable";
import { UpstreamChangesDialog } from "./data/UpstreamChangesDialog";
import { dataAccess, openServerPage } from "./roleHome";
import { ChoiceRow, StatPressable, TextAction } from "./stats/controls";

const PHONE_BREAKPOINT = 768;
const TABS = ["overview", "causes"] as const;
type Tab = (typeof TABS)[number];
const COLUMNS_KEY = "digitva.data.columns.v1";
const EXPORT_LABELS: Record<ExportKind, StringKey> = {
  data: "dataExportData", coded_cod_snapshot: "dataExportCoded", smartva_input: "dataExportSmartvaInput",
  smartva_results: "dataExportSmartvaResults", smartva_likelihoods: "dataExportSmartvaLikelihoods",
};

/** The column choices this browser remembers (a convenience only: filters, sort and page are never stored). */
function readColumnChoices(): Partial<Record<ColumnKey, boolean>> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(COLUMNS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeColumnChoices(choices: Partial<Record<ColumnKey, boolean>>): void {
  try {
    window.localStorage.setItem(COLUMNS_KEY, JSON.stringify(choices));
  } catch {
    // Storage unavailable: the choice lasts until reload.
  }
}

type Decision = "accept" | "keep" | "cancel";
const DECISION_TEXT: Record<Decision, { title: StringKey; message: StringKey; confirm: StringKey; done: StringKey; destructive: boolean }> = {
  accept: { title: "dataConfirmAcceptTitle", message: "dataConfirmAcceptMessage", confirm: "dataChangesAccept", done: "dataDoneAccept", destructive: false },
  keep: { title: "dataConfirmKeepTitle", message: "dataConfirmKeepMessage", confirm: "dataChangesKeep", done: "dataDoneKeep", destructive: false },
  cancel: { title: "dataConfirmCancelTitle", message: "dataConfirmCancelMessage", confirm: "dataActionCancel", done: "dataDoneCancel", destructive: true },
};

/**
 * Data management: the data manager overview over /api/v1/data-management/*, the Expo successor of /data-management/
 * (Overview tab), and for a data manager or admin the Causes tab (CausesTab; `tab=causes` in the URL, which keeps the
 * other params). The URL is the whole view (filters, sort, page, size, selected row; the Flask names) and is read with parseDataQuery;
 * only column visibility is remembered in this browser. The list is the main element; the counts above it are a quiet
 * strip, and the side panels, exports and row actions are a data manager's or admin's (the server refuses them to a
 * viewer anyway). A plain collaborator sees no staff names and searches the masked form id only.
 */
export default function DataScreen() {
  const { bootstrap } = useAppState();
  const { ui } = useTheme();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const params = useLocalSearchParams();
  const request: JsonRequester | undefined = useMemo(() => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined), [bootstrap]);
  const access = useMemo(() => (bootstrap ? dataAccess(bootstrap) : { allowed: false, manage: false, redacted: true }), [bootstrap]);
  const paramsKey = JSON.stringify(params);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const query = useMemo(() => parseDataQuery(params, access.redacted), [paramsKey, access.redacted]);
  const phone = width < PHONE_BREAKPOINT;
  const tab: Tab = access.manage && params.tab === "causes" ? "causes" : "overview";
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const causesQuery = useMemo(() => parseCausesQuery(params), [paramsKey]);

  const [options, setOptions] = useState<DmFilterOptions | null>(null);
  const [list, setList] = useState<{ key: string; page: DmSubmissionsPage } | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const [kpi, setKpi] = useState<{ key: string; data: DmKpi; at: string } | null>(null);
  const [kpiBusy, setKpiBusy] = useState(false);
  const [kpiError, setKpiError] = useState("");
  const [reload, setReload] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [changes, setChanges] = useState<{ row: DmSubmissionRow; details: UpstreamChangeDetails | null; loading: boolean; error: string } | null>(null);
  const [confirm, setConfirm] = useState<{ decision: Decision; row: DmSubmissionRow } | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [draft, setDraft] = useState(query.filters.search);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [panelsOpen, setPanelsOpen] = useState(width >= 900);
  // A coder clicked in the coder panel narrows the list and exports for this visit only: never in the URL or history.
  const [coder, setCoder] = useState("");
  const [choices, setChoices] = useState<Partial<Record<ColumnKey, boolean>>>(readColumnChoices);

  const go = useCallback((next: DataQuery) => router.setParams(paramsPatch(next)), [router]);
  const goCauses = useCallback((next: CausesQuery) => router.setParams(causesPatch(next)), [router]);
  const listKey = JSON.stringify(listApiParams(withCoder(query, coder)));
  const kpiKey = JSON.stringify(countApiParams(query.filters));
  const allowed = access.allowed && Boolean(request);
  const overview = allowed && tab === "overview";

  useEffect(() => setDraft(query.filters.search), [query.filters.search]);

  useEffect(() => {
    if (!request || !allowed) return undefined;
    let active = true;
    getDmFilterOptions(request).then((reply) => active && setOptions(reply)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [request, allowed]);

  useEffect(() => {
    if (!request || !overview) return undefined;
    let active = true;
    setListBusy(true);
    setListError("");
    getDmSubmissions(request, JSON.parse(listKey))
      .then((page) => active && setList({ key: listKey, page }))
      .catch((caught) => active && setListError(browserErrorText(caught)))
      .finally(() => active && setListBusy(false));
    return () => {
      active = false;
    };
  }, [request, overview, listKey, reload]);

  useEffect(() => {
    if (!request || !overview) return undefined;
    let active = true;
    setKpiBusy(true);
    setKpiError("");
    getDmKpi(request, JSON.parse(kpiKey))
      .then((data) => active && setKpi({ key: kpiKey, data, at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }))
      .catch((caught) => active && setKpiError(browserErrorText(caught)))
      .finally(() => active && setKpiBusy(false));
    return () => {
      active = false;
    };
  }, [request, overview, kpiKey, reload]);

  const page = list?.page;
  // A page past the end (a stale link, or rows gone since): back to the last page that exists.
  useEffect(() => {
    if (page && page.data.length === 0 && query.page > 1 && page.last_page < query.page && list?.key === listKey) {
      router.setParams(paramsPatch({ ...query, page: Math.max(1, page.last_page) }));
    }
  }, [page, list?.key, listKey, query, router]);

  const rows = page?.data ?? [];
  const columns = useMemo(
    () => visibleColumns(access.redacted, choices).filter((column) => column.key !== "visit_note" || rows.some((row) => row.visit_note)),
    [access.redacted, choices, rows],
  );

  if (!bootstrap) return <WebShell title={t("dataTitle")} wide>{null}</WebShell>;
  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  if (!access.allowed) return <WebShell title={t("dataTitle")}><Text style={muted}>{t("dataNoAccess")}</Text></WebShell>;

  const userId = bootstrap.user.user_id;
  const enc = encodeURIComponent;
  const filterTo = (patch: Partial<Filters>) => go(withFilters(query, patch));
  const treeProjects = (bootstrap.access?.projects ?? []).filter((project) => project.has_tree).map((project) => project.project_id);

  /** Remember the row in the URL, then leave: Back from the server page lands on the same row. */
  const leaveFrom = (row: DmSubmissionRow, open: () => void) => {
    router.setParams(paramsPatch({ ...query, selectedSid: row.va_sid }));
    setTimeout(open, 60);
  };

  const onAction = (action: RowAction, row: DmSubmissionRow) => {
    setNotice("");
    setActionError("");
    if (action === "view") {
      leaveFrom(row, () => openServerPage(userId, access.manage ? `/data-management/view/${enc(row.va_sid)}` : `/coding/area/${enc(row.va_sid)}`));
    } else if (action === "edit") {
      window.open(`/data-management/submissions/${enc(row.va_sid)}/odk-edit`, "_blank", "noopener");
    } else if (action === "cancel") {
      setConfirm({ decision: "cancel", row });
    } else if (request) {
      setChanges({ row, details: null, loading: true, error: "" });
      getUpstreamChangeDetails(request, row.va_sid)
        .then((details) => setChanges((current) => (current?.row.va_sid === row.va_sid ? { ...current, details, loading: false } : current)))
        .catch((caught) => setChanges((current) => (current?.row.va_sid === row.va_sid ? { ...current, loading: false, error: browserErrorText(caught) } : current)));
    }
  };

  async function decide() {
    if (!request || !confirm) return;
    const { decision, row } = confirm;
    setDeciding(true);
    setActionError("");
    try {
      await (decision === "accept" ? acceptUpstreamChange : decision === "keep" ? rejectUpstreamChange : cancelRevisionRequest)(request, row.va_sid);
      setNotice(t(DECISION_TEXT[decision].done));
      setChanges(null);
      setReload((count) => count + 1);
    } catch (caught) {
      setActionError(browserErrorText(caught));
    } finally {
      setConfirm(null);
      setDeciding(false);
    }
  }

  async function refresh() {
    if (!request) return;
    setRefreshing(true);
    setActionError("");
    try {
      await refreshDmAnalytics(request);
      setReload((count) => count + 1);
    } catch (caught) {
      setActionError(caught instanceof ClientApiError && caught.status === 429 ? t("dataRefreshLimited") : browserErrorText(caught));
    } finally {
      setRefreshing(false);
    }
  }

  const toggleColumn = (key: ColumnKey, on: boolean) => {
    const next = { ...choices, [key]: on };
    setChoices(next);
    writeColumnChoices(next);
  };

  const fieldStyle = { boxSizing: "border-box", flex: "1 1 200px", minWidth: 0, minHeight: 44, padding: `0 ${spacing.sm}px`, fontSize: fontSize.input, fontFamily: controls.fontFamily, color: ui.foreground, background: ui.background, border: `1px solid ${ui.input}`, borderRadius: radius.md } as const;
  const submitSearch = () => {
    setCoder("");
    go(withFilters(query, { search: draft.trim() }));
  };
  const lastPage = page?.last_page ?? 1;
  const error = actionError || listError || kpiError;
  const listFresh = list?.key === listKey;
  // The current query's fetch failed: the rows on screen belong to an earlier query, so they are dimmed and said so.
  const staleRows = isStaleResult(list?.key, listKey, listError);
  const apiFilters = withCoder(query, coder).filters;
  // Page 1 again: the narrowed list is shorter than the page the user was on.
  const pickCoder = (name: string) => {
    setCoder(name);
    go(withFilters(query, {}));
  };
  const selectTab = (next: Tab) => router.setParams({ tab: next === "causes" ? "causes" : undefined });
  const onTabKey = (event: { key: string; preventDefault: () => void }) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = tab === "overview" ? "causes" : "overview";
    selectTab(next);
    document.getElementById(`data-tab-${next}`)?.focus();
  };
  const searchHint = access.redacted ? t("dataSearchMasked") : t("dataSearchPlaceholder");

  return (
    <WebShell title={t("dataTitle")} wide>
      {access.manage
        ? createElement(
          "div",
          { role: "tablist", "aria-label": t("dataTabsLabel"), style: { display: "flex", gap: spacing.md, borderBottom: `1px solid ${ui.border}` } },
          ...TABS.map((name) => createElement(
            "button",
            {
              key: name, id: `data-tab-${name}`, type: "button", role: "tab", "aria-selected": tab === name, "aria-controls": "data-tabpanel", tabIndex: tab === name ? 0 : -1,
              onClick: () => selectTab(name), onKeyDown: onTabKey,
              style: { minHeight: 44, padding: `0 ${spacing.xs}px`, background: "none", border: "none", borderBottom: `2px solid ${tab === name ? ui.primary : "transparent"}`, marginBottom: -1, cursor: "pointer", fontSize: fontSize.body, fontWeight: tab === name ? 600 : 400, fontFamily: controls.fontFamily, color: tab === name ? ui.foreground : ui.mutedForeground },
            },
            t(name === "causes" ? "dataTabCauses" : "dataTabOverview"),
          )),
        )
        : null}
      {tab === "causes" && request ? (
        <View nativeID="data-tabpanel" role="tabpanel" aria-labelledby="data-tab-causes" style={{ gap: spacing.lg }}>
          <CausesTab request={request} query={causesQuery} options={options} onQuery={goCauses} />
        </View>
      ) : (
      <View nativeID="data-tabpanel" role={access.manage ? "tabpanel" : undefined} style={{ gap: spacing.lg }}>
      <DataCards
        kpi={kpi?.data ?? null}
        query={query}
        loadedAt={kpi?.at ?? "–"}
        busy={kpiBusy || isStaleResult(kpi?.key, kpiKey, kpiError)}
        canRefresh={access.manage}
        refreshing={refreshing}
        onQuery={go}
        onRefresh={() => void refresh()}
      />

      <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs }}>
        {createElement(
          "form",
          { role: "search", onSubmit: (event: { preventDefault: () => void }) => { event.preventDefault(); submitSearch(); }, style: { display: "flex", flex: "1 1 260px", gap: spacing.xs, minWidth: 0 } },
          createElement("input", { type: "search", "aria-label": searchHint, placeholder: searchHint, value: draft, maxLength: 200, onChange: (event: { target: { value: string } }) => setDraft(event.target.value), style: fieldStyle }),
          <Button kind="secondary" label={t("dataSearch")} onPress={submitSearch} />,
        )}
        <Button variant="outline" label={t("dataFilters")} expanded={filtersOpen} onPress={() => setFiltersOpen((open) => !open)} />
        <Button variant="outline" label={t("dataColumns")} expanded={columnsOpen} onPress={() => setColumnsOpen((open) => !open)} />
        {access.manage ? <Button variant="outline" label={t("dataExport")} expanded={exportOpen} onPress={() => setExportOpen((open) => !open)} /> : null}
      </View>

      {filtersOpen ? <FilterPanel query={query} options={options} onQuery={go} /> : null}

      {columnsOpen ? (
        <View accessibilityRole="toolbar" accessibilityLabel={t("dataColumns")} style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: ui.border, borderRadius: radius.lg }}>
          {columnsFor(access.redacted).map((column) => createElement(
            "label",
            { key: column.key, style: { display: "flex", alignItems: "center", gap: spacing.xs, minHeight: 32, fontSize: fontSize.body, color: ui.foreground, fontFamily: controls.fontFamily } },
            createElement("input", { type: "checkbox", checked: choices[column.key] ?? column.defaultVisible, onChange: (event: { target: { checked: boolean } }) => toggleColumn(column.key, event.target.checked) }),
            columnLabel(column.key),
          ))}
        </View>
      ) : null}

      {exportOpen && access.manage ? (
        <View style={{ gap: spacing.xxs, padding: spacing.sm, borderWidth: 1, borderColor: ui.border, borderRadius: radius.lg }}>
          <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataExportNote")}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.md }}>
            {EXPORT_KINDS.map((kind) => createElement(
              "a",
              { key: kind, href: dmExportUrl(kind, exportApiParams(apiFilters)), style: { display: "inline-flex", alignItems: "center", minHeight: 44, fontSize: fontSize.body, color: ui.primary, fontFamily: controls.fontFamily } },
              t(EXPORT_LABELS[kind]),
            ))}
          </View>
        </View>
      ) : null}

      <FilterChips query={query} onQuery={go} />
      {coder ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs }}>
          <StatPressable
            label={t("dataCoderChipRemove", { name: coder })}
            onPress={() => pickCoder("")}
            style={{ minHeight: 32, justifyContent: "center", paddingHorizontal: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: ui.input, backgroundColor: ui.secondary }}
          >
            <Text style={{ fontSize: fontSize.caption, color: ui.foreground }}>{`${t("dataCoderChip", { name: coder })}  ✕`}</Text>
          </StatPressable>
        </View>
      ) : null}

      {error ? (
        <View style={{ gap: spacing.xs }}>
          <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{error}</Text>
          {listError || kpiError ? <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={() => setReload((count) => count + 1)} style={{ alignSelf: "flex-start" }} /> : null}
        </View>
      ) : null}
      {notice ? <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.success }}>{notice}</Text> : null}

      <View accessibilityState={{ busy: listBusy }} style={{ gap: spacing.xs, opacity: (listBusy && rows.length) || staleRows ? 0.55 : 1 }}>
        {staleRows && rows.length ? <Text accessibilityLiveRegion="polite" style={muted}>{t("dataShowingPrevious")}</Text> : null}
        {page && !staleRows ? <Text accessibilityLiveRegion="polite" style={muted}>{t("dataTotalLine", { total: page.total.toLocaleString(), page: query.page, last: lastPage })}</Text> : null}
        {!page && !listError ? <View style={{ minHeight: 160 }}><Text style={muted}>{t("loading")}</Text></View> : null}
        {page && !rows.length && listFresh ? <Text style={muted}>{t("dataNoRows")}</Text> : null}
        {rows.length ? (
          phone
            ? <DataCardList rows={rows} columns={columns} query={query} handlers={{ manage: access.manage, onAction }} />
            : <DataTable rows={rows} columns={columns} query={query} handlers={{ manage: access.manage, onAction }} onQuery={go} />
        ) : null}
      </View>

      {page ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm }}>
          <Button kind="secondary" size="sm" label={t("dataPrevious")} disabled={query.page <= 1} onPress={() => go({ ...query, page: query.page - 1, selectedSid: "" })} />
          <Button kind="secondary" size="sm" label={t("dataNext")} disabled={query.page >= lastPage} onPress={() => go({ ...query, page: query.page + 1, selectedSid: "" })} />
          <View style={{ flexGrow: 1 }}>
            <ChoiceRow
              label={t("dataPageSize")}
              options={PAGE_SIZES.map((size) => ({ value: String(size), label: String(size) }))}
              value={String(query.size)}
              onChange={(next) => go({ ...query, size: Number(next), page: 1, selectedSid: "" })}
            />
          </View>
        </View>
      ) : null}

      {access.manage && request ? (
        <View style={{ gap: spacing.sm }}>
          <Button variant="outline" size="sm" label={t(panelsOpen ? "dataPanelsHide" : "dataPanelsShow")} expanded={panelsOpen} onPress={() => setPanelsOpen((open) => !open)} style={{ alignSelf: "flex-start" }} />
          {panelsOpen ? (
            <DataPanels request={request} filters={query.filters} options={options} treeProjects={treeProjects} workflowCounts={kpi?.data.workflow_counts ?? null} reload={reload} onFilter={filterTo} onCoder={pickCoder} />
          ) : null}
          <TextAction label={t("dataOpenSync")} onPress={() => window.location.assign("/data-management/")} />
        </View>
      ) : null}

      </View>
      )}

      {changes && !confirm ? (
        <UpstreamChangesDialog
          formId={changes.row.va_uniqueid_masked ?? ""}
          details={changes.details}
          loading={changes.loading}
          error={changes.error || actionError}
          onAccept={() => setConfirm({ decision: "accept", row: changes.row })}
          onKeep={() => setConfirm({ decision: "keep", row: changes.row })}
          onClose={() => setChanges(null)}
        />
      ) : null}
      {confirm ? (
        <ConfirmDialog
          title={t(DECISION_TEXT[confirm.decision].title)}
          message={t(DECISION_TEXT[confirm.decision].message, { id: confirm.row.va_uniqueid_masked ?? "" })}
          confirmLabel={t(DECISION_TEXT[confirm.decision].confirm)}
          destructive={DECISION_TEXT[confirm.decision].destructive}
          onConfirm={() => (deciding ? undefined : void decide())}
          onCancel={() => setConfirm(null)}
        />
      ) : null}
    </WebShell>
  );
}
