import { ActivityIndicator, Text, View } from "react-native";

import { t } from "../i18n";
import { useTheme } from "../theme";
import { WebShell } from "./common";

/** Keep navigation and the current canvas visible while a route's code downloads. */
export default function LoadingScreen() {
  const { colors } = useTheme();
  return <WebShell title={t("appName")}>
    <View testID="web-route-loading" accessibilityRole="progressbar" accessibilityLabel={t("loading")}
      style={{ flexGrow: 1, minHeight: 160, alignItems: "center", justifyContent: "center", gap: 12, backgroundColor: colors.background }}>
      <ActivityIndicator color={colors.accent} />
      <Text style={{ color: colors.textMuted }}>{t("loading")}</Text>
    </View>
  </WebShell>;
}
