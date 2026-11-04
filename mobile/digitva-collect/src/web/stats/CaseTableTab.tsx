import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, useWindowDimensions, View, type ViewStyle } from "react-native";

import { listCases, type AreaCauses, type CaseStatus, type CaseListPage, type CaseListRow } from "../../area/api";
import { t, type StringKey } from "../../i18n";
import { fontSize, spacing, typography, useTheme } from "../../theme";
import type { JsonRequester } from "../../workspace/api";
import { Button } from "../../ui";
import { CaseCard, formatDisplayTimestamp, sexLabel } from "../../ui/CaseCard";
import { browserErrorText } from "../common";
import { CausesList } from "./CausesList";
import { ChoiceRow } from "./controls";
import { allStatuses, casesQuery, chipCount, daysBetween, STATUS_CHIPS, type CaseTab, type StatsView } from "./view";

/** Below this window width the rows are case cards, not a table. */
const TABLE_MIN_WIDTH = 768;

type Column = { key: string; label: StringKey; text: (row: CaseListRow) => string; flex?: number; gate?: keyof CaseListRow };

const statusText = (row: CaseListRow) => {
  const key = `caseStatus_${row.status}` as StringKey;
  const label = t(key);
  return label === key ? row.status : label;
};

/** The days cell: overdue rows say so in words; Codings shows days to code once coded, else days waiting. */
function daysText(tab: CaseTab, row: CaseListRow): string {
  const waiting = row.days_waiting ?? null;
  if (row.overdue) return waiting === null ? t("statsOverdue") : t("statsOverdueDays", { days: waiting });
  if (tab === "codings") {
    const toCode = row.status === "coded" ? daysBetween(row.submitted_at, row.coded_at) : null;
    if (toCode !== null) return t("statsDaysToCodeValue", { days: toCode });
    return waiting === null ? "" : t("statsDaysWaitingValue", { days: waiting });
  }
  return waiting === null ? "" : String(waiting);
}

const ID: Column = { key: "id", label: "statsColId", text: (row) => row.unique_id, flex: 1.2 };
const NAME: Column = { key: "name", label: "statsColName", text: (row) => row.deceased_name ?? "", flex: 1.4, gate: "deceased_name" };
const AGE: Column = { key: "age", label: "statsColAge", text: (row) => (row.age_years == null ? "" : String(row.age_years)), flex: 0.6 };
const SEX: Column = { key: "sex", label: "statsColSex", text: (row) => sexLabel(row.deceased_sex), flex: 0.7 };
const DIED: Column = { key: "died", label: "statsColDeath", text: (row) => formatDisplayTimestamp(row.date_of_death) };
const FACILITY: Column = { key: "facility", label: "statsColFacility", text: (row) => row.unit_name ?? "", flex: 1.3 };
const STATUS: Column = { key: "status", label: "statsColStatus", text: statusText };
const INTERVIEWED: Column = { key: "interviewed", label: "statsColInterviewedOn", text: (row) => formatDisplayTimestamp(row.submitted_at) };

const COLUMNS: Record<CaseTab, Column[]> = {
  deaths: [ID, NAME, AGE, SEX, DIED, FACILITY,
    { key: "reporter", label: "statsColReporter", text: (row) => row.reporter_name ?? "", gate: "reporter_name" },
    STATUS, { key: "days", label: "statsColDaysWaiting", text: (row) => daysText("deaths", row) }],
  interviews: [ID, NAME, AGE, SEX, DIED, INTERVIEWED,
    { key: "interviewer", label: "statsColInterviewer", text: (row) => row.interviewer_name ?? "", gate: "interviewer_name" },
    FACILITY, STATUS, { key: "days", label: "statsColDaysSinceInterview", text: (row) => daysText("interviews", row) }],
  codings: [ID, NAME, INTERVIEWED,
    { key: "coded", label: "statsColCodedOn", text: (row) => formatDisplayTimestamp(row.coded_at) },
    { key: "coder", label: "statsColCoder", text: (row) => row.coder_name ?? "", gate: "coder_name" },
    STATUS, { key: "days", label: "statsColDaysToCode", text: (row) => daysText("codings", row) }],
};

const TAB_TITLES: Record<CaseTab, StringKey> = { deaths: "statsTabDeaths", interviews: "statsTabInterviews", codings: "statsTabCodings" };

/**
 * A read-only case table (Deaths, Interviews or Codings) over GET /api/v1/cases: status chips with the first page's
 * counts, then a table (cards on a narrow window), 50 rows a page with Load more. Gated columns (name, staff) show
 * only when the server sent the field on some row. A row gets a View action when the server says the caller can
 * open it (`can_open` with `va_sid`) and the screen supplied *onOpen* (a viewer or data-manager role).
 */
export function CaseTableTab({ view, projectIds, request, causes, onStatus, onOpen }: {
  view: StatsView & { tab: CaseTab };
  projectIds: string[];
  request: JsonRequester;
  /** Shown under the Codings table when one project is in view. */
  causes?: AreaCauses | null;
  onStatus: (status: string | null) => void;
  /** Opens a row's case page; absent when the user holds no role that may view cases. */
  onOpen?: (sid: string) => void;
}) {
  const { ui } = useTheme();
  const wide = useWindowDimensions().width >= TABLE_MIN_WIDTH;
  const [page, setPage] = useState<CaseListPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);
  // One "now" per view, so a re-render does not move the period start and refetch.
  const firstQuery = useMemo(() => casesQuery(view, projectIds, new Date(), null), [view, projectIds]);
  const queryKey = JSON.stringify(firstQuery);

  useEffect(() => {
    const mine = ++generation.current;
    setPage(null);
    setBusy(true);
    setError("");
    listCases(request, JSON.parse(queryKey))
      .then((reply) => {
        if (generation.current === mine) setPage(reply);
      })
      .catch((caught) => {
        if (generation.current === mine) setError(browserErrorText(caught));
      })
      .finally(() => {
        if (generation.current === mine) setBusy(false);
      });
    return () => {
      generation.current += 1;
    };
  }, [request, queryKey, retry]);

  const loadMore = useCallback(() => {
    if (!page?.next_cursor) return;
    const mine = generation.current;
    setBusy(true);
    listCases(request, { ...JSON.parse(queryKey), cursor: page.next_cursor })
      .then((reply) => {
        // Counts come with the first page only; they are kept while paging.
        if (generation.current === mine) setPage((current) => current && { ...current, cases: [...current.cases, ...reply.cases], next_cursor: reply.next_cursor });
      })
      .catch((caught) => {
        if (generation.current === mine) setError(browserErrorText(caught));
      })
      .finally(() => {
        if (generation.current === mine) setBusy(false);
      });
  }, [page, request, queryKey]);

  const rows = page?.cases ?? [];
  const opener = (row: CaseListRow) => (onOpen && row.can_open && row.va_sid ? () => onOpen(row.va_sid!) : undefined);
  const columns = COLUMNS[view.tab].filter((column) => !column.gate || page?.cases.some((row) => row[column.gate!] !== undefined));
  // No counts until the first page lands: "(0)" while loading would read as a real zero.
  const chipLabel = (label: string, statuses: CaseStatus[]) =>
    page ? t("statsChipCount", { label, count: chipCount(page.counts, statuses) }) : label;
  const chips = [
    { value: "all", label: chipLabel(t("statsChipAll"), allStatuses(view.tab)) },
    ...STATUS_CHIPS[view.tab].map((chip) => ({ value: chip.key, label: chipLabel(t(chip.label), chip.statuses) })),
  ];
  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;

  return (
    <View style={{ gap: spacing.md }}>
      <ChoiceRow label={t("statsStatusFilter")} options={chips} value={view.status ?? "all"} onChange={(next) => onStatus(next === "all" ? null : next)} />
      {view.overdue ? <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("statsOverdueAllTime")}</Text> : null}
      {error ? (
        <View style={{ gap: spacing.xs }}>
          <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{`${t("statsLoadFailed")}\n${error}`}</Text>
          <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={() => setRetry((count) => count + 1)} style={{ alignSelf: "flex-start" }} />
        </View>
      ) : null}
      {page && rows.length === 0 && !page.next_cursor ?<Text style={muted}>{t("statsNoCases")}</Text> : null}
      {!page && busy ? <Text style={muted}>{t("loading")}</Text> : null}
      {rows.length ? (wide ? <CaseTable tab={view.tab} columns={columns} rows={rows} opener={opener} /> : rows.map((row) => <CaseRowCard key={row.death_id} tab={view.tab} row={row} open={opener(row)} />)) : null}
      {page?.next_cursor ? <Button kind="secondary" loading={busy} label={t("loadMore")} onPress={loadMore} style={{ alignSelf: "flex-start" }} /> : null}
      {view.tab === "codings" && causes ? <CausesList causes={causes} /> : null}
    </View>
  );
}

/** An overdue row: the warning fill, its border and dark-on-light (or light-on-dark) text, plus the words in the days cell. */
function useRowTone() {
  const { ui } = useTheme();
  return (overdue: boolean) => ({
    row: overdue ? { backgroundColor: ui.warning, borderLeftWidth: 3, borderLeftColor: ui.warningBorder } : { borderLeftWidth: 3, borderLeftColor: "transparent" },
    text: overdue ? ui.warningForeground : ui.foreground,
  });
}

/** The View button of a row: 44 px high, named after the case for screen readers. */
function ViewButton({ row, open }: { row: CaseListRow; open: () => void }) {
  return <Button label={t("dataActionView")} accessibilityLabel={`${t("dataActionView")} ${row.unique_id}`} kind="secondary" size="sm" onPress={open} style={{ minHeight: 44 }} />;
}

/** Wide enough for the View button at its 44 px target. */
const ACTION_CELL_WIDTH = 88;

function CaseTable({ tab, columns, rows, opener }: { tab: CaseTab; columns: Column[]; rows: CaseListRow[]; opener: (row: CaseListRow) => (() => void) | undefined }) {
  const { ui } = useTheme();
  const tone = useRowTone();
  const cellStyle = (column: Column): ViewStyle => ({ flex: column.flex ?? 1, minWidth: 0, paddingVertical: spacing.xs, paddingHorizontal: spacing.xxs });
  // Every row and the header carry the same fixed action cell when any row opens, or the flex columns drift out of line.
  const actions = rows.some((row) => opener(row));
  const actionCell: ViewStyle = { width: ACTION_CELL_WIDTH, paddingHorizontal: spacing.xxs, justifyContent: "center" };
  return (
    <View role="table" aria-label={t(TAB_TITLES[tab])} style={{ borderTopWidth: 1, borderTopColor: ui.border }}>
      <View role="row" style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: ui.border, borderLeftWidth: 3, borderLeftColor: "transparent" }}>
        {columns.map((column) => (
          <View key={column.key} role="columnheader" style={cellStyle(column)}>
            <Text style={{ ...typography.subhead, fontWeight: "600", color: ui.mutedForeground }}>{t(column.label)}</Text>
          </View>
        ))}
        {actions ? <View role="columnheader" aria-label={t("dataActionView")} style={actionCell} /> : null}
      </View>
      {rows.map((row) => {
        const { row: rowStyle, text } = tone(Boolean(row.overdue));
        const open = opener(row);
        return (
          <View key={row.death_id} role="row" style={[{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: ui.border }, rowStyle]}>
            {columns.map((column) => (
              <View key={column.key} role="cell" style={cellStyle(column)}>
                <Text style={{ fontSize: fontSize.body, color: text, fontWeight: column.key === "days" && row.overdue ? "600" : "400" }}>{column.text(row)}</Text>
              </View>
            ))}
            {actions ? <View role="cell" style={actionCell}>{open ? <ViewButton row={row} open={open} /> : null}</View> : null}
          </View>
        );
      })}
    </View>
  );
}

/** The narrow-window row: the shared case card, with View when the row opens. */
function CaseRowCard({ tab, row, open }: { tab: CaseTab; row: CaseListRow; open?: () => void }) {
  const days = daysText(tab, row);
  const fact = (key: string, label: StringKey, value: string | null | undefined) => (value ? [{ key, text: t(label, { value }) }] : []);
  return (
    <CaseCard
      title={row.deceased_name || row.unique_id}
      caseId={row.deceased_name ? row.unique_id : undefined}
      ageYears={row.age_years}
      sex={row.deceased_sex}
      dateOfDeath={row.date_of_death}
      area={row.unit_name ?? undefined}
      extra={[
        ...fact("interviewed", "statsFactInterviewed", formatDisplayTimestamp(row.submitted_at)),
        ...fact("coded", "statsFactCoded", formatDisplayTimestamp(row.coded_at)),
        ...fact("reporter", "statsFactReporter", tab === "deaths" ? row.reporter_name : null),
        ...fact("interviewer", "statsFactInterviewer", tab === "interviews" ? row.interviewer_name : null),
        ...fact("coder", "statsFactCoder", tab === "codings" ? row.coder_name : null),
        ...(row.overdue ? [] : fact("days", "statsFactDays", days)),
      ]}
      badges={[
        { label: statusText(row) },
        ...(row.overdue && days ? [{ label: days, tone: "warning" as const }] : []),
      ]}
      actions={open ? <ViewButton row={row} open={open} /> : null}
    />
  );
}
