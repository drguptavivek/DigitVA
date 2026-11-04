import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { t } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Chevron } from "../web/Chevron";
import { toggleProject } from "../web/stats/view";

export type ProjectChoice = { id: string; name: string };

/** Width at which the menu drops below the button instead of rising as a bottom sheet (the filter panel's breakpoint). */
const WIDE = 768;
const MENU_WIDTH = 280;

function useSelectStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    field: {
      flexDirection: "row", alignItems: "center", gap: spacing.xs, flexShrink: 1, minHeight: controls.minTouchTarget, maxWidth: 320,
      borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm,
    },
    fieldText: { flexShrink: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    plain: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily, minHeight: controls.minTouchTarget, textAlignVertical: "center", lineHeight: controls.minTouchTarget },
    backdropSheet: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
    backdropMenu: { flex: 1 },
    sheet: {
      maxHeight: "80%", width: "100%", maxWidth: controls.contentMaxWidth, alignSelf: "center", padding: spacing.sm, gap: spacing.xs,
      backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
    },
    menu: {
      position: "absolute", width: MENU_WIDTH, maxHeight: 400, padding: spacing.xxs,
      backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    },
    option: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: controls.minTouchTarget, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.md },
    optionOn: { backgroundColor: colors.accentSoft },
    optionText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    box: { width: 20, height: 20, borderRadius: radius.sm, borderWidth: 2, alignItems: "center", justifyContent: "center" },
  }), [colors]);
}

function CheckMark({ color }: { color: string }) {
  return <Svg width={16} height={16} viewBox="0 0 16 16"><Path d="M3 8.5l3.5 3.5L13 4.5" stroke={color} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg>;
}

/** The field's text: "All projects", the one project's name, or "N projects". */
export function projectSummary(projects: ProjectChoice[], value: string[]): string {
  if (value.length === 0) return t("filterAllProjects");
  if (value.length === 1) return projects.find((project) => project.id === value[0])?.name ?? value[0];
  return t("projectSelectCount", { count: value.length });
}

/**
 * The project control every case screen shares on its top line (Collection, Coding, Reviewing, Statistics): a
 * field-like button "Project: …" opening a menu anchored below it on a wide screen, a bottom sheet on a narrow one.
 * The menu lists All projects, then each project. *value* empty means All. Single choice (the default) closes on a
 * press and reports `[]` or `[id]`; *multiple* keeps the menu open and reports the next set (from All a press narrows
 * to that project; every project, or none, is All). One project is plain text; no project renders nothing.
 */
export function ProjectSelect({ projects, value, onChange, multiple = false, disabled = false }: {
  projects: ProjectChoice[];
  value: string[];
  onChange: (next: string[]) => void;
  multiple?: boolean;
  disabled?: boolean;
}) {
  const s = useSelectStyles();
  const { colors } = useTheme();
  const { width } = useWindowDimensions();
  const wide = width >= WIDE;
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<{ top: number; right: number } | null>(null);
  const button = useRef<View>(null);
  const wasOpen = useRef(false);
  // Focus returns to the button once the menu has closed (while it is open the modal holds focus).
  useEffect(() => {
    if (wasOpen.current && !open) (button.current as unknown as { focus?: () => void } | null)?.focus?.();
    wasOpen.current = open;
  }, [open]);

  if (projects.length === 0) return null;
  const field = `${t("filterProject")}: ${projectSummary(projects, value)}`;
  if (projects.length === 1) return <Text style={s.plain}>{`${t("filterProject")}: ${projects[0].name}`}</Text>;

  const show = () => {
    setAnchor(null);
    setOpen(true);
    // Test renderers and some hosts have no layout; the menu then sits at the top right.
    button.current?.measureInWindow?.((x, y, w, h) => setAnchor({ top: y + h + spacing.xxs, right: Math.max(spacing.xs, width - x - w) }));
  };
  const all = value.length === 0;
  const press = (id: string | null) => {
    if (!multiple) {
      setOpen(false);
      onChange(id === null ? [] : [id]);
      return;
    }
    onChange(id === null ? [] : toggleProject(value, id, projects.map((project) => project.id)));
  };
  const row = (key: string, label: string, id: string | null, checked: boolean) => (
    <Pressable
      key={key}
      accessibilityRole={multiple ? "checkbox" : "radio"}
      accessibilityLabel={label}
      accessibilityState={{ checked }}
      onPress={() => press(id)}
      style={[s.option, checked && s.optionOn]}
    >
      {multiple ? (
        <View style={[s.box, { borderColor: checked ? colors.accent : colors.borderStrong, backgroundColor: checked ? colors.accent : colors.surface }]}>
          {checked ? <CheckMark color={colors.surface} /> : null}
        </View>
      ) : null}
      <Text style={s.optionText}>{label}</Text>
      {!multiple ? (checked ? <CheckMark color={colors.accent} /> : <View style={{ width: 16 }} />) : null}
    </Pressable>
  );
  const list = (
    <ScrollView keyboardDismissMode="on-drag" accessibilityRole={multiple ? "list" : "radiogroup"} accessibilityLabel={t("filterProject")}>
      {row("__all__", t("filterAllProjects"), null, all)}
      {projects.map((project) => row(project.id, project.name, project.id, multiple ? all || value.includes(project.id) : value[0] === project.id))}
    </ScrollView>
  );
  return (
    <>
      <Pressable
        ref={button}
        accessibilityRole="button"
        accessibilityLabel={field}
        accessibilityState={{ expanded: open, disabled }}
        disabled={disabled}
        onPress={show}
        style={[s.field, disabled && { opacity: 0.5 }]}
      >
        <Text numberOfLines={1} ellipsizeMode="tail" style={s.fieldText}>{field}</Text>
        <Chevron expanded />
      </Pressable>
      <Modal visible={open} transparent animationType={wide ? "none" : "slide"} onRequestClose={() => setOpen(false)}>
        <View style={wide ? s.backdropMenu : s.backdropSheet}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View
            accessibilityViewIsModal
            style={wide ? [s.menu, anchor ?? { top: spacing.xl, right: spacing.sm }] : s.sheet}
          >
            {list}
          </View>
        </View>
      </Modal>
    </>
  );
}
