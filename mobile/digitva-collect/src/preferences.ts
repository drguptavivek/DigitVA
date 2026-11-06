/**
 * Storage for non-sensitive UI preferences only.
 *
 * The browser adapter deliberately has a short key allowlist. Interview answers,
 * identifiers and tokens must stay in their existing stores and never enter
 * localStorage.
 */
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export type PreferenceKey = "ui_locale" | "ui_theme" | "ui_text_size" | "ui_high_contrast" | "update_check_at";
export type ThemePreference = "system" | "light" | "dark";
/** Settings > Display > Text size; device-local, never sent to the server. */
export type TextSizePreference = "small" | "medium" | "large";
/** Settings > Display > High contrast; "system" (never chosen) follows the phone's own contrast setting. */
export type HighContrastPreference = "system" | "on" | "off";

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
  return value === "ui_locale" || value === "ui_theme" || value === "ui_text_size" || value === "ui_high_contrast" || value === "update_check_at";
}

const asTextSize = (value: string | null): TextSizePreference => (value === "small" || value === "large" ? value : "medium");
const asHighContrast = (value: string | null): HighContrastPreference => (value === "on" || value === "off" ? value : "system");

/** Synchronous read of `key` for first paint: in-memory value, else browser storage; undefined when unknown. */
function peekUiPreference(key: PreferenceKey): string | null | undefined {
  const value = memoryPreferences[key];
  if (value !== undefined) return value;
  try {
    return browserStorage()?.getItem(key);
  } catch {
    return undefined;
  }
}

/** Synchronous read for first paint: in-memory value, else browser storage. Null when unknown (native before its async read). */
export function peekUiTheme(): ThemePreference | null {
  const value = peekUiPreference("ui_theme");
  if (value === undefined) return null;
  return value === "light" || value === "dark" ? value : "system";
}

/** As peekUiTheme, for the text size. */
export function peekUiTextSize(): TextSizePreference | null {
  const value = peekUiPreference("ui_text_size");
  return value === undefined ? null : asTextSize(value);
}

/** As peekUiTheme, for high contrast. */
export function peekUiHighContrast(): HighContrastPreference | null {
  const value = peekUiPreference("ui_high_contrast");
  return value === undefined ? null : asHighContrast(value);
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
  const stored = await SecureStore.getItemAsync(key).catch(() => null);
  // A set while the read was in flight wins; otherwise cache so peekUiTheme() is known after the first read.
  if (memoryPreferences[key] !== undefined) return memoryPreferences[key] ?? null;
  if (stored !== null) memoryPreferences[key] = stored;
  return stored;
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

export async function getUiTextSize(): Promise<TextSizePreference> {
  return asTextSize(await getUiPreference("ui_text_size"));
}

export async function setUiTextSize(size: TextSizePreference): Promise<void> {
  return setUiPreference("ui_text_size", size);
}

export async function getUiHighContrast(): Promise<HighContrastPreference> {
  return asHighContrast(await getUiPreference("ui_high_contrast"));
}

export async function setUiHighContrast(value: HighContrastPreference): Promise<void> {
  return setUiPreference("ui_high_contrast", value);
}

/** Subscribe to preference changes made by this app instance. */
export function subscribeUiPreferences(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
