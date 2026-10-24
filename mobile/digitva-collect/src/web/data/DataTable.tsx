import { createElement, useEffect, type ReactNode } from "react";
import { Text, View } from "react-native";

import type { DmSubmissionRow } from "../../data/api";
import { rowState, sortBy, type ColumnDef, type ColumnKey, type DataQuery } from "../../data/query";
import { t, type StringKey } from "../../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { StatPressable } from "../stats/controls";
import { workflowLabel } from "./DataFilters";

const COLUMN_LABELS: Record<ColumnKey, StringKey> = {
  site_id: "dataColSite", project_id: "dataColProject", va_submission_date: "dataColSubmitted", va_uniqueid_masked: "dataColFormId",
  va_data_collector: "dataColCollector", attachment_count: "dataColAttachments", has_smartva: "dataColSmartva",
  va_odk_reviewstate: "dataColOdkStatus", analytics_age_band: "dataColAge", va_deceased_gender: "dataColGender",
  odk_sync_status: "dataColSync", workflow_state: "dataColWorkflow", coded_on: "dataColCodedOn", coded_by: "dataColCodedBy",
  va_dmreview_createdat: "dataColFlaggedAt", va_consent: "dataColConsent", visit_note: "dataColVisitNote",
};
export const columnLabel = (key: ColumnKey): string => t(COLUMN_LABELS[key]);

export type RowAction = "view" | "edit" | "changes" | "cancel";
export interface RowHandlers {
  /** Data manager or admin: Edit in ODK, View changes and Cancel request are theirs. */
  manage: boolean;
  onAction: (action: RowAction, row: DmSubmissionRow) => void;
}

const dash = "–";
const DATE_COLUMNS: ColumnKey[] = ["va_submission_date", "coded_on", "va_dmreview_createdat"];
const day = (value: string | null) => (value ? String(value).slice(0, 10) : dash);
const dateTime = (value: string | null) => (value ? String(value).slice(0, 16).replace("T", " ") : dash);

function Badge({ text, tone, title, wrap }: { text: string; tone?: "warn" | "bad" | "ok" | "teal"; title?: string; wrap?: boolean }) {
  const { ui } = useTheme();
  const colour = tone === "warn" ? ui.warningText : tone === "bad" ? ui.destructiveText : tone === "ok" ? ui.success : tone === "teal" ? ui.chart[1].foreground : ui.foreground;
  return createElement("span", {
    title,
    style: { display: "inline-block", padding: "1px 6px", border: `1px solid ${tone ? colour : ui.border}`, borderRadius: radius.sm, color: colour, fontSize: fontSize.caption, fontFamily: controls.fontFamily, whiteSpace: wrap ? "normal" : "nowrap" },
  }, text);
}

function smartvaBadge(row: DmSubmissionRow) {
  if (row.workflow_state === "consent_refused") return <Badge text={t("dataSmartvaIneligible")} />;
  if (row.has_smartva_failed) return <Badge text={t("dataSmartva_failed")} tone="bad" />;
  return <Badge text={t(row.has_smartva ? "dataSmartva_available" : "dataSmartva_missing")} tone={row.has_smartva ? "ok" : undefined} />;
}

/** The ODK reviewer's comments of a row that has issues, as one line of text ("" when none). */
const reviewComments = (row: DmSubmissionRow): string =>
  row.va_odk_reviewstate === "hasIssues" ? (row.va_odk_reviewcomments ?? []).map((comment) => comment.body ?? "").filter(Boolean).join(" | ") : "";

function odkBadge(row: DmSubmissionRow) {
  if (row.va_odk_reviewstate === "hasIssues") return <Badge text={t("dataOdk_hasIssues")} tone="warn" />;
  return <Badge text={t(row.va_odk_reviewstate === "approved" ? "dataOdk_approved" : "dataOdk_no_review_state")} />;
}

function workflowBadge(row: DmSubmissionRow) {
  const state = rowState(row);
  const tone = state === "finalized_upstream_changed" ? "warn" : state === "sent_back_for_revision" ? "teal" : state === "not_codeable_by_data_manager" ? "bad" : undefined;
  return <Badge text={workflowLabel(state)} tone={tone} wrap />;
}

function visitNoteText(row: DmSubmissionRow): string {
  const note = row.visit_note;
  if (!note) return dash;
  const date = note.date ? String(note.date).slice(0, 10) : "";
  if (note.redacted) return `${date} ${t("dataVisitNoteWithheld")}`.trim();
  return [date, note.address].filter(Boolean).join(" · ") || dash;
}

/** One cell's content. Text from the server is rendered as text only. */
function cell(row: DmSubmissionRow, key: ColumnKey): ReactNode {
  switch (key) {
    case "site_id": return row.site_id;
    case "project_id": return row.project_id;
    case "va_submission_date": return day(row.va_submission_date);
    case "va_uniqueid_masked": return row.va_uniqueid_masked ?? dash;
    case "va_data_collector": return row.va_data_collector || dash;
    case "attachment_count": return String(row.attachment_count ?? 0);
    case "has_smartva": return smartvaBadge(row);
    case "va_odk_reviewstate": return odkBadge(row);
    case "analytics_age_band": return row.analytics_age_band ? t(`dataAge_${row.analytics_age_band}` as StringKey) : dash;
    case "va_deceased_gender": return row.va_deceased_gender || dash;
    case "odk_sync_status": return <Badge text={t(row.odk_sync_status === "missing_in_odk" ? "dataSync_missing_in_odk" : "dataSync_in_sync")} tone={row.odk_sync_status === "missing_in_odk" ? "bad" : undefined} />;
    case "workflow_state": return workflowBadge(row);
    case "coded_on": return dateTime(row.coded_on);
    case "coded_by": return row.coded_by || dash;
    case "va_dmreview_createdat": return dateTime(row.va_dmreview_createdat);
    case "va_consent": return row.va_consent || dash;
    case "visit_note": return visitNoteText(row);
  }
}

/** The actions a row offers this viewer. A viewer only opens the read-only area view; the server enforces both. */
export function rowActions(row: DmSubmissionRow, manage: boolean): { action: RowAction; label: StringKey }[] {
  const actions: { action: RowAction; label: StringKey }[] = [{ action: "view", label: "dataActionView" }];
  if (!manage) return actions;
  if (row.workflow_state !== "finalized_upstream_changed") actions.push({ action: "edit", label: "dataActionEdit" });
  else actions.push(row.revision_requested ? { action: "cancel", label: "dataActionCancel" } : { action: "changes", label: "dataActionChanges" });
  return actions;
}

function Actions({ row, handlers, small }: { row: DmSubmissionRow; handlers: RowHandlers; small?: boolean }) {
  const { ui } = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.sm }}>
      {rowActions(row, handlers.manage).map(({ action, label }) => (
        <StatPressable
          key={action}
          label={`${t(label)} ${row.va_uniqueid_masked ?? ""}`.trim()}
          onPress={() => handlers.onAction(action, row)}
          style={{ minHeight: small ? 32 : 44, justifyContent: "center" }}
        >
          <Text style={{ fontSize: fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{t(label)}</Text>
        </StatPressable>
      ))}
    </View>
  );
}

/** Scroll the opened row into view once, so Back from a server page lands where the user was. */
function useScrollToSelected(selectedSid: string, ready: boolean) {
  useEffect(() => {
    if (!selectedSid || !ready || typeof document === "undefined") return;
    document.getElementById(`data-row-${selectedSid}`)?.scrollIntoView?.({ block: "center" });
  }, [selectedSid, ready]);
}

/** Wide screens: a real table. Headers of sortable columns are buttons that carry aria-sort; the table scrolls inside its own region. */
export function DataTable({ rows, columns, query, handlers, onQuery }: {
  rows: DmSubmissionRow[];
  columns: ColumnDef[];
  query: DataQuery;
  handlers: RowHandlers;
  onQuery: (next: DataQuery) => void;
}) {
  const { ui } = useTheme();
  useScrollToSelected(query.selectedSid, rows.length > 0);
  // The last column stays in view while the table scrolls inside its region, so Actions are always reachable.
  const stickyEnd = { position: "sticky", right: 0, minWidth: 104, boxShadow: `-1px 0 0 ${ui.border}` } as const;
  const cellStyle = { padding: `${spacing.xs}px ${spacing.xs + 2}px`, borderBottom: `1px solid ${ui.border}`, textAlign: "left", verticalAlign: "top", fontSize: fontSize.body, color: ui.foreground } as const;
  const head = (column: ColumnDef) => {
    const sorted = column.sort === query.sortField;
    const label = columnLabel(column.key);
    return createElement(
      "th",
      { key: column.key, scope: "col", "aria-sort": column.sort ? (sorted ? (query.sortDir === "asc" ? "ascending" : "descending") : "none") : undefined, style: { ...cellStyle, fontWeight: 600, color: ui.mutedForeground, whiteSpace: "nowrap", verticalAlign: "middle" } },
      column.sort ? (
        <StatPressable label={t("dataSortBy", { column: label })} onPress={() => onQuery(sortBy(query, column.sort!))} style={{ minHeight: 32, justifyContent: "center" }}>
          <Text numberOfLines={1} style={{ fontSize: fontSize.body, fontWeight: "600", color: sorted ? ui.foreground : ui.mutedForeground }}>{`${label}${sorted ? (query.sortDir === "asc" ? " ▲" : " ▼") : ""}`}</Text>
        </StatPressable>
      ) : label,
    );
  };
  return createElement(
    "div",
    { role: "region", tabIndex: 0, "aria-label": t("dataTableRegion"), style: { overflowX: "auto", width: "100%" } },
    createElement(
      "table",
      { style: { width: "100%", borderCollapse: "collapse", fontFamily: controls.fontFamily } },
      createElement("caption", { style: { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" } }, t("dataTableCaption")),
      createElement("thead", null, createElement("tr", null, ...columns.map(head), createElement("th", { key: "actions", scope: "col", style: { ...cellStyle, ...stickyEnd, background: ui.background, fontWeight: 600, color: ui.mutedForeground } }, t("dataColActions")))),
      createElement(
        "tbody",
        null,
        ...rows.map((row) => {
          const selected = row.va_sid === query.selectedSid;
          return createElement(
            "tr",
            { key: row.va_sid, id: `data-row-${row.va_sid}`, "aria-current": selected ? "true" : undefined, style: { background: selected ? ui.accent : undefined } },
            ...columns.map((column) => createElement(
              "td",
              { key: column.key, style: DATE_COLUMNS.includes(column.key) ? { ...cellStyle, whiteSpace: "nowrap" } : column.key === "workflow_state" ? { ...cellStyle, minWidth: 110, maxWidth: 150 } : cellStyle },
              cell(row, column.key),
              column.key === "va_odk_reviewstate" && reviewComments(row)
                ? createElement("div", { style: { marginTop: 2, maxWidth: 220, fontSize: fontSize.caption, color: ui.mutedForeground, overflowWrap: "anywhere" } }, reviewComments(row))
                : null,
            )),
            createElement("td", { key: "actions", style: { ...cellStyle, ...stickyEnd, background: selected ? ui.accent : ui.background } }, <Actions row={row} handlers={handlers} small />),
          );
        }),
      ),
    ),
  );
}

/** Phones: one compact card per submission. Only the columns that matter at a glance, plus the optional ones turned on. */
export function DataCardList({ rows, columns, query, handlers }: { rows: DmSubmissionRow[]; columns: ColumnDef[]; query: DataQuery; handlers: RowHandlers }) {
  const { ui } = useTheme();
  useScrollToSelected(query.selectedSid, rows.length > 0);
  const shown = new Set(columns.map((column) => column.key));
  const lead: ColumnKey[] = ["site_id", "va_submission_date", "project_id"];
  const detail: ColumnKey[] = ["has_smartva", "va_odk_reviewstate", "attachment_count", "analytics_age_band", "va_deceased_gender", "odk_sync_status", "va_consent", "va_dmreview_createdat", "va_data_collector"];
  const small = { fontSize: fontSize.caption, color: ui.mutedForeground } as const;
  return (
    <View role="list">
      {rows.map((row) => {
        const selected = row.va_sid === query.selectedSid;
        const coded = shown.has("coded_on") && row.coded_on ? `${t("dataColCodedOn")} ${dateTime(row.coded_on)}` : "";
        const by = shown.has("coded_by") && row.coded_by ? `${t("dataColCodedBy")} ${row.coded_by}` : "";
        return (
          <View
            key={row.va_sid}
            nativeID={`data-row-${row.va_sid}`}
            role="listitem"
            style={{ gap: spacing.xxs, paddingVertical: spacing.sm, paddingHorizontal: spacing.xs, borderTopWidth: 1, borderTopColor: ui.border, backgroundColor: selected ? ui.accent : undefined }}
          >
            <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: spacing.xs }}>
              <Text style={{ ...typography.body, fontWeight: "600", color: ui.foreground }}>{row.va_uniqueid_masked ?? dash}</Text>
              {shown.has("workflow_state") ? workflowBadge(row) : null}
            </View>
            <Text style={small}>{lead.filter((key) => shown.has(key)).map((key) => String(cell(row, key))).join(" · ")}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs }}>
              {detail.filter((key) => shown.has(key)).map((key) => {
                const value = cell(row, key);
                return typeof value === "string" ? <Text key={key} style={small}>{`${columnLabel(key)}: ${value}`}</Text> : <View key={key}>{value}</View>;
              })}
            </View>
            {coded || by ? <Text style={small}>{[coded, by].filter(Boolean).join(" · ")}</Text> : null}
            {shown.has("visit_note") && row.visit_note ? <Text style={small}>{`${columnLabel("visit_note")}: ${visitNoteText(row)}`}</Text> : null}
            {reviewComments(row) ? <Text style={small}>{reviewComments(row)}</Text> : null}
            <Actions row={row} handlers={handlers} />
          </View>
        );
      })}
    </View>
  );
}
