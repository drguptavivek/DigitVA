import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View, useWindowDimensions, type LayoutChangeEvent } from "react-native";

import { controlText } from "../../../theme";
import { Button, font, gap, uiRadius, useUi } from "../ui";
import { isComplete, isMandatory, type PickerItem } from "./expression";
import { MaternalIcon, PerinatalIcon } from "./icons";

export type Chapter = "maternal" | "perinatal";

/** Pills and captions stop growing at this multiple of the system font scale; titles and body text grow freely. */
const PILL_SCALE = 1.3;
/** From this font scale the Details control sits under line 1 instead of beside it. */
export const STACK_FONT_SCALE = 1.5;

interface BadgeProps {
  item: PickerItem;
  /** The pregnancy and perinatal badges are buttons only when this is given. */
  onRelated?: (chapter: Chapter) => void;
  /** "+ Build" is a button only when this is given; otherwise a plain "+" marker. */
  onBuild?: () => void;
  /** The coding-note badge is a button only when this is given. */
  onDetails?: () => void;
}

/** The web's five badge tints (doris_demo.css `.doris-context-icon--*`): chart token index and which of its fills. */
const TINTS = {
  post: [1, "tint"],
  required: [1, "soft"],
  maternal: [0, "soft"],
  perinatal: [4, "soft"],
  note: [2, "soft"],
} as const;

/** Whether a result has any badge to draw. */
const hasBadges = (item: PickerItem): boolean => Boolean(item.postcoordination || item.related_maternal || item.related_perinatal || item.has_coding_note);

/** The pill box: 28 dp tall (hit-slop 8 brings the reach to 44), grows with its text. */
function pillBox(borderColor: string, backgroundColor: string) {
  return { flexDirection: "row" as const, alignItems: "center" as const, gap: gap.xs, minHeight: 28, paddingHorizontal: gap.sm, borderRadius: uiRadius.full, borderWidth: 1, borderColor, backgroundColor };
}

/** Pill text: 14 on a 20 line (Devanagari needs 1.4x), capped so a large system font cannot outgrow the row. */
const pillText = (color: string) => ({ ...controlText, fontSize: font.body, lineHeight: 20, fontWeight: "600" as const, color });

/** One badge: a button when `onPress` is given, otherwise a marker carrying the same label for assistive tech. */
function Tag({ label, kind, onPress, children }: { label: string; kind: keyof typeof TINTS; onPress?: () => void; children: ReactNode }) {
  const { t } = useUi();
  const [index, fill] = TINTS[kind];
  const chart = t.chart[index];
  const box = pillBox(chart.foreground, chart[fill]);
  return onPress
    ? <Pressable accessibilityRole="button" accessibilityLabel={label} hitSlop={8} onPress={onPress} style={box}>{children}</Pressable>
    : <View accessible accessibilityLabel={label} style={box}>{children}</View>;
}

/** Postcoordination, pregnancy, perinatal and coding-note badges of a result; nothing renders when the code has none. */
export function ContextBadges({ item, onRelated, onBuild, onDetails }: BadgeProps) {
  const { t } = useUi();
  if (!hasBadges(item)) return null;
  const mandatory = isMandatory(item);
  const tint = (index: number) => pillText(t.chart[index].foreground);
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: gap.xs }}>
      {item.postcoordination ? (
        <Tag label={mandatory ? "Mandatory postcoordination" : "Postcoordination available"} kind={mandatory ? "required" : "post"} onPress={onBuild}>
          <Text maxFontSizeMultiplier={PILL_SCALE} style={tint(1)}>{onBuild ? "+ Build" : "+"}</Text>
        </Tag>
      ) : null}
      {item.related_maternal ? (
        <Tag label="Open pregnancy related terms" kind="maternal" onPress={onRelated && (() => onRelated("maternal"))}>
          <MaternalIcon color={t.chart[0].foreground} /><Text maxFontSizeMultiplier={PILL_SCALE} style={tint(0)}>J</Text>
        </Tag>
      ) : null}
      {item.related_perinatal ? (
        <Tag label="Open perinatal related terms" kind="perinatal" onPress={onRelated && (() => onRelated("perinatal"))}>
          <PerinatalIcon color={t.chart[4].foreground} /><Text maxFontSizeMultiplier={PILL_SCALE} style={tint(4)}>K</Text>
        </Tag>
      ) : null}
      {item.has_coding_note ? (
        <Tag label={onDetails ? "Open coding note" : "Coding note available"} kind="note" onPress={onDetails}>
          <Text maxFontSizeMultiplier={PILL_SCALE} style={tint(2)}>☰</Text>
        </Tag>
      ) : null}
    </View>
  );
}

/** "Usually used only for certain age groups": the web's fallback when the note is missing. */
const AGE_NOTE = "Usually used only for certain age groups.";

export interface ResultRowProps {
  item: PickerItem;
  /** Tap on line 1: stages the code, or opens the builder when postcoordination is mandatory (the picker's `stage`). */
  onTitle: () => void;
  onUse: () => void;
  onDetails: () => void;
  onRelated: (chapter: Chapter) => void;
  onBuild: () => void;
  /** Wide, single-pane results (tablet): small Use and Details buttons at the right instead of the "ⓘ". */
  inline: boolean;
  /** The row's y in the scroller, so "Back to results" can return to it. */
  onLayout?: (event: LayoutChangeEvent) => void;
}

/**
 * One search result as a flat two-line row with a hairline below (no card). Line 1 is a single tap target for the
 * whole line (code and title; the picker's `stage` decides between Use and Build) with a trailing "ⓘ" for Details.
 * Line 2 exists only when there is something to show: the badge pills, the matched wording on one line, and the
 * age-restricted tag. Hierarchy is in the Details card. At a font scale of 1.5 or more the Details control moves
 * under line 1 so the title keeps the width.
 */
export function ResultRow({ item, onTitle, onUse, onDetails, onRelated, onBuild, inline, onLayout }: ResultRowProps) {
  const { t } = useUi();
  const stacked = useWindowDimensions().fontScale >= STACK_FONT_SCALE;
  const showUse = isComplete(item.code) || !isMandatory(item);
  const matched = item.matching_text && item.matching_text !== item.title ? item.matching_text : "";
  const hasMeta = Boolean(matched || item.age_restricted || hasBadges(item));
  const needsBuild = isMandatory(item) && !isComplete(item.code);
  return (
    <View onLayout={onLayout} style={{ paddingVertical: 2, paddingHorizontal: gap.xs, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: t.border }}>
      <View testID="result-line" style={{ flexDirection: stacked ? "column" : "row", alignItems: stacked ? "stretch" : "center", gap: gap.xs }}>
        <Pressable accessibilityRole="button" accessibilityLabel={`${item.code} ${item.title}`} accessibilityHint={needsBuild ? "Opens the builder, because postcoordination is mandatory" : "Selects this code"} onPress={onTitle} style={[{ minHeight: 44, justifyContent: "center" }, stacked ? null : { flex: 1 }]}>
          <Text style={{ fontSize: font.title, lineHeight: 24, color: t.foreground }}>
            <Text style={{ color: t.mutedForeground, fontVariant: ["tabular-nums"] }}>{item.code}</Text> — <Text style={{ fontWeight: "600" }}>{item.title}</Text>
          </Text>
        </Pressable>
        {inline ? (
          <View testID="result-actions" style={{ flexDirection: "row", gap: gap.xs }}>
            {showUse ? <Button label="Use" variant="outline" size="sm" accessibilityLabel={`Use ${item.code}`} onPress={onUse} style={{ minWidth: 0, paddingHorizontal: gap.sm }} /> : null}
            <Button label="Details" variant="outline" size="sm" accessibilityLabel={`Details of ${item.code}`} onPress={onDetails} style={{ minWidth: 0, paddingHorizontal: gap.sm }} />
          </View>
        ) : stacked ? (
          <Pressable accessibilityRole="button" accessibilityLabel={`Details of ${item.code}`} onPress={onDetails} style={{ flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: gap.xs, minHeight: 44 }}>
            <Text maxFontSizeMultiplier={PILL_SCALE} style={{ fontSize: 20, lineHeight: 28, color: t.primary }}>ⓘ</Text>
            <Text maxFontSizeMultiplier={PILL_SCALE} style={{ fontSize: font.body, lineHeight: 20, color: t.primary }}>Details</Text>
          </Pressable>
        ) : (
          <Pressable accessibilityRole="button" accessibilityLabel={`Details of ${item.code}`} hitSlop={6} onPress={onDetails} style={{ minWidth: 32, minHeight: 32, alignItems: "center", justifyContent: "center" }}>
            <Text maxFontSizeMultiplier={PILL_SCALE} style={{ fontSize: 20, lineHeight: 28, color: t.primary }}>ⓘ</Text>
          </Pressable>
        )}
      </View>
      {hasMeta ? (
        <View testID="result-meta" style={{ flexDirection: "row", flexWrap: stacked ? "wrap" : "nowrap", alignItems: "center", columnGap: gap.xs, rowGap: gap.xs, paddingBottom: gap.xs }}>
          <ContextBadges item={item} onRelated={onRelated} onBuild={onBuild} onDetails={onDetails} />
          {item.age_restricted ? (
            <View accessible accessibilityRole="image" accessibilityLabel={`Age-restricted: ${item.restriction_note || AGE_NOTE}`} style={{ minHeight: 28, justifyContent: "center", paddingHorizontal: gap.sm, borderRadius: uiRadius.full, borderWidth: 1, borderColor: t.warningBorder, backgroundColor: t.warning }}>
              <Text maxFontSizeMultiplier={PILL_SCALE} style={{ ...controlText, fontSize: font.caption, lineHeight: 18, fontWeight: "600", color: t.warningForeground }}>age-restricted</Text>
            </View>
          ) : null}
          {matched ? <Text numberOfLines={1} maxFontSizeMultiplier={PILL_SCALE} style={{ flexShrink: 1, minWidth: 0, fontSize: font.caption, lineHeight: 18, color: t.mutedForeground }}>Matched: {matched}</Text> : null}
        </View>
      ) : null}
      {item.age_restricted && item.restriction_note ? <Text maxFontSizeMultiplier={PILL_SCALE} style={{ paddingBottom: gap.xs, fontSize: font.caption, lineHeight: 18, color: t.warningForeground }}>{item.restriction_note}</Text> : null}
    </View>
  );
}
