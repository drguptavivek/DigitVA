/** The phone shell's shared state: which sheet is open, the sync status chip/sheet read, and which chrome is showing. */
import { createContext, useContext } from "react";

import { t, uiLanguageTag } from "../i18n";
import type { WorkSummary } from "../unsentWork";

export type ShellSheet = "account" | "help" | "sync" | null;

export interface SyncStatus {
  /** What Send now will upload from this phone (src/unsentWork.ts); undefined while locked or not counted yet. */
  work: WorkSummary | undefined;
  /** Epoch ms of the last successful sync or refresh. */
  lastAt: number | undefined;
  busy: boolean;
  /** The last send or refresh outcome, as one line (never a Ref). */
  result: string | undefined;
  /** The last background poll failed for lack of network. */
  offline: boolean;
}

export interface Shell {
  sheet: ShellSheet;
  openSheet(sheet: Exclude<ShellSheet, null>): void;
  closeSheet(): void;
  /** The interviewer the current screen belongs to (route param `userId`), when it is a known account. */
  userId: string | undefined;
  /** Server of the selected server account; unavailable when signed out or the enrolment does not match. */
  server?: string;
  sync: SyncStatus;
  sendNow(): Promise<void>;
  /** Count the phone's unsent work again (a screen that sent or saved work calls it). */
  recount(): Promise<void>;
  refreshNow(): Promise<void>;
  /** Whether the header and the tabs are on screen, so Screen leaves their insets to them. */
  header: boolean;
  tabs: boolean;
  /** The bar shows the back arrow and the screen title (navAdapter `showNativeBackTitle`); Screen then hides its own. */
  titleInBar: boolean;
  /** Title of the screen on top, published by Screen. */
  screenTitle: string | undefined;
  /**
   * Screen publishes its title under its own key; `undefined` withdraws it. The newest key still mounted wins, so a
   * pushed screen shows its title and popping it shows the one underneath again (the Stack keeps it mounted).
   */
  publishTitle(key: object, title: string | undefined): void;
}

const IDLE: Shell = {
  sheet: null,
  openSheet: () => undefined,
  closeSheet: () => undefined,
  userId: undefined,
  sync: { work: undefined, lastAt: undefined, busy: false, result: undefined, offline: false },
  sendNow: async () => undefined,
  recount: async () => undefined,
  refreshNow: async () => undefined,
  header: false,
  tabs: false,
  titleInBar: false,
  screenTitle: undefined,
  publishTitle: () => undefined,
};

export const ShellContext = createContext<Shell>(IDLE);

/** Safe without a provider (tests, web): sheets never open and no chrome is reported. */
export const useShell = (): Shell => useContext(ShellContext);

/** "4:50 am" in the phone's time zone and the app language's conventions, like every other time on the phone. */
export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString(uiLanguageTag(), { hour: "numeric", minute: "2-digit" });
}

/**
 * When the phone last synced, in the app language's conventions: "Synced today, 1:19 pm" or "Synced 3 Nov, 10:20 am";
 * "Not synced yet" when it has not.
 */
export function syncedText(lastAt: number | undefined, now: number = Date.now()): string {
  if (!lastAt) return t("syncChipNever");
  const locale = uiLanguageTag();
  const at = new Date(lastAt);
  const time = at.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
  if (at.toDateString() === new Date(now).toDateString()) return t("syncedToday", { time });
  return t("syncedOn", { date: at.toLocaleDateString(locale, { day: "numeric", month: "short" }), time });
}
