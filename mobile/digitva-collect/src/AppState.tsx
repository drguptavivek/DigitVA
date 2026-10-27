/**
 * App-wide state: the enrolment record, the accounts on this device, the UI
 * language, and locking. Everything per interviewer (drafts, bootstrap) is
 * loaded by the screen from that interviewer's own database.
 *
 * Locking (auto after idle or time in the background, or "Lock now") runs
 * the registered before-lock hooks first (the open form saves its draft),
 * then closes every database and returns to the home screen.
 *
 * Active and Demo (docs/policy/public-demo.md section 10.1): `device` and
 * `accounts` are the chosen slot's (src/auth.ts). Switching locks first, as
 * above, then chooses the other slot; nothing is deleted or signed out.
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
  bindLegacyAccounts,
  loadAccounts,
  loadActiveSlot,
  loadDevice,
  setActiveSlot,
  subscribeAccountChanges,
  subscribeAccessChanges,
  type Account,
  type Device,
  type Slot,
} from "./auth";
import { createAutoLock, type AutoLock } from "./autoLock";
import { setUiLocale } from "./i18n";
import { anyUnlocked, isUnlocked, lockAll, openInterviewerDb } from "./interviewerDb";
import { errorText } from "./ui";
import { isOffline, onReconnect, OfflineError, startNetworkWatch, useIsOffline } from "./network";
import { accountServerChanged, lacksServer } from "./accountServer";
import { NotInSlotError, SessionRevokedError, SignInRequiredError } from "./authErrors";
import { reconcileReferenceAccess, refreshReferenceData } from "./sync";
import type { ClientBootstrap } from "./client/api";
import { refreshNativeNotifications, runNativeSync, type NativeSyncCallbacks, type NativeSyncResult } from "./nativeNotificationSync";
import type { Db } from "./drafts";
import { loadPhoneClock, usePhoneClock } from "./phoneClock";

const UI_LOCALE_KEY = "ui_locale";
const POLL_MS = 60_000;
/** After the phone comes back online, wait this long (a flapping connection) before the one catch-up pass. */
const RECONNECT_DEBOUNCE_MS = 2_000;
const POLL_MAX_MS = 600_000;

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
/** A refusal for a user the chosen slot no longer serves (a switch or wipe landed mid-pass) is skipped, not reported. */
const skipNotInSlot = (error: unknown) => {
  if (!(error instanceof NotInSlotError)) throw error;
};

interface AppState {
  ready: boolean;
  device: Device | undefined;
  accounts: Account[];
  /** Native only: the enrolment in use, Active (live server) or Demo. */
  slot?: Slot;
  /**
   * Native only: lock as lockNow does, then use `slot`; a slot not yet
   * enrolled opens its enrolment screen instead and stays unchosen until that
   * enrols. Resolves false when locking failed and nothing changed.
   */
  switchSlot?(slot: Slot): Promise<boolean>;
  uiLocale: string;
  reload(): Promise<void>;
  chooseUiLocale(code: string): Promise<void>;
  /** Bumps on every lock or unlock so screens re-read isUnlocked(). */
  lockVersion: number;
  /** Run a full upload/download while coalescing with notification sync. */
  syncAccount(userId: string, db: Db, callbacks?: NativeSyncCallbacks): Promise<NativeSyncResult>;
  lockNow(): Promise<boolean>;
  unlocked(): void;
  /** Restart the idle timer (touches are caught at the root; the form reports its saves). */
  activity(): void;
  /** Native only: an automatic refresh failed; shown as a banner, never the gate. */
  backgroundError?: string;
  dismissBackgroundError?(): void;
  /** Native only: the last automatic refresh failed for lack of network (the header's Offline chip). */
  offline?: boolean;
  /** Native only: data changed outside a screen's own load (the Sync sheet); mounted lists reload. */
  dataChanged?(): void;
  /**
   * Native only: while a form is open, refreshes must not remount it. Returns
   * the release function; a refresh that arrived meanwhile applies on release.
   */
  holdRefresh?(): () => void;
  /** Clear a transient foreground/access error after a successful retry. */
  clearError(): void;
  /** Run `hook` before the next lock; returns the unregister function. */
  onBeforeLock(hook: () => Promise<void>): () => void;
  /** Browser-only session fields; absent on native. */
  authenticated?: boolean;
  bootstrap?: ClientBootstrap;
  /** Web only (TrainingScope): the user's real bootstrap beneath the Training screens' scoped one. */
  unscopedBootstrap?: ClientBootstrap;
  loginUrl?: string;
  actionCode?: "terms_required";
  error?: string;
  /** Native only: `error` stops the app (revoked session, sign-in required); otherwise it is shown as a toast. */
  errorBlocking?: boolean;
  logout?: () => Promise<void>;
}

const Context = createContext<AppState | undefined>(undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [device, setDevice] = useState<Device | undefined>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [slot, setSlot] = useState<Slot>("active");
  const [uiLocale, setLocaleState] = useState("en");
  const [lockVersion, setLockVersion] = useState(0);
  const [error, setErrorText] = useState<string>();
  const [errorBlocking, setErrorBlocking] = useState(false);
  const [backgroundErrorText, setBackgroundErrorText] = useState<string>();
  const [failedOffline, setOffline] = useState(false);
  const offline = useIsOffline() || failedOffline;
  const router = useRouter();
  const beforeLock = useRef(new Set<() => Promise<void>>());
  const accountsRef = useRef<Account[]>([]);
  const autoLock = useRef<AutoLock | undefined>(undefined);
  const foregroundNotificationRefresh = useRef<(() => Promise<boolean>) | undefined>(undefined);
  const holds = useRef(0);
  const refreshPending = useRef(false);
  const lastAccess = useRef(new Map<string, string>());

  // A refresh that changed data bumps lockVersion; with a form open it waits.
  const bumpRefresh = useCallback(() => {
    if (holds.current > 0) refreshPending.current = true;
    else setLockVersion((v) => v + 1);
  }, []);
  const holdRefresh = useCallback(() => {
    holds.current += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      holds.current -= 1;
      if (holds.current === 0 && refreshPending.current) {
        refreshPending.current = false;
        setLockVersion((v) => v + 1);
      }
    };
  }, []);
  /** Only a revoked session or a sign-in demand blocks; any other failure is a toast and the app stays usable. */
  const setError = useCallback((failure: unknown) => {
    if (failure === undefined) {
      setErrorText(undefined);
      setErrorBlocking(false);
      return;
    }
    setErrorText(errorText(failure));
    setErrorBlocking(failure instanceof SessionRevokedError || failure instanceof SignInRequiredError);
  }, []);
  const setBackgroundError = useCallback((text: string | undefined) => {
    setBackgroundErrorText(text);
    if (text === undefined) setOffline(false);
  }, []);
  const reportBackgroundError = useCallback((e: unknown) => {
    if (e instanceof NotInSlotError) return;
    // Offline is shown by the header marker only; no banner, no log entry.
    setBackgroundErrorText(e instanceof OfflineError ? undefined : errorText(e));
    setOffline(e instanceof TypeError);
  }, []);
  const dismissBackgroundError = useCallback(() => setBackgroundError(undefined), [setBackgroundError]);

  const lockNow = useCallback(async () => {
    if (!anyUnlocked()) return true;
    try {
      for (const hook of [...beforeLock.current]) await hook();
    } catch (lockError) {
      setError(lockError);
      return false;
    }
    try {
      await lockAll();
      lastAccess.current.clear();
      setError(undefined);
      router.replace("/");
      setLockVersion((v) => v + 1);
      return true;
    } catch (lockError) {
      setError(lockError);
      return false;
    }
  }, [router, setError]);

  useEffect(() => {
    const timer = createAutoLock(() => {
      void lockNow().catch((lockError) => setError(lockError));
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
    // Device and accounts from one slot, read once, even if a switch lands meanwhile.
    const nextSlot = await loadActiveSlot();
    const [nextDevice, storedAccounts] = await Promise.all([
      loadDevice(nextSlot),
      loadAccounts(nextSlot),
    ]);
    // Accounts kept before they recorded a server belong to this device's: one write, then never again.
    const slotAccounts = nextDevice && storedAccounts.some(lacksServer) && (await bindLegacyAccounts(nextSlot))
      ? await loadAccounts(nextSlot)
      : storedAccounts;
    // An account signed in on another server than the phone now uses (it was
    // re-enrolled elsewhere) is not shown at all: its encrypted store stays on
    // the phone, unsent work included, and returns if the phone is enrolled on
    // that server again.
    const nextAccounts = slotAccounts.filter((account) => !accountServerChanged(account, nextDevice));
    setSlot(nextSlot);
    // Keep identities when nothing changed so an idle poll redraws nothing.
    setDevice((prev) => (sameJson(prev, nextDevice) ? prev : nextDevice));
    setAccounts((prev) => (sameJson(prev, nextAccounts) ? prev : nextAccounts));
  }, []);

  const switchSlot = useCallback(async (next: Slot) => {
    if (!(await lockNow())) return false;
    // Enrolled as Home counts it: a device, or (Active only) a standalone account.
    const enrolled = (await loadDevice(next)) !== undefined
      || (next === "active" && (await loadAccounts(next)).some((account) => account.standalone));
    // An empty Demo slot is never kept: leaving it chooses Active, whose Home opens QR enrolment if needed.
    const leavingEmptyDemo = next === "active" && (await loadDevice("demo")) === undefined;
    if (!enrolled && !leavingEmptyDemo) {
      // That screen's enrolment chooses the slot (src/auth.ts storeEnrolment); leaving it keeps this one.
      router.push(next === "demo" ? "/demo" : "/enrol");
      return true;
    }
    await setActiveSlot(next);
    await reload();
    router.replace("/");
    setLockVersion((v) => v + 1);
    return true;
  }, [lockNow, reload, router]);

  const flushBeforeRefresh = useCallback(async () => {
    for (const hook of [...beforeLock.current]) await hook();
  }, []);

  // Phone clock: the stored offset applies from start-up; when it turns into a block, what is typed is saved first.
  const { level: clockLevel } = usePhoneClock();
  useEffect(() => void loadPhoneClock(), []);
  useEffect(() => {
    if (clockLevel === "block") void flushBeforeRefresh().catch(() => undefined);
  }, [clockLevel, flushBeforeRefresh]);

  const reconcileAccess = useCallback(async (userId: string, access: Parameters<Parameters<typeof subscribeAccessChanges>[0]>[1]) => {
    if (!isUnlocked(userId)) return;
    const key = JSON.stringify(access);
    if (lastAccess.current.get(userId) === key) return;
    await flushBeforeRefresh();
    const handle = await openInterviewerDb(userId);
    await reconcileReferenceAccess(handle, access);
    lastAccess.current.set(userId, key);
    bumpRefresh();
    await reload();
  }, [flushBeforeRefresh, reload, bumpRefresh]);

  const refreshUnlocked = useCallback(async () => {
    await flushBeforeRefresh();
    if (isOffline()) return;
    for (const account of accountsRef.current) {
      if (account.standalone || account.needs_sign_in || account.terms_required || account.access_blocked) continue;
      try {
        const handle = isUnlocked(account.user_id)
          ? await openInterviewerDb(account.user_id)
          : undefined;
        const didSync = await refreshNativeNotifications(account.user_id, handle);
        if (didSync) {
          bumpRefresh();
          continue;
        }
        const currentAccount = (await loadAccounts()).find(({ user_id }) => user_id === account.user_id);
        if (!handle || currentAccount?.collection_access !== true) continue;
        try {
          await refreshReferenceData(account.user_id, handle, { force: true });
        } catch (refreshError) {
          if (refreshError instanceof TypeError) continue;
          throw refreshError;
        }
        bumpRefresh();
      } catch (refreshError) {
        skipNotInSlot(refreshError);
      }
    }
    await reload();
  }, [flushBeforeRefresh, reload, bumpRefresh]);

  /** Resolves true when the poll succeeded; false feeds the caller's backoff. */
  const pollForegroundNotifications = useCallback(async (): Promise<boolean> => {
    try {
      await flushBeforeRefresh();
      if (isOffline()) return true;
      for (const account of accountsRef.current) {
        if (account.standalone || account.needs_sign_in || account.terms_required || account.access_blocked) continue;
        try {
          const handle = isUnlocked(account.user_id)
            ? await openInterviewerDb(account.user_id)
            : undefined;
          if (await refreshNativeNotifications(account.user_id, handle)) bumpRefresh();
        } catch (accountError) {
          skipNotInSlot(accountError);
        }
      }
      await reload();
      setBackgroundError(undefined);
      return true;
    } catch (pollError) {
      reportBackgroundError(pollError);
      return false;
    }
  }, [flushBeforeRefresh, reload, bumpRefresh, reportBackgroundError, setBackgroundError]);

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
        reportBackgroundError(accessError);
        throw accessError;
      }),
    ),
    [reconcileAccess, reportBackgroundError],
  );

  useEffect(() => {
    void (async () => {
      const saved = await SecureStore.getItemAsync(UI_LOCALE_KEY);
      setLocaleState(setUiLocale(saved ?? getLocales()[0]?.languageCode));
      await reload();
      setReady(true);
    })();
  }, [reload]);

  // Network watch; on reconnect, one debounced pass sends what queued up while offline.
  useEffect(() => {
    const stopWatch = startNetworkWatch();
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const stopReconnect = onReconnect(() => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(async () => {
        try {
          for (const account of accountsRef.current) {
            if (account.standalone || account.needs_sign_in || account.terms_required || account.access_blocked) continue;
            if (account.collection_access !== true || !isUnlocked(account.user_id)) continue;
            try {
              await runNativeSync(account.user_id, await openInterviewerDb(account.user_id));
              bumpRefresh();
            } catch (accountError) {
              skipNotInSlot(accountError);
            }
          }
          await pollForegroundNotifications();
        } catch (syncError) {
          reportBackgroundError(syncError);
        }
      }, RECONNECT_DEBOUNCE_MS);
    });
    return () => {
      if (debounce) clearTimeout(debounce);
      stopReconnect();
      stopWatch();
    };
  }, [bumpRefresh, pollForegroundNotifications, reportBackgroundError]);

  useEffect(() => {
    let previous = NativeAppState.currentState;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_MS;
    // A failing poll doubles the wait (up to 10 min); a success resets it.
    const schedule = () => {
      timer = setTimeout(async () => {
        const ok = await pollForegroundNotifications();
        delay = ok ? POLL_MS : Math.min(delay * 2, POLL_MAX_MS);
        if (timer) schedule();
      }, delay);
    };
    const startTimer = () => {
      if (timer) clearTimeout(timer);
      delay = POLL_MS;
      schedule();
    };
    const stopTimer = () => {
      if (timer) clearTimeout(timer);
      timer = undefined;
    };
    foregroundNotificationRefresh.current = pollForegroundNotifications;
    if (ready && previous === "active") {
      void refreshUnlocked().then(() => setBackgroundError(undefined), reportBackgroundError);
      startTimer();
    }
    const subscription = NativeAppState.addEventListener("change", (next) => {
      if (next === "active" && previous !== "active") {
        void refreshUnlocked().then(() => setBackgroundError(undefined), reportBackgroundError);
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
  }, [ready, refreshUnlocked, pollForegroundNotifications, reportBackgroundError, setBackgroundError]);

  const chooseUiLocale = useCallback(async (code: string) => {
    setLocaleState(setUiLocale(code));
    await SecureStore.setItemAsync(UI_LOCALE_KEY, code);
  }, []);

  const clearError = useCallback(() => setError(undefined), [setError]);

  const value = useMemo(
    () => ({
      ready,
      device,
      accounts,
      slot,
      switchSlot,
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
      errorBlocking,
      backgroundError: backgroundErrorText,
      dismissBackgroundError,
      holdRefresh,
      offline,
      dataChanged: bumpRefresh,
    }),
    [
      ready,
      device,
      accounts,
      slot,
      switchSlot,
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
      errorBlocking,
      backgroundErrorText,
      dismissBackgroundError,
      holdRefresh,
      offline,
      bumpRefresh,
    ],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The Training screens are web only; on a device this renders nothing. */
export function TrainingScope(_props: { children: ReactNode; fallback?: ReactNode }) {
  return null;
}

export function useAppState(): AppState {
  const state = useContext(Context);
  if (!state)
    throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
