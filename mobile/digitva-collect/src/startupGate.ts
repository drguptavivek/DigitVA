/**
 * The native splash screen stays up until the first screen can paint right: the app state is ready, the stored
 * display preferences (theme, text size, contrast) are read, and the stored server UI language pack is applied
 * (digitva-j01l, w9lz, pbgx). Without it the phone showed a spinner, then the default light theme, then English text
 * before the stored dark theme or server-only language landed. A timeout releases the splash anyway.
 */
import * as SplashScreen from "expo-splash-screen";
import { useEffect, useState } from "react";
import { Platform } from "react-native";

import { useAppState } from "./AppState";
import { normalizeLocale, requestedUiLocale, setServerUiLanguages, uiLanguages } from "./i18n";
import { displayPreferencesLoaded } from "./theme";
import { applyUiPack, parseUiLanguageList } from "./uiPacks";
import { readStoredPack } from "./uiPackStore";

/** Longest the splash is held; a hung storage read must not leave the app behind it. */
export const SPLASH_MAX_MS = 4000;

const native = Platform.OS !== "web";
if (native) SplashScreen.preventAutoHideAsync().catch(() => undefined);

/**
 * Lay the stored language list and pack for the current locale over the bundled text, from disk only (the network
 * refresh stays in AppState). Mirrors the first half of syncUiPacks (src/uiPacks.ts), whose storage slug it repeats;
 * never throws.
 */
export async function applyStoredUiPack(server: string, locale: string | null | undefined): Promise<void> {
  try {
    const slug = server ? server.toLowerCase().replace(/[^a-z0-9]+/g, "_") : "same_origin";
    setServerUiLanguages(true, parseUiLanguageList(await readStoredPack(`${slug}-list`)));
    const code = normalizeLocale(locale);
    if (!uiLanguages().some((entry) => entry.code === code && entry.version)) return;
    const pack = (await readStoredPack(`${slug}-${code}`)) as { version?: unknown; strings?: unknown; form?: unknown } | undefined;
    if (pack && typeof pack.version === "string") applyUiPack(code, pack);
  } catch {
    // The network sync (or the bundled text) covers a missing or damaged pack.
  }
}

/**
 * Hold the native splash until the first screen is ready; call once inside AppStateProvider. Its own state changes
 * must not re-render the app, so mount it through <SplashHold />.
 */
function useSplashHold(): void {
  const { ready, device } = useAppState();
  const server = device?.server;
  const [preferences, setPreferences] = useState(false);
  const [pack, setPack] = useState(false);
  const [late, setLate] = useState(false);
  useEffect(() => {
    // Promise.resolve: a test double of ./theme may not export it.
    void Promise.resolve(displayPreferencesLoaded).then(() => setPreferences(true));
    const timer = setTimeout(() => setLate(true), SPLASH_MAX_MS);
    return () => clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (!ready) return;
    if (!server) { setPack(true); return; }
    void applyStoredUiPack(server, requestedUiLocale()).then(() => setPack(true));
  }, [ready, server]);
  const go = late || (ready && preferences && pack);
  useEffect(() => {
    if (!native || !go) return;
    // One frame so the committed screen (theme, text) is what the splash lifts off.
    const frame = requestAnimationFrame(() => SplashScreen.hideAsync().catch(() => undefined));
    return () => cancelAnimationFrame(frame);
  }, [go]);
}

/** Renders nothing; only holds and then lifts the splash, in a component of its own so the app does not re-render. */
export function SplashHold(): null {
  useSplashHold();
  return null;
}
