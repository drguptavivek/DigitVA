import { createElement, useEffect, useRef, useState } from "react";
import { Linking, Platform, Text, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { fontSize, spacing, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";

/** One optional GPS fix of the house (docs/policy/web-intake.md, "Death-site GPS location"). */
export interface GpsFix {
  latitude: number;
  longitude: number;
  /** Metres; null when the device gave none. */
  accuracy_m: number | null;
}

type Geolocator = Pick<Geolocation, "getCurrentPosition">;
type Phase = "idle" | "capturing" | "error";

/** Tabler "map-pin" outline, the line-icon family of the app header. */
const PIN_PATHS = ["M9 11a3 3 0 1 0 6 0a3 3 0 0 0 -6 0", "M17.657 16.657l-4.243 4.243a2 2 0 0 1 -2.827 0l-4.244 -4.243a8 8 0 1 1 11.314 0z"];
const pinIcon = (color: string) =>
  createElement("svg", { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: color, strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, focusable: false },
    ...PIN_PATHS.map((d) => createElement("path", { key: d, d })));

const isFix = (lat: unknown, lng: unknown): lat is number =>
  typeof lat === "number" && typeof lng === "number" && Number.isFinite(lat) && Number.isFinite(lng);

/** Google Maps search by coordinates; the numbers are formatted here, never taken as text. */
export function mapsUrl(latitude: number, longitude: number): string {
  return `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
}

/** "Open in maps" plus the coordinates in small muted text. Renders nothing without a full fix. */
export function MapsLink({ latitude, longitude }: { latitude?: number | null; longitude?: number | null }) {
  const styles = useUiStyles();
  const theme = useTheme();
  if (!isFix(latitude, longitude)) return null;
  const url = mapsUrl(latitude, longitude as number);
  const coordinates = `${latitude.toFixed(6)}, ${(longitude as number).toFixed(6)}`;
  const linkColor = theme.ui.primary;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, flexWrap: "wrap" }}>
      {Platform.OS === "web"
        ? createElement("a", { href: url, target: "_blank", rel: "noopener noreferrer", style: { color: linkColor, fontSize: fontSize.body } }, t("openInMaps"))
        : <Text accessibilityRole="link" style={[styles.text, { color: linkColor }]} onPress={() => void Linking.openURL(url).catch(() => undefined)}>{t("openInMaps")}</Text>}
      <Text style={[styles.muted, { fontSize: fontSize.caption }]}>{coordinates}</Text>
    </View>
  );
}

const ERROR_TEXT: Record<number, StringKey> = { 1: "locationDenied", 2: "locationUnavailable", 3: "locationTimeout" };

/**
 * Optional "Capture location" control (web). The position is read once per press, never on load and never
 * watched; a failure is a short message and the form still saves without a fix.
 */
export function LocationCapture({ value, onChange, geolocation }: {
  value: GpsFix | null;
  onChange: (next: GpsFix | null) => void;
  /** Injectable for tests; defaults to the browser's. */
  geolocation?: Geolocator;
}) {
  const styles = useUiStyles();
  const theme = useTheme();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<StringKey>();
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const locator = geolocation ?? (typeof navigator !== "undefined" ? navigator.geolocation : undefined);
  if (Platform.OS !== "web" || !locator) return null;

  function capture() {
    if (phase === "capturing" || !locator) return;
    setPhase("capturing");
    setError(undefined);
    locator.getCurrentPosition(
      (position) => {
        if (!mounted.current) return;
        const { latitude, longitude, accuracy } = position.coords;
        if (!isFix(latitude, longitude)) { setPhase("error"); setError("locationUnavailable"); return; }
        setPhase("idle");
        onChange({ latitude, longitude, accuracy_m: Number.isFinite(accuracy) && accuracy >= 0 ? accuracy : null });
      },
      (failure) => {
        if (!mounted.current) return;
        setPhase("error");
        setError(ERROR_TEXT[failure?.code] ?? "locationUnavailable");
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  }

  const capturing = phase === "capturing";
  return (
    <View style={{ gap: spacing.xs }}>
      {value ? (
        <>
          <Text style={styles.text}>
            {value.accuracy_m === null ? t("locationCapturedNoAccuracy") : t("locationCaptured", { meters: Math.round(value.accuracy_m) })}
          </Text>
          <View style={styles.row}>
            <Button kind="secondary" label={t("locationRetake")} loading={capturing} disabled={capturing} onPress={capture} />
            <Button kind="secondary" label={t("locationClear")} disabled={capturing} onPress={() => { setPhase("idle"); setError(undefined); onChange(null); }} />
          </View>
        </>
      ) : (
        <View style={[styles.row, { alignItems: "center" }]}>
          {pinIcon(theme.ui.mutedForeground)}
          <Button kind="secondary" label={t(capturing ? "locationCapturing" : "locationCapture")} loading={capturing} disabled={capturing} onPress={capture} />
        </View>
      )}
      {phase === "error" && error ? <Text style={styles.error} accessibilityRole="alert">{t(error)}</Text> : null}
      {!value && phase !== "error" ? <Text style={styles.muted}>{t("locationHelp")}</Text> : null}
    </View>
  );
}
