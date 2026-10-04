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

type BrowserDefinitionCache = ReturnType<typeof createBrowserDefinitionCache>;

interface BrowserDefinitionSession {
  accountId: string;
  cache: BrowserDefinitionCache;
  servedProjects: Set<string>;
  intakeProjects: Set<string>;
}

interface BrowserAppState {
  ready: boolean;
  authenticated: boolean;
  bootstrap?: ClientBootstrap;
  loginUrl?: string;
  actionCode?: "terms_required" | "factor_setup_required";
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
  const [lockVersion] = useState(0);
  const browserRequestGeneration = useRef(0);
  const refreshInFlight = useRef<Promise<void> | undefined>(undefined);
  const definitionSession = useRef<BrowserDefinitionSession | undefined>(undefined);

  const clearDefinitionSession = useCallback(() => {
    definitionSession.current?.cache.clear();
    definitionSession.current = undefined;
  }, []);

  const applyDefinitionAccess = useCallback((result: BootstrapResult) => {
    if (!result.authenticated) {
      if (definitionSession.current) {
        clearDefinitionSession();
        setSessionGeneration((current) => current + 1);
      }
      return;
    }

    const { user, access } = result.bootstrap;
    const intakeProjects = new Set(access.projects
      .filter((project) => project.grants.some((grant) => grant.role === "interviewer"))
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
      return;
    }

    if (!previous) {
      definitionSession.current = {
        accountId: user.user_id,
        cache: createBrowserDefinitionCache(user.user_id),
        servedProjects: new Set(),
        intakeProjects,
      };
      setSessionGeneration((current) => current + 1);
      return;
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
  }, [clearDefinitionSession]);

  const applySession = useCallback((result: BootstrapResult) => {
    applyDefinitionAccess(result);
    if (result.authenticated) {
      setError(undefined);
      setAuthenticated(true);
      setBootstrap(result.bootstrap);
      setLoginUrl(undefined);
      setActionCode(undefined);
    } else {
      setError(undefined);
      setAuthenticated(false);
      setBootstrap(undefined);
      setLoginUrl(result.loginUrl);
      setActionCode(result.actionCode);
    }
  }, [applyDefinitionAccess]);

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
  }, [applySession, clearDefinitionSession]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    const refresh = () => { if (document.visibilityState === "visible") void reload(); };
    const accessStale = () => { void reload(); };
    window.addEventListener("digitva-access-stale", accessStale);
    window.addEventListener("pageshow", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("digitva-access-stale", accessStale);
      window.removeEventListener("pageshow", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [reload]);

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
  }, [bootstrap, clearDefinitionSession, reload]);

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
      sessionGeneration
    }),
    [ready, authenticated, bootstrap, loginUrl, actionCode, error, uiLocale, chooseUiLocale, reload, lockVersion, logout, hasServedDefinition, markServedDefinition, sessionGeneration]
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): BrowserAppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
