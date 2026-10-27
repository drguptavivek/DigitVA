import { ActivityIndicator, Modal, Platform, StyleSheet, Text, View } from "react-native";

import { t } from "./i18n";
import { controls, radius, spacing, typography, useTheme } from "./theme";

/**
 * Blocks Home while a freshly signed-in phone downloads its projects,
 * questionnaires and cases, so the interviewer does not go offline before
 * the phone can start an interview. It cannot be dismissed: it closes when
 * the download settles, and a failure shows the usual Home message.
 */
export function FirstDownloadModal() {
  const { colors } = useTheme();
  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => undefined}>
      <View style={s.backdrop}>
        <View
          accessibilityViewIsModal
          {...(Platform.OS === "web" ? { role: "alertdialog" as never } : { accessibilityRole: "alert" as const })}
          accessibilityLabel={t("firstDownloadTitle")}
          testID="first-download-modal"
          style={[s.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <ActivityIndicator size="large" />
          <Text accessibilityRole="header" style={[s.title, { color: colors.text }]}>{t("firstDownloadTitle")}</Text>
          <Text style={[s.message, { color: colors.textMuted }]}>{t("firstDownloadMessage")}</Text>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md, backgroundColor: "rgba(0,0,0,0.5)" },
  dialog: { width: "100%", maxWidth: 420, borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm, alignItems: "center" },
  title: { ...typography.headline, fontFamily: controls.fontFamily, textAlign: "center" },
  message: { ...typography.subhead, fontFamily: controls.fontFamily, textAlign: "center" },
});
