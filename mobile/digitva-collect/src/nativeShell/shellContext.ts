/** The phone shell's shared state: which sheet is open, the sync status chip/sheet read, and which chrome is showing. */
import { createContext, useContext } from "react";

export type ShellSheet = "account" | "help" | "sync" | null;

export interface SyncStatus {
  /** Items on this phone the server has not acknowledged; undefined while locked or not counted yet. */
  unsent: number | undefined;
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
  sync: SyncStatus;
  sendNow(): Promise<void>;
  refreshNow(): Promise<void>;
  /** Whether the header and the tabs are on screen, so Screen leaves their insets to them. */
  header: boolean;
  tabs: boolean;
}

const IDLE: Shell = {
  sheet: null,
  openSheet: () => undefined,
  closeSheet: () => undefined,
  userId: undefined,
  sync: { unsent: undefined, lastAt: undefined, busy: false, result: undefined, offline: false },
  sendNow: async () => undefined,
  refreshNow: async () => undefined,
  header: false,
  tabs: false,
};

export const ShellContext = createContext<Shell>(IDLE);

/** Safe without a provider (tests, web): sheets never open and no chrome is reported. */
export const useShell = (): Shell => useContext(ShellContext);

/** "HH:MM" in the phone's time zone. */
export function clock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
