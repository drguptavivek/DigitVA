/**
 * A full-height bottom sheet with a search box and a virtualised list of 52dp rows: the site/unit picker and
 * the project chooser. The caller supplies `build(query)` (so grouping and matching stay pure and testable);
 * the sheet only lays rows out and never keeps a selection of its own.
 */
import { useMemo, useState } from "react";
import { FlatList, Pressable, Text, TextInput, View } from "react-native";

import { t } from "../i18n";
import { BottomSheet } from "../nativeShell/BottomSheet";
import { controls, radius, spacing, typography, useTheme } from "../theme";

export interface ChoiceRow { key: string; label: string; selected?: boolean; onPick(): void }
export interface ChoiceSection { key: string; title?: string; rows: ChoiceRow[] }
export interface ChoiceList { recent?: ChoiceRow; sections: ChoiceSection[] }

type Entry = { kind: "cap"; key: string; text: string } | { kind: "row"; key: string; row: ChoiceRow };

/** Mounted only while open, so a closed sheet costs nothing and its search box starts empty next time. */
export function ChoiceSheet(props: { visible: boolean; title: string; searchLabel: string; onClose(): void; build(query: string): ChoiceList }) {
  return props.visible ? <OpenChoiceSheet {...props} /> : null;
}

function OpenChoiceSheet({ visible, title, searchLabel, onClose, build }: {
  visible: boolean; title: string; searchLabel: string; onClose(): void; build(query: string): ChoiceList;
}) {
  const { ui } = useTheme();
  const [query, setQuery] = useState("");
  const entries = useMemo<Entry[]>(() => {
    const list = build(query);
    const out: Entry[] = [];
    // "Recent" is a shortcut for browsing; a search shows only matches.
    if (list.recent && !query.trim()) out.push({ kind: "cap", key: "cap-recent", text: t("pickerRecent") }, { kind: "row", key: `recent-${list.recent.key}`, row: { ...list.recent, selected: true } });
    for (const section of list.sections) {
      if (section.rows.length === 0) continue;
      if (section.title) out.push({ kind: "cap", key: `cap-${section.key}`, text: section.title });
      for (const row of section.rows) out.push({ kind: "row", key: `${section.key}-${row.key}`, row });
    }
    return out;
  }, [query, build]);
  return (
    <BottomSheet visible={visible} title={title} onClose={onClose} full>
      <TextInput
        accessibilityLabel={searchLabel}
        placeholder={searchLabel}
        placeholderTextColor={ui.mutedForeground}
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        style={{ minHeight: 48, borderWidth: 1, borderColor: ui.input, borderRadius: radius.md, paddingHorizontal: spacing.sm, ...typography.body, color: ui.foreground, backgroundColor: ui.background }}
      />
      <FlatList
        data={entries}
        keyExtractor={(entry) => entry.key}
        keyboardShouldPersistTaps="handled"
        ListEmptyComponent={<Text style={{ ...typography.body, color: ui.mutedForeground, paddingVertical: spacing.md }}>{t("pickerNoMatch")}</Text>}
        renderItem={({ item }) =>
          item.kind === "cap" ? (
            <Text accessibilityRole="header" style={{ ...typography.caption, fontWeight: "600", textTransform: "uppercase", color: ui.mutedForeground, marginTop: spacing.xs }}>{item.text}</Text>
          ) : (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={item.row.label}
              accessibilityState={{ selected: Boolean(item.row.selected) }}
              onPress={item.row.onPick}
              style={{ height: 52, justifyContent: "center", borderBottomWidth: 1, borderBottomColor: ui.border, minWidth: controls.minTouchTarget }}
            >
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                <Text numberOfLines={1} style={{ ...typography.body, color: ui.popoverForeground, flex: 1 }}>{item.row.label}</Text>
                {item.row.selected ? <Text accessibilityElementsHidden style={{ ...typography.body, color: ui.primary }}>✓</Text> : null}
              </View>
            </Pressable>
          )
        }
      />
    </BottomSheet>
  );
}
