import { useState, type ReactNode } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { setIcd11DorisEnabled, useIcd11DorisPreference } from "./icd11DorisPreference";
import { t } from "./i18n";
import { Button, Screen, useUiStyles } from "./ui";
import { useShell } from "./nativeShell/shellContext";
import { ModeBanner } from "./nativeShell/ModeBanner";

export default function NativeIcd11DorisFirstLaunchGate({ children }: { children: ReactNode }) {
  const preference = useIcd11DorisPreference();
  const styles = useUiStyles();
  const insets = useSafeAreaInsets();
  const shell = useShell();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function answer(enabled: boolean) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await setIcd11DorisEnabled(enabled);
    } catch {
      setError(t("icd11DorisPreferenceSaveError"));
    } finally {
      setBusy(false);
    }
  }

  if (preference.ready && preference.answered) return children;
  return (
    <View style={{ flex: 1 }}>
      <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ flex: 1 }}>
        {children}
      </View>
      <View style={{ position: "absolute", inset: 0, paddingTop: shell.header ? insets.top : 0, paddingBottom: shell.tabs ? insets.bottom : 0 }} accessibilityViewIsModal>
        <ModeBanner />
        <Screen title={t("icd11DorisPreferenceTitle")}>
          {!preference.ready ? <ActivityIndicator accessibilityLabel={t("loading")} /> : null}
          <Text style={styles.text}>{t("icd11DorisPreferenceDescription")}</Text>
          <Text style={styles.muted}>{t("icd11DorisPreferenceScope")}</Text>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Button label={t("icd11DorisPreferenceEnable")} loading={busy} disabled={busy || !preference.ready} onPress={() => void answer(true)} />
          <Button kind="secondary" label={t("icd11DorisPreferenceNotNow")} loading={busy} disabled={busy || !preference.ready} onPress={() => void answer(false)} />
        </Screen>
      </View>
    </View>
  );
}
