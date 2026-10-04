/**
 * Storage for non-sensitive UI preferences only.
 *
 * The browser adapter deliberately has a two-key allowlist. Interview answers,
 * identifiers and tokens must stay in their existing stores and never enter
 * localStorage.
 */
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export type PreferenceKey = "ui_locale" | "ui_theme";
export type ThemePreference = "system" | "light" | "dark";

const listeners = new Set<() => void>();
const memoryPreferences: Partial<Record<PreferenceKey, string>> = {};

function browserStorage(): Storage | undefined {
  if (Platform.OS !== "web") return undefined;
  try {
    return typeof globalThis.localStorage === "undefined" ? undefined : globalThis.localStorage;
  } catch {
    // Private browsing and restrictive web views can deny localStorage access.
    return undefined;
  }
}

function isPreferenceKey(value: string): value is PreferenceKey {
  return value === "ui_locale" || value === "ui_theme";
}

export async function getUiPreference(key: PreferenceKey): Promise<string | null> {
  if (memoryPreferences[key] !== undefined) return memoryPreferences[key] ?? null;
  const storage = browserStorage();
  if (storage) {
    try {
      return storage.getItem(key);
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(key).catch(() => null);
}

export async function setUiPreference(key: PreferenceKey, value: string): Promise<void> {
  if (!isPreferenceKey(key)) return;
  memoryPreferences[key] = value;
  const storage = browserStorage();
  if (storage) {
    try {
      storage.setItem(key, value);
    } catch {
      // A preference is optional; the UI remains usable without persistence.
    }
  } else {
    await SecureStore.setItemAsync(key, value).catch(() => undefined);
  }
  for (const listener of listeners) listener();
}

export async function getUiLocalePreference(): Promise<string | null> {
  return getUiPreference("ui_locale");
}

export async function setUiLocalePreference(locale: string): Promise<void> {
  return setUiPreference("ui_locale", locale);
}

export async function getUiTheme(): Promise<ThemePreference> {
  const value = await getUiPreference("ui_theme");
  return value === "light" || value === "dark" ? value : "system";
}

export async function setUiTheme(theme: ThemePreference): Promise<void> {
  return setUiPreference("ui_theme", theme);
}

/** Subscribe to preference changes made by this app instance. */
export function subscribeUiPreferences(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
