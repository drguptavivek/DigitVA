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
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, AppState, InteractionManager } from "react-native";

import { useAppState } from "../AppState";
import { SessionRevokedError, SignInRequiredError, takePickedHomeProject } from "../auth";
import {
  listActions,
  listCases,
  listRegistrations,
  type CaseAction,
  type CaseRow,
  type CaseDetail,
  type Registration,
} from "../cases";
import { sendRefusals, type SendRefusal } from "../unsentWork";
import { deleteUnsentDraft, getMeta, listDraftsNamed, setMeta, reopenCompletedDraft, retryHeldDraft, type Db, type DraftRow } from "../drafts";
import { codingNotices, dismissCodingNotices, type CodingNotice } from "../codingUploadNotices";
import { codingNoticeText } from "../standalone/adopt";
import { checkCollectionGate, gateMessage, recordCollectionStart, type GateDecision } from "../collectionGate";
import { ConfirmDialog } from "../ConfirmDialog";
import { FirstDownloadModal } from "../FirstDownloadModal";
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
  preloadLastFormLocale,
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
import { dropWorklist, heldWorklist, holdWorklist } from "../worklistCache";
import { icons } from "../Icon";
import { displayProjectName } from "../projectName";
import { Button, Card, DetailsChip, errorText, ListRow, Screen, Separator } from "../ui";
import { buildInterviewItems, interviewCounts, type InterviewAction, type InterviewItem, type ListedDraft } from "../ui/interviewRows";
import { homeSummary } from "../ui/homeSummary";
import { readRecentTarget, writeRecentTarget, type RecentTarget } from "../recentTarget";
import type { PickerTarget } from "../ui/sitePicker";
import RegisteredDeaths from "./RegisteredDeaths";
import { HomeView, InterviewsView, Notice, ProjectLine, ProjectSheet, SitePickerSheet } from "./worklistParts";

type ClosedGate = Exclude<GateDecision, { open: true }>;

/** Per-account meta key for the project the user chose on Interviews. */
const PICKED_PROJECT_KEY = "worklist.project.v1";
/** The submitted-interviews list is fetched at most this often per account unless something changed it (Refresh, Send, a lock bump). */
const SUBMITTED_TTL_MS = 60_000;

export default function Worklist() {
  const { userId, registeredMine, view, filter } = useLocalSearchParams<{ userId: string; registeredMine?: string; view?: string; filter?: string }>();
  const { accounts } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const reporterOnly = account?.collection_access !== true && account?.registration_access === true;
  if (reporterOnly || (registeredMine === "1" && account?.registered_deaths_access === true)) {
    return <RegisteredDeaths userId={userId} registeredMine />;
  }
  return <InterviewWorklist interviews={(Array.isArray(view) ? view[0] : view) === "interviews"} filter={filter} />;
}

function InterviewWorklist({ interviews, filter }: { interviews: boolean; filter?: string | string[] }) {
  const router = useRouter();
  const { userId, refresh: refreshOnFocus } = useLocalSearchParams<{
    userId: string;
    refresh?: string;
  }>();
  const { accounts, device, reload, lockVersion, syncAccount, offline, uiLocale } = useAppState();
  const lastLockVersion = useRef(lockVersion);
  const shell = useShell();
  const account = accounts.find((a) => a.user_id === userId);
  // The last data this tab (or its sibling) loaded, if the same store is still open: drawn at once while it refreshes.
  const [held] = useState(() => (userId ? heldWorklist(userId) : undefined));
  const [db, setDb] = useState<Db | undefined>();
  const [drafts, setDrafts] = useState<ListedDraft[]>(held?.drafts ?? []);
  const [refusals, setRefusals] = useState<Map<string, SendRefusal>>(held?.refusals ?? new Map());
  const [revisions, setRevisions] = useState<RevisionRow[]>(held?.revisions ?? []);
  const [firstDownload, setFirstDownload] = useState(false);
  const [submittedRevisions, setSubmittedRevisions] = useState<SubmittedRevisionSummary[]>(held?.submittedRevisions ?? []);
  const [submittedRevisionsLoaded, setSubmittedRevisionsLoaded] = useState(false);
  // The revisions list failed to load: undefined = fine; the text is what Interviews shows (no connection, or Retry + the Ref line).
  const [submittedRevisionsError, setSubmittedRevisionsError] = useState<string | undefined>();
  const [cases, setCases] = useState<CaseDetail[]>(held?.cases ?? []);
  const [selectedProjectId, setSelectedProjectId] = useState<string | undefined>(held?.selectedProjectId);
  // The user's own pick (kept in this account's database) survives blur and reference refreshes, unlike the state above.
  const pickedProjectRef = useRef<string | undefined>(undefined);
  const deviceProjectRef = useRef<string | undefined>(undefined);
  deviceProjectRef.current = device?.project_id;
  // Keep the current project while authorized, else the saved pick, else the project this phone was enrolled on, else the first.
  const defaultProject = useCallback((ids: string[], current?: string) =>
    [current, pickedProjectRef.current, deviceProjectRef.current].find((id) => id && ids.includes(id)) ?? ids[0], []);
  const [onlineCases, setOnlineCases] = useState<CaseRow[]>(held?.onlineCases ?? []);
  const [onlineCursor, setOnlineCursor] = useState<string | null>(null);
  const [onlineBusy, setOnlineBusy] = useState(false);
  const [registrations, setRegistrations] = useState<Registration[]>(held?.registrations ?? []);
  const [actions, setActions] = useState<CaseAction[]>(held?.actions ?? []);
  const [pausedProjects, setPausedProjects] = useState<PausedProject[]>(held?.pausedProjects ?? []);
  const [referenceData, setReferenceData] =
    useState<Awaited<ReturnType<typeof getCachedReferenceData>>>(held?.referenceData);
  // The cached reference data has been read since the last unlock (it may be absent on a first sign-in). Until then
  // the views show their skeletons: without it they would draw an account with no project and then jump.
  const [referenceRead, setReferenceRead] = useState(held !== undefined);
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
  const [codingUploadNotices, setCodingUploadNotices] = useState<CodingNotice[]>([]);
  const [deleting, setDeleting] = useState<DraftRow | undefined>();
  const [reopening, setReopening] = useState<DraftRow | undefined>();
  const focusedRef = useRef(false);
  const dbRef = useRef<Db | undefined>(undefined);
  const onlineRequestGenerationRef = useRef(0);
  const submittedRequestGenerationRef = useRef(0);
  const selectedProjectRef = useRef<string | undefined>(held?.selectedProjectId);
  const referenceDataRef =
    useRef<Awaited<ReturnType<typeof getCachedReferenceData>>>(held?.referenceData);
  const consumedRefreshFor = useRef<string | undefined>(undefined);
  const appStateRef = useRef(AppState.currentState);
  const submittedFetchedRef = useRef<{ key: string; at: number } | undefined>(undefined);
  const submittedInFlightRef = useRef<string | undefined>(undefined);

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
        submittedFetchedRef.current = undefined;
        setSubmittedRevisions((rows) => rows.filter((row) => authorizedProjects.has(row.project_id)));
        setSubmittedRevisionsLoaded(false);
        setSubmittedRevisionsError(undefined);
        setSelectedProjectId((selected) =>
          defaultProject(next?.projects.map(({ project }) => project.project_id) ?? [], selected),
        );
      }
      referenceDataRef.current = next;
      setReferenceData(next);
    },
    [defaultProject],
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

  /** Leaving the screen: late answers are dropped, but what is shown stays for the way back (no skeleton flash). */
  const stopWork = useCallback(() => {
    focusedRef.current = false;
    onlineRequestGenerationRef.current += 1;
    submittedRequestGenerationRef.current += 1;
  }, []);

  /** Account change, lock or session error: the decrypted rows held in state go with it. */
  const clearVisible = useCallback(() => {
    stopWork();
    submittedFetchedRef.current = undefined;
    selectedProjectRef.current = undefined;
    dbRef.current = undefined;
    referenceDataRef.current = undefined;
    setDb(undefined);
    setReferenceData(undefined);
    setReferenceRead(false);
    setDrafts([]);
    setRevisions([]);
    setSubmittedRevisions([]);
    setSubmittedRevisionsLoaded(false);
    setSubmittedRevisionsError(undefined);
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
    setCodingUploadNotices([]);
  }, [stopWork]);

  // Another account (or this screen going away) drops the rows held for the last one.
  useEffect(() => () => clearVisible(), [account?.user_id, clearVisible]);

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
      const [d, c, r, a, localRevisions, reference, lastRefusals, codingNoticesForAccount] = await Promise.all([
        listDraftsNamed(handle),
        listCases(handle),
        listRegistrations(handle),
        listActions(handle),
        listLocalRevisions(handle),
        getCachedReferenceData(handle),
        sendRefusals(handle),
        codingNotices(handle),
      ]);
      const paused = await listPausedProjects(
        handle,
        new Set(reference?.projects.map(({ project }) => project.project_id) ?? []),
      );
      if (!current()) return;
      setDrafts(d);
      setRefusals(lastRefusals);
      setCodingUploadNotices(codingNoticesForAccount);
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
        setSubmittedRevisionsError(undefined);
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
          setSubmittedRevisionsError(undefined);
          setMessage(errorText(storageError));
        }
        return;
      }
      if (!current()) return;
      setReference(latest);
      setSelectedProjectId((selected) =>
        defaultProject(latest?.projects.map(({ project }) => project.project_id) ?? [], selected),
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
        dropWorklist();
        clearVisible();
        await reload();
        router.replace("/");
        return;
      }
      // Tokens dropped, data kept: the home screen now flags this account.
      if (error instanceof SignInRequiredError) {
        dropWorklist();
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
    async (projectIds: Set<string>, current: () => boolean = () => true, force = false) => {
      if (!account) return;
      const key = [...projectIds].sort().join("|");
      const fetched = submittedFetchedRef.current;
      // The second call of a focus (after the reference refresh) and a quick return to the screen ask the same question.
      if (!force && (submittedInFlightRef.current === key ||
          (fetched?.key === key && Date.now() - fetched.at < SUBMITTED_TTL_MS))) return;
      const generation = ++submittedRequestGenerationRef.current;
      submittedInFlightRef.current = key;
      setSubmittedRevisionsError(undefined);
      try {
        const rows = await fetchSubmittedRevisions(account.user_id);
        if (!current() || generation !== submittedRequestGenerationRef.current) return;
        setSubmittedRevisions(rows.filter((row) => projectIds.has(row.project_id)));
        setSubmittedRevisionsLoaded(true);
        submittedFetchedRef.current = { key, at: Date.now() };
      } catch (error) {
        if (!current() || generation !== submittedRequestGenerationRef.current) return;
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
          await handleError(error);
          return;
        }
        // No network (the fetch threw a TypeError, the same signal that flags the phone offline) is not a fault to retry; any other failure keeps its Ref line.
        setSubmittedRevisionsError(error instanceof TypeError ? t("revisionsNeedConnection") : `${t("revisionRetry")}\n${errorText(error).split("\n").pop()}`);
        setSubmittedRevisionsLoaded(false);
      } finally {
        if (submittedInFlightRef.current === key) submittedInFlightRef.current = undefined;
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
          // A home project picked at enrolment (src/nativeRoutes/enrol.tsx) seeds the remembered pick once.
          const enrolPick = takePickedHomeProject(account.user_id);
          if (enrolPick) await setMeta(handle, PICKED_PROJECT_KEY, enrolPick).catch(() => undefined);
          pickedProjectRef.current = (await getMeta<string>(handle, PICKED_PROJECT_KEY).catch(() => undefined)) || undefined;
          if (!active) return;
          await loadLocal(handle, () => active && isCurrent());
          const cached = await getCachedReferenceData(handle);
          if (!active) return;
          setReference(cached);
          setReferenceRead(true);
          // Home is drawn: now, off the interaction path, bring the last-used form language into memory.
          InteractionManager.runAfterInteractions(() => {
            try { void preloadLastFormLocale(handle, cached).catch(() => undefined); } catch { /* preload is best-effort */ }
          });
          // Nothing downloaded yet (first sign-in on this phone): block Home until it is.
          const isFirstDownload = !cached;
          if (isFirstDownload) setFirstDownload(true);
          void loadSubmittedInterviews(
            new Set(cached?.projects.map(({ project }) => project.project_id) ?? []),
            () => active && isCurrent(),
          );
          const cachedIds = cached?.projects.map(({ project }) => project.project_id) ?? [];
          if (pickedProjectRef.current && cached && !cachedIds.includes(pickedProjectRef.current)) {
            pickedProjectRef.current = undefined;
            void setMeta(handle, PICKED_PROJECT_KEY, null).catch(() => undefined);
          }
          // The pick made on another tab wins over this tab's older one.
          setSelectedProjectId(defaultProject(cachedIds));
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
                defaultProject(fresh?.projects.map(({ project }) => project.project_id) ?? [], current),
              );
              void loadSubmittedInterviews(
                authorizedProjectIds,
                () => active && isCurrent(),
              );
              if (forceRefresh || isFirstDownload) await refreshCases(account.user_id, handle);
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
          } finally {
            if (isFirstDownload) setFirstDownload(false);
          }
        } catch (error) {
          if (active) await handleError(error);
        }
      })();
      return () => {
        active = false;
        stopWork();
      };
    }, [
      account,
      stopWork,
      clearVisible,
      handleError,
      isCurrent,
      loadSubmittedInterviews,
      refreshDefinitions,
      loadLocal,
      recoverAfterRefreshFailure,
      defaultProject,
      refreshCases,
      refreshOnFocus,
      router,
      setReference,
    ]),
  );

  // Data changed under the open screen (a Send or Refresh from the shell, an access change) or the store was locked/unlocked:
  // reread quietly in place, never through the focus effect's reset. A lock drops what is held.
  useEffect(() => {
    if (lastLockVersion.current === lockVersion) return;
    lastLockVersion.current = lockVersion;
    if (!account) return;
    if (!isUnlocked(account.user_id)) {
      dropWorklist();
      clearVisible();
      return;
    }
    const handle = dbRef.current;
    if (!handle || !focusedRef.current) return;
    void (async () => {
      try {
        await loadLocal(handle, isCurrent);
        const cached = await getCachedReferenceData(handle);
        if (!isCurrent()) return;
        setReference(cached);
        void loadSubmittedInterviews(new Set(cached?.projects.map(({ project }) => project.project_id) ?? []), isCurrent, true);
      } catch (error) {
        if (isCurrent()) await handleError(error);
      }
    })();
  }, [lockVersion, account, clearVisible, loadLocal, isCurrent, setReference, loadSubmittedInterviews, handleError]);

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

  const selectedProject = useMemo(
    () => (referenceData?.projects ?? []).find(({ project }) => project.project_id === selectedProjectId),
    [referenceData, selectedProjectId],
  );
  const targets = useMemo(
    () => selectedProject
      ? targetsFrom(selectedProject.project, selectedProject.units).filter((target) => startsDirectly(selectedProject.project, target.siteId))
      : [],
    [selectedProject],
  );
  const registerTargets = useMemo(
    () => selectedProject
      ? targetsFrom(selectedProject.project, selectedProject.units).filter((target) => registersDeaths(selectedProject.project, target.siteId))
      : [],
    [selectedProject],
  );
  const projects = useMemo(() => referenceData?.projects.map(({ project }) => project) ?? [], [referenceData]);
  const items = useMemo(() => {
    const authorized = new Set(projects.map(({ project_id }) => project_id));
    const visible = <T extends { project_id: string | null | undefined }>(rows: T[]) =>
      rows.filter((row) => row.project_id && authorized.has(row.project_id) && (!selectedProjectId || row.project_id === selectedProjectId));
    return buildInterviewItems({
      drafts: visible(drafts),
      registrations: visible(registrations),
      cases: visible(cases),
      onlineCases: selectedProjectId ? onlineCases : [],
      submitted: visible(submittedRevisions),
      revisions: visible(revisions),
      refusals,
      sync: shell.sync,
    });
    // uiLocale: the card words (badge, action, time) are translated when built, so a language change rebuilds them.
  }, [projects, selectedProjectId, drafts, registrations, cases, onlineCases, submittedRevisions, revisions, refusals, shell.sync.lastAt, uiLocale]);
  useEffect(() => {
    if (db && userId && referenceRead) {
      holdWorklist(userId, db, { drafts, refusals, revisions, cases, registrations, actions, pausedProjects, submittedRevisions, onlineCases, referenceData, selectedProjectId });
    }
  }, [db, userId, referenceRead, drafts, refusals, revisions, cases, registrations, actions, pausedProjects, submittedRevisions, onlineCases, referenceData, selectedProjectId]);
  const summary = useMemo(() => homeSummary(items, interviewCounts(items)), [items]);

  // A closed collection gate (paused, outside its dates, daily limit) for every place a new start could go: the start
  // buttons are disabled and a banner says why. Resume and finishing are never gated. Offline or a stale answer is open.
  const [startGate, setStartGate] = useState<ClosedGate>();
  const [registerGate, setRegisterGate] = useState<ClosedGate>();
  useEffect(() => {
    let live = true;
    const closedFor = async (list: typeof targets) => {
      if (!db || list.length === 0) return undefined;
      let first: ClosedGate | undefined;
      for (const target of list) {
        const gate = await checkCollectionGate(db, target.projectId, target.siteId, target.orgUnitId);
        if (gate.open) return undefined;
        first ??= gate;
      }
      return first;
    };
    void Promise.all([closedFor(targets), closedFor(registerTargets)])
      .then(([start, register]) => { if (live) { setStartGate(start); setRegisterGate(register); } })
      .catch(() => { if (live) { setStartGate(undefined); setRegisterGate(undefined); } });
    return () => { live = false; };
  }, [db, targets, registerTargets, offline, lockVersion, drafts]);

  const openRevision = useCallback((summary: SubmittedRevisionSummary | RevisionRow) => {
    if (
      !userId ||
      !db ||
      !isUnlocked(userId) ||
      !referenceDataRef.current?.projects.some(({ project }) => project.project_id === summary.project_id)
    ) {
      setMessage(t("revisionUnavailable"));
      return;
    }
    router.push({
      pathname: "/revision",
      params: { userId, draftId: summary.draft_id, projectId: summary.project_id, siteId: summary.site_id, vaSid: summary.va_sid },
    });
  }, [userId, db, router, setMessage]);

  const openRegister = useCallback(() => {
    router.push({ pathname: "/register", params: { userId, projectId: selectedProject?.project.project_id ?? "" } });
  }, [router, userId, selectedProject]);

  const runAction = useCallback((action: InterviewAction) => {
    if (action.type === "resume") {
      router.push({
        pathname: "/form",
        params: { userId, draftId: action.draft.id, ...(action.draft.project_id ? { projectId: action.draft.project_id } : {}) },
      });
    } else if (action.type === "reopen") {
      setReopening(action.draft);
    } else if (action.type === "case") {
      router.push({ pathname: "/case", params: { userId, projectId: action.projectId, deathId: action.deathId } });
    } else if (action.type === "registration") {
      router.push({ pathname: "/case", params: { userId, clientDeathId: action.clientDeathId } });
    } else {
      openRevision(action.source);
    }
  }, [router, userId, openRevision]);

  const retryDemo = useCallback((item: InterviewItem) => {
    const handle = dbRef.current;
    if (handle && item.retryDemo) void retryHeldDraft(handle, item.retryDemo.id).then(() => loadLocal(handle));
  }, [loadLocal]);

  const deleteDraftRow = useCallback((item: InterviewItem) => setDeleting(item.deletable), []);

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
      await loadSubmittedInterviews(authorizedProjectIds, isCurrent, true);
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
        // New submissions are on the server now; the cached list is stale.
        if (result.sent > 0) {
          void loadSubmittedInterviews(
            new Set(fresh?.projects.map(({ project }) => project.project_id) ?? []),
            isCurrent,
            true,
          );
        }
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

  const canRegister = Boolean(selectedProject && registersDeaths(selectedProject.project) && account.registration_access);
  const loaded = Boolean(db && referenceData);
  const isOffline = Boolean(offline);
  const goRows = [
    canRegister ? <ListRow key="register" icon={icons.register} label={t("registerDeath")} disabled={registerGate !== undefined} onPress={openRegister} /> : null,
    account.registered_deaths_access ? (
      <ListRow key="mine" icon={icons.interviews} label={t("myRegisteredDeaths")} onPress={() => router.push({ pathname: "/worklist", params: { userId: account.user_id, registeredMine: "1" } })} />
    ) : null,
  ].filter((row) => row !== null);
  // Each row is followed by a separator when another row comes after it in the same card.
  const homeRows = goRows.length ? goRows.flatMap((row, index) => (index < goRows.length - 1 ? [row, <Separator key={`sep-${index}`} icon />] : [row])) : undefined;
  const gateBanner = startGate || registerGate ? <Notice tone="warning">{gateMessage((startGate ?? registerGate)!)}</Notice> : null;

  /** A new interview with no registration is a new start, checked against the collection gate (digitva-dj29). */
  async function startInterview(target: PickerTarget) {
    setPicking(false);
    if (db) {
      const gate = await checkCollectionGate(db, target.projectId, target.siteId, target.orgUnitId);
      if (!gate.open) {
        setMessage(gateMessage(gate));
        return;
      }
      await recordCollectionStart(db, target.projectId, target.siteId, target.orgUnitId);
      void writeRecentTarget(db, target.projectId, { siteId: target.siteId, orgUnitId: target.orgUnitId });
    }
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

  /** Delete a never-sent draft after the danger dialog; the store re-checks it was never sent and deletes nothing on the server. */
  async function confirmDeleteDraft() {
    const draft = deleting;
    const handle = dbRef.current;
    setDeleting(undefined);
    if (!draft || !handle) return;
    try {
      if (!(await deleteUnsentDraft(handle, draft.id))) throw new Error("draft_not_deletable");
      setMessage(t("deleteDraftDone"), "success");
    } catch {
      setMessage(t("deleteDraftFailed"));
    }
    await loadLocal(handle);
  }

  /** Reopen a ready interview after the dialog; refused (nothing changed) once a send has started, then open the form. */
  async function confirmReopen() {
    const draft = reopening;
    const handle = dbRef.current;
    setReopening(undefined);
    if (!draft || !handle) return;
    try {
      const outcome = await reopenCompletedDraft(handle, account!.user_id, draft.id);
      if (outcome !== "reopened") {
        setMessage(t(outcome === "busy" ? "reopenBusy" : "reopenRefused"));
        await loadLocal(handle);
        return;
      }
    } catch {
      setMessage(t("reopenRefused"));
      await loadLocal(handle);
      return;
    }
    runAction({ type: "resume", draft, label: t("actionResume") });
  }

  async function dismissCodingUploadNotices() {
    const handle = dbRef.current;
    if (!handle) return;
    try {
      await dismissCodingNotices(handle);
      setCodingUploadNotices([]);
    } catch (error) {
      setMessage(errorText(error));
    }
  }

  // Sync outcomes the old list showed under its buttons; kept as notices on both tabs.
  const notices = (
    <>
      {draftConflict ? <Notice>{t("draftConflictNotice")}</Notice> : null}
      {codingUploadNotices.length ? (
        <>
          {codingUploadNotices.map((notice, index) => (
            <Fragment key={`${notice.draftId}-${notice.codingSha256 ?? notice.at}-${index}`}>
              <Notice>{codingNoticeText(notice.code)}</Notice>
              <DetailsChip code={notice.code} />
            </Fragment>
          ))}
          <Button kind="secondary" size="sm" label={t("dismiss")} onPress={() => void dismissCodingUploadNotices()} />
        </>
      ) : null}
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
          <Fragment key={`paused-${paused.projectId}`}>
            <Notice>
              {t("pausedProjectTitle", { name: paused.projectName ?? paused.projectId, count })} {t("pausedProjectReason")}
              {paused.refusal ? ` ${t("pausedProjectRefused")}` : ""}
            </Notice>
            {paused.refusal ? <DetailsChip code={paused.refusal.code ?? String(paused.refusal.status)} /> : null}
          </Fragment>
        );
      })}
    </>
  );

  // "GUJ026 · Gujarat Health System": the project's code and display name (the account's name is on the avatar).
  const projectLine = (
    <ProjectLine
      project={selectedProject?.project.project_id}
      name={displayProjectName(selectedProject?.project.project_name)}
      onPress={projects.length > 1 ? () => setChoosingProject(true) : undefined}
    />
  );
  const sheets = (
    <>
      {firstDownload ? <FirstDownloadModal /> : null}
      {deleting ? (
        <ConfirmDialog
          destructive
          title={t("deleteDraftTitle")}
          message={t("deleteDraftMessage")}
          confirmLabel={t("deleteDraft")}
          onConfirm={() => void confirmDeleteDraft()}
          onCancel={() => setDeleting(undefined)}
        />
      ) : null}
      {reopening ? (
        <ConfirmDialog
          title={t("reopenTitle")}
          message={t("reopenMessage")}
          confirmLabel={t("actionReopen")}
          onConfirm={() => void confirmReopen()}
          onCancel={() => setReopening(undefined)}
        />
      ) : null}
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
          pickedProjectRef.current = projectId;
          if (db) void setMeta(db, PICKED_PROJECT_KEY, projectId).catch(() => undefined);
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
          loaded={referenceRead}
          offline={isOffline}
          items={items}
          initialFilter={filter}
          canRegister={canRegister && registerGate === undefined}
          refreshing={refreshing}
          busy={busy}
          canRefresh={Boolean(db)}
          hasMore={Boolean(onlineCursor)}
          loadingMore={onlineBusy}
          loadFailed={submittedRevisionsError !== undefined}
          loadFailedText={submittedRevisionsError}
          onAction={runAction}
          onRetryDemo={retryDemo}
          onDeleteDraft={deleteDraftRow}
          onRegister={openRegister}
          onRefresh={() => void refresh()}
          onLoadMore={() => void loadOnlineMore()}
          header={<>{projectLine}{gateBanner}</>}
          footer={notices}
        />
        {sheets}
      </Screen>
    );
  }
  return (
    <Screen title={t("home")}>
      {projectLine}
      {gateBanner}
      <HomeView
        loaded={referenceRead}
        offline={isOffline}
        summary={summary}
        unsent={shell.sync.work?.unsent}
        unsentFiles={shell.sync.work?.unsentFiles}
        canStart={Boolean(db && referenceData && targets.length > 0)}
        startClosed={startGate !== undefined}
        busy={busy}
        onOpenSync={() => shell.openSheet("sync")}
        onResume={(item) => item.action && runAction(item.action)}
        onStart={() => setPicking(true)}
        onSend={() => void send()}
        onViewTodo={() => router.push({ pathname: "/worklist", params: { userId: account.user_id, view: "interviews", filter: "todo" } })}
        onViewDrafts={() => router.push({ pathname: "/worklist", params: { userId: account.user_id, view: "interviews", filter: "drafts" } })}
      >
        {/* One card of "go somewhere" rows: Register a death and My registered deaths. Coder lists live in the Code tab. */}
        {homeRows ? <Card grouped testID="home-go-rows">{homeRows}</Card> : null}
        {notices}
      </HomeView>
      {sheets}
    </Screen>
  );
}
