/**
 * The one compact top bar of the immersive form screens (interview and revision): back, a truncating title,
 * a save-state dot and an overflow menu. `Sheet` is the bottom list also used for the revision reason select.
 */
import { useState } from "react";
import { Modal, Pressable, Text, View } from "react-native";

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

/** A bottom sheet of choices; choosing one closes the sheet, then calls its handler. */
export function Sheet({ visible, title, items, onClose }: { visible: boolean; title?: string; items: SheetItem[]; onClose(): void }) {
  const { ui } = useTheme();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable accessibilityLabel={t("cancel")} onPress={onClose} style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}>
        <View style={{ backgroundColor: ui.popover, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, paddingBottom: spacing.lg }}>
          {title ? <Text style={{ ...typography.subhead, color: ui.mutedForeground, padding: spacing.md }}>{title}</Text> : null}
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
        </View>
      </Pressable>
    </Modal>
  );
}

const SAVE_LABEL = { saved: "saveStateSaved", saving: "saveStateSaving", unsaved: "saveStateUnsaved" } as const;

export function FormTopBar({
  title,
  saveState,
  onBack,
  menuItems,
  disabled
}: {
  title: string;
  saveState: SaveState;
  onBack(): void;
  menuItems: SheetItem[];
  disabled?: boolean;
}) {
  const { ui } = useTheme();
  const [open, setOpen] = useState(false);
  const dot = saveState === "saved" ? ui.success : saveState === "saving" ? ui.warningText : ui.destructiveText;
  const state = t(SAVE_LABEL[saveState]);
  return (
    <View style={{ height: BAR_HEIGHT, flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xs, gap: spacing.xs, borderBottomWidth: 1, borderColor: ui.border, backgroundColor: ui.background }}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("back")} disabled={disabled} onPress={onBack} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: 22, color: ui.foreground }}>‹</Text>
      </Pressable>
      <Text numberOfLines={1} accessibilityRole="header" style={{ flex: 1, ...typography.headline, color: ui.foreground }}>
        {title}
      </Text>
      <View accessible accessibilityLabel={state} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xxs }}>
        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: dot }} />
        <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{state}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={t("moreActions")} disabled={disabled} onPress={() => setOpen(true)} style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}>
        <Text style={{ fontSize: 22, color: ui.foreground }}>⋮</Text>
      </Pressable>
      <Sheet visible={open} items={menuItems} onClose={() => setOpen(false)} />
    </View>
  );
}
