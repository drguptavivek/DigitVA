/**
 * App-wide state: the enrolment record, the accounts on this device, the UI
 * language, and locking. Everything per interviewer (drafts, bootstrap) is
 * loaded by the screen from that interviewer's own database.
 *
 * Locking (auto after idle or time in the background, or "Lock now") runs
 * the registered before-lock hooks first (the open form saves its draft),
 * then closes every database and returns to the home screen.
 */
import { useRouter } from "expo-router";
import { getLocales } from "expo-localization";
import * as SecureStore from "expo-secure-store";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState as NativeAppState } from "react-native";

import {
  loadAccounts,
  loadDevice,
  subscribeAccountChanges,
  subscribeAccessChanges,
  type Account,
  type Device,
} from "./auth";
import { createAutoLock, type AutoLock } from "./autoLock";
import { setUiLocale } from "./i18n";
import { anyUnlocked, isUnlocked, lockAll, openInterviewerDb } from "./interviewerDb";
import { errorText } from "./ui";
import { reconcileReferenceAccess, refreshReferenceData } from "./sync";
import type { ClientBootstrap } from "./client/api";
import { refreshNativeNotifications, runNativeSync, type NativeSyncCallbacks, type NativeSyncResult } from "./nativeNotificationSync";
import type { Db } from "./drafts";

const UI_LOCALE_KEY = "ui_locale";

interface AppState {
  ready: boolean;
  device: Device | undefined;
  accounts: Account[];
  uiLocale: string;
  reload(): Promise<void>;
  chooseUiLocale(code: string): Promise<void>;
  /** Bumps on every lock or unlock so screens re-read isUnlocked(). */
  lockVersion: number;
  /** Run a full upload/download while coalescing with notification sync. */
  syncAccount(userId: string, db: Db, callbacks?: NativeSyncCallbacks): Promise<NativeSyncResult>;
  lockNow(): Promise<void>;
  unlocked(): void;
  /** Restart the idle timer (touches are caught at the root; the form reports its saves). */
  activity(): void;
  /** Clear a transient foreground/access error after a successful retry. */
  clearError(): void;
  /** Run `hook` before the next lock; returns the unregister function. */
  onBeforeLock(hook: () => Promise<void>): () => void;
  /** Browser-only session fields; absent on native. */
  authenticated?: boolean;
  bootstrap?: ClientBootstrap;
  loginUrl?: string;
  actionCode?: "terms_required" | "factor_setup_required";
  error?: string;
  logout?: () => Promise<void>;
}

const Context = createContext<AppState | undefined>(undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [device, setDevice] = useState<Device | undefined>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [uiLocale, setLocaleState] = useState("en");
  const [lockVersion, setLockVersion] = useState(0);
  const [error, setError] = useState<string>();
  const router = useRouter();
  const beforeLock = useRef(new Set<() => Promise<void>>());
  const accountsRef = useRef<Account[]>([]);
  const autoLock = useRef<AutoLock | undefined>(undefined);
  const foregroundNotificationRefresh = useRef<(() => Promise<void>) | undefined>(undefined);

  const lockNow = useCallback(async () => {
    if (!anyUnlocked()) return;
    try {
      for (const hook of [...beforeLock.current]) await hook();
    } catch (lockError) {
      setError(errorText(lockError));
      return;
    }
    try {
      await lockAll();
      setError(undefined);
      router.replace("/");
      setLockVersion((v) => v + 1);
    } catch (lockError) {
      setError(errorText(lockError));
    }
  }, [router]);

  useEffect(() => {
    const timer = createAutoLock(() => {
      void lockNow().catch((lockError) => setError(errorText(lockError)));
    });
    autoLock.current = timer;
    const subscription = NativeAppState.addEventListener("change", (state) =>
      timer.appStateChanged(state),
    );
    return () => {
      subscription.remove();
      timer.stop();
    };
  }, [lockNow]);

  const activity = useCallback(() => autoLock.current?.activity(), []);
  const unlocked = useCallback(() => {
    autoLock.current?.activity();
    setLockVersion((v) => v + 1);
    void foregroundNotificationRefresh.current?.();
  }, []);
  const onBeforeLock = useCallback((hook: () => Promise<void>) => {
    beforeLock.current.add(hook);
    return () => void beforeLock.current.delete(hook);
  }, []);

  const reload = useCallback(async () => {
    const [nextDevice, nextAccounts] = await Promise.all([
      loadDevice(),
      loadAccounts(),
    ]);
    setDevice(nextDevice);
    setAccounts(nextAccounts);
  }, []);

  const flushBeforeRefresh = useCallback(async () => {
    for (const hook of [...beforeLock.current]) await hook();
  }, []);

  const reconcileAccess = useCallback(async (userId: string, access: Parameters<Parameters<typeof subscribeAccessChanges>[0]>[1]) => {
    if (!isUnlocked(userId)) return;
    await flushBeforeRefresh();
    const handle = await openInterviewerDb(userId);
    await reconcileReferenceAccess(handle, access);
    setError(undefined);
    setLockVersion((version) => version + 1);
    await reload();
  }, [flushBeforeRefresh, reload]);

  const refreshUnlocked = useCallback(async () => {
    try {
      await flushBeforeRefresh();
    } catch (refreshError) {
      setError(errorText(refreshError));
      throw refreshError;
    }
    setError(undefined);
    for (const account of accountsRef.current) {
      if (account.needs_sign_in || account.terms_required || account.access_blocked) continue;
      const handle = isUnlocked(account.user_id)
        ? await openInterviewerDb(account.user_id)
        : undefined;
      const didSync = await refreshNativeNotifications(account.user_id, handle);
      if (didSync) {
        setLockVersion((version) => version + 1);
        continue;
      }
      if (!handle) continue;
      try {
        await refreshReferenceData(account.user_id, handle, { force: true });
      } catch (refreshError) {
        if (refreshError instanceof TypeError) continue;
        setError(errorText(refreshError));
        throw refreshError;
      }
      setLockVersion((version) => version + 1);
    }
    await reload();
  }, [flushBeforeRefresh, reload]);

  const pollForegroundNotifications = useCallback(async () => {
    try {
      await flushBeforeRefresh();
      for (const account of accountsRef.current) {
        if (account.needs_sign_in || account.terms_required || account.access_blocked) continue;
        const handle = isUnlocked(account.user_id)
          ? await openInterviewerDb(account.user_id)
          : undefined;
        const didSync = await refreshNativeNotifications(account.user_id, handle);
        if (didSync) setLockVersion((version) => version + 1);
      }
      await reload();
    } catch (pollError) {
      setError(errorText(pollError));
    }
  }, [flushBeforeRefresh, reload]);

  const syncAccount = useCallback(async (
    userId: string,
    handle: Db,
    callbacks?: NativeSyncCallbacks,
  ) => {
    return runNativeSync(userId, handle, callbacks);
  }, []);

  useEffect(() => {
    accountsRef.current = accounts;
  }, [accounts]);

  useEffect(
    () =>
      subscribeAccountChanges(() => {
        void reload();
      }),
    [reload],
  );

  useEffect(
    () => subscribeAccessChanges((userId, access) =>
      reconcileAccess(userId, access).catch((accessError) => {
        setError(errorText(accessError));
        throw accessError;
      }),
    ),
    [reconcileAccess],
  );

  useEffect(() => {
    void (async () => {
      const saved = await SecureStore.getItemAsync(UI_LOCALE_KEY);
      setLocaleState(setUiLocale(saved ?? getLocales()[0]?.languageCode));
      await reload();
      setReady(true);
    })();
  }, [reload]);

  useEffect(() => {
    let previous = NativeAppState.currentState;
    let timer: ReturnType<typeof setInterval> | undefined;
    const startTimer = () => {
      if (timer) clearInterval(timer);
      timer = setInterval(() => void pollForegroundNotifications(), 60_000);
    };
    const stopTimer = () => {
      if (timer) clearInterval(timer);
      timer = undefined;
    };
    foregroundNotificationRefresh.current = pollForegroundNotifications;
    if (ready && previous === "active") {
      void refreshUnlocked().catch((refreshError) => setError(errorText(refreshError)));
      startTimer();
    }
    const subscription = NativeAppState.addEventListener("change", (next) => {
      if (next === "active" && previous !== "active") {
        void refreshUnlocked().catch((refreshError) => setError(errorText(refreshError)));
        startTimer();
      } else if (next !== "active") {
        stopTimer();
      }
      previous = next;
    });
    return () => {
      stopTimer();
      foregroundNotificationRefresh.current = undefined;
      subscription.remove();
    };
  }, [ready, refreshUnlocked, pollForegroundNotifications]);

  const chooseUiLocale = useCallback(async (code: string) => {
    setLocaleState(setUiLocale(code));
    await SecureStore.setItemAsync(UI_LOCALE_KEY, code);
  }, []);

  const clearError = useCallback(() => setError(undefined), []);

  const value = useMemo(
    () => ({
      ready,
      device,
      accounts,
      uiLocale,
      reload,
      chooseUiLocale,
      lockVersion,
      syncAccount,
      lockNow,
      unlocked,
      activity,
      clearError,
      onBeforeLock,
      error,
    }),
    [
      ready,
      device,
      accounts,
      uiLocale,
      reload,
      chooseUiLocale,
      lockVersion,
      syncAccount,
      lockNow,
      unlocked,
      activity,
      clearError,
      onBeforeLock,
      error,
    ],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): AppState {
  const state = useContext(Context);
  if (!state)
    throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
