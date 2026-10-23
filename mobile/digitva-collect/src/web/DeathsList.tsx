import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import { intakeContextFromAccess } from "../api";
import { getCases, type CaseRow, type ClientBootstrap } from "../client/api";
import { useAppState } from "../AppState";
import { canStartDeathInterview } from "../deathWorkflow";
import { CodeNowButton } from "../workspace/CodeNowButton";
import { createWorkspaceApi } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, stateLabel, useUiStyles } from "../ui";
import { browserErrorText } from "./common";
import {
  appliedAdvancedChips, CaseFilterBar, EMPTY_ADVANCED, isInternalPlaceholderUnit, matchesAdvanced, useAreaFilter, withinLastDays,
  type AdvancedFilters,
} from "./caseFilters";
import { AddIdentifierAction, IdentifierFacts } from "./CaseIdentifiers";
import { MapsPinButton } from "./LocationCapture";
import { rememberCasePreviews } from "./newCasePreview";

/**
 * The reported-deaths list (docs/policy/case-list-views.md): the one list the
 * VA Interview "Reported deaths" tab and the Deaths screen both show, from
 * GET /intake/cases (the caller's interviewer scope plus the deaths they
 * registered as a death_reporter). Filters are client side over the loaded
 * pages, except Project, which re-fetches on the server.
 */

export function sexLabel(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = value.toLowerCase();
  const key = `sex${normalized[0]?.toUpperCase() ?? ""}${normalized.slice(1)}` as StringKey;
  const label = t(key);
  return label === key ? value : label;
}

export function formatDisplayTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return trimmed;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

const TERMINAL_CASE_STATES = new Set(["completed", "submitted", "cancelled", "closed", "duplicate", "not_codeable"]);
const VISIT_CASE_STATES = new Set(["registered", "scheduled", "not_reachable", "paused", "pending"]);
const IN_PROGRESS_CASE_STATES = new Set(["in_progress", "draft_identity", "active"]);
const WARNING_CASE_STATES = new Set(["not_reachable", "paused", "refused"]);

type DeathStatusFilter = "all" | "to_visit" | "in_progress" | "submitted" | "ready_to_code";

function matchesStatusFilter(row: CaseRow, filter: DeathStatusFilter): boolean {
  if (filter === "all") return true;
  const rawState = (row.state ?? row.status ?? "").toLowerCase();
  if (filter === "ready_to_code") return row.code_now === true;
  const done = TERMINAL_CASE_STATES.has(rawState) || rawState === "refused" || row.other_complete_interview === true;
  if (filter === "submitted") return done;
  if (filter === "in_progress") {
    return IN_PROGRESS_CASE_STATES.has(rawState) || Boolean(row.my_draft_id) || row.other_draft_active === true;
  }
  if (done) return false;
  return VISIT_CASE_STATES.has(rawState) || (!row.my_draft_id && !IN_PROGRESS_CASE_STATES.has(rawState));
}

/** A user whose only death role is death_reporter: the list opens on their own registrations. */
export function reporterOnly(bootstrap: Pick<ClientBootstrap, "access"> | undefined): boolean {
  const roles = bootstrap?.access.roles ?? [];
  return roles.includes("death_reporter") && !bootstrap?.access.is_admin &&
    !roles.some((role) => ["admin", "interviewer", "interview_supervisor", "data_manager"].includes(role));
}

/** The case ID's face; the theme has no monospace token. */
const MONOSPACE = Platform.select({ web: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", ios: "Menlo", default: "monospace" });

/**
 * Card styles shared by both case lists (reported deaths and My interviews). Every card text is >= 14px
 * in `colors.text`, the one token with >= 7:1 on the card in both modes (ui-token-contrast test); facts
 * are plain text, not chips. No fixed heights, so 200% zoom and text spacing wrap instead of clipping.
 */
export function useCaseCardStyles() {
  const { colors, ui } = useTheme();
  return useMemo(() => StyleSheet.create({
    line: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", columnGap: spacing.md, rowGap: spacing.xxs },
    titleGroup: { flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", columnGap: spacing.sm, rowGap: spacing.xxs, flexShrink: 1, minWidth: 0 },
    cardTitle: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    factList: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.md, rowGap: spacing.xxs },
    factLine: { flexGrow: 1, justifyContent: "space-between" },
    fact: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    caseId: { ...typography.subhead, color: colors.text, fontFamily: MONOSPACE },
    badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    badge: { paddingVertical: spacing.xxs / 2, paddingHorizontal: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    badgeAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    badgeWarning: { borderColor: ui.warningBorder, backgroundColor: ui.warning },
    badgeText: { ...typography.subhead, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    badgeAccentText: { color: ui.accentForeground },
    badgeWarningText: { color: ui.warningForeground },
    noticeBanner: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    noticeBannerDanger: { borderColor: colors.danger, backgroundColor: colors.dangerSoft },
    noticeBannerAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    noticeText: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    cardActions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
    actionButton: { minHeight: controls.minTouchTarget },
    listHeader: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
  }), [colors, ui]);
}

/** One fact of a card: its visible text and, for a bare value, the name a screen reader hears instead. */
type CaseFact = { key: string; text: string; a11y?: string };
export type CaseBadge = { label: string; tone?: "neutral" | "accent" | "warning" };

/** A row of facts as a list (role list / listitem), so a screen reader hears each as one named item. */
function FactList({ facts, style }: { facts: CaseFact[]; style?: object }) {
  const c = useCaseCardStyles();
  if (facts.length === 0) return null;
  return (
    <View role="list" style={[c.factList, style]}>
      {facts.map((fact) => (
        <Text key={fact.key} role="listitem" accessibilityLabel={fact.a11y} style={c.fact} testID={`case-fact-${fact.key}`}>{fact.text}</Text>
      ))}
    </View>
  );
}

/**
 * The one case card of both case lists (docs/current-state/expo-client.md, "Case cards"). Line 1: name,
 * age, sex and the status badges; line 2: date of death, area; line 3: last contact, next visit
 * and *extra* facts; then *children* (notices); line 4: *actions* with the map pin, and the case ID on
 * the right. Empty items are omitted; on a narrow screen items wrap in the same order. The map pin shows
 * only when the row carries a GPS fix (the server sends one only to callers who may see it).
 */
export function CaseCard({
  title, titleTestID, caseId, ageYears, sex, dateOfDeath, area, lastContactAt, nextVisitAt,
  extra = [], badges, actions, latitude, longitude, testID, children,
}: {
  title: string;
  titleTestID?: string;
  caseId?: string | null;
  ageYears?: number | null;
  sex?: string | null;
  dateOfDeath?: string | null;
  area?: string;
  lastContactAt?: string | null;
  nextVisitAt?: string | null;
  extra?: CaseFact[];
  badges: CaseBadge[];
  actions: ReactNode;
  latitude?: number | null;
  longitude?: number | null;
  testID?: string;
  children?: ReactNode;
}) {
  const styles = useUiStyles();
  const c = useCaseCardStyles();
  const sexText = sexLabel(sex);
  const identity: CaseFact[] = [
    ...(ageYears != null ? [{ key: "age", text: t("metaAgeYears", { value: ageYears }), a11y: t("metaAgeA11y", { value: ageYears }) }] : []),
    ...(sexText ? [{ key: "sex", text: sexText, a11y: t("metaSexA11y", { value: sexText }) }] : []),
  ];
  const death: CaseFact[] = [
    ...(dateOfDeath ? [{ key: "died", text: t("metaDied", { value: dateOfDeath }), a11y: t("metaDiedA11y", { value: dateOfDeath }) }] : []),
    ...(area ? [{ key: "area", text: t("metaArea", { value: area }) }] : []),
  ];
  const contact: CaseFact[] = [
    ...(lastContactAt ? [{ key: "lastContact", text: t("metaLastContact", { value: formatDisplayTimestamp(lastContactAt) }) }] : []),
    ...(nextVisitAt ? [{ key: "nextVisit", text: t("actionVisit", { date: formatDisplayTimestamp(nextVisitAt) }) }] : []),
    ...extra,
  ];
  return (
    <View style={styles.card} testID={testID}>
      <View style={c.line}>
        <View style={c.titleGroup}>
          <Text style={c.cardTitle} testID={titleTestID}>{title}</Text>
          <FactList facts={identity} />
        </View>
        {badges.length > 0 ? (
          <View style={c.badgeRow}>
            {badges.map((badge) => (
              <View key={badge.label} style={[c.badge, badge.tone === "accent" && c.badgeAccent, badge.tone === "warning" && c.badgeWarning]}>
                <Text style={[c.badgeText, badge.tone === "accent" && c.badgeAccentText, badge.tone === "warning" && c.badgeWarningText]}>{badge.label}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
      <FactList facts={death} style={c.factLine} />
      <FactList facts={contact} style={c.factLine} />
      {children}
      <View style={c.line}>
        <View style={c.cardActions}>
          {actions}
          <MapsPinButton latitude={latitude} longitude={longitude} />
        </View>
        {caseId ? <FactList facts={[{ key: "caseId", text: caseId, a11y: t("metaCaseIdA11y", { value: caseId }) }]} style={{ marginLeft: "auto" }} /> : null}
      </View>
    </View>
  );
}

export type DeathCases = {
  cases: CaseRow[];
  counts: Record<string, number>;
  nextCursor: string | null;
  busy: boolean;
  message: string;
  project?: string;
  /** Reload the first page for the current project; false (and `message`) on failure. */
  refresh: () => Promise<boolean>;
  loadMore: () => Promise<void>;
  /** Project is the one server-side filter: re-fetch the first page for it. */
  changeProject: (next: string | undefined) => Promise<void>;
};

/**
 * The reported-deaths pages of the signed-in user. A reply for an earlier
 * bootstrap, an unmounted list or another project is dropped, so one user's
 * rows never reach the next user's screen.
 */
export function useDeathCases(bootstrap: ClientBootstrap | undefined): DeathCases {
  const training = bootstrap?.scope === "training";
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [project, setProject] = useState<string | undefined>(undefined);
  const projectRef = useRef<string | undefined>(undefined);
  const mounted = useRef(false);
  const bootstrapRef = useRef(bootstrap);
  const generationRef = useRef(0);
  if (bootstrapRef.current !== bootstrap) {
    bootstrapRef.current = bootstrap;
    generationRef.current += 1;
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setCases([]);
    setCounts({});
    setNextCursor(null);
    setBusy(false);
    setMessage("");
    setProject(undefined);
    projectRef.current = undefined;
  }, [bootstrap]);

  /** Fetch one page; apply it only while the bootstrap, mount and project still match. */
  const fetchPage = useCallback(async (cursor: string | null, apply: (result: Awaited<ReturnType<typeof getCases>>) => void) => {
    if (!bootstrap) return false;
    const generation = generationRef.current;
    const requested = projectRef.current;
    const isCurrent = () => mounted.current && generationRef.current === generation && bootstrapRef.current === bootstrap;
    setBusy(true);
    setMessage("");
    try {
      const result = await getCases(bootstrap.links.intakeCases, bootstrap.csrf, cursor, requested, training);
      if (!isCurrent()) return false;
      rememberCasePreviews(bootstrap, result.cases ?? []);
      if (projectRef.current === requested) apply(result);
      return true;
    } catch (error) {
      if (isCurrent()) setMessage(browserErrorText(error));
      return false;
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }, [bootstrap, training]);

  const replace = useCallback((result: Awaited<ReturnType<typeof getCases>>) => {
    setCases(result.cases ?? []);
    setCounts(result.counts ?? {});
    setNextCursor(result.next_cursor ?? null);
  }, []);

  const refresh = useCallback(() => fetchPage(null, replace), [fetchPage, replace]);

  const loadMore = useCallback(async () => {
    if (!nextCursor) return;
    await fetchPage(nextCursor, (result) => {
      setCases((previous) => [...previous, ...(result.cases ?? [])]);
      setNextCursor(result.next_cursor ?? null);
    });
  }, [fetchPage, nextCursor]);

  const changeProject = useCallback(async (next: string | undefined) => {
    if (!bootstrap || projectRef.current === next) return;
    projectRef.current = next;
    setProject(next);
    setCases([]);
    setCounts({});
    setNextCursor(null);
    await fetchPage(null, replace);
  }, [bootstrap, fetchPage, replace]);

  return { cases, counts, nextCursor, busy, message, project, refresh, loadMore, changeProject };
}

/**
 * The list with its filter bar and cards. *headerAction* sits above the bar
 * (the Deaths screen's "Register a death"). Edit opens the registration
 * form; a death reached only as its reporter opens it from the reporter's own
 * registrations (`registered=mine`), as the case detail is the interviewer's.
 */
export function DeathsList({ list, headerAction }: { list: DeathCases; headerAction?: ReactNode }) {
  const router = useRouter();
  const appState = useAppState();
  const { bootstrap } = appState;
  const styles = useUiStyles();
  const c = useCaseCardStyles();
  const workspaceApi = useMemo(
    () => bootstrap ? createWorkspaceApi(createWebWorkspaceTransport(bootstrap.csrf)) : undefined,
    [bootstrap?.csrf, bootstrap?.user.user_id],
  );
  const canCode = bootstrap?.access.roles.some((role) => role === "coder" || role === "coding_tester") === true;
  const training = bootstrap?.scope === "training";
  const mayInterview = bootstrap?.capabilities.intake === true;
  // Projects whose registrations this user may edit: the contexts the registration screen opens
  // (a direct-only interviewer has none, and would land on "no collection access").
  const registerProjects = useMemo(() => new Set(bootstrap ? intakeContextFromAccess(bootstrap.access, "register_death")
    .filter((entry) => entry.web_intake_mode === "death_register" || entry.web_intake_mode === "both")
    .map((entry) => entry.project_id) : []), [bootstrap]);
  const defaultMine = reporterOnly(bootstrap);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<DeathStatusFilter>("all");
  const [unit, setUnit] = useState<string | undefined>(undefined);
  const [advanced, setAdvanced] = useState<AdvancedFilters>(EMPTY_ADVANCED);
  const [mine, setMine] = useState(defaultMine);
  const [last30, setLast30] = useState(false);

  useEffect(() => {
    setSearch("");
    setStatus("all");
    setUnit(undefined);
    setAdvanced(EMPTY_ADVANCED);
    setMine(reporterOnly(bootstrap));
    setLast30(false);
  }, [bootstrap]);

  // Projects the user interviews or registers deaths in; the Project filter shows only with more than one.
  const context = useMemo(() => bootstrap ? [
    ...intakeContextFromAccess(bootstrap.access, "interview"),
    ...intakeContextFromAccess(bootstrap.access, "register_death"),
  ] : [], [bootstrap]);
  const projectOptions = useMemo(() => {
    const byId = new Map<string, string>();
    for (const entry of context) if (!byId.has(entry.project_id)) byId.set(entry.project_id, entry.project_name ?? entry.project_id);
    return Array.from(byId, ([value, label]) => ({ value, label }));
  }, [context]);

  const rowUnits = useMemo(() => list.cases.map((row) => ({ id: row.org_unit_id, name: row.unit_name ?? row.org_unit_name })), [list.cases]);
  const { orgLookup, unitOptions, unitMatches } = useAreaFilter(bootstrap?.access.projects, context, rowUnits, list.project);
  const hasReadyToCode = useMemo(() => list.cases.some((row) => row.code_now === true), [list.cases]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    const now = new Date();
    return list.cases.filter((row) => {
      if (!matchesStatusFilter(row, status)) return false;
      if (mine && row.registered_by_me !== true) return false;
      if (last30 && !withinLastDays(row.created_at, 30, now)) return false;
      const rowUnit = (row.unit_name ?? row.org_unit_name ?? "").trim();
      if (!unitMatches(unit, row.org_unit_id, rowUnit)) return false;
      if (!matchesAdvanced(row, advanced)) return false;
      if (!query) return true;
      const info = (row.org_unit_id ? orgLookup.byId.get(row.org_unit_id) : undefined) ?? orgLookup.byName.get(rowUnit);
      return [row.deceased_name, row.unique_id, row.unit_name, row.org_unit_name, info?.breadcrumb, info?.code,
        row.site_name, row.date_of_death]
        .filter(Boolean).join(" ").toLowerCase().includes(query);
    });
  }, [advanced, last30, list.cases, mine, orgLookup, search, status, unit, unitMatches]);

  const filtersActive = search.trim().length > 0 || status !== "all" || unit !== undefined || mine || last30 ||
    appliedAdvancedChips(advanced, "").length > 0;
  const clearAll = () => {
    setSearch("");
    setStatus("all");
    setUnit(undefined);
    setAdvanced(EMPTY_ADVANCED);
    // Clear all returns the toggles to the role's defaults, not to a wider view.
    setMine(defaultMine);
    setLast30(false);
    void list.changeProject(undefined);
  };
  const openEdit = (row: CaseRow) => router.push({
    pathname: training ? "/training/register" : "/death-registration",
    params: { deathId: row.death_id, ...(row.can_interview === false ? { registered: "mine" } : {}) },
  });

  return (
    <>
      {headerAction ? <View style={c.listHeader}>{headerAction}</View> : null}
      {list.cases.length > 0 || list.project || mine || last30 ? (
        <CaseFilterBar<DeathStatusFilter>
          search={search}
          onSearch={setSearch}
          statusChips={[
            { key: "all", label: t("filterAll") },
            { key: "to_visit", label: t("filterToVisit") },
            { key: "in_progress", label: t("filterInProgress") },
            { key: "submitted", label: t("filterSubmitted") },
            ...(hasReadyToCode ? [{ key: "ready_to_code" as const, label: t("filterReadyToCode") }] : []),
          ]}
          status={status}
          allStatus="all"
          onStatus={setStatus}
          toggles={[
            { key: "mine", on: mine, onLabel: t("filterMine"), offLabel: t("filterAll"), a11yLabel: (label) => t("filterWhoseLabel", { label }), onChange: setMine },
            { key: "last30", on: last30, onLabel: t("filterLast30Days"), offLabel: t("filterAll"), a11yLabel: (label) => t("filterPeriodLabel", { label }), onChange: setLast30 },
          ]}
          projects={projectOptions}
          project={list.project}
          onProject={(next) => void list.changeProject(next)}
          units={unitOptions}
          unit={unit}
          onUnit={setUnit}
          advanced={advanced}
          onAdvanced={setAdvanced}
          reportedLabel={t("filterDateReported")}
          onClearAll={clearAll}
        />
      ) : null}
      {list.message ? <Text style={styles.error} accessibilityRole="alert">{list.message}</Text> : null}
      {filtersActive && list.nextCursor ? (
        <Text style={styles.muted}>{t("filteringLoadedCases", { shown: filtered.length, loaded: list.cases.length })}</Text>
      ) : null}
      {list.cases.length === 0 && !list.message ? <Text style={styles.muted}>{list.busy ? t("loading") : t("noReportedDeaths")}</Text> : null}
      {list.cases.length > 0 && filtered.length === 0 ? <Text style={styles.muted}>{t("noMatchingCases")}</Text> : null}
      {filtered.map((row) => {
        const rawState = row.state ?? row.status ?? "";
        const state = rawState.toLowerCase();
        const rawUnit = row.unit_name ?? row.org_unit_name ?? row.site_name;
        const unitLabel = rawUnit && !isInternalPlaceholderUnit(rawUnit) ? rawUnit : undefined;
        // Interview actions and the case detail need an interviewer grant that reaches the case.
        const interviewable = mayInterview && row.can_interview !== false;
        const codeNow = canCode && row.code_now === true && typeof row.va_sid === "string" && workspaceApi;
        const resume = interviewable && Boolean(row.my_draft_id) && !TERMINAL_CASE_STATES.has(state);
        const start = interviewable && !row.my_draft_id && canStartDeathInterview(rawState) && row.other_complete_interview !== true &&
          row.other_draft_active !== true && row.details_pending !== true;
        const edit = row.other_complete_interview !== true && row.details_pending !== true &&
          typeof row.project_id === "string" && registerProjects.has(row.project_id);
        // One primary action per card: the first of code, resume, start, edit, view.
        const primary = codeNow ? "code" : resume ? "resume" : start ? "start" : edit ? "edit" : "view";
        const kind = (action: string) => primary === action ? "primary" as const : "secondary" as const;
        const badges: CaseBadge[] = [{
          label: stateLabel(rawState || "registered"),
          tone: WARNING_CASE_STATES.has(state) ? "warning" : IN_PROGRESS_CASE_STATES.has(state) ? "accent" : "neutral",
        }];
        if (row.my_draft_id && !TERMINAL_CASE_STATES.has(state) && !IN_PROGRESS_CASE_STATES.has(state)) {
          badges.push({ label: t("draftInProgress"), tone: "accent" });
        }
        return (
          <CaseCard
            key={row.death_id}
            testID={`death-card-${row.death_id}`}
            title={row.deceased_name || row.unique_id}
            titleTestID="death-card-title"
            caseId={row.deceased_name ? row.unique_id : undefined}
            ageYears={row.age_years}
            sex={row.deceased_sex}
            dateOfDeath={row.date_of_death}
            area={unitLabel}
            lastContactAt={row.last_contact_at}
            nextVisitAt={row.next_visit_at}
            latitude={row.latitude}
            longitude={row.longitude}
            badges={badges}
            actions={<>
              {codeNow && workspaceApi && typeof row.va_sid === "string" ? <CodeNowButton
                api={workspaceApi}
                vaSid={row.va_sid}
                onOpen={(vaSid) => router.push({ pathname: "/workspace", params: { vaSid, mode: "coding" } })}
                onAccessLost={() => {
                  void appState.reload();
                  router.replace("/workspace");
                }}
              /> : null}
              {resume ? (
                <Button size="sm" style={c.actionButton} kind={kind("resume")} label={t("resumeInterview")} onPress={() => router.push({ pathname: "/interview", params: {
                  draftId: row.my_draft_id!, ...(row.project_id ? { projectId: row.project_id } : {}), ...(row.site_id ? { siteId: row.site_id } : {}),
                  ...(row.org_unit_id ? { orgUnitId: row.org_unit_id } : {}),
                } })} />
              ) : null}
              {start ? (
                <Button size="sm" style={c.actionButton} kind={kind("start")} label={t("startInterview")} onPress={() => router.push({ pathname: "/interview", params: { deathId: row.death_id } })} />
              ) : null}
              {edit ? <Button size="sm" style={c.actionButton} kind={kind("edit")} label={t("editRegistration")} onPress={() => openEdit(row)} /> : null}
              {interviewable ? (
                <Button size="sm" style={c.actionButton} kind={kind("view")} label={t("viewDetails")} onPress={() => router.push({ pathname: "/case", params: { deathId: row.death_id } })} />
              ) : null}
              <AddIdentifierAction row={row} onChanged={() => void list.refresh()} />
            </>}
          >
            <IdentifierFacts identifiers={row.identifiers} variant="card" />
            {row.other_draft_active === true ? (
              <View style={[c.noticeBanner, c.noticeBannerDanger]}>
                <Text style={c.noticeText} accessibilityRole="alert">{otherDraftNotice(row.other_draft_started_at)}</Text>
              </View>
            ) : null}
            {row.other_complete_interview === true ? (
              <View style={c.noticeBanner}><Text style={c.noticeText}>{t("otherCompleteInterviewNotice")}</Text></View>
            ) : null}
            {row.code_now === true ? (
              <View style={[c.noticeBanner, c.noticeBannerAccent]}><Text style={c.noticeText}>{t("readyForCode")}</Text></View>
            ) : null}
          </CaseCard>
        );
      })}
      {list.nextCursor ? <Button kind="secondary" loading={list.busy} label={t("loadMore")} onPress={() => void list.loadMore()} /> : null}
    </>
  );
}

/** The list loading its own pages, for a screen that has no other data to refresh with it. */
export function DeathsListPanel({ headerAction }: { headerAction?: ReactNode }) {
  const { bootstrap } = useAppState();
  const list = useDeathCases(bootstrap);
  const { refresh } = list;
  useEffect(() => { void refresh(); }, [refresh]);
  return <DeathsList list={list} headerAction={headerAction} />;
}

function otherDraftNotice(startedAt: string | null | undefined): string {
  if (typeof startedAt === "string") {
    const date = new Date(startedAt);
    if (!Number.isNaN(date.getTime())) return t("otherDraftActiveAt", { date: date.toLocaleString() });
  }
  return t("otherDraftActive");
}
