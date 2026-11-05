import { Pressable, Text, View } from "react-native";

import { CheckMark } from "../../../ui/controls";
import { font, gap, uiRadius, useUi } from "../ui";

/**
 * One choice of a build axis or of an axis search: a 44 dp row with a check circle. The label may wrap, so the row grows with its text and with the font scale.
 */
export function OptionRow({ children, selected, disabled, accessibilityLabel, onPress }: { children: string; selected: boolean; disabled?: boolean; accessibilityLabel: string; onPress: () => void }) {
  const { t } = useUi();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} accessibilityState={disabled === undefined ? { selected } : { selected, disabled }} disabled={disabled} onPress={onPress}
      style={{ flexDirection: "row", alignItems: "center", gap: gap.sm, minHeight: 44, paddingVertical: gap.xs, paddingHorizontal: gap.sm, borderRadius: uiRadius.md, backgroundColor: selected ? t.accent : "transparent", opacity: disabled ? 0.5 : 1 }}>
      <View style={{ width: 22, height: 22, borderRadius: uiRadius.full, borderWidth: 2, alignItems: "center", justifyContent: "center", borderColor: selected ? t.primary : t.input, backgroundColor: selected ? t.primary : "transparent" }}>
        {selected ? <CheckMark color={t.primaryForeground} size={14} /> : null}
      </View>
      <Text style={{ flexShrink: 1, fontSize: font.title, lineHeight: 24, color: t.foreground }}>{children}</Text>
    </Pressable>
  );
}
