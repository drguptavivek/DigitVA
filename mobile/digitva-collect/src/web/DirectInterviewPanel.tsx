import { useMemo, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import type { AccessProject } from "../api";
import type { Target } from "../sync";
import { t } from "../i18n";
import { radius, spacing, useTheme } from "../theme";
import { Button, FieldLabel } from "../ui";
import { Select } from "../ui/Select";
import { placeOptions } from "./placeOptions";

function usePickerStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    panel: { gap: spacing.sm },
    iconButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  }), [colors]);
}

/** Icon-only refresh control, drawn like the review queue's refresh button. */
export function RefreshIconButton({ onPress, disabled }: { onPress: () => void; disabled: boolean }) {
  const { colors } = useTheme();
  const s = usePickerStyles();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={t("refresh")} accessibilityState={{ disabled, busy: disabled }} disabled={disabled} onPress={onPress} style={[s.iconButton, disabled && { opacity: 0.5 }]}>
      {/* Tabler "refresh": two arrows round a circle, like the chevrons (Chevron.tsx). */}
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <Path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

/**
 * Inline chooser for a direct VA interview: one "Site and unit" dropdown of the places the user may start in (the page's
 * Project has already narrowed *targets*). A single choice is picked automatically; Start stays disabled until one is known.
 */
export function DirectInterviewPanel({ targets, projects, onStart }: {
  targets: Target[];
  projects: AccessProject[];
  onStart: (target: Target) => void;
}) {
  const s = usePickerStyles();
  const [chosen, setChosen] = useState<string>();
  const choices = useMemo(() => placeOptions(targets, projects), [targets, projects]);
  // "One choice" counts what the user sees (placeholder-named sites are not offered).
  const key = choices.some((choice) => choice.value === chosen) ? chosen : choices.length === 1 ? choices[0].value : undefined;
  const target = targets.find((entry) => entry.key === key);
  return (
    <View style={s.panel}>
      {/* The same visible label as the Add a Death form's place field. */}
      <View style={{ gap: spacing.xxs }}>
      <FieldLabel label={t("chooseSite")} />
      <Select
        label={t("chooseSite")}
        placeholder={t("siteUnitNotChosen")}
        searchLabel={t("filterUnitSearch")}
        searchable
        options={choices}
        value={key ?? ""}
        onChange={setChosen}
      />
      </View>
      <Button label={t("startInterview")} disabled={!target} onPress={() => { if (target) onStart(target); }} />
    </View>
  );
}
