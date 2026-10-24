import { createElement, useState, type ReactNode } from "react";
import { Platform, Pressable, Text, View, type StyleProp, type ViewStyle } from "react-native";

import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";

/** A pressable with the app's visible web focus ring; the one place the stats pieces draw it. */
export function StatPressable({ label, onPress, selected, style, children }: {
  label: string;
  onPress: () => void;
  selected?: boolean;
  style?: StyleProp<ViewStyle>;
  children: ReactNode;
}) {
  const { ui } = useTheme();
  const [focused, setFocused] = useState(false);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={selected === undefined ? undefined : { selected }}
      onPress={onPress}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={({ pressed }) => [
        { opacity: pressed ? 0.85 : 1 },
        style,
        focused && Platform.OS === "web" && ({ outlineStyle: "solid", outlineWidth: 2, outlineColor: ui.ring, outlineOffset: 2 } as ViewStyle),
      ]}
    >
      {children}
    </Pressable>
  );
}

/** One choice among a few, laid out in a wrapping row (project, period). The chosen one is filled. */
export function ChoiceRow<T extends string>({ label, options, value, onChange }: {
  label: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (next: T) => void;
}) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{label}</Text>
      <View accessibilityRole="toolbar" accessibilityLabel={label} style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
        {options.map((option) => {
          const chosen = option.value === value;
          return (
            <StatPressable
              key={option.value}
              label={option.label}
              selected={chosen}
              onPress={() => onChange(option.value)}
              style={{
                minHeight: 44,
                maxWidth: "100%",
                justifyContent: "center",
                paddingVertical: spacing.xxs,
                paddingHorizontal: spacing.sm,
                borderRadius: radius.md,
                borderWidth: 1,
                borderColor: chosen ? ui.primary : ui.input,
                backgroundColor: chosen ? ui.accent : ui.background,
              }}
            >
              <Text style={{ flexShrink: 1, fontSize: fontSize.body, fontWeight: chosen ? "600" : "400", color: chosen ? ui.accentForeground : ui.foreground }}>{option.label}</Text>
            </StatPressable>
          );
        })}
      </View>
    </View>
  );
}

/** One choice among many: the browser's own select (web only; this screen is web only), for long project lists. */
export function SelectRow<T extends string>({ label, options, value, onChange }: {
  label: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (next: T) => void;
}) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{label}</Text>
      {createElement(
        "select",
        {
          "aria-label": label,
          value: value ?? "",
          onChange: (event: { target: { value: string } }) => onChange(event.target.value as T),
          style: {
            boxSizing: "border-box", width: "100%", maxWidth: 480, minHeight: 44, padding: `0 ${spacing.sm}px`, fontSize: fontSize.body,
            fontFamily: controls.fontFamily, color: ui.foreground, background: ui.background, border: `1px solid ${ui.input}`, borderRadius: radius.md,
          },
        },
        ...options.map((option) => createElement("option", { key: option.value, value: option.value }, option.label)),
      )}
    </View>
  );
}

/** A plain underlined-looking text action (links to other screens, download). `small` is for a link inside a row. */
export function TextAction({ label, onPress, small }: { label: string; onPress: () => void; small?: boolean }) {
  const { ui } = useTheme();
  return (
    <StatPressable label={label} onPress={onPress} style={{ minHeight: small ? 32 : 44, justifyContent: "center", alignSelf: "flex-start" }}>
      <Text style={{ fontSize: small ? fontSize.caption : fontSize.body, color: ui.primary, textDecorationLine: "underline" }}>{label}</Text>
    </StatPressable>
  );
}
