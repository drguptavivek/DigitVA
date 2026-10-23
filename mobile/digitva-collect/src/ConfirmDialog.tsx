import { useEffect, useRef } from "react";
import { Modal, Platform, StyleSheet, Text, View } from "react-native";

import { t } from "./i18n";
import { controls, radius, spacing, typography, useTheme } from "./theme";
import { Button } from "./ui";

/**
 * The app's one confirmation dialog, mounted only while it asks (policy: no window.confirm/alert/prompt in the Expo client).
 * Cancel takes focus first so Enter never confirms a destructive action by accident. On the web
 * Escape cancels and Tab cycles between the two buttons (the dialog is a focus trap).
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel = t("cancel"),
  destructive = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { colors } = useTheme();
  const cancelRef = useRef<{ focus?: () => void } | null>(null);
  const confirmRef = useRef<{ focus?: () => void } | null>(null);
  const cancelCb = useRef(onCancel);
  cancelCb.current = onCancel;

  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return undefined;
    const timer = setTimeout(() => cancelRef.current?.focus?.(), 0);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelCb.current();
      } else if (event.key === "Tab") {
        event.preventDefault();
        const onCancelButton = document.activeElement === (cancelRef.current as unknown);
        (onCancelButton ? confirmRef : cancelRef).current?.focus?.();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onCancel}>
      <View style={s.backdrop}>
        <View
          accessibilityViewIsModal
          accessibilityRole={"alertdialog" as never}
          accessibilityLabel={title}
          style={[s.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Text accessibilityRole="header" style={[s.title, { color: colors.text }]}>{title}</Text>
          <Text style={[s.message, { color: colors.textMuted }]}>{message}</Text>
          <View style={s.actions}>
            <View ref={cancelRef as never}>
              <Button kind="secondary" label={cancelLabel} onPress={onCancel} />
            </View>
            <View ref={confirmRef as never}>
              <Button kind={destructive ? "danger" : "primary"} label={confirmLabel} onPress={onConfirm} />
            </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md, backgroundColor: "rgba(0,0,0,0.5)" },
  dialog: { width: "100%", maxWidth: 420, borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  title: { ...typography.headline, fontFamily: controls.fontFamily },
  message: { ...typography.subhead, fontFamily: controls.fontFamily },
  actions: { flexDirection: "row", justifyContent: "flex-end", flexWrap: "wrap", gap: spacing.xs },
});
