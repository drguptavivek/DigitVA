import { useEffect, useState } from "react";
import { Platform } from "react-native";

import { ConfirmDialog } from "./ConfirmDialog";
import { t } from "./i18n";
import { getPerformanceTelemetryChoice, setPerformanceTelemetryEnabled } from "./performanceTelemetry";

/**
 * One-time opt-in question for aggregate diagnostics, shown on native only while the choice is "unasked".
 * Both buttons (and Android back) store an explicit answer, so it never asks again; "Not now" stores off.
 */
export function TelemetryPrompt() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (Platform.OS !== "android" && Platform.OS !== "ios") return;
    let active = true;
    void getPerformanceTelemetryChoice().then((choice) => {
      if (active && choice === "unasked") setOpen(true);
    });
    return () => {
      active = false;
    };
  }, []);
  if (!open) return null;
  const answer = (on: boolean) => {
    setOpen(false);
    void setPerformanceTelemetryEnabled(on).catch(() => undefined);
  };
  return (
    <ConfirmDialog
      title={t("telemetryPromptTitle")}
      message={t("telemetryPromptBody")}
      confirmLabel={t("telemetryPromptOn")}
      cancelLabel={t("telemetryPromptOff")}
      onConfirm={() => answer(true)}
      onCancel={() => answer(false)}
    />
  );
}
