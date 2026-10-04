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
import { loadBrowserSession } from "./client/session";
import type { BootstrapResult } from "./client/api";

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
  const [lockVersion] = useState(0);
  const sessionGeneration = useRef(0);
  const refreshInFlight = useRef<Promise<void> | undefined>(undefined);

  const applySession = useCallback((result: BootstrapResult) => {
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
  }, []);

  const reload = useCallback(async () => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const generation = sessionGeneration.current;
    let task!: Promise<void>;
    task = (async () => {
      try {
        const result = await loadBrowserSession();
        if (generation === sessionGeneration.current) applySession(result);
      } catch (error) {
        if (generation === sessionGeneration.current) {
          if (error instanceof ApiError && [401, 403].includes(error.status)) {
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
  }, [applySession]);

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
      sessionGeneration.current += 1;
    };
  }, [reload]);

  const chooseUiLocale = useCallback(async (code: string) => {
    const normalized = setUiLocale(code);
    setLocaleState(normalized);
    await setUiLocalePreference(normalized);
  }, []);

  const logout = useCallback(async () => {
    const link = bootstrap?.links.logout;
    if (!link || !bootstrap) return;
    sessionGeneration.current += 1;
    refreshInFlight.current = undefined;
    try {
      await requestClientJson(link, { method: "POST", csrf: bootstrap.csrf, allowRedirect: true });
      await reload();
    } catch {
      setError("server_unavailable");
    }
  }, [bootstrap, reload]);

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
      logout
    }),
    [ready, authenticated, bootstrap, loginUrl, actionCode, error, uiLocale, chooseUiLocale, reload, lockVersion, logout]
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): BrowserAppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
