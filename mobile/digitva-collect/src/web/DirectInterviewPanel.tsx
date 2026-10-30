import { useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import type { IntakeBootstrap } from "../client/api";
import { t } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button } from "../ui";

/** One place a direct interview can start: a project site, narrowed to one unit when the site has several. */
export type DirectInterviewTarget = {
  key: string;
  projectId: string;
  projectName: string;
  siteId: string;
  orgUnitId?: string;
  label: string;
};

/**
 * Expand the intake context into startable targets with the same rules the
 * old per-unit buttons used: direct/both sites only, selectable units only,
 * one target per unit when a site has several, otherwise one per site.
 */
export function directInterviewTargets(context: IntakeBootstrap["context"]): DirectInterviewTarget[] {
  return context
    .filter((entry) => entry.web_intake_mode === "direct" || entry.web_intake_mode === "both")
    .flatMap((entry) => {
      const units = (entry.org_units ?? []).filter((unit) => unit.selectable !== false);
      const base = { projectId: entry.project_id, projectName: entry.project_name ?? entry.project_id, siteId: entry.site_id };
      if (units.length > 1) {
        return units.map((unit) => ({
          ...base,
          key: `${entry.project_id}:${entry.site_id}:${unit.org_unit_id}`,
          orgUnitId: unit.org_unit_id,
          label: unit.unit_name ?? unit.unit_code ?? unit.org_unit_id,
        }));
      }
      return [{
        ...base,
        key: `${entry.project_id}:${entry.site_id}`,
        orgUnitId: units[0]?.org_unit_id,
        label: units[0]?.unit_name ?? entry.site_name ?? entry.site_id,
      }];
    });
}

function usePickerStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    panel: { gap: spacing.sm },
    fieldLabel: { ...typography.subhead, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    field: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm },
    fieldText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    placeholder: { color: colors.textMuted },
    backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
    sheet: { maxHeight: "80%", backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.sm, gap: spacing.xs, width: "100%", maxWidth: controls.contentMaxWidth, alignSelf: "center" },
    option: { flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 48, paddingVertical: spacing.xs, paddingHorizontal: spacing.sm, borderRadius: radius.md },
    optionOn: { backgroundColor: colors.accentSoft },
    optionText: { flex: 1, minWidth: 0, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    iconButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  }), [colors]);
}

/** Icon-only refresh control, drawn like the review queue's refresh button. */
export function RefreshIconButton({ onPress, disabled }: { onPress: () => void; disabled: boolean }) {
  const { colors } = useTheme();
  const s = usePickerStyles();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={t("refresh")} accessibilityState={{ disabled, busy: disabled }} disabled={disabled} onPress={onPress} style={[s.iconButton, disabled && { opacity: 0.5 }]}>
      <Svg width={20} height={20} viewBox="0 0 20 20">
        <Path d="M16 10a6 6 0 1 1-1.8-4.3" stroke={colors.text} strokeWidth={1.8} fill="none" strokeLinecap="round" />
        <Path d="M16.5 3v4h-4" stroke={colors.text} strokeWidth={1.8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

/** Field-like control that opens a bottom sheet of choices, matching the review queue's project picker. */
function SelectField({ label, placeholder, options, value, onSelect }: {
  label: string;
  placeholder: string;
  options: { value: string; label: string }[];
  value?: string;
  onSelect: (value: string) => void;
}) {
  const { colors } = useTheme();
  const s = usePickerStyles();
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text style={s.fieldLabel}>{label}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${selected?.label ?? placeholder}`} accessibilityState={{ expanded: open }} onPress={() => setOpen(true)} style={s.field}>
        <Text numberOfLines={1} ellipsizeMode="tail" style={[s.fieldText, !selected && s.placeholder]}>{selected?.label ?? placeholder}</Text>
        <Svg width={14} height={14} viewBox="0 0 14 14"><Path d="M2 5l5 5 5-5" stroke={colors.text} strokeWidth={1.8} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg>
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={s.backdrop}>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeList")} onPress={() => setOpen(false)} style={StyleSheet.absoluteFill} />
          <View style={s.sheet} accessibilityViewIsModal>
            <ScrollView keyboardDismissMode="on-drag">
              {options.map((option) => {
                const on = option.value === value;
                return (
                  <Pressable key={option.value} accessibilityRole="button" accessibilityLabel={option.label} accessibilityState={{ selected: on }} onPress={() => { setOpen(false); onSelect(option.value); }} style={[s.option, on && s.optionOn]}>
                    <Text style={s.optionText}>{option.label}</Text>
                    {on ? (
                      <Svg width={16} height={16} viewBox="0 0 16 16"><Path d="M3 8.5l3.5 3.5L13 4.5" stroke={colors.accent} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg>
                    ) : <View style={{ width: 16 }} />}
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/**
 * Inline chooser for a direct VA interview: project, then site or unit within
 * it. A single choice is picked automatically; Start stays disabled until both
 * are known.
 */
export function DirectInterviewPanel({ targets, onStart }: { targets: DirectInterviewTarget[]; onStart: (target: DirectInterviewTarget) => void }) {
  const s = usePickerStyles();
  const [chosenProject, setChosenProject] = useState<string>();
  const [chosenTarget, setChosenTarget] = useState<string>();
  const projects = useMemo(() => {
    const byId = new Map<string, string>();
    for (const target of targets) if (!byId.has(target.projectId)) byId.set(target.projectId, target.projectName);
    return Array.from(byId, ([value, label]) => ({ value, label }));
  }, [targets]);
  const projectId = projects.some((project) => project.value === chosenProject)
    ? chosenProject
    : projects.length === 1 ? projects[0].value : undefined;
  const places = targets.filter((target) => target.projectId === projectId);
  const target = places.find((place) => place.key === chosenTarget) ?? (places.length === 1 ? places[0] : undefined);
  return (
    <View style={s.panel}>
      <SelectField
        label={t("interviewProject")}
        placeholder={t("chooseProject")}
        options={projects}
        value={projectId}
        onSelect={(next) => { setChosenProject(next); setChosenTarget(undefined); }}
      />
      {projectId ? (
        <SelectField
          label={t("interviewPlace")}
          placeholder={t("choosePlace")}
          options={places.map((place) => ({ value: place.key, label: place.label }))}
          value={target?.key}
          onSelect={setChosenTarget}
        />
      ) : null}
      <Button label={t("startInterview")} disabled={!target} onPress={() => { if (target) onStart(target); }} />
    </View>
  );
}
