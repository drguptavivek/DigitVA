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
  type ReactNode
} from "react";
import { AppState as NativeAppState } from "react-native";

import { loadAccounts, loadDevice, type Account, type Device } from "./auth";
import { createAutoLock, type AutoLock } from "./autoLock";
import { setUiLocale } from "./i18n";
import { anyUnlocked, lockAll } from "./interviewerDb";

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
  lockNow(): Promise<void>;
  unlocked(): void;
  /** Restart the idle timer (touches are caught at the root; the form reports its saves). */
  activity(): void;
  /** Run `hook` before the next lock; returns the unregister function. */
  onBeforeLock(hook: () => Promise<void>): () => void;
}

const Context = createContext<AppState | undefined>(undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [device, setDevice] = useState<Device | undefined>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [uiLocale, setLocaleState] = useState("en");
  const [lockVersion, setLockVersion] = useState(0);
  const router = useRouter();
  const beforeLock = useRef(new Set<() => Promise<void>>());
  const autoLock = useRef<AutoLock | undefined>(undefined);

  const lockNow = useCallback(async () => {
    if (!anyUnlocked()) return;
    for (const hook of [...beforeLock.current]) await hook().catch(() => undefined);
    await lockAll();
    router.replace("/");
    setLockVersion((v) => v + 1);
  }, [router]);

  useEffect(() => {
    const timer = createAutoLock(() => void lockNow());
    autoLock.current = timer;
    const subscription = NativeAppState.addEventListener("change", (state) => timer.appStateChanged(state));
    return () => {
      subscription.remove();
      timer.stop();
    };
  }, [lockNow]);

  const activity = useCallback(() => autoLock.current?.activity(), []);
  const unlocked = useCallback(() => {
    autoLock.current?.activity();
    setLockVersion((v) => v + 1);
  }, []);
  const onBeforeLock = useCallback((hook: () => Promise<void>) => {
    beforeLock.current.add(hook);
    return () => void beforeLock.current.delete(hook);
  }, []);

  const reload = useCallback(async () => {
    const [nextDevice, nextAccounts] = await Promise.all([loadDevice(), loadAccounts()]);
    setDevice(nextDevice);
    setAccounts(nextAccounts);
  }, []);

  useEffect(() => {
    void (async () => {
      const saved = await SecureStore.getItemAsync(UI_LOCALE_KEY);
      setLocaleState(setUiLocale(saved ?? getLocales()[0]?.languageCode));
      await reload();
      setReady(true);
    })();
  }, [reload]);

  const chooseUiLocale = useCallback(async (code: string) => {
    setLocaleState(setUiLocale(code));
    await SecureStore.setItemAsync(UI_LOCALE_KEY, code);
  }, []);

  const value = useMemo(
    () => ({
      ready,
      device,
      accounts,
      uiLocale,
      reload,
      chooseUiLocale,
      lockVersion,
      lockNow,
      unlocked,
      activity,
      onBeforeLock
    }),
    [ready, device, accounts, uiLocale, reload, chooseUiLocale, lockVersion, lockNow, unlocked, activity, onBeforeLock]
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): AppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
