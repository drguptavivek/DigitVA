/**
 * One interviewer's in-flight work: the cases downloaded for offline visits,
 * deaths registered on this phone and not yet sent, and interviews on this
 * phone. Two tabs share this route (`view`): Home, a dashboard (next step,
 * unsent, cases needing a visit, Register a death), and Interviews, the
 * searchable list. The data, sync and refresh logic is one; the views are in
 * worklistParts.tsx. Reached only while the interviewer's store is unlocked.
 */
import { randomUUID } from "expo-crypto";
import {
  Redirect,
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AppState } from "react-native";

import { useAppState } from "../AppState";
import { SessionRevokedError, SignInRequiredError } from "../auth";
import {
  listActions,
  listCases,
  listRegistrations,
  type CaseAction,
  type CaseRow,
  type CaseDetail,
  type Registration,
} from "../cases";
import { listDrafts, retryDemoLimitDraft, type Db, type DraftRow } from "../drafts";
import { t } from "../i18n";
import { useShell } from "../nativeShell/shellContext";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import {
  fetchSubmittedRevisions,
  listLocalRevisions,
  type RevisionRow,
  type SubmittedRevisionSummary,
} from "../revisions";
import {
  getCachedReferenceData,
  fetchCasePage,
  listPausedProjects,
  type PausedProject,
  refreshAuthorizedProjectDefinitions,
  refreshReferenceData,
  refreshCases,
  registersDeaths,
  startsDirectly,
  targetsFrom,
} from "../sync";
import { useToast } from "../toast";
import { Button, errorText, Screen } from "../ui";
import { buildInterviewItems, interviewCounts, type InterviewAction, type InterviewItem } from "../ui/interviewRows";
import { homeSummary } from "../ui/homeSummary";
import { readRecentTarget, writeRecentTarget, type RecentTarget } from "../recentTarget";
import type { PickerTarget } from "../ui/sitePicker";
import RegisteredDeaths from "./RegisteredDeaths";
import { HomeView, InterviewsView, Notice, ProjectLine, ProjectSheet, SitePickerSheet } from "./worklistParts";

export default function Worklist() {
  const { userId, registeredMine, view, filter } = useLocalSearchParams<{ userId: string; registeredMine?: string; view?: string; filter?: string }>();
  const { accounts } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const reporterOnly = account?.collection_access !== true && account?.registration_access === true;
  if (reporterOnly || (registeredMine === "1" && account?.registered_deaths_access === true)) {
    return <RegisteredDeaths userId={userId} registeredMine={!reporterOnly} />;
  }
  return <InterviewWorklist interviews={(Array.isArray(view) ? view[0] : view) === "interviews"} filter={filter} />;
}

function InterviewWorklist({ interviews, filter }: { interviews: boolean; filter?: string | string[] }) {
  const router = useRouter();
  const { userId, refresh: refreshOnFocus } = useLocalSearchParams<{
    userId: string;
    refresh?: string;
  }>();
  const { accounts, reload, lockVersion, syncAccount, offline } = useAppState();
  const shell = useShell();
  const account = accounts.find((a) => a.user_id === userId);
  const [db, setDb] = useState<Db | undefined>();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [revisions, setRevisions] = useState<RevisionRow[]>([]);
  const [submittedRevisions, setSubmittedRevisions] = useState<SubmittedRevisionSummary[]>([]);
  const [submittedRevisionsLoaded, setSubmittedRevisionsLoaded] = useState(false);
  const [submittedRevisionsError, setSubmittedRevisionsError] = useState(false);
  const [cases, setCases] = useState<CaseDetail[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>();
  const [onlineCases, setOnlineCases] = useState<CaseRow[]>([]);
  const [onlineCursor, setOnlineCursor] = useState<string | null>(null);
  const [onlineBusy, setOnlineBusy] = useState(false);
  const [registrations, setRegistrations] = useState<Registration[]>([]);
  const [actions, setActions] = useState<CaseAction[]>([]);
  const [pausedProjects, setPausedProjects] = useState<PausedProject[]>([]);
  const [referenceData, setReferenceData] =
    useState<Awaited<ReturnType<typeof getCachedReferenceData>>>();
  const [picking, setPicking] = useState(false);
  const [choosingProject, setChoosingProject] = useState(false);
  const [recent, setRecent] = useState<RecentTarget>();
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Results and failures are toasts, so the list never shifts under the user's thumb. A clear ("") is a no-op.
  const toast = useToast();
  const setMessage = useCallback(
    (text: string, kind: "error" | "success" = "error") => {
      if (text) toast.show({ kind, text });
    },
    [toast],
  );
  const [supersededUniqueIds, setSupersededUniqueIds] = useState<string[]>([]);
  const [serverKeptUploads, setServerKeptUploads] = useState<
    Array<{ uniqueId: string; locked: boolean }>
  >([]);
  const [canCodeNowUniqueIds, setCanCodeNowUniqueIds] = useState<string[]>([]);
  const [draftConflict, setDraftConflict] = useState(false);
  const focusedRef = useRef(false);
  const dbRef = useRef<Db | undefined>(undefined);
  const onlineRequestGenerationRef = useRef(0);
  const submittedRequestGenerationRef = useRef(0);
  const selectedProjectRef = useRef<string | undefined>(undefined);
  const referenceDataRef =
    useRef<Awaited<ReturnType<typeof getCachedReferenceData>>>(undefined);
  const consumedRefreshFor = useRef<string | undefined>(undefined);
  const appStateRef = useRef(AppState.currentState);

  const setReference = useCallback(
    (next: Awaited<ReturnType<typeof getCachedReferenceData>>) => {
      const previousProjects = new Set(
        referenceDataRef.current?.projects.map(({ project }) => project.project_id) ?? [],
      );
      const authorizedProjects = new Set(
        next?.projects.map(({ project }) => project.project_id) ?? [],
      );
      const authorizationChanged =
        previousProjects.size !== authorizedProjects.size ||
        [...previousProjects].some((projectId) => !authorizedProjects.has(projectId));
      if (authorizationChanged) {
        submittedRequestGenerationRef.current += 1;
        setSubmittedRevisions((rows) => rows.filter((row) => authorizedProjects.has(row.project_id)));
        setSubmittedRevisionsLoaded(false);
        setSubmittedRevisionsError(false);
        setSelectedProjectId((selected) =>
          selected && authorizedProjects.has(selected)
            ? selected
            : next?.projects[0]?.project.project_id,
        );
      }
      referenceDataRef.current = next;
      setReferenceData(next);
    },
    [],
  );

  const isCurrent = useCallback(
    () =>
      Boolean(
        account &&
          account.user_id === userId &&
          focusedRef.current &&
          isUnlocked(account.user_id),
      ),
    [account, userId],
  );

  const clearVisible = useCallback(() => {
    focusedRef.current = false;
    onlineRequestGenerationRef.current += 1;
    submittedRequestGenerationRef.current += 1;
    selectedProjectRef.current = undefined;
    dbRef.current = undefined;
    referenceDataRef.current = undefined;
    setDb(undefined);
    setReferenceData(undefined);
    setDrafts([]);
    setRevisions([]);
    setSubmittedRevisions([]);
    setSubmittedRevisionsLoaded(false);
    setSubmittedRevisionsError(false);
    setCases([]);
    setRegistrations([]);
    setActions([]);
    setPausedProjects([]);
    setOnlineCases([]);
    setOnlineCursor(null);
    setSelectedProjectId(undefined);
    setPicking(false);
    setChoosingProject(false);
    setSupersededUniqueIds([]);
    setServerKeptUploads([]);
    setCanCodeNowUniqueIds([]);
    setDraftConflict(false);
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
    async (
      handle: Db,
      current: () => boolean = () => true,
      caseFlagsAuthoritative = false,
    ) => {
      const [d, c, r, a, localRevisions, reference] = await Promise.all([
        listDrafts(handle),
        listCases(handle),
        listRegistrations(handle),
        listActions(handle),
        listLocalRevisions(handle),
        getCachedReferenceData(handle),
      ]);
      const paused = await listPausedProjects(
        handle,
        new Set(reference?.projects.map(({ project }) => project.project_id) ?? []),
      );
      if (!current()) return;
      setDrafts(d);
      setRevisions(localRevisions);
      setCases(c);
      if (caseFlagsAuthoritative) {
        const authoritativeUniqueIds = new Set(c.map(({ unique_id }) => unique_id));
        setCanCodeNowUniqueIds((currentHints) =>
          currentHints.filter((uniqueId) => !authoritativeUniqueIds.has(uniqueId)),
        );
      }
      setRegistrations(r);
      setActions(a);
      setPausedProjects(paused);
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
        setActions([]);
        setPausedProjects([]);
        setCanCodeNowUniqueIds([]);
        setSubmittedRevisions([]);
        setSubmittedRevisionsLoaded(false);
        setSubmittedRevisionsError(false);
        setMessage(errorText(error));
        // Unsent work stays visible (as paused) when access is refused.
        try {
          await loadLocal(handle, current);
        } catch {
          // The cleared state is safer than retaining stale encrypted rows.
        }
        return;
      }
      let latest: Awaited<ReturnType<typeof getCachedReferenceData>>;
      try {
        latest = await getCachedReferenceData(handle);
      } catch (storageError) {
        if (current()) {
          setReference(undefined);
          setSubmittedRevisions([]);
          setSubmittedRevisionsLoaded(false);
          setSubmittedRevisionsError(false);
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
      setActions([]);
      setPausedProjects([]);
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
        Alert.alert(errorText(error));
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

  const refreshDefinitions = useCallback(
    async (userId: string, handle: Db, reference: Awaited<ReturnType<typeof getCachedReferenceData>>) => {
      try {
        await refreshAuthorizedProjectDefinitions(userId, handle, reference);
      } catch (error) {
        if (!isCurrent()) return;
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
          await handleError(error);
          return;
        }
        setMessage(errorText(error));
      }
    },
    [handleError, isCurrent],
  );

  const loadSubmittedInterviews = useCallback(
    async (projectIds: Set<string>, current: () => boolean = () => true) => {
      if (!account) return;
      const generation = ++submittedRequestGenerationRef.current;
      setSubmittedRevisionsError(false);
      try {
        const rows = await fetchSubmittedRevisions(account.user_id);
        if (!current() || generation !== submittedRequestGenerationRef.current) return;
        setSubmittedRevisions(rows.filter((row) => projectIds.has(row.project_id)));
        setSubmittedRevisionsLoaded(true);
      } catch (error) {
        if (!current() || generation !== submittedRequestGenerationRef.current) return;
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
          await handleError(error);
          return;
        }
        setSubmittedRevisionsError(true);
        setSubmittedRevisionsLoaded(false);
      }
    },
    [account, handleError],
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
          void loadSubmittedInterviews(
            new Set(cached?.projects.map(({ project }) => project.project_id) ?? []),
            () => active && isCurrent(),
          );
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
              await refreshDefinitions(account.user_id, handle, fresh);
              if (!active || !isCurrent()) return;
              const authorizedProjectIds = new Set(
                fresh?.projects.map(({ project }) => project.project_id) ?? [],
              );
              setSelectedProjectId((current) =>
                current &&
                fresh?.projects.some(
                  ({ project }) => project.project_id === current,
                )
                  ? current
                  : fresh?.projects[0]?.project.project_id,
              );
              void loadSubmittedInterviews(
                authorizedProjectIds,
                () => active && isCurrent(),
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
      loadSubmittedInterviews,
      refreshDefinitions,
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
          await refreshDefinitions(account.user_id, handle, fresh);
          if (!isCurrent()) return;
          const authorizedProjectIds = new Set(
            fresh?.projects.map(({ project }) => project.project_id) ?? [],
          );
          void loadSubmittedInterviews(authorizedProjectIds, isCurrent);
          await loadLocal(handle, isCurrent);
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
    loadSubmittedInterviews,
    refreshDefinitions,
    loadLocal,
    recoverAfterRefreshFailure,
    setReference,
  ]);

  // "Recent" in the site picker: the last choice for this project, read from the interviewer's own store.
  useEffect(() => {
    let active = true;
    setRecent(undefined);
    if (db && selectedProjectId) void readRecentTarget(db, selectedProjectId).then((value) => { if (active) setRecent(value); });
    return () => { active = false; };
  }, [db, selectedProjectId]);

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
    setRefreshing(true);
    try {
      const fresh = await refreshReferenceData(account.user_id, db, {
        force: true,
      });
      if (!isCurrent()) return;
      setReference(fresh);
      await refreshDefinitions(account.user_id, db, fresh);
      if (!isCurrent()) return;
      await refreshCases(account.user_id, db);
      await loadLocal(db, isCurrent, true);
      const authorizedProjectIds = new Set(
        fresh?.projects.map(({ project }) => project.project_id) ?? [],
      );
      await loadSubmittedInterviews(authorizedProjectIds, isCurrent);
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
      if (isCurrent()) setMessage(t("refreshed"), "success");
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
      setRefreshing(false);
    }
  }

  function openRevision(summary: SubmittedRevisionSummary | RevisionRow) {
    if (
      !account ||
      !db ||
      !isUnlocked(account.user_id) ||
      !referenceDataRef.current?.projects.some(
        ({ project }) => project.project_id === summary.project_id,
      )
    ) {
      setMessage(t("revisionUnavailable"));
      return;
    }
    router.push({
      pathname: "/revision",
      params: {
        userId: account.user_id,
        draftId: summary.draft_id,
        projectId: summary.project_id,
        siteId: summary.site_id,
        vaSid: summary.va_sid,
      },
    });
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
    const syncGeneration = onlineRequestGenerationRef.current;
    const isCurrentSync = () =>
      isCurrent() && syncGeneration === onlineRequestGenerationRef.current;
    let caseFlagsAuthoritative = false;
    setBusy(true);
    setSupersededUniqueIds([]);
    setServerKeptUploads([]);
    setCanCodeNowUniqueIds([]);
    try {
      const { sync: result, reference: fresh } = await syncAccount(account.user_id, db, {
        onSuperseded: (uniqueId) => {
          if (isCurrentSync()) {
            setSupersededUniqueIds((current) =>
              current.includes(uniqueId) ? current : [...current, uniqueId],
            );
          }
        },
        onDraftConflict: () => {
          if (isCurrentSync()) setDraftConflict(true);
        },
        onServerKept: (notice) => {
          if (!isCurrentSync()) return;
          setServerKeptUploads((current) => {
            const existing = current.find((item) => item.uniqueId === notice.uniqueId);
            if (existing) {
              return current.map((item) =>
                item.uniqueId === notice.uniqueId
                  ? { ...item, locked: item.locked || notice.locked }
                  : item,
              );
            }
            return [...current, notice];
          });
        },
        onCanCodeNow: (uniqueId) => {
          if (isCurrentSync()) {
            setCanCodeNowUniqueIds((current) => current.includes(uniqueId) ? current : [...current, uniqueId]);
          }
        },
      });
      caseFlagsAuthoritative = true;
      if (isCurrentSync()) {
        setMessage(
          t("syncResult", {
            sent: result.sent,
            failed: result.failed,
            remaining: result.remaining,
          }),
          result.failed ? "error" : "success",
        );
        setSupersededUniqueIds((current) =>
          [...new Set([...current, ...result.supersededUniqueIds])],
        );
        if (result.serverKeptUploads?.length) {
          setServerKeptUploads((current) => {
            const merged = new Map(current.map((notice) => [notice.uniqueId, notice]));
            for (const notice of result.serverKeptUploads ?? []) {
              const existing = merged.get(notice.uniqueId);
              merged.set(notice.uniqueId, {
                ...notice,
                locked: notice.locked || existing?.locked === true,
              });
            }
            return [...merged.values()];
          });
        }
        const acknowledgedCodeHints = result.canCodeNowUniqueIds ?? [];
        if (acknowledgedCodeHints.length) {
          setCanCodeNowUniqueIds((current) => [...new Set([...current, ...acknowledgedCodeHints])]);
        }
        if (result.draftConflictIds?.length) setDraftConflict(true);
      }
      if (isCurrentSync()) {
        setReference(fresh);
      }
    } catch (error) {
      if (isCurrent()) await handleError(error);
    } finally {
      try {
        await loadLocal(db, isCurrent, caseFlagsAuthoritative);
      } catch (error) {
        if (isCurrent()) await handleError(error);
      }
      setBusy(false);
      void shell.recount();
    }
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
  const authorizedProjectIds = new Set(projects.map(({ project_id }) => project_id));
  const authorizedCases = cases.filter((row) => row.project_id && authorizedProjectIds.has(row.project_id));
  const authorizedRegistrations = registrations.filter((row) => authorizedProjectIds.has(row.project_id));
  const authorizedDrafts = drafts.filter((row) => row.project_id && authorizedProjectIds.has(row.project_id));
  const visibleCases = selectedProjectId
    ? authorizedCases.filter((row) => row.project_id === selectedProjectId)
    : authorizedCases;
  const visibleRegistrations = selectedProjectId
    ? authorizedRegistrations.filter((row) => row.project_id === selectedProjectId)
    : authorizedRegistrations;
  const visibleDrafts = selectedProjectId
    ? authorizedDrafts.filter((row) => row.project_id === selectedProjectId)
    : authorizedDrafts;
  const visibleRevisions = revisions.filter(
    (row) =>
      authorizedProjectIds.has(row.project_id) &&
      (!selectedProjectId || row.project_id === selectedProjectId),
  );
  const visibleSubmittedRevisions = submittedRevisions.filter(
    (row) =>
      authorizedProjectIds.has(row.project_id) &&
      (!selectedProjectId || row.project_id === selectedProjectId),
  );
  const items = buildInterviewItems({
    drafts: visibleDrafts,
    registrations: visibleRegistrations,
    cases: visibleCases,
    onlineCases: selectedProjectId ? onlineCases : [],
    submitted: visibleSubmittedRevisions,
    revisions: visibleRevisions,
  });
  const summary = homeSummary(items, interviewCounts(items));
  const canRegister = Boolean(selectedProject && registersDeaths(selectedProject.project) && account.registration_access);
  const loaded = Boolean(db && referenceData);
  const isOffline = Boolean(offline);

  function startInterview(target: PickerTarget) {
    setPicking(false);
    if (db) void writeRecentTarget(db, target.projectId, { siteId: target.siteId, orgUnitId: target.orgUnitId });
    router.push({
      pathname: "/form",
      params: {
        userId: account!.user_id,
        draftId: randomUUID(),
        projectId: target.projectId,
        siteId: target.siteId,
        ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {}),
      },
    });
  }

  function openRegister() {
    router.push({ pathname: "/register", params: { userId: account!.user_id, projectId: selectedProject?.project.project_id ?? "" } });
  }

  function runAction(action: InterviewAction) {
    if (action.type === "resume") {
      router.push({
        pathname: "/form",
        params: { userId: account!.user_id, draftId: action.draft.id, ...(action.draft.project_id ? { projectId: action.draft.project_id } : {}) },
      });
    } else if (action.type === "case") {
      router.push({ pathname: "/case", params: { userId: account!.user_id, projectId: action.projectId, deathId: action.deathId } });
    } else if (action.type === "registration") {
      router.push({ pathname: "/case", params: { userId: account!.user_id, clientDeathId: action.clientDeathId } });
    } else {
      openRevision(action.source);
    }
  }

  function retryDemo(item: InterviewItem) {
    const handle = dbRef.current;
    if (handle && item.retryDemo) void retryDemoLimitDraft(handle, item.retryDemo.id).then(() => loadLocal(handle));
  }

  // Sync outcomes the old list showed under its buttons; kept as notices on both tabs.
  const notices = (
    <>
      {draftConflict ? <Notice>{t("draftConflictNotice")}</Notice> : null}
      {canCodeNowUniqueIds
        .filter((uniqueId) =>
          !cases.some((row) => row.unique_id === uniqueId && row.code_now === true) &&
          !onlineCases.some((row) => row.unique_id === uniqueId && row.code_now === true)
        )
        .map((uniqueId) => <Notice key={`code-now-${uniqueId}`}>{t("readyForCodeOnWeb")}</Notice>)}
      {supersededUniqueIds.map((uniqueId, index) => (
        <Notice key={`${uniqueId}-${index}`}>{t("supersededInterviewNotice")} {t("storedInterviewId", { uniqueId })}</Notice>
      ))}
      {serverKeptUploads
        .filter((notice) => !supersededUniqueIds.includes(notice.uniqueId))
        .map(({ uniqueId, locked }) => (
          <Notice key={`server-kept-${uniqueId}`}>
            {t("submissionHistoryNotice")} {locked ? t("submissionLockedNotice") : ""} {t("storedInterviewId", { uniqueId })}
          </Notice>
        ))}
      {pausedProjects.map((paused) => {
        const count =
          drafts.filter((row) => row.project_id === paused.projectId).length +
          registrations.filter((row) => row.project_id === paused.projectId).length +
          actions.filter((row) => row.project_id === paused.projectId).length +
          revisions.filter((row) => row.project_id === paused.projectId).length;
        return (
          <Notice key={`paused-${paused.projectId}`}>
            {t("pausedProjectTitle", { name: paused.projectName ?? paused.projectId, count })} {t("pausedProjectReason")}
            {paused.refusal ? ` ${t("pausedProjectRefused", { code: paused.refusal.code ?? String(paused.refusal.status) })}` : ""}
          </Notice>
        );
      })}
    </>
  );

  const projectLine = (
    <ProjectLine
      project={selectedProject?.project.project_name}
      name={account.name}
      onPress={projects.length > 1 ? () => setChoosingProject(true) : undefined}
    />
  );
  const sheets = (
    <>
      <SitePickerSheet visible={picking} targets={targets} recent={recent} onPick={startInterview} onClose={() => setPicking(false)} />
      <ProjectSheet
        visible={choosingProject}
        projects={projects}
        selectedId={selectedProjectId}
        onClose={() => setChoosingProject(false)}
        onPick={(projectId) => {
          setChoosingProject(false);
          onlineRequestGenerationRef.current += 1;
          setSelectedProjectId(projectId);
          setOnlineCases([]);
          setOnlineCursor(null);
        }}
      />
    </>
  );

  if (interviews) {
    return (
      <Screen title={t("tabInterviews")} scroll={false}>
        <InterviewsView
          loaded={Boolean(db)}
          offline={isOffline}
          items={items}
          initialFilter={filter}
          canRegister={canRegister}
          refreshing={refreshing}
          busy={busy}
          canRefresh={Boolean(db)}
          hasMore={Boolean(onlineCursor)}
          loadingMore={onlineBusy}
          loadFailed={submittedRevisionsError}
          onAction={runAction}
          onRetryDemo={retryDemo}
          onRegister={openRegister}
          onRefresh={() => void refresh()}
          onSend={() => void send()}
          onLoadMore={() => void loadOnlineMore()}
          header={projectLine}
          footer={notices}
        />
        {sheets}
      </Screen>
    );
  }
  return (
    <Screen title={t("home")}>
      {projectLine}
      <HomeView
        loaded={Boolean(db)}
        offline={isOffline}
        summary={summary}
        unsent={shell.sync.work?.unsent}
        canStart={Boolean(db && referenceData && targets.length > 0)}
        canRegister={canRegister}
        busy={busy}
        onResume={(item) => item.action && runAction(item.action)}
        onStart={() => setPicking(true)}
        onRegister={openRegister}
        onSend={() => void send()}
        onViewTodo={() => router.push({ pathname: "/worklist", params: { userId: account.user_id, view: "interviews", filter: "todo" } })}
      >
        {account.registered_deaths_access ? (
          <Button
            kind="secondary"
            label={t("myRegisteredDeaths")}
            onPress={() => router.push({ pathname: "/worklist", params: { userId: account.user_id, registeredMine: "1" } })}
          />
        ) : null}
        {notices}
      </HomeView>
      {sheets}
    </Screen>
  );
}
