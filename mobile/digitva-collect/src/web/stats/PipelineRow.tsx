import { Text, View } from "react-native";

import type { AreaRow } from "../../area/api";
import { t } from "../../i18n";
import { fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { StatPressable, TextAction } from "./controls";
import { stageWidths } from "./pipeline";

/**
 * One unit as a proportional bar: deaths reported (widest, lightest), interviews received, coded (darkest).
 * Widths are percentages of *scale*, shared by every row, so units compare by eye. The numbers are always written
 * under the bar, never carried by the bar alone. Backlog and SmartVA failures are quiet text, only when non-zero.
 * A row is a button when *onOpen* is given (a unit or site that opens). *showReported* is false for a project with no
 * death register: the reported stage and its legend entry are left out. *link* is the server link of the interviews
 * count shown on this row (the row's other links name counts the row does not show, so they are left out); it sits
 * beside the open button, never inside it.
 */
export function PipelineRow({ row, scale, showReported = true, onOpen, link }: {
  row: AreaRow; scale: number; showReported?: boolean; onOpen?: () => void; link?: { label: string; onPress: () => void };
}) {
  const { ui } = useTheme();
  const { counts } = row;
  const widths = stageWidths(counts, scale);
  const stages = [
    ...(showReported ? [{ key: "reported", colour: ui.border, width: widths.reported, text: t("statsReported", { count: counts.deaths_reported }) }] : []),
    { key: "interviewed", colour: ui.mutedForeground, width: widths.interviewed, text: t("statsInterviewed", { count: counts.submitted }) },
    { key: "coded", colour: ui.primary, width: widths.coded, text: t("statsCoded", { count: counts.final_cod }) },
  ];
  const flags = [
    counts.pending_over_7_days > 0 ? t("statsPendingOver7", { count: counts.pending_over_7_days }) : "",
    counts.pending_over_30_days > 0 ? t("statsPendingOver30", { count: counts.pending_over_30_days }) : "",
    counts.smartva_failed > 0 ? t("statsSmartvaFailed", { count: counts.smartva_failed }) : "",
  ].filter(Boolean);
  const spokenKey = `statsRow${onOpen ? "Open" : "Static"}${showReported ? "" : "NoRegister"}` as const;
  const spoken = t(spokenKey, {
    name: row.name, reported: counts.deaths_reported, interviewed: counts.submitted, coded: counts.final_cod,
  });
  const body = (
    <View style={{ gap: spacing.xs }}>
      <Text style={{ ...typography.body, fontWeight: "600", color: ui.foreground }}>{row.name}</Text>
      <View importantForAccessibility="no-hide-descendants" accessibilityElementsHidden style={{ height: 10, borderRadius: radius.sm, backgroundColor: ui.secondary, overflow: "hidden" }}>
        {stages.map((stage) => (
          <View key={stage.key} style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${stage.width}%`, backgroundColor: stage.colour }} />
        ))}
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.md, rowGap: spacing.xxs }}>
        {stages.map((stage) => (
          <View key={stage.key} style={{ flexDirection: "row", alignItems: "center", gap: spacing.xxs }}>
            <View style={{ width: 8, height: 8, borderRadius: radius.sm, backgroundColor: stage.colour }} />
            <Text style={{ fontSize: fontSize.body, color: ui.foreground }}>{stage.text}</Text>
          </View>
        ))}
      </View>
      {flags.length ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.md, rowGap: spacing.xxs }}>
          {flags.map((flag) => <Text key={flag} style={{ fontSize: fontSize.caption, color: ui.warningText }}>{flag}</Text>)}
        </View>
      ) : null}
    </View>
  );
  const frame = { paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: ui.border };
  return (
    <View style={frame}>
      {onOpen ? (
        <StatPressable label={spoken} onPress={onOpen}>{body}</StatPressable>
      ) : (
        <View accessible accessibilityLabel={spoken}>{body}</View>
      )}
      {link ? <TextAction small label={link.label} onPress={link.onPress} /> : null}
    </View>
  );
}
