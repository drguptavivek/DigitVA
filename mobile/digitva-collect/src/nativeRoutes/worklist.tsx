/**
 * One interviewer's in-flight work: the cases downloaded for offline visits,
 * deaths registered on this phone and not yet sent, and interviews on this
 * phone. "New interview" (site/unit from the cached bootstrap), "Register a
 * death", sync (send everything, then refresh the case list), lock, and
 * sign out. Reached only while the interviewer's store is unlocked.
 */
import { randomUUID } from "expo-crypto";
import {
  Redirect,
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AppState, Pressable, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { SessionRevokedError, SignInRequiredError, signOut } from "../auth";
import {
  listActions,
  listCases,
  listRegistrations,
  type CaseRow,
  type CaseDetail,
  type Registration,
} from "../cases";
import { listDrafts, type Db, type DraftRow } from "../drafts";
import { t } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import {
  getCachedReferenceData,
  fetchCasePage,
  refreshReferenceData,
  refreshCases,
  registersDeaths,
  startsDirectly,
  syncInterviewer,
  targetsFrom,
} from "../sync";
import { Button, errorText, Row, Screen, stateLabel, useUiStyles } from "../ui";

function displayDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleDateString();
}

function fieldValue(
  label: string,
  value: string | number | null | undefined,
): string | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  return `${label}: ${value}`;
}

export default function Worklist() {
  const styles = useUiStyles();
  const router = useRouter();
  const { userId, refresh: refreshOnFocus } = useLocalSearchParams<{
    userId: string;
    refresh?: string;
  }>();
  const { accounts, reload, lockNow, lockVersion } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [db, setDb] = useState<Db | undefined>();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [cases, setCases] = useState<CaseDetail[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>();
  const [onlineCases, setOnlineCases] = useState<CaseRow[]>([]);
  const [onlineCursor, setOnlineCursor] = useState<string | null>(null);
  const [onlineBusy, setOnlineBusy] = useState(false);
  const [registrations, setRegistrations] = useState<Registration[]>([]);
  const [queued, setQueued] = useState(0);
  const [referenceData, setReferenceData] =
    useState<Awaited<ReturnType<typeof getCachedReferenceData>>>();
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const focusedRef = useRef(false);
  const dbRef = useRef<Db | undefined>(undefined);
  const onlineRequestGenerationRef = useRef(0);
  const selectedProjectRef = useRef<string | undefined>(undefined);
  const referenceDataRef =
    useRef<Awaited<ReturnType<typeof getCachedReferenceData>>>(undefined);
  const consumedRefreshFor = useRef<string | undefined>(undefined);
  const appStateRef = useRef(AppState.currentState);

  const setReference = useCallback(
    (next: Awaited<ReturnType<typeof getCachedReferenceData>>) => {
      referenceDataRef.current = next;
      setReferenceData(next);
    },
    [],
  );

  const isCurrent = useCallback(
    () => Boolean(account && account.user_id === userId && focusedRef.current),
    [account, userId],
  );

  const clearVisible = useCallback(() => {
    focusedRef.current = false;
    onlineRequestGenerationRef.current += 1;
    selectedProjectRef.current = undefined;
    dbRef.current = undefined;
    referenceDataRef.current = undefined;
    setDb(undefined);
    setReferenceData(undefined);
    setDrafts([]);
    setCases([]);
    setRegistrations([]);
    setQueued(0);
    setOnlineCases([]);
    setOnlineCursor(null);
    setSelectedProjectId(undefined);
    setPicking(false);
  }, []);

  useEffect(() => {
    if (selectedProjectRef.current !== selectedProjectId) {
      onlineRequestGenerationRef.current += 1;
      setOnlineCases([]);
      setOnlineCursor(null);
    }
    selectedProjectRef.current = selectedProjectId;
  }, [selectedProjectId]);

  const loadLocal = useCallback(
    async (handle: Db, current: () => boolean = () => true) => {
      const [d, c, r, a] = await Promise.all([
        listDrafts(handle),
        listCases(handle),
        listRegistrations(handle),
        listActions(handle),
      ]);
      if (!current()) return;
      setDrafts(d);
      setCases(c);
      setRegistrations(r);
      setQueued(a.length);
    },
    [],
  );

  // A failed settings refresh may already have purged projects from the
  // encrypted pack. Re-read that sanitized pack and rebuild visible state so
  // revoked-project contacts do not remain on screen.
  const recoverAfterRefreshFailure = useCallback(
    async (handle: Db, current: () => boolean, error: unknown) => {
      if (!(error instanceof TypeError)) {
        if (!current()) return;
        setReference(undefined);
        setSelectedProjectId(undefined);
        setOnlineCases([]);
        setOnlineCursor(null);
        setDrafts([]);
        setCases([]);
        setRegistrations([]);
        setQueued(0);
        setMessage(errorText(error));
        return;
      }
      let latest: Awaited<ReturnType<typeof getCachedReferenceData>>;
      try {
        latest = await getCachedReferenceData(handle);
      } catch (storageError) {
        if (current()) {
          setReference(undefined);
          setMessage(errorText(storageError));
        }
        return;
      }
      if (!current()) return;
      setReference(latest);
      setSelectedProjectId((selected) =>
        selected &&
        latest?.projects.some(({ project }) => project.project_id === selected)
          ? selected
          : latest?.projects[0]?.project.project_id,
      );
      setOnlineCases([]);
      setOnlineCursor(null);
      setDrafts([]);
      setCases([]);
      setRegistrations([]);
      setQueued(0);
      try {
        await loadLocal(handle, current);
      } catch {
        // The cleared state is safer than retaining stale encrypted rows.
      }
      if (current() && !latest) setMessage(t("referenceDataUnavailable"));
    },
    [loadLocal, setReference],
  );

  const handleError = useCallback(
    async (error: unknown) => {
      if (error instanceof SessionRevokedError) {
        Alert.alert(t("sessionRevoked"));
        clearVisible();
        await reload();
        router.replace("/");
        return;
      }
      // Tokens dropped, data kept: the home screen now flags this account.
      if (error instanceof SignInRequiredError) {
        clearVisible();
        await reload();
        router.replace("/");
        return;
      }
      setMessage(errorText(error));
    },
    [clearVisible, reload, router],
  );

  useFocusEffect(
    useCallback(() => {
      if (!account) return;
      let active = true;
      focusedRef.current = true;
      const forceRefresh =
        refreshOnFocus === "1" &&
        consumedRefreshFor.current !== account.user_id;
      if (forceRefresh) {
        consumedRefreshFor.current = account.user_id;
        const setParams = (
          router as typeof router & {
            setParams?: (params: { refresh?: string }) => void;
          }
        ).setParams;
        setParams?.({ refresh: undefined });
      }
      void (async () => {
        try {
          const handle = await openInterviewerDb(account.user_id);
          if (!active) return;
          dbRef.current = handle;
          setDb(handle);
          await loadLocal(handle, () => active && isCurrent());
          const cached = await getCachedReferenceData(handle);
          if (!active) return;
          setReference(cached);
          const firstProject = cached?.projects[0]?.project.project_id;
          setSelectedProjectId((current) =>
            current &&
            cached?.projects.some(
              ({ project }) => project.project_id === current,
            )
              ? current
              : firstProject,
          );
          try {
            const fresh = forceRefresh
              ? await refreshReferenceData(account.user_id, handle, {
                  force: true,
                })
              : await refreshReferenceData(account.user_id, handle);
            if (active) {
              setReference(fresh);
              setSelectedProjectId((current) =>
                current &&
                fresh?.projects.some(
                  ({ project }) => project.project_id === current,
                )
                  ? current
                  : fresh?.projects[0]?.project.project_id,
              );
              if (forceRefresh) await refreshCases(account.user_id, handle);
              await loadLocal(handle, () => active && isCurrent());
              if (fresh) setMessage("");
              else if (!cached) setMessage(t("referenceDataUnavailable"));
            }
          } catch (error) {
            if (
              error instanceof SessionRevokedError ||
              error instanceof SignInRequiredError
            ) {
              if (active) await handleError(error);
              return;
            }
            if (active)
              await recoverAfterRefreshFailure(
                handle,
                () => active && isCurrent(),
                error,
              );
          }
        } catch (error) {
          if (active) await handleError(error);
        }
      })();
      return () => {
        active = false;
        clearVisible();
      };
    }, [
      account,
      clearVisible,
      handleError,
      isCurrent,
      loadLocal,
      recoverAfterRefreshFailure,
      refreshCases,
      refreshOnFocus,
      router,
      setReference,
      lockVersion,
    ]),
  );

  useEffect(() => {
    appStateRef.current = AppState.currentState;
    const subscription = AppState.addEventListener("change", (next) => {
      const previous = appStateRef.current;
      appStateRef.current = next;
      if (
        next !== "active" ||
        previous === "active" ||
        !focusedRef.current ||
        !account ||
        !isUnlocked(account.user_id)
      ) {
        return;
      }
      const handle = dbRef.current;
      if (!handle) return;
      void refreshReferenceData(account.user_id, handle, { force: true })
        .then(async (fresh) => {
          if (isCurrent()) {
            setReference(fresh);
            await loadLocal(handle, isCurrent);
            setMessage("");
          }
        })
        .catch(async (error) => {
          if (!isCurrent()) return;
          if (
            error instanceof SessionRevokedError ||
            error instanceof SignInRequiredError
          ) {
            await handleError(error);
            return;
          }
          await recoverAfterRefreshFailure(handle, isCurrent, error);
        });
    });
    return () => subscription.remove();
  }, [
    account,
    handleError,
    isCurrent,
    loadLocal,
    recoverAfterRefreshFailure,
    setReference,
  ]);

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return (
      <Redirect
        href={{ pathname: "/unlock", params: { userId: account.user_id } }}
      />
    );
  }

  async function refresh() {
    if (!db || !account) return;
    const requestGeneration = onlineRequestGenerationRef.current;
    const projectId = selectedProjectId;
    setBusy(true);
    setMessage("");
    try {
      const fresh = await refreshReferenceData(account.user_id, db, {
        force: true,
      });
      if (!isCurrent()) return;
      setReference(fresh);
      await refreshCases(account.user_id, db);
      await loadLocal(db, isCurrent);
      if (projectId) {
        const page = await fetchCasePage(account.user_id, projectId, {
          limit: 50,
        });
        if (
          isCurrent() &&
          requestGeneration === onlineRequestGenerationRef.current &&
          selectedProjectRef.current === projectId
        ) {
          setOnlineCases(page.cases);
          setOnlineCursor(page.next_cursor ?? null);
        }
      }
    } catch (error) {
      if (isCurrent()) {
        if (
          error instanceof SessionRevokedError ||
          error instanceof SignInRequiredError
        ) {
          await handleError(error);
        } else {
          await recoverAfterRefreshFailure(db, isCurrent, error);
        }
      }
    } finally {
      setBusy(false);
    }
  }

  async function loadOnlineMore() {
    if (!account || !selectedProjectId || onlineBusy) return;
    const projectId = selectedProjectId;
    const requestGeneration = onlineRequestGenerationRef.current;
    const cursor = onlineCursor;
    setOnlineBusy(true);
    try {
      const page = await fetchCasePage(account.user_id, projectId, {
        limit: 50,
        ...(cursor ? { cursor } : {}),
      });
      if (
        isCurrent() &&
        requestGeneration === onlineRequestGenerationRef.current &&
        selectedProjectRef.current === projectId
      ) {
        setOnlineCases((current) =>
          cursor ? [...current, ...page.cases] : page.cases,
        );
        setOnlineCursor(page.next_cursor ?? null);
      }
    } catch (error) {
      if (isCurrent()) await handleError(error);
    } finally {
      setOnlineBusy(false);
    }
  }

  async function send() {
    if (!db || !account) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await syncInterviewer(account.user_id, db);
      const fresh = await refreshReferenceData(account.user_id, db, {
        force: true,
      });
      if (isCurrent()) {
        setReference(fresh);
        setMessage(t("syncResult", { ...result }));
      }
    } catch (error) {
      if (isCurrent()) await handleError(error);
    } finally {
      try {
        await loadLocal(db, isCurrent);
      } catch (error) {
        if (isCurrent()) await handleError(error);
      }
      setBusy(false);
    }
  }

  function confirmSignOut() {
    if (!account) return;
    const doSignOut = async () => {
      await signOut(account.user_id);
      await reload();
      router.replace("/");
    };
    const unsent = drafts.length + registrations.length + queued;
    if (unsent === 0) {
      void doSignOut();
      return;
    }
    Alert.alert(t("signOut"), t("signOutUnsent", { count: unsent }), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("signOutConfirm"),
        style: "destructive",
        onPress: () => void doSignOut(),
      },
    ]);
  }

  const selectedProject = (referenceData?.projects ?? []).find(
    ({ project }) => project.project_id === selectedProjectId,
  );
  const targets = selectedProject
    ? targetsFrom(selectedProject.project, selectedProject.units).filter(
        (target) => startsDirectly(selectedProject.project, target.siteId),
      )
    : [];
  const projects = referenceData?.projects.map(({ project }) => project) ?? [];
  const visibleCases = selectedProjectId
    ? cases.filter((row) => row.project_id === selectedProjectId)
    : cases;
  const visibleRegistrations = selectedProjectId
    ? registrations.filter((row) => row.project_id === selectedProjectId)
    : registrations;
  const visibleDrafts = selectedProjectId
    ? drafts.filter((row) => row.project_id === selectedProjectId)
    : drafts;
  return (
    <Screen title={t("worklistTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      {projects.length > 1 ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{t("chooseProject")}</Text>
          {projects.map((project) => (
            <Button
              key={project.project_id}
              kind={
                project.project_id === selectedProjectId
                  ? "primary"
                  : "secondary"
              }
              label={project.project_name}
              onPress={() => {
                onlineRequestGenerationRef.current += 1;
                setSelectedProjectId(project.project_id);
                setOnlineCases([]);
                setOnlineCursor(null);
              }}
            />
          ))}
        </View>
      ) : null}
      {picking ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{t("chooseSite")}</Text>
          {targets.length === 0 ? (
            <Text style={styles.muted}>{t("noSites")}</Text>
          ) : null}
          {targets.map((target) => (
            <Button
              key={target.key}
              kind="secondary"
              label={target.label}
              onPress={() => {
                setPicking(false);
                router.push({
                  pathname: "/form",
                  params: {
                    userId: account.user_id,
                    draftId: randomUUID(),
                    projectId: target.projectId,
                    siteId: target.siteId,
                    ...(target.orgUnitId
                      ? { orgUnitId: target.orgUnitId }
                      : {}),
                  },
                });
              }}
            />
          ))}
          <Button
            kind="secondary"
            label={t("cancel")}
            onPress={() => setPicking(false)}
          />
        </View>
      ) : (
        <Row>
          <Button
            label={t("newInterview")}
            disabled={!db || !referenceData || targets.length === 0}
            onPress={() => setPicking(true)}
          />
          <Button
            kind="secondary"
            label={t("registerDeath")}
            disabled={
              !db ||
              !selectedProject ||
              !registersDeaths(selectedProject.project)
            }
            onPress={() =>
              router.push({
                pathname: "/register",
                params: {
                  userId: account.user_id,
                  projectId: selectedProject?.project.project_id ?? "",
                },
              })
            }
          />
        </Row>
      )}
      <Text style={styles.text} accessibilityRole="header">
        {t("reportedDeaths")}
      </Text>
      <Text style={styles.muted}>{t("followUpDeathsOnly")}</Text>
      {visibleCases.length === 0 ? (
        <Text style={styles.muted}>{t("noReportedDeaths")}</Text>
      ) : null}
      {visibleCases.map((row) => (
        <View key={row.death_id} style={styles.card}>
          <Text style={styles.text}>{row.deceased?.name ?? row.unique_id}</Text>
          <Text style={styles.muted}>{row.unique_id}</Text>
          {[
            fieldValue(
              t("fieldAge").replace(/\s*\*\s*$/, ""),
              row.deceased?.age_years,
            ),
            fieldValue(
              t("fieldSex").replace(/\s*\*\s*$/, ""),
              row.deceased?.sex,
            ),
            fieldValue(
              t("fieldDateOfDeath").replace(/\s*\*\s*$/, ""),
              displayDate(row.deceased?.date_of_death),
            ),
            fieldValue(t("chooseUnit"), row.unit_name),
            fieldValue(t("deathStatus"), stateLabel(row.state)),
            row.next_visit_at
              ? t("nextVisit", {
                  date: displayDate(row.next_visit_at) ?? row.next_visit_at,
                })
              : undefined,
          ]
            .filter((value): value is string => Boolean(value))
            .map((value) => (
              <Text key={value} style={styles.muted}>
                {value}
              </Text>
            ))}
          <Button
            kind="secondary"
            label={t("viewDetails")}
            onPress={() =>
              router.push({
                pathname: "/case",
                params: {
                  userId: account.user_id,
                  projectId: row.project_id,
                  deathId: row.death_id,
                },
              })
            }
          />
        </View>
      ))}
      {onlineCases.length > 0 ? (
        <>
          <Text style={styles.text} accessibilityRole="header">
            {t("reportedDeaths")} · {selectedProject?.project.project_name}
          </Text>
          {onlineCases.map((row) => (
            <View key={"online-" + row.death_id} style={styles.card}>
              <Text style={styles.text}>
                {row.deceased_name ?? row.unique_id}
              </Text>
              <Text style={styles.muted}>
                {row.unique_id} · {stateLabel(row.state)}
              </Text>
              <Button
                kind="secondary"
                label={t("viewDetails")}
                onPress={() =>
                  router.push({
                    pathname: "/case",
                    params: {
                      userId: account.user_id,
                      projectId: row.project_id,
                      deathId: row.death_id,
                    },
                  })
                }
              />
            </View>
          ))}
        </>
      ) : null}
      {selectedProject ? (
        <Button
          kind="secondary"
          loading={onlineBusy}
          label={t("refresh")}
          onPress={() => void loadOnlineMore()}
        />
      ) : null}
      {onlineCursor ? (
        <Button
          kind="secondary"
          loading={onlineBusy}
          label={t("loadMore")}
          onPress={() => void loadOnlineMore()}
        />
      ) : null}
      {visibleRegistrations.length > 0 ? (
        <Text style={styles.text} accessibilityRole="header">
          {t("registrationsTitle")}
        </Text>
      ) : null}
      {visibleRegistrations.map((reg) => (
        <Pressable
          key={reg.client_death_id}
          accessibilityRole="button"
          style={styles.card}
          onPress={() =>
            router.push({
              pathname: "/case",
              params: {
                userId: account.user_id,
                clientDeathId: reg.client_death_id,
              },
            })
          }
        >
          <Text style={styles.text}>{reg.fields.deceased_name}</Text>
          <Text
            style={reg.state === "needs_edit" ? styles.error : styles.muted}
          >
            {reg.state === "needs_edit" ? t("needsEdit") : t("pendingSend")}
          </Text>
        </Pressable>
      ))}
      <Text style={styles.text} accessibilityRole="header">
        {t("interviewsTitle")}
      </Text>
      {visibleDrafts.length === 0 ? (
        <Text style={styles.muted}>{t("noDrafts")}</Text>
      ) : null}
      {visibleDrafts.map((draft) => (
        <Pressable
          key={draft.id}
          accessibilityRole="button"
          disabled={draft.completed === 1}
          style={styles.card}
          onPress={() =>
            router.push({
              pathname: "/form",
              params: {
                userId: account.user_id,
                draftId: draft.id,
                ...(draft.project_id ? { projectId: draft.project_id } : {}),
              },
            })
          }
        >
          <Text style={styles.text}>
            {draft.completed ? t("draftReady") : t("draftInProgress")}
          </Text>
          <Text style={styles.muted}>
            {new Date(draft.updated_at).toLocaleString()} ·{" "}
            {draft.unique_id ?? draft.id.slice(0, 8)}
          </Text>
        </Pressable>
      ))}
      <Row>
        <Button
          label={t("sync")}
          disabled={busy || !db}
          onPress={() => void send()}
        />
        <Button
          kind="secondary"
          label={t("refresh")}
          disabled={busy || !db}
          onPress={() => void refresh()}
        />
      </Row>
      {message ? <Text style={styles.text}>{message}</Text> : null}
      <Row>
        <Button
          kind="secondary"
          label={t("home")}
          onPress={() => router.replace("/")}
        />
        <Button
          kind="secondary"
          label={t("lockNow")}
          disabled={busy}
          onPress={() => void lockNow()}
        />
        <Button
          kind="danger"
          label={t("signOut")}
          disabled={busy}
          onPress={confirmSignOut}
        />
      </Row>
    </Screen>
  );
}
