import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import { t } from "../i18n";
import { controls, radius, spacing, useTheme } from "../theme";
import { Chevron } from "../web/Chevron";
import { anchorMenu, CheckMark, useSelectStyles } from "./ProjectSelect";
import { RevealFieldContext } from "./revealField";

/** *detail* is an optional muted second line (e.g. a unit's ancestors); search matches it too. */
export type SelectOption = { value: string; label: string; detail?: string };

const named = (option: SelectOption) => (option.detail ? `${option.label}, ${option.detail}` : option.label);

const MENU_WIDTH = 360;
const LIST_MAX_HEIGHT = 320;

/**
 * A compact single-choice dropdown: a field-like button (current label or *placeholder*) opening a menu attached
 * to it (below, or above when there is no room below). The option list scrolls at a capped height. *searchable*
 * adds a box filtering options by a case-insensitive substring of the label or detail. Closes on a choice, the backdrop or back;
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
  const win = useWindowDimensions();
  const { width } = win;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [anchor, setAnchor] = useState<ReturnType<typeof anchorMenu> | null>(null);
  const button = useRef<View>(null);
  const reveal = useContext(RevealFieldContext);
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
    // Fills the field so the chevron sits at its right edge when there is no detail line.
    fieldGrow: { flexGrow: 1 },
    detail: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    menu: { width: Math.min(MENU_WIDTH, Math.max(0, width - 2 * spacing.xs)) },
  }), [colors, typography, width]);

  const selected = options.find((option) => option.value === value);
  const needle = query.trim().toLowerCase();
  const shown = needle ? options.filter((option) => `${option.label} ${option.detail ?? ""}`.toLowerCase().includes(needle)) : options;

  const show = () => {
    setAnchor(null);
    setQuery("");
    setOpen(true);
    const place = () => {
      // Test renderers and some hosts have no layout; the menu then sits at the top left.
      button.current?.measureInWindow?.((x, y, w, h) => setAnchor(anchorMenu({ x, y, w, h }, win, { side: "left", menuWidth: MENU_WIDTH })));
    };
    // Inside a scroll area that offers it, bring the field to the top first so the menu (and the keyboard the search box raises) has room below it.
    if (reveal && button.current) reveal(button.current, place);
    else place();
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
        accessibilityLabel={selected ? `${label}: ${named(selected)}` : label}
        accessibilityState={{ expanded: open }}
        onPress={show}
        style={[s.field, { maxWidth: "100%", alignSelf: "stretch" }]}
      >
        {selected?.detail ? (
          // The chosen name, its detail (a unit's lineage) on a muted line underneath.
          <View style={{ flex: 1, flexShrink: 1 }}>
            <Text numberOfLines={1} ellipsizeMode="tail" style={s.fieldText}>{selected.label}</Text>
            <Text numberOfLines={1} ellipsizeMode="tail" style={extra.detail}>{selected.detail}</Text>
          </View>
        ) : (
          <Text numberOfLines={1} ellipsizeMode="tail" style={[s.fieldText, extra.fieldGrow, !selected && { color: colors.textMuted }]}>
            {selected ? selected.label : placeholder}
          </Text>
        )}
        <Chevron expanded />
      </Pressable>
      <Modal visible={open} transparent animationType="none" onRequestClose={() => setOpen(false)}>
        <View style={s.backdropMenu}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View accessibilityViewIsModal style={[s.menu, extra.menu, anchor ?? { top: spacing.xl, left: spacing.sm }]}>
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
            <ScrollView style={{ maxHeight: LIST_MAX_HEIGHT, flexShrink: 1 }} keyboardShouldPersistTaps="handled" accessibilityRole="radiogroup" accessibilityLabel={label}>
              {shown.length === 0 ? <Text style={extra.none}>{t("pickerNoMatch")}</Text> : null}
              {shown.map((option) => {
                const checked = option.value === value;
                return (
                  <Pressable
                    key={option.value}
                    accessibilityRole="radio"
                    accessibilityLabel={named(option)}
                    accessibilityState={{ checked }}
                    onPress={() => pick(option.value)}
                    style={[s.option, checked && s.optionOn]}
                  >
                    {option.detail ? (
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={[s.optionText, { flex: 0 }]}>{option.label}</Text>
                        <Text style={extra.detail}>{option.detail}</Text>
                      </View>
                    ) : <Text style={s.optionText}>{option.label}</Text>}
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
