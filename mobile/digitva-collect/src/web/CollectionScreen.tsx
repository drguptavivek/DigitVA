import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { getCases, getDrafts, getIntakeContext, type CaseRow, type DraftSummary, type IntakeBootstrap } from "../client/api";
import { getSubmittedRevisions, type SubmittedRevisionSummary } from "../client/revisions";
import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import { Button, stateLabel, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { rememberCasePreviews } from "./newCasePreview";

function sexLabel(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = value.toLowerCase();
  const key = `sex${normalized[0]?.toUpperCase() ?? ""}${normalized.slice(1)}` as StringKey;
  const label = t(key);
  return label === key ? value : label;
}

const TERMINAL_CASE_STATES = new Set(["completed", "submitted", "cancelled", "closed", "duplicate", "not_codeable"]);

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
  const params = useLocalSearchParams<{ superseded?: string }>();
  const appState = useAppState() as ReturnType<typeof useAppState> & BrowserNotificationRefresh;
  const { bootstrap, notificationGeneration, acknowledgeAuthoritativeRefresh } = appState;
  const styles = useUiStyles();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [submitted, setSubmitted] = useState<SubmittedRevisionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
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
        const [caseResult, draftResult, submittedResult] = await Promise.all([
          getCases(bootstrap.links.intakeCases, bootstrap.csrf),
          getDrafts(bootstrap.links.intakeDrafts, bootstrap.csrf),
          getSubmittedRevisions(bootstrap.csrf)
        ]);
        if (!isCurrent()) return { success: false, revision };
        setIntake(nextIntake);
        setCases(caseResult.cases ?? []);
        rememberCasePreviews(bootstrap, caseResult.cases ?? []);
        setNextCursor(caseResult.next_cursor ?? null);
        setDrafts(draftResult.drafts ?? []);
        setSubmitted(submittedResult);
        return { success: true, revision };
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
  }, [bootstrap, loadIntake]);

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

  const loadMore = useCallback(async () => {
    if (!bootstrap || !nextCursor) return;
    const generation = generationRef.current;
    const requestBootstrap = bootstrap;
    setBusy(true);
    try {
      const result = await getCases(bootstrap.links.intakeCases, bootstrap.csrf, nextCursor);
      if (generationRef.current !== generation || bootstrapRef.current !== requestBootstrap) return;
      setCases((previous) => [...previous, ...(result.cases ?? [])]);
      rememberCasePreviews(requestBootstrap, result.cases ?? []);
      setNextCursor(result.next_cursor ?? null);
    } catch (error) {
      if (generationRef.current === generation && bootstrapRef.current === requestBootstrap) {
        setMessage(browserErrorText(error));
      }
    } finally {
      if (generationRef.current === generation && bootstrapRef.current === requestBootstrap) setBusy(false);
    }
  }, [bootstrap, nextCursor]);

  useEffect(() => {
    setIntake(undefined);
    setCases([]);
    setDrafts([]);
    setSubmitted([]);
    setNextCursor(null);
    setMessage("");
    setBusy(false);
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

  return (
    <WebShell title={t("reportedDeaths")}>
      {params.superseded === "1" ? (
        <Text style={styles.muted} accessibilityRole="alert">
          {t("supersededInterviewNotice")}
        </Text>
      ) : null}
      {!bootstrap?.capabilities.intake ? (
        <Text style={styles.error}>{t("noCollectionAccess")}</Text>
      ) : (
        <>
          {intake?.context.some((entry) => entry.web_intake_mode === "death_register" || entry.web_intake_mode === "both") ? (
            <Button label={t("newDeath")} onPress={() => router.push("/death-registration")} />
          ) : null}
          {intake?.context.filter((entry) => entry.web_intake_mode === "direct" || entry.web_intake_mode === "both").map((entry) => {
            const units = (entry.org_units ?? []).filter((unit) => unit.selectable !== false);
            if (units.length > 1) {
              return units.map((unit) => (
                <Button
                  key={`direct:${entry.project_id}:${entry.site_id}:${unit.org_unit_id}`}
                  kind="secondary"
                  label={`${t("newInterview")} · ${unit.unit_name ?? unit.unit_code ?? unit.org_unit_id}`}
                  onPress={() => router.push({ pathname: "/interview", params: { projectId: entry.project_id, siteId: entry.site_id, orgUnitId: unit.org_unit_id } })}
                />
              ));
            }
            return (
              <Button
                key={`direct:${entry.project_id}:${entry.site_id}`}
                kind="secondary"
                label={t("newInterview")}
                onPress={() => router.push({ pathname: "/interview", params: { projectId: entry.project_id, siteId: entry.site_id, ...(units[0] ? { orgUnitId: units[0].org_unit_id } : {}) } })}
              />
            );
          })}
          <Button kind="secondary" loading={busy} label={t("refresh")} onPress={() => {
            void refresh().then((result) => {
              if (result.success) {
                acknowledgeAuthoritativeRefresh?.(result.revision);
                acknowledgedNotificationRevision.current = Math.max(acknowledgedNotificationRevision.current, result.revision);
              }
            });
          }} />
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          <Text style={styles.headline}>{t("draftsTitle")}</Text>
          {drafts.length === 0 ? <Text style={styles.muted}>{t("noDrafts")}</Text> : null}
          {drafts.map((draft) => (
            <View key={draft.draft_id} style={styles.card}>
              <Text style={styles.text}>{draft.unique_id ?? draft.draft_id}</Text>
              <Text style={styles.muted}>{draft.current_section ?? t("draftInProgress")}</Text>
              <Button label={t("resumeInterview")} onPress={() => router.push({ pathname: "/interview", params: { draftId: draft.draft_id } })} />
            </View>
          ))}
          <Text style={styles.headline}>{t("submittedInterviewsTitle")}</Text>
          {submitted.length === 0 ? <Text style={styles.muted}>{t("noSubmittedInterviews")}</Text> : null}
          {submitted.map((draft) => (
            <View key={draft.draft_id} style={styles.card}>
              <Text style={styles.text}>{draft.unique_id ?? draft.draft_id}</Text>
              <Text style={styles.muted}>{draft.updated_at ?? draft.site_name ?? draft.site_id}</Text>
              <Button
                label={t("reviseInterview")}
                onPress={() => router.push({ pathname: "/interview", params: {
                  revisionDraftId: draft.draft_id,
                  revisionProjectId: draft.project_id,
                  revisionSiteId: draft.site_id,
                  revisionVaSid: draft.va_sid,
                } })}
              />
            </View>
          ))}
          <Text style={styles.headline}>{t("reportedDeaths")}</Text>
          {cases.length === 0 ? <Text style={styles.muted}>{t("noReportedDeaths")}</Text> : null}
          {cases.map((row) => (
            <View key={row.death_id} style={styles.card}>
              <Text style={styles.text}>{row.deceased_name ?? row.unique_id}</Text>
              <Text style={styles.muted}>
                {row.unique_id} · {stateLabel(row.state ?? row.status ?? "")}
                {row.age_years == null ? "" : ` · ${row.age_years}`}
                {row.deceased_sex ? ` · ${sexLabel(row.deceased_sex)}` : ""}
                {row.unit_name || row.org_unit_name ? ` · ${row.unit_name ?? row.org_unit_name}` : ""}
                {row.date_of_death ? ` · ${row.date_of_death}` : ""}
              </Text>
              {row.other_draft_active === true ? (
                <Text style={styles.error} accessibilityRole="alert">
                  {otherDraftNotice(row.other_draft_started_at)}
                </Text>
              ) : null}
              <Button
                kind="secondary"
                label={t("viewDetails")}
                onPress={() => router.push({ pathname: "/case", params: { deathId: row.death_id } })}
              />
              {row.my_draft_id && !TERMINAL_CASE_STATES.has(row.state ?? row.status ?? "") ? (
                <Button label={t("resumeInterview")} onPress={() => router.push({ pathname: "/interview", params: { draftId: row.my_draft_id!, ...(row.project_id ? { projectId: row.project_id } : {}), ...(row.site_id ? { siteId: row.site_id } : {}), ...(row.org_unit_id ? { orgUnitId: row.org_unit_id } : {}) } })} />
              ) : null}
            </View>
          ))}
          {nextCursor ? <Button kind="secondary" loading={busy} label={t("loadMore")} onPress={() => void loadMore()} /> : null}
        </>
      )}
    </WebShell>
  );
}

function otherDraftNotice(startedAt: string | null | undefined): string {
  if (typeof startedAt === "string") {
    const date = new Date(startedAt);
    if (!Number.isNaN(date.getTime())) {
      return t("otherDraftActiveAt", { date: date.toLocaleString() });
    }
  }
  return t("otherDraftActive");
}
