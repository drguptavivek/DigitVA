import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { t } from "../i18n";
import { controls, radius, spacing, useTheme } from "../theme";
import { Chevron } from "../web/Chevron";
import { toggleProject } from "../web/stats/view";

export type ProjectChoice = { id: string; name: string };

const MENU_WIDTH = 280;
const MENU_MAX_HEIGHT = 400;
// Room for about five rows: below a field this tall a menu still reads well, so it opens down rather than over the
// fields above (a mid-screen field opened upward and hid the controls the user had just used).
const MENU_MIN_BELOW = 240;

/**
 * Where a dropdown menu sits, attached to its field at every width: below it when there is room for about five rows
 * (or more room than above), otherwise above it. *field* is its `measureInWindow` box; *side* is the field
 * edge the menu lines up with. The menu is at least as wide as the field, never wider than the window, and kept on screen.
 */
export function anchorMenu(
  field: { x: number; y: number; w: number; h: number },
  win: { width: number; height: number },
  { side, menuWidth, maxHeight = MENU_MAX_HEIGHT }: { side: "left" | "right"; menuWidth: number; maxHeight?: number },
): { top?: number; bottom?: number; left?: number; right?: number; width: number; maxHeight: number } {
  const below = win.height - (field.y + field.h) - spacing.xxs;
  const above = field.y - spacing.xxs;
  const down = below >= above || below >= Math.min(maxHeight, MENU_MIN_BELOW);
  const width = Math.min(Math.max(menuWidth, field.w), win.width - 2 * spacing.xs);
  const edge = side === "left" ? field.x : win.width - field.x - field.w;
  return {
    ...(down ? { top: field.y + field.h + spacing.xxs } : { bottom: win.height - field.y + spacing.xxs }),
    [side]: Math.max(spacing.xs, Math.min(edge, win.width - width - spacing.xs)),
    width,
    maxHeight: Math.min(maxHeight, (down ? below : above) - spacing.xs),
  };
}

export function useSelectStyles() {
  const { colors, typography } = useTheme();
  return useMemo(() => StyleSheet.create({
    field: {
      flexDirection: "row", alignItems: "center", gap: spacing.xs, flexShrink: 1, minHeight: controls.minTouchTarget, maxWidth: 320,
      borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm,
    },
    fieldText: { flexShrink: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    plain: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily, minHeight: controls.minTouchTarget, textAlignVertical: "center", lineHeight: controls.minTouchTarget },
    backdropMenu: { flex: 1 },
    menu: {
      position: "absolute", width: MENU_WIDTH, maxHeight: MENU_MAX_HEIGHT, padding: spacing.xxs,
      backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    },
    option: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: controls.minTouchTarget, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.md },
    optionOn: { backgroundColor: colors.accentSoft },
    optionText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    box: { width: 20, height: 20, borderRadius: radius.sm, borderWidth: 2, alignItems: "center", justifyContent: "center" },
  }), [colors, typography]);
}

export function CheckMark({ color }: { color: string }) {
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
 * field-like button "Project: …" opening a menu attached to it (below, or above when there is no room below).
 * The menu lists All projects, then each project. *value* empty means All. Single choice (the default) closes on a
 * press and reports `[]` or `[id]`; *multiple* keeps the menu open and reports the next set (from All a press narrows
 * to that project; every project, or none, is All). One project still renders the field, its menu listing just that
 * project (no All row: it would mean the same) and closing on a press without a change; no project renders nothing.
 */
export function ProjectSelect({ projects, value, onChange, multiple = false, disabled = false, fieldRow = false }: {
  projects: ProjectChoice[];
  value: string[];
  onChange: (next: string[]) => void;
  multiple?: boolean;
  disabled?: boolean;
  /** Phone presentation: the plain project row Home uses (no label, no border); ignored on the web. */
  fieldRow?: boolean;
}) {
  const s = useSelectStyles();
  const { colors, ui, typography } = useTheme();
  const win = useWindowDimensions();
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<ReturnType<typeof anchorMenu> | null>(null);
  const button = useRef<View>(null);
  const wasOpen = useRef(false);
  // Focus returns to the button once the menu has closed (while it is open the modal holds focus).
  useEffect(() => {
    if (wasOpen.current && !open) (button.current as unknown as { focus?: () => void } | null)?.focus?.();
    wasOpen.current = open;
  }, [open]);

  if (projects.length === 0) return null;
  // The web shows the dropdown even for one project (title-row control); the phone keeps its plain line.
  if (projects.length === 1 && Platform.OS !== "web") return <Text style={s.plain}>{`${t("filterProject")}: ${projects[0].name}`}</Text>;
  const field = `${t("filterProject")}: ${projectSummary(projects, projects.length === 1 ? [projects[0].id] : value)}`;

  const show = () => {
    setAnchor(null);
    setOpen(true);
    // Test renderers and some hosts have no layout; the menu then sits at the top right.
    button.current?.measureInWindow?.((x, y, w, h) => setAnchor(anchorMenu({ x, y, w, h }, win, { side: "right", menuWidth: MENU_WIDTH })));
  };
  const all = value.length === 0;
  const single = projects.length === 1;
  const press = (id: string | null) => {
    if (single) {
      setOpen(false);
      return;
    }
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
      {single ? null : row("__all__", t("filterAllProjects"), null, all)}
      {projects.map((project) => row(project.id, project.name, project.id, single || (multiple ? all || value.includes(project.id) : value[0] === project.id)))}
    </ScrollView>
  );
  const phoneRow = fieldRow && Platform.OS !== "web";
  const trigger = phoneRow ? (
    // The plain row Home's project line uses (ProjectLine in nativeRoutes/worklistParts): no label, no border.
    <Pressable
      ref={button}
      accessibilityRole="button"
      accessibilityLabel={field}
      accessibilityState={{ expanded: open, disabled }}
      disabled={disabled}
      onPress={show}
      style={[{ minHeight: controls.minTouchTarget, justifyContent: "center" }, disabled && { opacity: 0.5 }]}
    >
      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xxs }}>
        <Text numberOfLines={1} style={{ ...typography.subhead, color: ui.mutedForeground, flexShrink: 1 }}>{projectSummary(projects, value)}</Text>
        <Chevron expanded size={18} color={ui.mutedForeground} />
      </View>
    </Pressable>
  ) : (
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
  );
  return (
    <>
      {trigger}
      <Modal visible={open} transparent animationType="none" onRequestClose={() => setOpen(false)}>
        <View style={s.backdropMenu}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View
            accessibilityViewIsModal
            style={[s.menu, anchor ?? { top: spacing.xl, right: spacing.sm }]}
          >
            {list}
          </View>
        </View>
      </Modal>
    </>
  );
}
