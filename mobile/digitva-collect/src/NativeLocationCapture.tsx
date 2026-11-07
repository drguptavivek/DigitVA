import * as Location from "expo-location";
import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { t, type StringKey } from "./i18n";
import { spacing } from "./theme";
import { Button, useUiStyles } from "./ui";
import type { GpsFix } from "./web/LocationCapture";

/** The expo-location calls the control makes; injectable for tests. */
export type NativeLocator = Pick<typeof Location, "requestForegroundPermissionsAsync" | "getCurrentPositionAsync" | "getLastKnownPositionAsync"> &
  Partial<Pick<typeof Location, "getForegroundPermissionsAsync" | "watchPositionAsync">>;

const HIGH_TIMEOUT_MS = 10000;
const BALANCED_TIMEOUT_MS = 8000;
const GPS_TIMEOUT_MS = 15000;
const LAST_KNOWN_MAX_AGE_MS = 120000;
const LAST_KNOWN_REQUIRED_ACCURACY_M = 500;
const WARM_MAX_AGE_MS = 60000;
const WARM_GOOD_ACCURACY_M = 100;
const WARM_INTERVAL_MS = 5000;

const TIMED_OUT = Symbol("timed out");

/** The promise's value, or TIMED_OUT after `ms`; a rejection passes through. */
function timed<T>(promise: Promise<T>, ms: number): Promise<T | typeof TIMED_OUT> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([promise, new Promise<typeof TIMED_OUT>((resolve) => { timer = setTimeout(() => resolve(TIMED_OUT), ms); })])
    .finally(() => clearTimeout(timer));
}

/**
 * One reading, degrading instead of failing. Each live step has its own timeout, so a High request that
 * hangs indoors (or waits behind the Android "Location Accuracy" dialog) still falls through: High, then
 * Balanced without the settings dialog, then High without the dialog, then a recent coarse cached fix. The
 * no-dialog High step is the GPS fallback: with "Location Accuracy" declined the network provider is off,
 * Balanced has no source, but a fused High request without the dialog still runs on the GPS provider. A recent warm fix counts as a
 * success at any step. `allTimedOut` is true only when every live step timed out and nothing else answered.
 * The accuracy is shown, so the user can judge the fix.
 */
async function readPosition(locator: NativeLocator, warm: () => Location.LocationObject | null): Promise<{ position: Location.LocationObject | null; allTimedOut: boolean }> {
  const steps = [
    { options: { accuracy: Location.Accuracy.High }, ms: HIGH_TIMEOUT_MS },
    { options: { accuracy: Location.Accuracy.Balanced, mayShowUserSettingsDialog: false }, ms: BALANCED_TIMEOUT_MS },
    { options: { accuracy: Location.Accuracy.High, mayShowUserSettingsDialog: false }, ms: GPS_TIMEOUT_MS },
  ];
  let timeouts = 0;
  for (const step of steps) {
    const fix = warm();
    if (fix) return { position: fix, allTimedOut: false };
    try {
      const result = await timed(locator.getCurrentPositionAsync(step.options), step.ms);
      if (result !== TIMED_OUT) return { position: result, allTimedOut: false };
      timeouts += 1;
    } catch { /* fall through to the next step */ }
  }
  const fix = warm();
  if (fix) return { position: fix, allTimedOut: false };
  try {
    const last = await locator.getLastKnownPositionAsync({ maxAge: LAST_KNOWN_MAX_AGE_MS, requiredAccuracy: LAST_KNOWN_REQUIRED_ACCURACY_M });
    return { position: last, allTimedOut: !last && timeouts === steps.length };
  } catch {
    return { position: null, allTimedOut: false };
  }
}

/**
 * Optional "Capture location" control on the native register form
 * (docs/policy/native-location-capture.md). Permission is asked only on a tap, when-in-use only; the
 * position is read once, never watched. GPS needs no network, so it works offline. Coordinates are never
 * logged: a failure shows the same short messages as the web control and the form still saves without a fix.
 */
export function NativeLocationCapture({ value, onChange, disabled, locator = Location, watching = false }: {
  value: GpsFix | null;
  onChange: (next: GpsFix | null) => void;
  disabled?: boolean;
  locator?: NativeLocator;
  /** The screen is focused and the app is in the foreground: warm the GPS while so, if permission is already granted. */
  watching?: boolean;
}) {
  const styles = useUiStyles();
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState<StringKey>();
  const mounted = useRef(true);
  const readId = useRef(0); // a newer capture supersedes an older one still reading
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  // GPS warmup: a watch that keeps the best recent fix in memory only (never stored or logged) so a tap
  // can answer at once. Started only with permission already granted; stopped on blur, unmount, background.
  const warm = useRef<{ position: Location.LocationObject; at: number } | null>(null);
  const subscription = useRef<{ remove: () => void } | null>(null);
  const warmToken = useRef(0);
  const watchingRef = useRef(watching);
  watchingRef.current = watching;

  function stopWarm() {
    warmToken.current += 1;
    subscription.current?.remove();
    subscription.current = null;
    warm.current = null;
  }

  async function startWarm() {
    if (subscription.current || !locator.getForegroundPermissionsAsync || !locator.watchPositionAsync) return;
    const token = ++warmToken.current;
    try {
      if ((await locator.getForegroundPermissionsAsync()).status !== "granted" || token !== warmToken.current) return;
      const sub = await locator.watchPositionAsync(
        // Never the Android "Location Accuracy" dialog: opening the screen must not prompt.
        { accuracy: Location.Accuracy.Balanced, timeInterval: WARM_INTERVAL_MS, distanceInterval: 0, mayShowUserSettingsDialog: false },
        (position) => {
          const now = Date.now();
          const current = warm.current;
          const accuracy = position.coords.accuracy;
          if (!current || now - current.at > WARM_MAX_AGE_MS || (typeof accuracy === "number" && accuracy <= (current.position.coords.accuracy ?? Infinity))) {
            warm.current = { position, at: now };
          }
        },
        () => { if (token === warmToken.current) stopWarm(); }, // a failing watch ends warmup; no retry
      );
      if (token !== warmToken.current) sub.remove();
      else subscription.current = sub;
    } catch { /* settings unsatisfied or no fix source: no warmup, no retry; the tap still reads normally */ }
  }

  useEffect(() => {
    if (!watching) return;
    void startWarm();
    return stopWarm;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching]);

  /** A warm fix that is recent and good enough to use without waiting. */
  function warmPosition() {
    const current = warm.current;
    if (!current || Date.now() - current.at > WARM_MAX_AGE_MS) return null;
    const accuracy = current.position.coords.accuracy;
    return typeof accuracy === "number" && accuracy <= WARM_GOOD_ACCURACY_M ? current.position : null;
  }

  async function capture() {
    const id = ++readId.current;
    setCapturing(true);
    setError(undefined);
    let failure: StringKey | undefined;
    try {
      const permission = await locator.requestForegroundPermissionsAsync();
      if (permission.status !== "granted") failure = "locationDenied";
      else {
        if (watchingRef.current) void startWarm();
        const warmFix = warmPosition();
        const { position, allTimedOut } = warmFix ? { position: warmFix, allTimedOut: false } : await readPosition(locator, warmPosition);
        if (id !== readId.current) return; // superseded: the newer capture owns the result
        if (!position) failure = allTimedOut ? "locationTimeout" : "locationUnavailable";
        else {
          const { latitude, longitude, accuracy } = position.coords;
          if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) failure = "locationUnavailable";
          else if (mounted.current) {
            onChange({ latitude, longitude, accuracy_m: typeof accuracy === "number" && Number.isFinite(accuracy) && accuracy >= 0 ? accuracy : null });
          }
        }
      }
    } catch {
      failure = "locationUnavailable";
    }
    if (!mounted.current || id !== readId.current) return;
    setCapturing(false);
    setError(failure);
  }

  const busy = capturing || disabled;
  return (
    <View style={{ gap: spacing.xs }}>
      {value ? (
        <>
          <Text style={styles.text}>
            {value.accuracy_m === null ? t("locationCapturedNoAccuracy") : t("locationCaptured", { meters: Math.round(value.accuracy_m) })}
          </Text>
          <View style={styles.row}>
            <Button kind="secondary" label={t("locationRetake")} loading={capturing} disabled={busy} onPress={() => void capture()} />
            <Button kind="secondary" label={t("locationClear")} disabled={busy} onPress={() => { setError(undefined); onChange(null); }} />
          </View>
        </>
      ) : (
        <Button kind="secondary" label={t(capturing ? "locationCapturing" : "locationCapture")} loading={capturing} disabled={busy} onPress={() => void capture()} />
      )}
      {error ? <Text style={styles.error} accessibilityRole="alert">{t(error)}</Text> : null}
      {!value && !error ? <Text style={styles.muted}>{t("locationHelp")}</Text> : null}
    </View>
  );
}
