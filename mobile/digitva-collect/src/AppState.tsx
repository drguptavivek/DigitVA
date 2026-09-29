/**
 * App-wide state: the enrolment record, the accounts on this device and the
 * UI language. Everything per interviewer (drafts, bootstrap) is loaded by
 * the screen from that interviewer's own database.
 */
import { getLocales } from "expo-localization";
import * as SecureStore from "expo-secure-store";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { loadAccounts, loadDevice, type Account, type Device } from "./auth";
import { setUiLocale } from "./i18n";

const UI_LOCALE_KEY = "ui_locale";

interface AppState {
  ready: boolean;
  device: Device | undefined;
  accounts: Account[];
  uiLocale: string;
  reload(): Promise<void>;
  chooseUiLocale(code: string): Promise<void>;
}

const Context = createContext<AppState | undefined>(undefined);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [device, setDevice] = useState<Device | undefined>();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [uiLocale, setLocaleState] = useState("en");

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
    () => ({ ready, device, accounts, uiLocale, reload, chooseUiLocale }),
    [ready, device, accounts, uiLocale, reload, chooseUiLocale]
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState(): AppState {
  const state = useContext(Context);
  if (!state) throw new Error("useAppState must be used inside AppStateProvider");
  return state;
}
