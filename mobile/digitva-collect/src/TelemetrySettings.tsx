import { useEffect, useState } from "react";
import { View } from "react-native";

import { t } from "./i18n";
import { getPerformanceTelemetryEnabled, setPerformanceTelemetryEnabled } from "./performanceTelemetry";
import { spacing } from "./theme";
import { Button, ListRow, Notice, ThemedSwitch } from "./ui";

/**
 * The owner-visible opt-out, as one row of Settings' Diagnostics card ("Usage diagnostics" and its switch; the card's
 * footer explains it). It only changes aggregate performance diagnostics, never field data or sync.
 */
export function TelemetrySettings() {
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
    <>
      <ListRow
        label={t("telemetryTitle")}
        trailing={<ThemedSwitch accessibilityLabel={t("telemetryTitle")} accessibilityHint={t("telemetryDescription")} value={enabled} onValueChange={(next) => void change(next)} />}
      />
      {error ? (
        <View style={{ padding: spacing.sm }}>
          <Notice tone="error" action={<Button size="sm" kind="secondary" label={t("telemetryRetry")} onPress={() => void change(false)} />}>{error}</Notice>
        </View>
      ) : null}
    </>
  );
}
