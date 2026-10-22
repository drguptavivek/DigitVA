/**
 * Web build: the browser is never enrolled, and its Settings screen is
 * browserScreens' SettingsScreen, so re-enrolling does not exist here. This
 * stub keeps app/settings.tsx from pulling the phone's SQLite store
 * (interviewerDb, expo-sqlite's wasm worker) into the web bundle.
 */
import type { Account } from "./auth";

export async function confirmReEnrol(_accounts: Account[], _onConfirmed: () => void): Promise<void> {
  throw new Error("re_enrol_native_only");
}

export async function reEnrolDevice(_accounts: Account[]): Promise<void> {
  throw new Error("re_enrol_native_only");
}
