import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import { t } from "../i18n";
import { controls, radius, spacing, useTheme } from "../theme";
import { Chevron } from "../web/Chevron";
import { CheckMark, useSelectStyles } from "./ProjectSelect";

export type SelectOption = { value: string; label: string };

/** Width at which the menu drops below the field instead of rising as a bottom sheet (ProjectSelect's breakpoint). */
const WIDE = 768;
const MENU_WIDTH = 360;
const LIST_MAX_HEIGHT = 320;

/**
 * A compact single-choice dropdown: a field-like button (current label or *placeholder*) opening a menu anchored
 * below it on a wide window, a bottom sheet on a narrow one. The option list scrolls at a capped height. *searchable*
 * adds a box filtering options by a case-insensitive substring of the label. Closes on a choice, the backdrop or back;
 * focus returns to the field. *label* is the field's accessibility label.
 */
export function Select({ label, placeholder, options, value, onChange, searchable = false, searchLabel, testID }: {
  label: string;
  placeholder: string;
  options: SelectOption[];
  value: string;
  onChange: (next: string) => void;
  searchable?: boolean;
  searchLabel?: string;
  testID?: string;
}) {
  const s = useSelectStyles();
  const { colors, typography } = useTheme();
  const { width } = useWindowDimensions();
  const wide = width >= WIDE;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<View>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) (button.current as unknown as { focus?: () => void } | null)?.focus?.();
    wasOpen.current = open;
  }, [open]);

  const extra = useMemo(() => StyleSheet.create({
    search: {
      minHeight: controls.minTouchTarget, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md,
      backgroundColor: colors.surface, paddingHorizontal: spacing.sm, color: colors.text, ...typography.subhead, fontFamily: controls.fontFamily,
    },
    none: { padding: spacing.sm, ...typography.subhead, color: colors.textMuted, fontFamily: controls.fontFamily },
    menu: { width: Math.min(MENU_WIDTH, Math.max(0, width - 2 * spacing.xs)) },
  }), [colors, typography, width]);

  const selected = options.find((option) => option.value === value);
  const needle = query.trim().toLowerCase();
  const shown = needle ? options.filter((option) => option.label.toLowerCase().includes(needle)) : options;

  const show = () => {
    setAnchor(null);
    setQuery("");
    setOpen(true);
    // Test renderers and some hosts have no layout; the menu then sits at the top left.
    button.current?.measureInWindow?.((x, y, w, h) => setAnchor({ top: y + h + spacing.xxs, left: Math.max(spacing.xs, Math.min(x, width - MENU_WIDTH - spacing.xs)) }));
  };
  const pick = (next: string) => {
    setOpen(false);
    onChange(next);
  };
  return (
    <>
      <Pressable
        ref={button}
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={selected ? `${label}: ${selected.label}` : label}
        accessibilityState={{ expanded: open }}
        onPress={show}
        style={[s.field, { maxWidth: "100%", alignSelf: "stretch" }]}
      >
        <Text numberOfLines={1} ellipsizeMode="tail" style={[s.fieldText, !selected && { color: colors.textMuted }]}>{selected ? selected.label : placeholder}</Text>
        <Chevron expanded />
      </Pressable>
      <Modal visible={open} transparent animationType={wide ? "none" : "slide"} onRequestClose={() => setOpen(false)}>
        <View style={wide ? s.backdropMenu : s.backdropSheet}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View accessibilityViewIsModal style={wide ? [s.menu, extra.menu, anchor ?? { top: spacing.xl, left: spacing.sm }] : s.sheet}>
            {searchable ? (
              <TextInput
                accessibilityLabel={searchLabel ?? label}
                placeholder={searchLabel ?? label}
                placeholderTextColor={colors.textMuted}
                value={query}
                onChangeText={setQuery}
                autoFocus
                style={extra.search}
              />
            ) : null}
            <ScrollView style={{ maxHeight: LIST_MAX_HEIGHT }} keyboardShouldPersistTaps="handled" accessibilityRole="radiogroup" accessibilityLabel={label}>
              {shown.length === 0 ? <Text style={extra.none}>{t("pickerNoMatch")}</Text> : null}
              {shown.map((option) => {
                const checked = option.value === value;
                return (
                  <Pressable
                    key={option.value}
                    accessibilityRole="radio"
                    accessibilityLabel={option.label}
                    accessibilityState={{ checked }}
                    onPress={() => pick(option.value)}
                    style={[s.option, checked && s.optionOn]}
                  >
                    <Text style={s.optionText}>{option.label}</Text>
                    {checked ? <CheckMark color={colors.accent} /> : <View style={{ width: 16 }} />}
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}
