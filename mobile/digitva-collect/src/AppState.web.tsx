/** Browser session state. It deliberately has no native SQLite, SecureStore or bearer auth imports. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from "react";

import { setUiLocale, t } from "./i18n";
import { trainingBootstrap } from "./training";
import { getUiLocalePreference, setUiLocalePreference } from "./preferences";
import { abortClientRequests, ApiError, requestClientJson, type ClientBootstrap } from "./client/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { useIdleSignOut } from "./idleSignOut";
import { createBrowserDefinitionCache } from "./client/formDefinitionCache";
import { loadBrowserSession } from "./client/session";
import type { BootstrapResult } from "./client/api";
import { createNotificationPollGate, drainNotificationPages } from "./notificationPoll";
import { resetFirstHomeLoad } from "./web/roleHome";
import { browserSessionStore, clearAllScroll } from "./workspace/viewState";

const NOTIFICATION_POLL_INTERVAL_MS = 60_000;
const NOTIFICATION_AUTH_RETRY_MS = 60_000;
const AUTHORITATIVE_REFRESH_INTERVAL_MS = 15 * 60_000;
// An aborted request can still be finishing on the server and re-save the session it loaded, so the
// logout is repeated until the session answers 401.
const LOGOUT_ATTEMPTS = 4;
const LOGOUT_RETRY_MS = 400;

type BrowserDefinitionCache = ReturnType<typeof createBrowserDefinitionCache>;

interface BrowserDefinitionSession {
  accountId: string;
  cache: BrowserDefinitionCache;
  servedProjects: Set<string>;
  intakeProjects: Set<string>;
}

/** Memory-only polling state scoped to the current authenticated browser user. */
interface BrowserNotificationSession {
  userId: string;
  cursor: number;
  gate: ReturnType<typeof createNotificationPollGate>;
  lastAuthoritativeRefreshAt?: number;
  syncPending: boolean;
  revision: number;
  hasPolled: boolean;
}

interface BrowserAppState {
  ready: boolean;
  authenticated: boolean;
  bootstrap?: ClientBootstrap;
  /** Set inside TrainingScope: the user's real bootstrap, which the menu keeps using. */
  unscopedBootstrap?: ClientBootstrap;
  loginUrl?: string;
  actionCode?: "terms_required";
  error?: string;
  uiLocale: string;
  chooseUiLocale(code: string): Promise<void>;
  reload(): Promise<void>;
  activity(): void;
  lockNow(): Promise<void>;
  lockVersion: number;
  unlocked(): void;
  onBeforeLock(hook: () => Promise<void>): () => void;
  logout(): Promise<void>;
  definitionCache?: BrowserDefinitionCache;
  hasServedDefinition(projectId: string): boolean;
  markServedDefinition(projectId: string): Promise<void>;
  sessionGeneration: number;
  notificationGeneration: number;
  acknowledgeAuthoritativeRefresh(expectedRevision: number): void;
}

const Context = createContext<BrowserAppState | undefined>(undefined);

/**
 * True when a re-read of /me/access changed nothing but its CSRF token. Screens reset on a new
 * bootstrap object, so a tab resume or refusal reload must keep the old one; requests take the
 * newest token from the API module, not from this snapshot.
 */
function sameBootstrap(previous: ClientBootstrap | undefined, next: ClientBootstrap): boolean {
  if (!previous) return false;
  const { csrf: _previousCsrf, ...previousRest } = previous;
  const { csrf: _nextCsrf, ...nextRest } = next;
  return JSON.stringify(previousRest) === JSON.stringify(nextRest);
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [bootstrap, setBootstrap] = useState<ClientBootstrap>();
  const [loginUrl, setLoginUrl] = useState<string>();
  const [actionCode, setActionCode] = useState<BrowserAppState["actionCode"]>();
  const [error, setError] = useState<string>();
  const [uiLocale, setLocaleState] = useState("en");
  const [sessionGeneration, setSessionGeneration] = useState(0);
  const [notificationGeneration, setNotificationGeneration] = useState(0);
  const notificationRevision = useRef(0);
  const [lockVersion] = useState(0);
  const browserRequestGeneration = useRef(0);
  const loggingOut = useRef(false);
  const refreshInFlight = useRef<Promise<void> | undefined>(undefined);
  const definitionSession = useRef<BrowserDefinitionSession | undefined>(undefined);
  const notificationSession = useRef<BrowserNotificationSession | undefined>(undefined);
  const notificationAuthRetry = useRef<{ userId: string; retryAt: number } | undefined>(undefined);

  const nextNotificationRevision = useCallback(() => {
    notificationRevision.current += 1;
    setNotificationGeneration(notificationRevision.current);
    return notificationRevision.current;
  }, []);

  const clearNotificationSession = useCallback(() => {
    notificationSession.current = undefined;
    nextNotificationRevision();
  }, [nextNotificationRevision]);

  const resetNotificationSession = useCallback((userId: string, clearAuthRetry = false) => {
    if (clearAuthRetry || (notificationAuthRetry.current && notificationAuthRetry.current.userId !== userId)) {
      notificationAuthRetry.current = undefined;
    }
    notificationSession.current = {
      userId,
      cursor: 0,
      gate: createNotificationPollGate(),
      syncPending: true,
      revision: nextNotificationRevision(),
      hasPolled: false,
    };
  }, [nextNotificationRevision]);

  const clearDefinitionSession = useCallback(() => {
    definitionSession.current?.cache.clear();
    definitionSession.current = undefined;
  }, []);

  const applyDefinitionAccess = useCallback((result: BootstrapResult): boolean => {
    if (!result.authenticated) {
      if (definitionSession.current) {
        clearDefinitionSession();
        setSessionGeneration((current) => current + 1);
      }
      return false;
    }

    const { user, access } = result.bootstrap;
    const intakeProjects = new Set(access.projects
      .filter((project) => project.actions.interview.length > 0)
      .map((project) => project.project_id));
    const previous = definitionSession.current;
    if (previous?.accountId !== user.user_id) {
      clearDefinitionSession();
      definitionSession.current = {
        accountId: user.user_id,
        cache: createBrowserDefinitionCache(user.user_id),
        servedProjects: new Set(),
        intakeProjects,
      };
      setSessionGeneration((current) => current + 1);
      return true;
    }

    if (!previous) {
      definitionSession.current = {
        accountId: user.user_id,
        cache: createBrowserDefinitionCache(user.user_id),
        servedProjects: new Set(),
        intakeProjects,
      };
      setSessionGeneration((current) => current + 1);
      return true;
    }

    let accessChanged = previous.intakeProjects.size !== intakeProjects.size;
    for (const projectId of previous.intakeProjects) {
      if (intakeProjects.has(projectId)) continue;
      previous.cache.removeProject(projectId);
      previous.servedProjects.delete(projectId);
      accessChanged = true;
    }
    previous.intakeProjects = intakeProjects;
    if (accessChanged) setSessionGeneration((current) => current + 1);
    return accessChanged;
  }, [clearDefinitionSession]);

  const applySession = useCallback((result: BootstrapResult) => {
    const accessChanged = applyDefinitionAccess(result);
    if (result.authenticated) {
      const userId = result.bootstrap.user.user_id;
      if (accessChanged || notificationSession.current?.userId !== userId) {
        resetNotificationSession(userId, accessChanged);
      }
      setError(undefined);
      setAuthenticated(true);
      setBootstrap((previous) => sameBootstrap(previous, result.bootstrap) ? previous : result.bootstrap);
      setLoginUrl(undefined);
      setActionCode(undefined);
    } else {
      resetFirstHomeLoad();
      if (notificationSession.current) clearNotificationSession();
      setError(undefined);
      setAuthenticated(false);
      setBootstrap(undefined);
      setLoginUrl(result.loginUrl);
      setActionCode(result.actionCode);
    }
  }, [applyDefinitionAccess, clearNotificationSession, resetNotificationSession]);

  const loadSession = useCallback(async (background: boolean) => {
    if (loggingOut.current) return;
    if (refreshInFlight.current) return refreshInFlight.current;
    const generation = browserRequestGeneration.current;
    let task!: Promise<void>;
    task = (async () => {
      try {
        const result = await loadBrowserSession(background);
        if (generation === browserRequestGeneration.current) applySession(result);
      } catch (error) {
        if (generation === browserRequestGeneration.current) {
          if (error instanceof ApiError && [401, 403].includes(error.status)) {
            resetFirstHomeLoad();
            clearDefinitionSession();
            clearNotificationSession();
            setSessionGeneration((current) => current + 1);
            setAuthenticated(false);
            setBootstrap(undefined);
            setLoginUrl(error.redirectUrl ?? "/");
          }
          setError("server_unavailable");
          setActionCode(undefined);
        }
      } finally {
        if (refreshInFlight.current === task) refreshInFlight.current = undefined;
      }
    })();
    refreshInFlight.current = task;
    return task;
  }, [applySession, clearDefinitionSession, clearNotificationSession]);
  // Not `loadSession` itself: handlers such as onPress would pass an event as the flag.
  const reload = useCallback(() => loadSession(false), [loadSession]);
  const reloadInBackground = useCallback(() => loadSession(true), [loadSession]);

  const acknowledgeAuthoritativeRefresh = useCallback((expectedRevision: number) => {
    const current = notificationSession.current;
    if (!current || current.userId !== bootstrap?.user.user_id
      || current.revision !== expectedRevision || notificationRevision.current !== expectedRevision) return;
    current.lastAuthoritativeRefreshAt = Date.now();
    current.syncPending = false;
  }, [bootstrap?.user.user_id]);

  const pollNotifications = useCallback(async () => {
    if (loggingOut.current || !authenticated || !bootstrap || typeof document === "undefined" || document.visibilityState !== "visible") return;
    const current = notificationSession.current;
    const userId = bootstrap.user.user_id;
    if (!current || current.userId !== userId) return;
    if (notificationAuthRetry.current?.userId === userId && Date.now() < notificationAuthRetry.current.retryAt) return;

    const periodicRefreshRequested = current.lastAuthoritativeRefreshAt === undefined
      || Date.now() - current.lastAuthoritativeRefreshAt >= AUTHORITATIVE_REFRESH_INTERVAL_MS;
    let requestedPeriodicRefresh = false;
    if (periodicRefreshRequested) {
      if (!current.syncPending) {
        current.syncPending = true;
        current.revision = nextNotificationRevision();
        requestedPeriodicRefresh = true;
      }
    }

    const requestGeneration = browserRequestGeneration.current;
    const isCurrent = () => notificationSession.current === current
      && current.userId === userId
      && browserRequestGeneration.current === requestGeneration;
    try {
      const result = await current.gate.run(() => drainNotificationPages({
        after: current.cursor,
        request: (after) => requestClientJson(`/api/v1/me/notifications?after=${after}`, { background: true }),
      }));
      if (!result || !isCurrent()) return;
      const retryPending = current.hasPolled;
      current.hasPolled = true;
      current.cursor = result.nextCursor;
      if (result.needsSync || result.hasMore) {
        current.syncPending = true;
        current.revision = nextNotificationRevision();
      } else if (current.syncPending && retryPending && !requestedPeriodicRefresh) {
        current.revision = nextNotificationRevision();
      }
    } catch (pollError) {
      if (!isCurrent()) return;
      if (pollError instanceof ApiError && [401, 403].includes(pollError.status)) {
        notificationAuthRetry.current = { userId, retryAt: Date.now() + NOTIFICATION_AUTH_RETRY_MS };
        clearNotificationSession();
        await reloadInBackground();
      }
    }
  }, [authenticated, bootstrap, clearNotificationSession, nextNotificationRevision, reloadInBackground]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    const refresh = () => { if (document.visibilityState === "visible") void reloadInBackground(); };
    const accessStale = () => { void reloadInBackground(); };
    const poll = () => { if (document.visibilityState === "visible") void pollNotifications(); };
    const timer = window.setInterval(poll, NOTIFICATION_POLL_INTERVAL_MS);
    window.addEventListener("digitva-access-stale", accessStale);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("pageshow", poll);
    document.addEventListener("visibilitychange", refresh);
    document.addEventListener("visibilitychange", poll);
    poll();
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("digitva-access-stale", accessStale);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("pageshow", poll);
      document.removeEventListener("visibilitychange", refresh);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [pollNotifications, reloadInBackground]);

  useEffect(() => {
    let active = true;
    void (async () => {
      const stored = await getUiLocalePreference();
      if (!active) return;
      setLocaleState(setUiLocale(stored ?? (typeof navigator !== "undefined" ? navigator.language : "en")));
      try {
        await reload();
      } catch {
        if (active) {
          setError("server_unavailable");
          setActionCode(undefined);
        }
      } finally {
        if (active) setReady(true);
      }
    })();
    return () => {
      active = false;
      browserRequestGeneration.current += 1;
    };
  }, [reload]);

  const chooseUiLocale = useCallback(async (code: string) => {
    const normalized = setUiLocale(code);
    setLocaleState(normalized);
    await setUiLocalePreference(normalized);
  }, []);

  const hasServedDefinition = useCallback((projectId: string) => {
    const current = definitionSession.current;
    return !!current && current.accountId === bootstrap?.user.user_id && current.servedProjects.has(projectId);
  }, [bootstrap?.user.user_id]);

  const markServedDefinition = useCallback(async (projectId: string) => {
    const current = definitionSession.current;
    if (!bootstrap || current?.accountId !== bootstrap.user.user_id || !current.intakeProjects.has(projectId)) {
      throw new ApiError(403, "forbidden");
    }
    current.servedProjects.add(projectId);
  }, [bootstrap]);

  const logout = useCallback(async () => {
    const link = bootstrap?.links.logout;
    if (!link || !bootstrap) return;
    // Stop every source of authenticated traffic first: a request that ends after the logout response
    // would save the old session again and keep the user signed in. The signed-in state stays untouched
    // until the page navigates away: clearing it re-mounts screens, and their loaders would send exactly
    // such a request while the logout is in progress.
    loggingOut.current = true;
    browserRequestGeneration.current += 1;
    abortClientRequests();
    resetFirstHomeLoad();
    clearAllScroll(browserSessionStore());
    try {
      for (let attempt = 0; attempt < LOGOUT_ATTEMPTS; attempt += 1) {
        if (attempt > 0) await new Promise((done) => setTimeout(done, LOGOUT_RETRY_MS));
        await requestClientJson(link, { method: "POST", csrf: bootstrap.csrf, allowRedirect: true });
        if (!(await loadBrowserSession()).authenticated) {
          // A full navigation drops every in-memory cache, timer and pending promise of the old session.
          window.location.assign(bootstrap.links.login);
          return;
        }
      }
      throw new Error("session_still_active");
    } catch {
      loggingOut.current = false;
      setError("server_unavailable");
      await reload();
    }
  }, [bootstrap, reload]);

  // Idle sign-out (docs/policy/expo-client.md): the page reaches the sign-in page with a reason the Flask
  // login page shows. The logout POST is best effort: the server may already have ended the session.
  const goToSignIn = useCallback((signOutFirst: boolean) => {
    if (loggingOut.current) return;
    loggingOut.current = true;
    browserRequestGeneration.current += 1;
    abortClientRequests();
    void (async () => {
      const link = bootstrap?.links.logout;
      if (signOutFirst && link && bootstrap) {
        try {
          await requestClientJson(link, { method: "POST", csrf: bootstrap.csrf, allowRedirect: true, timeoutMs: 5000 });
        } catch {
          // Already signed out, or unreachable: the server enforces the timeout on its own.
        }
      }
      const login = bootstrap?.links.login ?? "/vaauth/valogin?next=%2Fapp%2F";
      window.location.assign(`${login}${login.includes("?") ? "&" : "?"}reason=idle`);
    })();
  }, [bootstrap]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const idle = () => goToSignIn(false);
    window.addEventListener("digitva-session-idle", idle);
    return () => window.removeEventListener("digitva-session-idle", idle);
  }, [goToSignIn]);

  const idleWarning = useIdleSignOut(
    authenticated,
    () => { void requestClientJson("/api/v1/me/access").catch(() => undefined); },
    () => goToSignIn(true),
  );

  const value = useMemo<BrowserAppState>(
    () => ({
      ready,
      authenticated,
      bootstrap,
      loginUrl,
      actionCode,
      error,
      uiLocale,
      chooseUiLocale,
      reload,
      activity: () => undefined,
      lockNow: async () => undefined,
      lockVersion,
      unlocked: () => undefined,
      onBeforeLock: () => () => undefined,
      logout,
      definitionCache: definitionSession.current?.cache,
      hasServedDefinition,
      markServedDefinition,
      sessionGeneration,
      notificationGeneration,
      acknowledgeAuthoritativeRefresh
    }),
    [ready, authenticated, bootstrap, loginUrl, actionCode, error, uiLocale, chooseUiLocale, reload, lockVersion, logout, hasServedDefinition, markServedDefinition, sessionGeneration, notificationGeneration, acknowledgeAuthoritativeRefresh]
  );
  return (
    <Context.Provider value={value}>
      {children}
      {idleWarning.warning ? (
        <ConfirmDialog
          title={t("idleWarningTitle")}
          message={t("idleWarningMessage")}
          confirmLabel={t("idleStaySignedIn")}
          cancelLabel={t("signOut")}
          onConfirm={idleWarning.stay}
          onCancel={() => goToSignIn(true)}
        />
      ) : null}
    </Context.Provider>
  );
}

/**
 * The Training screens: everything below sees the training bootstrap (training.ts `trainingBootstrap`), the menu
 * keeps the real one (`unscopedBootstrap`). A user without a participation gets *fallback*.
 */
export function TrainingScope({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const parent = useContext(Context);
  const real = parent?.bootstrap;
  const scoped = useMemo(() => (real ? trainingBootstrap(real) : undefined), [real]);
  const value = useMemo(() => (parent && scoped ? { ...parent, bootstrap: scoped, unscopedBootstrap: real } : undefined), [parent, scoped, real]);
  if (!value) return <>{real ? fallback : null}</>;
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): BrowserAppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
