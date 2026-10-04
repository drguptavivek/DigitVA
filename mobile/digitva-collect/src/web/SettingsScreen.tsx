import { Text, View } from "react-native";

import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";
import { useTheme } from "../theme";
import { WebShell } from "./common";

export default function SettingsScreen() {
  const styles = useUiStyles();
  const theme = useTheme();
  return (
    <WebShell title={t("navSettings")}>
      <Text style={styles.headline}>{t("appearance")}</Text>
      <View style={styles.row}>
        <Button kind={theme.preference === "system" ? "primary" : "secondary"} label={t("themeSystem")} onPress={() => void theme.setPreference("system")} />
        <Button kind={theme.preference === "light" ? "primary" : "secondary"} label={t("themeLight")} onPress={() => void theme.setPreference("light")} />
        <Button kind={theme.preference === "dark" ? "primary" : "secondary"} label={t("themeDark")} onPress={() => void theme.setPreference("dark")} />
      </View>
    </WebShell>
  );
}
