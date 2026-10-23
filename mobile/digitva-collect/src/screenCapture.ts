import { preventScreenCaptureAsync } from "expo-screen-capture";
import { Platform } from "react-native";

// Owner decision 2026-10-23: screenshots allowed for field testing in builds made
// with EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL=<ISO date>; blocked again from that
// date by the same APK. Unset or invalid = blocked. See docs/policy/expo-client.md.
const MAX_ALLOWANCE_MS = 14 * 24 * 60 * 60 * 1000;
const loadedAt = Date.now();

/** True only while the device clock is before the build-time date; a date more than 14 days past app start is treated as invalid (caps misuse). */
export function screenshotsAllowed(
  now: Date = new Date(),
  // Literal property access so Metro inlines the build-time value.
  until: string | undefined = process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL,
): boolean {
  const end = until ? Date.parse(until) : NaN;
  if (Number.isNaN(end) || end > loadedAt + MAX_ALLOWANCE_MS) return false;
  return now.getTime() < end;
}

/** FLAG_SECURE on the whole app (no screenshots, blank in recent apps) unless the dated allowance or the debug opt-out applies. */
export function applyScreenCaptureBlock(): void {
  if (Platform.OS === "web") return;
  // __DEV__ is false in release, so release never honours the debug opt-out.
  if (__DEV__ && process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS === "1") return;
  if (screenshotsAllowed()) return;
  void preventScreenCaptureAsync();
}
