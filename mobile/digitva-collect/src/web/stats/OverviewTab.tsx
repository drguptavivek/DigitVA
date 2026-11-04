import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { areaCsvUrl, getAreaStaff, type AreaStaff, type AreaSummary } from "../../area/api";
import { t, type StringKey } from "../../i18n";
import { fontSize, spacing, typography, useTheme } from "../../theme";
import type { JsonRequester } from "../../workspace/api";
import { Button } from "../../ui";
import { browserErrorText } from "../common";
import { CausesList } from "./CausesList";
import { StatPressable, TextAction } from "./controls";
import { canDrill, formatDays, hasDeathRegister, pipelineScale } from "./pipeline";
import { PipelineRow } from "./PipelineRow";
import { sumCounts, type StageCounts } from "./view";

/** Which count a server link belongs to, and how to say where it leads. */
const LINK_LABELS: Record<string, StringKey> = {
  submitted: "statsLinkSubmitted", awaiting_coding: "statsLinkAwaiting", visit_notes: "statsLinkVisitNotes",
};

/** Reported -> Interviewed -> Coded with the number under each; Reported is left out without a death register. */
export function StageLine({ counts, showReported }: { counts: StageCounts; showReported: boolean }) {
  const { ui } = useTheme();
  const stages = [
    ...(showReported ? [{ key: "statsStageReported" as const, value: counts.deaths_reported }] : []),
    { key: "statsStageInterviewed" as const, value: counts.submitted },
    { key: "statsStageCoded" as const, value: counts.final_cod },
  ];
  const spoken = showReported
    ? t("statsSummary", { reported: counts.deaths_reported, interviewed: counts.submitted, coded: counts.final_cod })
    : t("statsSummaryNoRegister", { interviewed: counts.submitted, coded: counts.final_cod });
  return (
    <View accessible accessibilityLabel={spoken} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.md, rowGap: spacing.xs }}>
      {stages.map((stage, index) => (
        <View key={stage.key} style={{ flexDirection: "row", alignItems: "center", columnGap: spacing.md }}>
          {index > 0 ? <Text style={{ fontSize: fontSize.body, color: ui.mutedForeground }}>{"→"}</Text> : null}
          <View style={{ gap: spacing.xxs }}>
            <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t(stage.key)}</Text>
            <Text style={{ ...typography.title, color: ui.foreground }}>{String(stage.value)}</Text>
          </View>
        </View>
      ))}
    </View>
  );
}

/**
 * The overdue counts as one warning line, each part a link into its filtered tab. Nothing while the server sends no
 * thresholds (an older server) or nothing is overdue.
 */
export function AttentionLine({ counts, thresholds, onOpen }: {
  counts: StageCounts;
  thresholds: AreaSummary["thresholds"];
  onOpen?: (tab: "deaths" | "codings") => void;
}) {
  const { ui } = useTheme();
  if (!thresholds) return null;
  const parts = [
    counts.overdue_interview > 0 ? { tab: "deaths" as const, text: t("statsOverdueInterviews", { count: counts.overdue_interview, days: thresholds.interview_days }) } : null,
    counts.overdue_coding > 0 ? { tab: "codings" as const, text: t("statsOverdueCodings", { count: counts.overdue_coding, days: thresholds.coding_days }) } : null,
  ].filter((part) => part !== null);
  if (parts.length === 0) return null;
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.xs }}>
      {parts.map((part, index) => (
        <View key={part.tab} style={{ flexDirection: "row", alignItems: "center", columnGap: spacing.xs }}>
          {index > 0 ? <Text style={{ fontSize: fontSize.body, color: ui.warningText }}>{"·"}</Text> : null}
          {onOpen ? (
            <StatPressable label={part.text} onPress={() => onOpen(part.tab)} style={{ minHeight: 44, justifyContent: "center" }}>
              <Text style={{ fontSize: fontSize.body, color: ui.warningText, textDecorationLine: "underline" }}>{part.text}</Text>
            </StatPressable>
          ) : <Text style={{ fontSize: fontSize.body, color: ui.warningText }}>{part.text}</Text>}
        </View>
      ))}
    </View>
  );
}

export function Freshness({ freshness }: { freshness: AreaSummary["freshness"] | undefined }) {
  const { ui } = useTheme();
  if (!freshness) return null;
  return (
    <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>
      {freshness.snapshot_refreshed_display
        ? t("statsFreshness", { live: freshness.live_at_display ?? "", snapshot: freshness.snapshot_refreshed_display })
        : t("statsFreshnessNoSnapshot", { live: freshness.live_at_display ?? "" })}
    </Text>
  );
}

/** The medians that exist, one line each; with *fallback* the "appear once there are enough interviews" line when neither does. */
export function Medians({ summary, fallback = true }: { summary: AreaSummary; fallback?: boolean }) {
  const { ui } = useTheme();
  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  const days = [
    ["statsMedianInterview", formatDays(summary.card.medians.death_to_interview_days)],
    ["statsMedianCod", formatDays(summary.card.medians.interview_to_final_cod_days)],
  ] as const;
  return days.some(([, value]) => value !== null)
    ? <>{days.map(([key, value]) => (value === null ? null : <Text key={key} style={muted}>{t(key, { days: value })}</Text>))}</>
    : fallback ? <Text style={muted}>{t("statsMediansNone")}</Text> : null;
}

/**
 * Overview: the stage line and the attention line over every project in view (counts summed, never medians or
 * percentages), then, for one project, its area detail (path, unit bars, causes, stations, staff, CSV); for several,
 * only the freshness (each project's medians are on its Projects card). *summaries* are the projects in view, at the chosen area when there is one project.
 */
export function OverviewTab({ summaries, sole, unit, site, soleRoot, busy, pending, failedCount, onRetryFailed, request, onDrill, onAttention, onOpenLink }: {
  summaries: AreaSummary[];
  sole: AreaSummary | null;
  unit: string | null;
  site: string | null;
  soleRoot: string | null;
  busy: boolean;
  /** Projects still loading and failed (several projects only); the lines above cover those that have answered. */
  pending: number;
  failedCount: number;
  onRetryFailed: () => void;
  request: JsonRequester;
  onDrill: (next: { unit?: string | null; site?: string | null }) => void;
  onAttention: (tab: "deaths" | "codings") => void;
  onOpenLink: (url: string) => void;
}) {
  const { ui } = useTheme();
  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  const counts = sumCounts(summaries.map((one) => one.card.counts));
  const showReported = hasDeathRegister(summaries.flatMap((one) => [one.card.counts, ...one.rows.map((row) => row.counts)]));
  return (
    <View accessibilityState={{ busy }} style={{ gap: spacing.md, opacity: busy ? 0.55 : 1 }}>
      {summaries.length ? (
        <View style={{ gap: spacing.xs }}>
          <StageLine counts={counts} showReported={showReported} />
          <AttentionLine counts={counts} thresholds={summaries[0]?.thresholds} onOpen={onAttention} />
        </View>
      ) : null}
      {pending ? <Text style={muted}>{t(pending === 1 ? "statsLoadingMoreOne" : "statsLoadingMore", { count: pending })}</Text> : null}
      {failedCount ? (
        <View style={{ gap: spacing.xs }}>
          <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{t(failedCount === 1 ? "statsSomeFailedOne" : "statsSomeFailed", { count: failedCount })}</Text>
          <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={onRetryFailed} style={{ alignSelf: "flex-start" }} />
        </View>
      ) : null}
      {sole ? (
        <AreaDetail summary={sole} unit={unit} site={site} soleRoot={soleRoot} busy={busy} request={request} showReported={showReported} onDrill={onDrill} onOpenLink={onOpenLink} />
      ) : summaries.length ? (
        <View style={{ gap: spacing.xs }}>
          <Freshness freshness={summaries[0]?.freshness} />
        </View>
      ) : null}
      {summaries.length === 0 && !failedCount ? <Text style={muted}>{t("loading")}</Text> : null}
    </View>
  );
}

/** One project's area: path, medians, links and CSV, unit bars, causes, stations and the by-interviewer list. */
function AreaDetail({ summary, unit, site, soleRoot, busy, request, showReported, onDrill, onOpenLink }: {
  summary: AreaSummary;
  unit: string | null;
  site: string | null;
  soleRoot: string | null;
  busy: boolean;
  request: JsonRequester;
  showReported: boolean;
  onDrill: (next: { unit?: string | null; site?: string | null }) => void;
  onOpenLink: (url: string) => void;
}) {
  const { ui } = useTheme();
  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  const { card } = summary;
  const project = summary.project_id;
  const [staffOpen, setStaffOpen] = useState(false);
  const [staff, setStaff] = useState<AreaStaff | null>(null);
  const [staffBusy, setStaffBusy] = useState(false);
  const [staffError, setStaffError] = useState("");

  // The by-interviewer list belongs to one project: a project change closes it.
  useEffect(() => {
    setStaffOpen(false);
    setStaff(null);
  }, [project]);

  useEffect(() => {
    if (!staffOpen) {
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

  const scale = pipelineScale(summary.rows, showReported);
  // A sites-mode site has no server breadcrumb: its one crumb is its own row.
  const crumbs = summary.breadcrumb.length
    ? summary.breadcrumb.map((crumb) => ({ id: crumb.org_unit_id, name: crumb.name }))
    : site ? [{ id: site, name: summary.rows.find((row) => row.key === site)?.name ?? site }] : [];
  const areaName = summary.unit?.name ?? (site ? crumbs[0]?.name : undefined) ?? summary.project_name;
  // The CSV is for the data on screen, so it waits for the level being loaded.
  const csv = busy ? "" : areaCsvUrl({ project, unit, site, period: summary.period });
  const canShowStaff = Boolean(summary.unit || summary.project_wide || site);
  const stations = summary.project_card?.stations;
  const { counts } = card;

  return (
    <View style={{ gap: spacing.md }}>
      {crumbs.length ? (
        <View accessibilityRole="toolbar" accessibilityLabel={t("statsPath")} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.xxs }}>
          {soleRoot ? null : (
            <StatPressable label={t("statsAllAreas")} onPress={() => onDrill({})} style={{ minHeight: 44, justifyContent: "center" }}>
              <Text style={{ fontSize: fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{t("statsAllAreas")}</Text>
            </StatPressable>
          )}
          {crumbs.map((crumb, index) => {
            const last = index === crumbs.length - 1;
            return (
              <View key={crumb.id} style={{ flexDirection: "row", alignItems: "center", columnGap: spacing.xxs }}>
                {index > 0 || !soleRoot ? <Text style={muted}>{"›"}</Text> : null}
                {last ? (
                  <Text accessibilityState={{ selected: true }} style={{ fontSize: fontSize.body, fontWeight: "600", color: ui.foreground }}>{crumb.name}</Text>
                ) : (
                  <StatPressable label={crumb.name} onPress={() => onDrill({ unit: crumb.id })} style={{ minHeight: 44, justifyContent: "center" }}>
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
        {[
          counts.pending_over_7_days > 0 ? t("statsPendingOver7", { count: counts.pending_over_7_days }) : "",
          counts.pending_over_30_days > 0 ? t("statsPendingOver30", { count: counts.pending_over_30_days }) : "",
          counts.smartva_failed > 0 ? t("statsSmartvaFailed", { count: counts.smartva_failed }) : "",
        ].filter(Boolean).map((flag) => <Text key={flag} style={{ fontSize: fontSize.body, color: ui.warningText }}>{flag}</Text>)}
        <Medians summary={summary} />
        <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("statsMediansAllTime")}</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.md }}>
          {Object.entries(card.links).map(([key, url]) => (LINK_LABELS[key] ? <TextAction key={key} label={t(LINK_LABELS[key])} onPress={() => onOpenLink(url)} /> : null))}
          {csv ? <TextAction label={t("statsCsv")} onPress={() => window.location.assign(csv)} /> : null}
        </View>
        <Freshness freshness={summary.freshness} />
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
                  onOpen={canDrill(row) ? () => onDrill(row.kind === "site" ? { site: row.key } : { unit: row.key }) : undefined}
                  link={submittedUrl ? { label: t("statsLinkSubmitted"), onPress: () => onOpenLink(submittedUrl) } : undefined}
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
                <Text key={`${person.name}:${index}`} style={{ fontSize: fontSize.body, color: ui.foreground }}>
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
  );
}
