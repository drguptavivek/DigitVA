/**
 * Phone clock notices (docs/policy/field-data-collection.md, "Phone clock"): ClockWarning is the persistent
 * strip under the header when the clock is 5 minutes to 4 hours off (and stays when it is more); ClockBlock
 * covers the entry screens when it is more than 4 hours off. Both apply only to the selected server account
 * and offer Date & time settings and Re-check; standalone never uses a retained server clock.
 */
import * as IntentLauncher from "expo-intent-launcher";
import { useState } from "react";
import { Linking, StyleSheet, Text, View } from "react-native";

import { t } from "../i18n";
import { type PhoneClock, recheckPhoneClock, usePhoneClock } from "../phoneClock";
import { spacing, useTheme } from "../theme";
import { Button, Screen } from "../ui";
import { useShell } from "./shellContext";

/** "2 days 3 h", "3 h 5 min" or "12 min" for a non-negative number of seconds. */
export function clockSpan(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours >= 24) return t("clockSpanDays", { days: Math.floor(hours / 24), hours: hours % 24 });
  if (hours >= 1) return t("clockSpanHours", { hours, minutes: minutes % 60 });
  return t("clockSpanMinutes", { minutes });
}

export function clockMessage(clock: PhoneClock): string {
  const amount = clockSpan(Math.abs(clock.offsetSeconds));
  return t(clock.offsetSeconds > 0 ? "clockWrongAhead" : "clockWrongBehind", { amount });
}

async function openDateSettings(): Promise<void> {
  try {
    await IntentLauncher.startActivityAsync(IntentLauncher.ActivityAction.DATE_SETTINGS);
  } catch {
    await Linking.openSettings().catch(() => undefined);
  }
}

function ClockActions({ onDark }: { onDark?: boolean }) {
  const { server } = useShell();
  const [checking, setChecking] = useState(false);
  const [failed, setFailed] = useState(false);
  const recheck = async () => {
    if (!server) return;
    setChecking(true);
    setFailed(!(await recheckPhoneClock(server)));
    setChecking(false);
  };
  const theme = useTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      <Button label={t("clockOpenSettings")} onPress={() => void openDateSettings()} />
      <Button kind="secondary" label={t("clockRecheck")} loading={checking} disabled={checking || !server} onPress={() => void recheck()} />
      {failed ? <Text style={{ color: onDark ? theme.colors.onAccent : theme.colors.text }}>{t("clockRecheckFailed")}</Text> : null}
    </View>
  );
}

export function ClockWarning() {
  const { server } = useShell();
  const { clock, level } = usePhoneClock();
  const theme = useTheme();
  if (!server || !clock || level === "ok") return null;
  return (
    <View accessibilityRole="alert" style={{ backgroundColor: theme.colors.warning, padding: spacing.sm, gap: spacing.xs }}>
      <Text style={{ color: theme.colors.onAccent }}>{clockMessage(clock)}</Text>
      <ClockActions onDark />
    </View>
  );
}

/** Covers a data-entry screen without unmounting it, so an open form keeps what was typed. */
export function ClockBlock() {
  const { server } = useShell();
  const { clock } = usePhoneClock();
  const theme = useTheme();
  if (!server || !clock) return null;
  return (
    <View style={[StyleSheet.absoluteFill, { backgroundColor: theme.colors.background }]}>
      <Screen title={t("clockBlockTitle")}>
        <Text style={{ color: theme.colors.text }}>{clockMessage(clock)}</Text>
        <Text style={{ color: theme.colors.text }}>{t("clockBlockBody")}</Text>
        <ClockActions />
      </Screen>
    </View>
  );
}
