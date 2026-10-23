/**
 * Provider of the phone shell (header, tabs and the Account, Help and Sync sheets): resolves which interviewer
 * the screen belongs to, keeps the sync status, runs Send now and Refresh from anywhere, and files the current
 * screen for the error log. Native only; the browser has its own header (src/web/AppHeader.web.tsx).
 */
import { useGlobalSearchParams, usePathname } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Keyboard } from "react-native";

import { useAppState } from "../AppState";
import { installErrorLog } from "../errorLogDb";
import { flushErrors, setErrorRoute } from "../errorLog";
import { t } from "../i18n";
import { isUnlocked, openInterviewerDb, unsentWorkCount } from "../interviewerDb";
import { readNotificationState } from "../notificationState";
import { refreshAuthorizedProjectDefinitions, refreshCases, refreshReferenceData } from "../sync";
import { useToast } from "../toast";
import { errorText } from "../ui";
import { showNativeHeader, showNativeTabs } from "./navAdapter";
import { AccountSheet, HelpSheet, SyncSheet } from "./sheets";
import { ShellContext, type Shell, type ShellSheet, type SyncStatus } from "./shellContext";

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);
/** The result line of a send: the message without its support line. */
const oneLine = (text: string) => text.split("\n")[0];

/** True while the soft keyboard is up (the tabs step aside). */
export function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const subscriptions = [Keyboard.addListener("keyboardDidShow", () => setOpen(true)), Keyboard.addListener("keyboardDidHide", () => setOpen(false))];
    return () => subscriptions.forEach((subscription) => subscription.remove());
  }, []);
  return open;
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname().replace(/\/$/, "") || "/";
  const params = useGlobalSearchParams<{ userId?: string | string[] }>();
  const { accounts, lockVersion, offline, dataChanged, syncAccount, reload } = useAppState();
  const toast = useToast();
  const keyboardOpen = useKeyboardOpen();
  const [sheet, setSheet] = useState<ShellSheet>(null);
  const [unsent, setUnsent] = useState<number>();
  const [lastAt, setLastAt] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>();
  const busyRef = useRef(false);

  const requested = first(params.userId);
  const userId = requested && accounts.some((account) => account.user_id === requested) ? requested : undefined;
  const unlocked = userId ? isUnlocked(userId) : false;

  useEffect(() => installErrorLog(), []);
  useEffect(() => setErrorRoute(pathname), [pathname]);
  useEffect(() => void flushErrors(), [lockVersion]);

  const recount = useCallback(async () => {
    if (!userId || !isUnlocked(userId)) {
      setUnsent(undefined);
      return;
    }
    try {
      setUnsent(await unsentWorkCount(userId));
      const state = await readNotificationState(userId);
      if (state?.lastSuccessfulFullSyncAt) setLastAt((current) => Math.max(current ?? 0, state.lastSuccessfulFullSyncAt!));
    } catch {
      setUnsent(undefined);
    }
  }, [userId]);
  // Work is saved on forms and sent from lists, so count again on every screen change and lock/unlock.
  useEffect(() => void recount(), [recount, pathname, lockVersion, busy]);
  useEffect(() => setLastAt(undefined), [userId]);

  const run = useCallback(async (action: (id: string, db: Awaited<ReturnType<typeof openInterviewerDb>>) => Promise<{ text: string; failed?: boolean }>) => {
    if (!userId || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const outcome = await action(userId, await openInterviewerDb(userId));
      setResult(outcome.text);
      setLastAt(Date.now());
      toast.show({ kind: outcome.failed ? "error" : "success", text: outcome.text });
      dataChanged?.();
    } catch (error) {
      const text = errorText(error);
      setResult(oneLine(text));
      toast.show({ kind: "error", text });
      await reload();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [userId, toast, dataChanged, reload]);

  const sendNow = useCallback(() => run(async (id, db) => {
    const { sync } = await syncAccount(id, db);
    return { text: t("syncResult", { sent: sync.sent, failed: sync.failed, remaining: sync.remaining }), failed: sync.failed > 0 };
  }), [run, syncAccount]);

  const refreshNow = useCallback(() => run(async (id, db) => {
    const fresh = await refreshReferenceData(id, db, { force: true });
    await refreshAuthorizedProjectDefinitions(id, db, fresh);
    await refreshCases(id, db);
    return { text: t("refreshed") };
  }), [run]);

  const header = showNativeHeader(pathname);
  const tabs = showNativeTabs({ pathname, userId, unlocked, keyboardOpen });
  const sync: SyncStatus = useMemo(() => ({ unsent, lastAt, busy, result, offline: Boolean(offline) }), [unsent, lastAt, busy, result, offline]);
  const value: Shell = useMemo(() => ({
    sheet,
    openSheet: setSheet,
    closeSheet: () => setSheet(null),
    userId,
    sync,
    sendNow,
    refreshNow,
    header,
    tabs,
  }), [sheet, userId, sync, sendNow, refreshNow, header, tabs]);
  return (
    <ShellContext.Provider value={value}>
      {children}
      <AccountSheet />
      <HelpSheet />
      <SyncSheet />
    </ShellContext.Provider>
  );
}
