/** A bottom sheet with a grab handle and a scrolling body; a tap on the dimmed area closes it. */
import type { ReactNode } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { t } from "../i18n";
import { radius, spacing, typography, useTheme } from "../theme";

export function BottomSheet({ visible, title, onClose, children }: { visible: boolean; title: string; onClose(): void; children: ReactNode }) {
  const { ui } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "flex-end" }}>
        <Pressable accessibilityLabel={t("cancel")} onPress={onClose} style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(15,27,45,0.55)" }} />
        <View style={{ maxHeight: "85%", backgroundColor: ui.popover, borderTopLeftRadius: radius.lg * 2, borderTopRightRadius: radius.lg * 2, paddingTop: spacing.xs, paddingHorizontal: spacing.md, paddingBottom: insets.bottom + spacing.md }}>
          <View style={{ width: 40, height: 4, borderRadius: 2, backgroundColor: ui.border, alignSelf: "center", marginBottom: spacing.xs }} />
          <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.popoverForeground, marginBottom: spacing.xs }}>{title}</Text>
          <ScrollView keyboardShouldPersistTaps="handled">{children}</ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** One tappable row of a sheet (52dp). */
export function SheetRow({ label, detail, onPress, tone = "normal", disabled, busy }: { label: string; detail?: string; onPress(): void; tone?: "normal" | "danger"; disabled?: boolean; busy?: boolean }) {
  const { ui } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled || busy), busy: Boolean(busy) }}
      disabled={disabled || busy}
      onPress={onPress}
      style={{ minHeight: 52, justifyContent: "center", opacity: disabled ? 0.5 : 1 }}
    >
      <Text style={{ ...typography.body, color: tone === "danger" ? ui.destructiveText : ui.popoverForeground }}>{label}</Text>
      {detail ? <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{detail}</Text> : null}
    </Pressable>
  );
}
