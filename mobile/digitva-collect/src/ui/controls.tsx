/**
 * Shared vector marks and small controls: one tick, one ✕, one checkbox, one menu choice row and one removable chip,
 * so no screen draws a state with a text glyph ("✓", "×", "•") whose size and centre depend on the font.
 */
import type { ReactNode } from "react";
import { Pressable, Text, View, type StyleProp, type TextStyle, type ViewStyle } from "react-native";
import Svg, { Path } from "react-native-svg";

import { controls, radius, spacing, useTheme } from "../theme";

/** Tabler "check" and "x"; also drawn as raw `<svg>` by the DOM-built account menu. */
export const CHECK_PATH = "M5 12l5 5l10 -10";
export const X_PATH = "M18 6l-12 12M6 6l12 12";

/** Decorative tick in `color`; the state it shows is announced by the control that holds it. */
export function CheckMark({ color, size = 16, strokeWidth = 3 }: { color: string; size?: number; strokeWidth?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <Path d={CHECK_PATH} stroke={color} strokeWidth={strokeWidth} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}

export function XMark({ color, size = 14, strokeWidth = 2.5 }: { color: string; size?: number; strokeWidth?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      <Path d={X_PATH} stroke={color} strokeWidth={strokeWidth} fill="none" strokeLinecap="round" />
    </Svg>
  );
}

/** The 20px box of a checkbox: input-coloured edge, brand fill and a white tick when checked. */
export function CheckboxBox({ checked, disabled = false }: { checked: boolean; disabled?: boolean }) {
  const { ui } = useTheme();
  const edge = disabled ? ui.disabled : checked ? ui.primary : ui.input;
  return (
    <View aria-hidden style={{ width: 20, height: 20, borderRadius: radius.sm, borderWidth: 2, borderColor: edge, backgroundColor: checked ? edge : ui.background, alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      {checked ? <CheckMark color={ui.primaryForeground} size={14} /> : null}
    </View>
  );
}

/**
 * A checkbox with role and checked state and a 44px target. `label` is drawn beside the box, or only announced
 * when `hideLabel` (a table cell whose column header names it).
 */
export function Checkbox({ checked, onChange, label, hideLabel = false, disabled = false, testID, style }: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hideLabel?: boolean;
  disabled?: boolean;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const { ui, typography } = useTheme();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityLabel={label}
      accessibilityState={{ checked, disabled }}
      aria-checked={checked}
      disabled={disabled}
      testID={testID}
      onPress={() => onChange(!checked)}
      style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: controls.minTouchTarget, minWidth: controls.minTouchTarget, justifyContent: hideLabel ? "center" : "flex-start", opacity: pressed ? 0.78 : 1 }, style]}
    >
      <CheckboxBox checked={checked} disabled={disabled} />
      {hideLabel ? null : <Text style={{ ...typography.body, color: disabled ? ui.disabled : ui.foreground, flexShrink: 1 }}>{label}</Text>}
    </Pressable>
  );
}

/**
 * One single-choice row of a popover menu (language, theme): label left, tick right, brand-soft fill when chosen.
 * `detail`: a secondary line under the label in the screen's language ("Machine-translated").
 */
export function MenuChoiceRow({ label, language, detail, selected, onPress, disabled = false, role = "radio" }: {
  label: string;
  /** BCP 47 tag of a label in another language than the screen's (the "हिन्दी" choice), so it is pronounced right. */
  language?: string;
  detail?: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
  role?: "radio" | "menuitem";
}) {
  const { ui, typography } = useTheme();
  return (
    <Pressable
      accessibilityRole={role}
      accessibilityLabel={label}
      accessibilityLanguage={language}
      // The detail is in the screen's language, so it is the hint, not part of the label read in `language`.
      accessibilityHint={detail}
      accessibilityState={role === "radio" ? { checked: selected, disabled } : { selected, disabled }}
      aria-checked={role === "radio" ? selected : undefined}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({ minHeight: 48, borderRadius: radius.md, paddingHorizontal: spacing.sm, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md, backgroundColor: selected ? ui.accent : "transparent", opacity: pressed ? 0.78 : 1 })}
    >
      <View style={{ flexShrink: 1 }}>
        <Text style={{ ...typography.body, color: selected ? ui.accentForeground : ui.popoverForeground, fontWeight: selected ? "700" : "400" }}>{label}</Text>
        {detail ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{detail}</Text> : null}
      </View>
      <View style={{ width: 20, alignItems: "center" }}>{selected ? <CheckMark color={ui.primary} size={18} /> : null}</View>
    </Pressable>
  );
}

/**
 * An applied value the user can drop (a filter, a chosen condition): the whole chip is one button, drawn 36px tall
 * and reached at 44px through hit-slop, with a vector ✕ after the text.
 */
export function RemovableChip({ label, removeLabel, onRemove, testID }: { label: string; removeLabel: string; onRemove: () => void; testID?: string }) {
  const { ui, typography } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={removeLabel}
      testID={testID}
      hitSlop={4}
      onPress={onRemove}
      style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 36, maxWidth: "100%", paddingLeft: spacing.sm, paddingRight: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: ui.input, backgroundColor: pressed ? ui.accent : ui.secondary })}
    >
      <Text numberOfLines={1} style={{ ...typography.subhead, color: ui.secondaryForeground, flexShrink: 1 }}>{label}</Text>
      <View style={{ width: 20, height: 20, alignItems: "center", justifyContent: "center" }}><XMark color={ui.mutedForeground} /></View>
    </Pressable>
  );
}

/** One bullet-list item: a 6px dot beside text that wraps under itself (a typed "• " would wrap under the dot). */
export function BulletItem({ children, textStyle, muted = false }: { children: ReactNode; textStyle?: StyleProp<TextStyle>; muted?: boolean }) {
  const { ui, typography } = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-start", gap: spacing.xs }}>
      <View aria-hidden style={{ width: 6, height: 6, borderRadius: 3, marginTop: 8, backgroundColor: ui.mutedForeground, flexShrink: 0 }} />
      <Text style={[{ ...typography.body, color: muted ? ui.mutedForeground : ui.foreground }, textStyle, { flexShrink: 1 }]}>{children}</Text>
    </View>
  );
}
