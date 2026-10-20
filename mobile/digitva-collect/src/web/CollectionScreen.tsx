import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { getDrafts, getIntakeContext, type DraftSummary, type IntakeBootstrap } from "../client/api";
import { getSubmittedRevisions, type SubmittedRevisionSummary } from "../client/revisions";
import { useAppState } from "../AppState";
import { CodeNowButton } from "../workspace/CodeNowButton";
import { createWorkspaceApi } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { t } from "../i18n";
import { controls, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { CaseFilterBar, EMPTY_ADVANCED, isInternalPlaceholderUnit, matchesAdvanced, useAreaFilter, type AdvancedFilters } from "./caseFilters";
import { CaseCard, DeathsList, formatDisplayTimestamp, useCaseCardStyles, useDeathCases } from "./DeathsList";
import { DirectInterviewPanel, directInterviewTargets, RefreshIconButton } from "./DirectInterviewPanel";

type InterviewStatusFilter = "all" | "in_progress" | "submitted";
type CollectionTab = "interviews" | "deaths";

function validTab(value: unknown): CollectionTab | undefined {
  return value === "interviews" || value === "deaths" ? value : undefined;
}

/** One "My interviews" row: an open draft (resume) or a submitted interview (revise). */
type InterviewRow = (DraftSummary & { kind: "draft" }) | (SubmittedRevisionSummary & { kind: "submitted" });

function useCollectionStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    toolbarCard: { gap: spacing.sm },
    toolbarActions: { flex: 1, minWidth: 0, flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
    toolbarRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.xs },
    tabBar: { flexDirection: "row", borderBottomWidth: 1, borderColor: colors.border },
    tab: {
      flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xs,
      borderBottomWidth: 2, borderColor: "transparent",
    },
    tabOn: { borderColor: colors.accent },
    tabText: { ...typography.subhead, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily, textAlign: "center" },
    tabTextOn: { color: colors.text },
  }), [colors]);
}

/** Browser-only refresh signal; native test and state interfaces omit it. */
type BrowserNotificationRefresh = {
  notificationGeneration?: number;
  acknowledgeAuthoritativeRefresh?: (expectedRevision: number) => void;
};

/** Binds a refresh outcome to the notification revision it actually fetched. */
type AuthoritativeRefreshResult = {
  success: boolean;
  revision: number;
};

export default function CollectionScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    superseded?: string;
    submissionHistory?: string;
    submissionLocked?: string;
    canCodeNow?: string;
    readyUniqueId?: string;
    readyVaSid?: string;
    saved?: string;
    tab?: string;
  }>();
  const appState = useAppState() as ReturnType<typeof useAppState> & BrowserNotificationRefresh;
  const { bootstrap, notificationGeneration, acknowledgeAuthoritativeRefresh } = appState;
  const styles = useUiStyles();
  const c = useCollectionStyles();
  const card = useCaseCardStyles();
  const workspaceApi = useMemo(
    () => bootstrap ? createWorkspaceApi(createWebWorkspaceTransport(bootstrap.csrf)) : undefined,
    [bootstrap?.csrf, bootstrap?.user.user_id],
  );
  const canCode = bootstrap?.access.roles.some((role) => role === "coder" || role === "coding_tester") === true;
  const deaths = useDeathCases(bootstrap);
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [submitted, setSubmitted] = useState<SubmittedRevisionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [unitFilter, setUnitFilter] = useState<string | undefined>(undefined);
  const [interviewStatus, setInterviewStatus] = useState<InterviewStatusFilter>("all");
  const [advanced, setAdvanced] = useState<AdvancedFilters>(EMPTY_ADVANCED);
  const [projectFilter, setProjectFilter] = useState<string | undefined>(undefined);
  const [tabChoice, setTabChoice] = useState<CollectionTab | undefined>(validTab(params.tab));
  const refreshInFlight = useRef<{ generation: number; promise: Promise<AuthoritativeRefreshResult> } | undefined>(undefined);
  const notificationRevisionRef = useRef(notificationGeneration ?? 0);
  const pendingNotificationRevision = useRef<number | undefined>(undefined);
  const notificationRefreshInFlight = useRef<Promise<void> | undefined>(undefined);
  const requestNotificationRefreshRef = useRef<((revision: number) => Promise<void>) | undefined>(undefined);
  const acknowledgedNotificationRevision = useRef(0);
  const mounted = useRef(false);
  notificationRevisionRef.current = notificationGeneration ?? 0;
  const bootstrapRef = useRef(bootstrap);
  const generationRef = useRef(0);
  if (bootstrapRef.current !== bootstrap) {
    bootstrapRef.current = bootstrap;
    generationRef.current += 1;
    refreshInFlight.current = undefined;
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generationRef.current += 1;
      pendingNotificationRevision.current = undefined;
      refreshInFlight.current = undefined;
      notificationRefreshInFlight.current = undefined;
    };
  }, []);

  const loadIntake = useCallback(async () => {
    if (!bootstrap) throw new Error("authentication_required");
    return getIntakeContext(bootstrap.csrf);
  }, [bootstrap]);

  const refreshDeaths = deaths.refresh;
  const refresh = useCallback(async () => {
    const revision = notificationRevisionRef.current;
    if (!bootstrap || bootstrapRef.current !== bootstrap) return { success: false, revision };
    const generation = generationRef.current;
    const isCurrent = () => mounted.current && generationRef.current === generation && bootstrapRef.current === bootstrap;
    const existingRefresh = refreshInFlight.current;
    if (existingRefresh?.generation === generation) return existingRefresh.promise;
    let task!: Promise<AuthoritativeRefreshResult>;
    task = (async () => {
      setBusy(true);
      setMessage("");
      try {
        const nextIntake = await loadIntake();
        // The deaths list keeps its own page and error; the refresh is authoritative only when it loaded too.
        const [deathsLoaded, draftResult, submittedResult] = await Promise.all([
          refreshDeaths(),
          getDrafts(bootstrap.links.intakeDrafts, bootstrap.csrf),
          getSubmittedRevisions(bootstrap.csrf)
        ]);
        if (!isCurrent()) return { success: false, revision };
        setIntake(nextIntake);
        setDrafts(draftResult.drafts ?? []);
        setSubmitted(submittedResult);
        return { success: deathsLoaded, revision };
      } catch (error) {
        if (isCurrent()) setMessage(browserErrorText(error));
        return { success: false, revision };
      } finally {
        if (isCurrent()) setBusy(false);
        if (refreshInFlight.current?.promise === task) refreshInFlight.current = undefined;
      }
    })();
    refreshInFlight.current = { generation, promise: task };
    return task;
  }, [bootstrap, loadIntake, refreshDeaths]);

  const requestNotificationRefresh = useCallback((revision: number) => {
    if (!mounted.current) return Promise.resolve();
    if (revision <= acknowledgedNotificationRevision.current) return Promise.resolve();
    pendingNotificationRevision.current = Math.max(pendingNotificationRevision.current ?? revision, revision);
    if (notificationRefreshInFlight.current) return notificationRefreshInFlight.current;

    const generation = generationRef.current;
    const accountId = bootstrapRef.current?.user.user_id;
    let task!: Promise<void>;
    task = (async () => {
      while (pendingNotificationRevision.current !== undefined) {
        if (!mounted.current) break;
        const expectedRevision = pendingNotificationRevision.current;
        pendingNotificationRevision.current = undefined;
        if (expectedRevision <= acknowledgedNotificationRevision.current) continue;
        const result = await refresh();
        if (generationRef.current !== generation) {
          if (mounted.current && bootstrapRef.current?.user.user_id === accountId) {
            pendingNotificationRevision.current = Math.max(pendingNotificationRevision.current ?? expectedRevision, expectedRevision);
          }
          break;
        }
        if (!result.success) break;
        acknowledgeAuthoritativeRefresh?.(result.revision);
        acknowledgedNotificationRevision.current = Math.max(acknowledgedNotificationRevision.current, result.revision);
        if (result.revision < expectedRevision) {
          pendingNotificationRevision.current = Math.max(pendingNotificationRevision.current ?? expectedRevision, expectedRevision);
        }
        if (notificationRevisionRef.current > result.revision) {
          pendingNotificationRevision.current = Math.max(pendingNotificationRevision.current ?? notificationRevisionRef.current, notificationRevisionRef.current);
        }
      }
    })();
    notificationRefreshInFlight.current = task;
    void task.finally(() => {
      if (notificationRefreshInFlight.current === task) notificationRefreshInFlight.current = undefined;
      if (mounted.current && pendingNotificationRevision.current !== undefined) {
        void requestNotificationRefreshRef.current?.(pendingNotificationRevision.current);
      }
    });
    return task;
  }, [acknowledgeAuthoritativeRefresh, refresh]);
  requestNotificationRefreshRef.current = requestNotificationRefresh;

  useEffect(() => {
    const fromUrl = validTab(params.tab);
    if (fromUrl) setTabChoice(fromUrl);
  }, [params.tab]);

  useEffect(() => {
    setIntake(undefined);
    setDrafts([]);
    setSubmitted([]);
    setMessage("");
    setBusy(false);
    setSearchQuery("");
    setUnitFilter(undefined);
    setInterviewStatus("all");
    setAdvanced(EMPTY_ADVANCED);
    setProjectFilter(undefined);
  }, [bootstrap]);

  useEffect(() => {
    void refresh().then((result) => {
      if (result.success) {
        acknowledgeAuthoritativeRefresh?.(result.revision);
        acknowledgedNotificationRevision.current = Math.max(acknowledgedNotificationRevision.current, result.revision);
        if (pendingNotificationRevision.current !== undefined && pendingNotificationRevision.current <= result.revision) {
          pendingNotificationRevision.current = undefined;
        }
      }
    });
  }, [acknowledgeAuthoritativeRefresh, refresh]);

  useEffect(() => {
    if (notificationGeneration === undefined || notificationGeneration === 0) return;
    void requestNotificationRefresh(notificationGeneration);
  }, [notificationGeneration, requestNotificationRefresh]);

  const interviewRows = useMemo<InterviewRow[]>(() => [
    ...drafts.map((draft) => ({ ...draft, kind: "draft" as const })),
    ...submitted.map((draft) => ({ ...draft, kind: "submitted" as const })),
  ], [drafts, submitted]);

  const interviewUnits = useMemo(
    () => interviewRows.filter((row) => !projectFilter || row.project_id === projectFilter).map((row) => ({ id: row.org_unit_id, name: row.org_unit_name })),
    [interviewRows, projectFilter],
  );
  const { orgLookup, unitOptions, unitMatches } = useAreaFilter(bootstrap?.access.projects, intake?.context, interviewUnits, projectFilter);

  /** Projects the user interviews in (the intake context); the Project filter shows only with more than one. */
  const projectOptions = useMemo(() => {
    const byId = new Map<string, string>();
    for (const entry of intake?.context ?? []) {
      if (!byId.has(entry.project_id)) byId.set(entry.project_id, entry.project_name ?? entry.project_id);
    }
    return Array.from(byId, ([value, label]) => ({ value, label }));
  }, [intake?.context]);
  const projectNames = useMemo(() => new Map(projectOptions.map((option) => [option.value, option.label])), [projectOptions]);

  const directTargets = useMemo(() => directInterviewTargets(intake?.context ?? []), [intake?.context]);
  const [directOpen, setDirectOpen] = useState(false);

  /** Drafts and submitted interviews are whole lists (the caller's own, at most 200 each), so these filters are complete. */
  const filteredInterviews = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return interviewRows.filter((row) => {
      if (interviewStatus === "in_progress" && row.kind !== "draft") return false;
      if (interviewStatus === "submitted" && row.kind !== "submitted") return false;
      if (projectFilter && row.project_id !== projectFilter) return false;
      const unitInfo = row.org_unit_id ? orgLookup.byId.get(row.org_unit_id) : undefined;
      const rowUnit = (unitInfo?.name ?? row.org_unit_name ?? "").trim();
      if (!unitMatches(unitFilter, row.org_unit_id, rowUnit)) return false;
      if (!matchesAdvanced(row, advanced)) return false;
      if (!normalizedQuery) return true;
      const haystack = [row.deceased_name, row.unique_id, rowUnit, unitInfo?.breadcrumb, unitInfo?.code, row.site_name, projectNames.get(row.project_id), row.date_of_death]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedQuery);
    });
  }, [advanced, interviewRows, interviewStatus, orgLookup, projectFilter, projectNames, searchQuery, unitFilter, unitMatches]);

  const caseTotal = Object.values(deaths.counts).reduce((sum, n) => sum + n, 0) || deaths.cases.length;
  const tab: CollectionTab = tabChoice ?? (drafts.length > 0 ? "interviews" : "deaths");
  const selectTab = (next: CollectionTab) => {
    setTabChoice(next);
    router.setParams({ tab: next });
  };
  const clearInterviewFilters = () => {
    setSearchQuery("");
    setInterviewStatus("all");
    setUnitFilter(undefined);
    setAdvanced(EMPTY_ADVANCED);
    setProjectFilter(undefined);
  };

  return (
    <WebShell title={t("reportedDeaths")}>
      <ContextualHelpBanner screen="collection" />
      {params.saved === "1" ? (
        <Text style={styles.text} accessibilityRole="alert">{t("registrationSaved")}</Text>
      ) : null}
      {params.superseded === "1" ? (
        <Text style={styles.muted} accessibilityRole="alert">
          {t("supersededInterviewNotice")}
        </Text>
      ) : params.submissionHistory === "1" ? (
        <View accessibilityRole="alert">
          <Text style={styles.muted}>{t("submissionHistoryNotice")}</Text>
          {params.submissionLocked === "1" ? (
            <Text style={styles.muted}>{t("submissionLockedNotice")}</Text>
          ) : null}
        </View>
      ) : null}
      {params.canCodeNow === "1" && !deaths.cases.some((row) => row.unique_id === params.readyUniqueId) ? (
        <View style={styles.card}>
          <Text style={styles.muted}>{t("readyForCodeOnWeb")}</Text>
          {canCode && typeof params.readyVaSid === "string" && params.readyVaSid.trim() && workspaceApi ? (
            <CodeNowButton
              api={workspaceApi}
              vaSid={params.readyVaSid.trim()}
              onOpen={(vaSid) => router.push({ pathname: "/workspace", params: { vaSid, mode: "coding" } })}
              onAccessLost={() => { void appState.reload(); router.replace("/workspace"); }}
            />
          ) : null}
        </View>
      ) : null}
      {!bootstrap?.capabilities.intake ? (
        <Text style={styles.error}>{t("noCollectionAccess")}</Text>
      ) : (
        <>
          <View style={[styles.card, c.toolbarCard]}>
            <View style={c.toolbarRow}>
              <View style={c.toolbarActions}>
                {intake?.context.some((entry) => entry.web_intake_mode === "death_register" || entry.web_intake_mode === "both") ? (
                  <Button label={t("recordDeath")} onPress={() => router.push("/death-registration")} />
                ) : null}
                {directTargets.length > 0 ? (
                  <Button kind="secondary" label={t("directVaInterview")} expanded={directOpen} onPress={() => setDirectOpen((open) => !open)} />
                ) : null}
              </View>
              <RefreshIconButton disabled={busy} onPress={() => {
                void refresh().then((result) => {
                  if (result.success) {
                    acknowledgeAuthoritativeRefresh?.(result.revision);
                    acknowledgedNotificationRevision.current = Math.max(acknowledgedNotificationRevision.current, result.revision);
                  }
                });
              }} />
            </View>
            {directOpen && directTargets.length > 0 ? (
              <DirectInterviewPanel
                targets={directTargets}
                onStart={(target) => router.push({ pathname: "/interview", params: { projectId: target.projectId, siteId: target.siteId, ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {}) } })}
              />
            ) : null}
          </View>
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          <View style={c.tabBar} accessibilityRole="tablist">
            {([
              { key: "interviews" as const, label: `${t("myInterviews")} (${interviewRows.length})` },
              { key: "deaths" as const, label: `${t("reportedDeaths")} (${caseTotal}${deaths.nextCursor && !Object.keys(deaths.counts).length ? "+" : ""})` },
            ]).map((entry) => {
              const on = tab === entry.key;
              return (
                <Pressable
                  key={entry.key}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={entry.label}
                  onPress={() => selectTab(entry.key)}
                  style={[c.tab, on && c.tabOn]}
                >
                  <Text style={[c.tabText, on && c.tabTextOn]}>{entry.label}</Text>
                </Pressable>
              );
            })}
          </View>
          {tab === "interviews" ? (
            <>
              {interviewRows.length > 0 ? (
                <CaseFilterBar<InterviewStatusFilter>
                  search={searchQuery}
                  onSearch={setSearchQuery}
                  statusChips={[
                    { key: "all", label: t("filterAll") },
                    { key: "in_progress", label: t("filterInProgress") },
                    { key: "submitted", label: t("filterSubmitted") },
                  ]}
                  status={interviewStatus}
                  allStatus="all"
                  onStatus={setInterviewStatus}
                  projects={projectOptions}
                  project={projectFilter}
                  onProject={setProjectFilter}
                  units={unitOptions}
                  unit={unitFilter}
                  onUnit={setUnitFilter}
                  advanced={advanced}
                  onAdvanced={setAdvanced}
                  reportedLabel={t("filterDateStarted")}
                  onClearAll={clearInterviewFilters}
                />
              ) : (
                <Text style={styles.muted}>{t("noInterviewsYet")}</Text>
              )}
              {interviewRows.length > 0 && filteredInterviews.length === 0 ? (
                <Text style={styles.muted}>{t("noMatchingCases")}</Text>
              ) : null}
              {filteredInterviews.map((row) => {
                const unitInfo = row.org_unit_id ? orgLookup.byId.get(row.org_unit_id) : undefined;
                const rawPlace = unitInfo?.name ?? row.org_unit_name ?? row.site_name;
                const place = rawPlace && !isInternalPlaceholderUnit(rawPlace) ? rawPlace : undefined;
                const project = projectNames.get(row.project_id);
                const extra = [
                  ...(row.kind === "draft" && typeof row.sections_saved === "number" ? [{ key: "sections", text: t("sectionsSaved", { count: row.sections_saved }) }] : []),
                  ...(row.updated_at ? [{ key: "updated", text: t("metaUpdated", { value: formatDisplayTimestamp(row.updated_at) }) }] : []),
                  ...(project && projectOptions.length > 1 ? [{ key: "project", text: t("metaProject", { value: project }) }] : []),
                ];
                return (
                  <CaseCard
                    key={`${row.kind}:${row.draft_id}`}
                    testID={`interview-card-${row.kind}-${row.draft_id}`}
                    title={row.deceased_name || row.unique_id || row.draft_id}
                    caseId={row.deceased_name ? row.unique_id : undefined}
                    ageYears={row.age_years}
                    sex={row.deceased_sex}
                    dateOfDeath={row.date_of_death}
                    area={place}
                    extra={extra}
                    badges={[row.kind === "draft" ? { label: t("draftInProgress"), tone: "accent" } : { label: t("filterSubmitted") }]}
                    actions={row.kind === "draft" ? (
                      <Button size="sm" style={card.actionButton} label={t("resumeInterview")} onPress={() => router.push({ pathname: "/interview", params: { draftId: row.draft_id } })} />
                    ) : (
                      <Button
                        size="sm"
                        style={card.actionButton}
                        label={t("reviseInterview")}
                        onPress={() => router.push({ pathname: "/interview", params: {
                          revisionDraftId: row.draft_id,
                          revisionProjectId: row.project_id,
                          revisionSiteId: row.site_id,
                          revisionVaSid: row.va_sid,
                        } })}
                      />
                    )}
                  />
                );
              })}
            </>
          ) : null}
          {tab === "deaths" ? <DeathsList list={deaths} /> : null}
        </>
      )}
    </WebShell>
  );
}
