import { useEffect, useState } from "react";
import { Switch, Text, View } from "react-native";

import { t } from "./i18n";
import { getPerformanceTelemetryEnabled, setPerformanceTelemetryEnabled } from "./performanceTelemetry";
import { Button, useUiStyles } from "./ui";

/** The owner-visible opt-out. It only changes aggregate performance diagnostics, never field data or sync. */
export function TelemetrySettings() {
  const styles = useUiStyles();
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getPerformanceTelemetryEnabled().then((value) => {
      if (active) setEnabled(value);
    });
    return () => {
      active = false;
    };
  }, []);
  async function change(next: boolean) {
    setError("");
    setEnabled(next);
    try {
      await setPerformanceTelemetryEnabled(next);
    } catch {
      // A failed preference write leaves collection disabled in memory; the visible switch can be retried.
      setEnabled(false);
      setError(t("telemetrySaveError"));
    }
  }
  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.muted}>{t("telemetryDescription")}</Text>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <Text style={styles.text}>{t(enabled ? "telemetryOn" : "telemetryOff")}</Text>
        <Switch
          accessibilityLabel={t("telemetryTitle")}
          value={enabled}
          onValueChange={(next) => void change(next)}
        />
      </View>
      {error ? (
        <>
          <Text accessibilityRole="alert" style={styles.error}>{error}</Text>
          <Button kind="secondary" label={t("telemetryRetry")} onPress={() => void change(false)} />
        </>
      ) : null}
    </View>
  );
}
