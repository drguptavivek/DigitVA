/**
 * The one compact top bar of the immersive form screens (interview and revision): back, a truncating title,
 * a save-state dot and an overflow menu. `Sheet` is the bottom list also used for the revision reason select.
 */
import { useState } from "react";
import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { t } from "./i18n";
import { radius, spacing, typography, useTheme } from "./theme";

export type SaveState = "saved" | "saving" | "unsaved";

export interface SheetItem {
  key: string;
  label: string;
  selected?: boolean;
  disabled?: boolean;
  onPress(): void;
}

const BAR_HEIGHT = 48;
const BAR_HEIGHT_WITH_LABEL = 56;

/**
 * A bottom sheet of choices; choosing one closes the sheet, then calls its handler. The sheet is laid out above the
 * system navigation bar (Android draws the Modal edge to edge) and scrolls when the list is taller than the screen.
 */
export function Sheet({ visible, title, items, onClose }: { visible: boolean; title?: string; items: SheetItem[]; onClose(): void }) {
  const { ui } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent navigationBarTranslucent onRequestClose={onClose}>
      <Pressable accessibilityLabel={t("cancel")} onPress={onClose} style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}>
        <View testID="sheet-panel" style={{ maxHeight: "85%", backgroundColor: ui.popover, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, paddingBottom: insets.bottom + spacing.lg }}>
          {title ? <Text style={{ ...typography.subhead, color: ui.mutedForeground, padding: spacing.md }}>{title}</Text> : null}
          <ScrollView keyboardDismissMode="on-drag" keyboardShouldPersistTaps="handled" bounces={false}>
          {items.map((item) => (
            <Pressable
              key={item.key}
              accessibilityRole="menuitem"
              accessibilityLabel={item.label}
              accessibilityState={{ disabled: Boolean(item.disabled), selected: Boolean(item.selected) }}
              disabled={item.disabled}
              onPress={() => {
                onClose();
                item.onPress();
              }}
              style={{ minHeight: 48, paddingHorizontal: spacing.md, justifyContent: "center", opacity: item.disabled ? 0.5 : 1 }}
            >
              <Text style={{ ...typography.body, color: ui.popoverForeground, fontWeight: item.selected ? "700" : "400" }}>
                {item.selected ? "✓ " : ""}
                {item.label}
              </Text>
            </Pressable>
          ))}
          </ScrollView>
        </View>
      </Pressable>
    </Modal>
  );
}

const SAVE_LABEL = { saved: "saveStateSaved", saving: "saveStateSaving", unsaved: "saveStateUnsaved" } as const;

export function FormTopBar({
  title,
  label,
  saveState,
  onBack,
  menuItems,
  disabled,
  problemCount = 0,
  onProblems,
  consentChip
}: {
  title: string;
  /** A small line above the title (the revision screen's "Revision"). */
  label?: string;
  saveState: SaveState;
  onBack(): void;
  menuItems: SheetItem[];
  disabled?: boolean;
  /** When above zero, a "N problems" chip opens the problems list (`onProblems`). */
  problemCount?: number;
  onProblems?(): void;
  /** Shown when the project requires consent: the decision in words (never colour alone); tapping changes it. */
  consentChip?: { label: string; decision: "granted" | "refused" | "none"; onPress?(): void };
}) {
  const { ui } = useTheme();
  const [open, setOpen] = useState(false);
  const dot = saveState === "saved" ? ui.success : saveState === "saving" ? ui.warningText : ui.destructiveText;
  const state = t(SAVE_LABEL[saveState]);
  return (
    <View style={{ height: label ? BAR_HEIGHT_WITH_LABEL : BAR_HEIGHT, flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xs, gap: spacing.xs, borderBottomWidth: 1, borderColor: ui.border, backgroundColor: ui.background }}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("back")} disabled={disabled} onPress={onBack} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: 22, color: ui.foreground }}>‹</Text>
      </Pressable>
      <View style={{ flex: 1, minWidth: 0 }}>
        {label ? <Text numberOfLines={1} style={{ ...typography.caption, color: ui.mutedForeground }}>{label}</Text> : null}
        <Text numberOfLines={1} accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>
          {title}
        </Text>
      </View>
      {problemCount > 0 ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t("problemsChip", { count: problemCount })}
          testID="problems-chip"
          onPress={onProblems}
          style={{ minHeight: 36, paddingHorizontal: spacing.sm, borderRadius: radius.lg * 2, borderWidth: 1, borderColor: ui.destructiveText, justifyContent: "center" }}
        >
          <Text numberOfLines={1} style={{ ...typography.caption, fontWeight: "700", color: ui.destructiveText }}>{t("problemsChip", { count: problemCount })}</Text>
        </Pressable>
      ) : null}
      {consentChip ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={consentChip.label}
          accessibilityHint={consentChip.onPress ? t("consentChipChangeHint") : undefined}
          accessibilityState={{ disabled: !consentChip.onPress }}
          testID="consent-chip"
          disabled={!consentChip.onPress || disabled}
          onPress={consentChip.onPress}
          style={{ minHeight: 36, paddingHorizontal: spacing.sm, borderRadius: radius.lg * 2, borderWidth: 1, borderColor: consentChip.decision === "granted" ? ui.success : consentChip.decision === "refused" ? ui.destructiveText : ui.warningText, justifyContent: "center" }}
        >
          <Text numberOfLines={1} style={{ ...typography.caption, fontWeight: "700", color: ui.foreground }}>{consentChip.label}</Text>
        </Pressable>
      ) : null}
      <View accessible accessibilityLabel={state} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xxs }}>
        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: dot }} />
        {problemCount > 0 || consentChip ? null : <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{state}</Text>}
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={t("moreActions")} disabled={disabled} onPress={() => setOpen(true)} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: 22, color: ui.foreground }}>⋮</Text>
      </Pressable>
      <Sheet visible={open} items={menuItems} onClose={() => setOpen(false)} />
    </View>
  );
}
