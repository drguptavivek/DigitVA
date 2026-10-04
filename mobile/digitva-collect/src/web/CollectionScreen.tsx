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

export default function CollectionScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ superseded?: string }>();
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [submitted, setSubmitted] = useState<SubmittedRevisionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const refreshInFlight = useRef<{ generation: number; promise: Promise<void> } | undefined>(undefined);
  const bootstrapRef = useRef(bootstrap);
  const generationRef = useRef(0);
  if (bootstrapRef.current !== bootstrap) {
    bootstrapRef.current = bootstrap;
    generationRef.current += 1;
    refreshInFlight.current = undefined;
  }

  const loadIntake = useCallback(async () => {
    if (!bootstrap) throw new Error("authentication_required");
    return getIntakeContext(bootstrap.csrf);
  }, [bootstrap]);

  const refresh = useCallback(async () => {
    if (!bootstrap) return;
    const generation = generationRef.current;
    const isCurrent = () => generationRef.current === generation && bootstrapRef.current === bootstrap;
    if (refreshInFlight.current?.generation === generation) return refreshInFlight.current.promise;
    let task!: Promise<void>;
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
        if (!isCurrent()) return;
        setIntake(nextIntake);
        setCases(caseResult.cases ?? []);
        rememberCasePreviews(bootstrap, caseResult.cases ?? []);
        setNextCursor(caseResult.next_cursor ?? null);
        setDrafts(draftResult.drafts ?? []);
        setSubmitted(submittedResult);
      } catch (error) {
        if (isCurrent()) setMessage(browserErrorText(error));
      } finally {
        if (isCurrent()) setBusy(false);
        if (refreshInFlight.current?.promise === task) refreshInFlight.current = undefined;
      }
    })();
    refreshInFlight.current = { generation, promise: task };
    return task;
  }, [bootstrap, loadIntake]);

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
    void refresh();
  }, [refresh]);

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
          <Button kind="secondary" loading={busy} label={t("refresh")} onPress={() => void refresh()} />
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
