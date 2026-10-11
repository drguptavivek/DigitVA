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

import { setUiLocale } from "./i18n";
import { getUiLocalePreference, setUiLocalePreference } from "./preferences";
import { ApiError, requestClientJson, type ClientBootstrap } from "./client/api";
import { createBrowserDefinitionCache } from "./client/formDefinitionCache";
import { loadBrowserSession } from "./client/session";
import type { BootstrapResult } from "./client/api";
import { createNotificationPollGate, drainNotificationPages } from "./notificationPoll";

const NOTIFICATION_POLL_INTERVAL_MS = 60_000;
const NOTIFICATION_AUTH_RETRY_MS = 60_000;
const AUTHORITATIVE_REFRESH_INTERVAL_MS = 15 * 60_000;

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
      setBootstrap(result.bootstrap);
      setLoginUrl(undefined);
      setActionCode(undefined);
    } else {
      if (notificationSession.current) clearNotificationSession();
      setError(undefined);
      setAuthenticated(false);
      setBootstrap(undefined);
      setLoginUrl(result.loginUrl);
      setActionCode(result.actionCode);
    }
  }, [applyDefinitionAccess, clearNotificationSession, resetNotificationSession]);

  const reload = useCallback(async () => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const generation = browserRequestGeneration.current;
    let task!: Promise<void>;
    task = (async () => {
      try {
        const result = await loadBrowserSession();
        if (generation === browserRequestGeneration.current) applySession(result);
      } catch (error) {
        if (generation === browserRequestGeneration.current) {
          if (error instanceof ApiError && [401, 403].includes(error.status)) {
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

  const acknowledgeAuthoritativeRefresh = useCallback((expectedRevision: number) => {
    const current = notificationSession.current;
    if (!current || current.userId !== bootstrap?.user.user_id
      || current.revision !== expectedRevision || notificationRevision.current !== expectedRevision) return;
    current.lastAuthoritativeRefreshAt = Date.now();
    current.syncPending = false;
  }, [bootstrap?.user.user_id]);

  const pollNotifications = useCallback(async () => {
    if (!authenticated || !bootstrap || typeof document === "undefined" || document.visibilityState !== "visible") return;
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
        request: (after) => requestClientJson(`/api/v1/me/notifications?after=${after}`),
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
        await reload();
      }
    }
  }, [authenticated, bootstrap, clearNotificationSession, nextNotificationRevision, reload]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    const refresh = () => { if (document.visibilityState === "visible") void reload(); };
    const accessStale = () => { void reload(); };
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
  }, [pollNotifications, reload]);

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
    browserRequestGeneration.current += 1;
    clearDefinitionSession();
    clearNotificationSession();
    setSessionGeneration((current) => current + 1);
    refreshInFlight.current = undefined;
    setAuthenticated(false);
    setBootstrap(undefined);
    try {
      await requestClientJson(link, { method: "POST", csrf: bootstrap.csrf, allowRedirect: true });
      await reload();
    } catch {
      setError("server_unavailable");
    }
  }, [bootstrap, clearDefinitionSession, clearNotificationSession, reload]);

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
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): BrowserAppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
