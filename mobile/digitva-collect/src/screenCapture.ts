import { allowScreenCaptureAsync, preventScreenCaptureAsync } from "expo-screen-capture";
import { AppState, Platform } from "react-native";

// Owner update 2026-10-28: screenshots allowed for field testing in builds made
// with EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL=<ISO date>; blocked again from that
// date by the same APK. Unset or invalid = blocked. See docs/policy/expo-client.md.
const MAX_ALLOWANCE_MS = 28 * 24 * 60 * 60 * 1000;
const MAX_TIMER_DELAY_MS = 2_147_483_647;
const loadedAt = Date.now();
let blockApplied = false;

/** True before the build-time expiry; allowances beyond four weeks from app start are invalid. */
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
export function applyScreenCaptureBlock(): () => void {
  if (Platform.OS === "web") return () => {};
  // __DEV__ is false in release, so release never honours the debug opt-out.
  if (__DEV__ && process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS === "1") return () => {};

  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  const update = () => {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = undefined;
    const now = Date.now();
    if (screenshotsAllowed(new Date(now))) {
      if (blockApplied) {
        blockApplied = false;
        void allowScreenCaptureAsync();
      }
      const end = Date.parse(process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS_UNTIL ?? "");
      expiryTimer = setTimeout(update, Math.min(end - now + 1, MAX_TIMER_DELAY_MS));
    } else if (!blockApplied) {
      blockApplied = true;
      void preventScreenCaptureAsync();
    }
  };

  update();
  const subscription = AppState.addEventListener("change", (state) => {
    if (state === "active") update();
  });
  return () => {
    if (expiryTimer) clearTimeout(expiryTimer);
    subscription.remove();
  };
}
