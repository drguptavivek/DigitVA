import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import {
  areaCsvUrl, DEFAULT_PERIOD, getAreaProjects, getAreaStaff, getAreaSummary, PERIODS,
  type AreaProject, type AreaStaff, type AreaSummary, type Period,
} from "../area/api";
import { ClientApiError } from "../client/api";
import { dataRouteForLink } from "../data/query";
import { t, type StringKey } from "../i18n";
import { fontSize, spacing, typography, useTheme } from "../theme";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { Button } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { openServerPage } from "./roleHome";
import { CausesList } from "./stats/CausesList";
import { ChoiceRow, SelectRow, StatPressable, TextAction } from "./stats/controls";
import {
  canDrill, formatDays, hasDeathRegister, parseSelection, pipelineScale, PROJECT_BUTTONS_MAX, selectionParams,
  type AreaSelection,
} from "./stats/pipeline";
import { PipelineRow } from "./stats/PipelineRow";

const PERIOD_LABELS: Record<Period, StringKey> = {
  "30d": "statsPeriod30d", "90d": "statsPeriod90d", "12m": "statsPeriod12m", all: "statsPeriodAll",
};
/** Which count a server link belongs to, and how to say where it leads. */
const LINK_LABELS: Record<string, StringKey> = {
  submitted: "statsLinkSubmitted", awaiting_coding: "statsLinkAwaiting", visit_notes: "statsLinkVisitNotes",
};

/** Height held while the first summary loads, so the page does not jump. */
const LOADING_MIN_HEIGHT = 240;

/**
 * Statistics: the area dashboard over /api/v1/area/*. Counts only. The view is the URL (project, unit, site, period,
 * the same names as the API): every choice and drill pushes a history entry, so reload and Back restore it. The URL is
 * untrusted: parseSelection checks it against the server's project list and the server scopes every number anyway.
 * Each unit below the selected one is a pipeline bar (src/web/stats); the card, causes and stations are quiet text.
 */
export default function StatisticsScreen() {
  const { bootstrap } = useAppState();
  const { ui } = useTheme();
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const router = useRouter();
  const params = useLocalSearchParams<{ project?: string | string[]; unit?: string | string[]; site?: string | string[]; period?: string | string[] }>();
  const [projects, setProjects] = useState<AreaProject[] | null>(null);
  const [loaded, setLoaded] = useState<{ selection: AreaSelection; data: AreaSummary } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [staffOpen, setStaffOpen] = useState(false);
  const [staff, setStaff] = useState<AreaStaff | null>(null);
  const [staffBusy, setStaffBusy] = useState(false);
  const [staffError, setStaffError] = useState("");

  const selection = useMemo(
    () => (projects ? parseSelection(params, projects) : null),
    [projects, params],
  );
  const project = selection?.project ?? null;
  const unit = selection?.unit ?? null;
  const site = selection?.site ?? null;
  const period = selection?.period ?? DEFAULT_PERIOD;

  useEffect(() => {
    if (!request) return undefined;
    let active = true;
    setError("");
    getAreaProjects(request)
      .then((rows) => {
        if (active) setProjects(rows);
      })
      .catch((caught) => {
        if (active) setError(browserErrorText(caught));
      });
    return () => {
      active = false;
    };
  }, [request, retry]);

  /** Push the view with *patch* applied; each step is one history entry. */
  const go = useCallback((patch: Partial<AreaSelection>) => {
    if (selection) router.push({ pathname: "/statistics", params: selectionParams({ ...selection, ...patch }) });
  }, [router, selection]);

  useEffect(() => {
    if (!request || !project) return undefined;
    let active = true;
    setBusy(true);
    setError("");
    const wanted: AreaSelection = { project, unit, site, period };
    getAreaSummary(request, wanted)
      .then((reply) => {
        if (active) setLoaded({ selection: wanted, data: reply });
      })
      .catch((caught) => {
        if (!active) return;
        // A unit or site the server does not know (a stale link): back to the project's top level, not an error page.
        if ((unit || site) && caught instanceof ClientApiError && caught.status === 404) {
          router.replace({ pathname: "/statistics", params: selectionParams({ project, unit: null, site: null, period }) });
          return;
        }
        setError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [request, project, unit, site, period, retry, router]);

  // The by-interviewer list belongs to one project: a project change closes it.
  useEffect(() => {
    setStaffOpen(false);
    setStaff(null);
  }, [project]);

  useEffect(() => {
    if (!request || !project || !staffOpen) {
      setStaffBusy(false);
      return undefined;
    }
    let active = true;
    setStaffError("");
    setStaff(null);
    setStaffBusy(true);
    getAreaStaff(request, { project, unit, site })
      .then((reply) => {
        if (active) setStaff(reply);
      })
      .catch((caught) => {
        if (active) setStaffError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setStaffBusy(false);
      });
    return () => {
      active = false;
    };
  }, [request, project, unit, site, staffOpen]);

  const choose = useCallback((next: string) => go({ project: next, unit: null, site: null }), [go]);
  const drill = useCallback((next: { unit?: string | null; site?: string | null }) => go({ unit: next.unit ?? null, site: next.site ?? null }), [go]);

  if (!bootstrap) return <WebShell title={t("statsTitle")}>{null}</WebShell>;

  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  // A link to the retired Flask data page opens the Data screen with the same filters.
  const open = (url: string) => {
    const data = dataRouteForLink(url);
    if (data) router.push({ pathname: "/data", params: data });
    else openServerPage(bootstrap.user.user_id, url);
  };
  const failed = error ? (
    <View style={{ gap: spacing.xs }}>
      <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{`${t("statsLoadFailed")}\n${error}`}</Text>
      <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={() => setRetry((count) => count + 1)} />
    </View>
  ) : null;

  if (projects && projects.length === 0 && !error) {
    return <WebShell title={t("statsTitle")}><Text style={muted}>{t("statsNoProjects")}</Text></WebShell>;
  }

  // Another project's numbers are never shown under this project's name; the same project's stay (dimmed) while the next level loads.
  const summary = loaded && loaded.selection.project === project ? loaded.data : null;
  const card = summary?.card;
  const counts = card?.counts;
  const showReported = summary ? hasDeathRegister([summary.card.counts, ...summary.rows.map((row) => row.counts)]) : true;
  const scale = pipelineScale(summary?.rows ?? [], showReported);
  // A sites-mode site has no server breadcrumb: its one crumb is its own row.
  const crumbs = summary
    ? summary.breadcrumb.length
      ? summary.breadcrumb.map((crumb) => ({ id: crumb.org_unit_id, name: crumb.name }))
      : site ? [{ id: site, name: summary.rows.find((row) => row.key === site)?.name ?? site }] : []
    : [];
  const areaName = summary?.unit?.name ?? (site ? crumbs[0]?.name : undefined) ?? summary?.project_name ?? "";
  const days = card ? [
    ["statsMedianInterview", formatDays(card.medians.death_to_interview_days)],
    ["statsMedianCod", formatDays(card.medians.interview_to_final_cod_days)],
  ] as const : [];
  // The CSV is for the data on screen, so it waits for the level being loaded.
  const csv = loaded && !busy && summary ? areaCsvUrl(loaded.selection) : "";
  const canShowStaff = Boolean(summary && (summary.unit || summary.project_wide || site));
  const stations = summary?.project_card?.stations;
  const freshness = summary?.freshness;

  return (
    <WebShell title={t("statsTitle")}>
      {failed}
      {projects && projects.length > 1 ? (
        projects.length > PROJECT_BUTTONS_MAX ? (
          <SelectRow
            label={t("statsProject")}
            options={projects.map((row) => ({ value: row.project_id, label: row.project_name }))}
            value={project}
            onChange={choose}
          />
        ) : (
          <ChoiceRow
            label={t("statsProject")}
            options={projects.map((row) => ({ value: row.project_id, label: row.project_name }))}
            value={project}
            onChange={choose}
          />
        )
      ) : null}
      <ChoiceRow
        label={t("statsPeriod")}
        options={PERIODS.map((value) => ({ value, label: t(PERIOD_LABELS[value]) }))}
        value={period}
        onChange={(next) => go({ period: next })}
      />

      {!summary && !error ? (
        <View style={{ minHeight: LOADING_MIN_HEIGHT }}><Text style={muted}>{t("loading")}</Text></View>
      ) : null}

      {summary && card && counts ? (
        <View accessibilityState={{ busy }} style={{ gap: spacing.md, opacity: busy ? 0.55 : 1 }}>
          {crumbs.length ? (
            <View accessibilityRole="toolbar" accessibilityLabel={t("statsPath")} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.xxs }}>
              <StatPressable label={t("statsAllAreas")} onPress={() => drill({})} style={{ minHeight: 44, justifyContent: "center" }}>
                <Text style={{ fontSize: fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{t("statsAllAreas")}</Text>
              </StatPressable>
              {crumbs.map((crumb, index) => {
                const last = index === crumbs.length - 1;
                return (
                  <View key={crumb.id} style={{ flexDirection: "row", alignItems: "center", columnGap: spacing.xxs }}>
                    <Text style={muted}>{"›"}</Text>
                    {last ? (
                      <Text accessibilityState={{ selected: true }} style={{ fontSize: fontSize.body, fontWeight: "600", color: ui.foreground }}>{crumb.name}</Text>
                    ) : (
                      <StatPressable label={crumb.name} onPress={() => drill({ unit: crumb.id })} style={{ minHeight: 44, justifyContent: "center" }}>
                        <Text style={{ fontSize: fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{crumb.name}</Text>
                      </StatPressable>
                    )}
                  </View>
                );
              })}
            </View>
          ) : null}

          <View style={{ gap: spacing.xs }}>
            <Text accessibilityRole="header" style={{ ...typography.title, color: ui.foreground }}>{areaName}</Text>
            <Text style={{ ...typography.body, color: ui.foreground }}>
              {showReported
                ? t("statsSummary", { reported: counts.deaths_reported, interviewed: counts.submitted, coded: counts.final_cod })
                : t("statsSummaryNoRegister", { interviewed: counts.submitted, coded: counts.final_cod })}
            </Text>
            {[
              counts.pending_over_7_days > 0 ? t("statsPendingOver7", { count: counts.pending_over_7_days }) : "",
              counts.pending_over_30_days > 0 ? t("statsPendingOver30", { count: counts.pending_over_30_days }) : "",
              counts.smartva_failed > 0 ? t("statsSmartvaFailed", { count: counts.smartva_failed }) : "",
            ].filter(Boolean).map((flag) => <Text key={flag} style={{ fontSize: fontSize.body, color: ui.warningText }}>{flag}</Text>)}
            {days.some(([, value]) => value !== null) ? (
              <>
                {days.map(([key, value]) => (value === null ? null : <Text key={key} style={muted}>{t(key, { days: value })}</Text>))}
                <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("statsMediansAllTime")}</Text>
              </>
            ) : <Text style={muted}>{t("statsMediansNone")}</Text>}
            <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.md }}>
              {Object.entries(card.links).map(([key, url]) => (LINK_LABELS[key] ? <TextAction key={key} label={t(LINK_LABELS[key])} onPress={() => open(url)} /> : null))}
              {csv ? <TextAction label={t("statsCsv")} onPress={() => window.location.assign(csv)} /> : null}
            </View>
            {freshness ? (
              <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>
                {freshness.snapshot_refreshed_display
                  ? t("statsFreshness", { live: freshness.live_at_display ?? "", snapshot: freshness.snapshot_refreshed_display })
                  : t("statsFreshnessNoSnapshot", { live: freshness.live_at_display ?? "" })}
              </Text>
            ) : null}
          </View>

          {site ? null : (
            <View style={{ gap: spacing.xxs }}>
              <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{t("statsRowsHeading")}</Text>
              <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t(showReported ? "statsPipelineKey" : "statsPipelineKeyNoRegister")}</Text>
              {summary.rows.length ? (
                summary.rows.map((row) => {
                  const submittedUrl = row.links?.submitted;
                  return (
                    <PipelineRow
                      key={`${row.kind}:${row.key}`}
                      row={row}
                      scale={scale}
                      showReported={showReported}
                      onOpen={canDrill(row) ? () => drill(row.kind === "site" ? { site: row.key } : { unit: row.key }) : undefined}
                      link={submittedUrl ? { label: t("statsLinkSubmitted"), onPress: () => open(submittedUrl) } : undefined}
                    />
                  );
                })
              ) : <Text style={muted}>{t("statsNoRows")}</Text>}
            </View>
          )}

          <CausesList causes={card.causes} />

          {stations ? (
            <View style={{ gap: spacing.xxs }}>
              <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{t("statsStationsHeading")}</Text>
              <Text style={{ ...typography.body, color: ui.foreground }}>{t("statsStationsLine", { active: stations.active, never: stations.never_synced })}</Text>
              {stations.latest_bundle_at_display ? <Text style={muted}>{t("statsStationsLatest", { time: stations.latest_bundle_at_display })}</Text> : null}
              {stations.oldest_last_bundle_at_display ? <Text style={muted}>{t("statsStationsOldest", { time: stations.oldest_last_bundle_at_display })}</Text> : null}
            </View>
          ) : null}

          {canShowStaff ? (
            <View style={{ gap: spacing.xs }}>
              <Button
                kind="secondary"
                size="sm"
                label={t(staffOpen ? "statsStaffHide" : "statsStaffShow")}
                expanded={staffOpen}
                onPress={() => setStaffOpen((current) => !current)}
                style={{ alignSelf: "flex-start" }}
              />
              {staffOpen ? (
                <View style={{ gap: spacing.xs }}>
                  <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{t("statsStaffHeading")}</Text>
                  {staffBusy ? <Text style={muted}>{t("statsStaffLoading")}</Text> : null}
                  {staffError ? <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{staffError}</Text> : null}
                  {staff?.staff_identity_redacted ? <Text style={muted}>{t("statsStaffRedacted")}</Text> : null}
                  {staff && !staffBusy && !staff.staff_identity_redacted && staff.interviewers.length === 0 ? <Text style={muted}>{t("statsStaffNone")}</Text> : null}
                  {staff?.interviewers.map((person, index) => (
                    <Text
                      key={`${person.name}:${index}`}
                      style={{ fontSize: fontSize.body, color: ui.foreground }}
                    >
                      {t("statsStaffRow", {
                        name: person.name, registered: person.cases_registered, started: person.interviews_started,
                        submitted: person.submitted, inProgress: person.in_progress, attempts: person.contact_attempts_30_days,
                      })}
                    </Text>
                  ))}
                  {staff?.truncated ? <Text style={muted}>{t("statsStaffTruncated")}</Text> : null}
                </View>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}
    </WebShell>
  );
}
