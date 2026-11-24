/**
 * Text and chip styles repeated in worklistParts.tsx, as functions of the theme (they cannot be constants:
 * the colours and the text scale change with the theme). Same values the views drew inline.
 */
import type { TextStyle, ViewStyle } from "react-native";

import { controlText, controls, radius, spacing, type useTheme } from "../theme";

type Theme = Pick<ReturnType<typeof useTheme>, "ui" | "typography">;

export const mutedSubhead = ({ ui, typography }: Theme): TextStyle => ({ ...typography.subhead, color: ui.mutedForeground });
export const mutedCaption = ({ ui, typography }: Theme): TextStyle => ({ ...typography.caption, color: ui.mutedForeground });
export const foregroundBody = ({ ui, typography }: Theme): TextStyle => ({ ...typography.body, color: ui.foreground });

/** A filter chip on the Interviews list: 36pt tall at scale 1, tinted while on. */
export const chipStyle = ({ ui }: Pick<Theme, "ui">, textScale: number, on: boolean): ViewStyle => ({
  minHeight: controls.compactHeight * Math.max(1, textScale),
  paddingHorizontal: spacing.sm,
  alignItems: "center",
  justifyContent: "center",
  borderRadius: radius.full,
  backgroundColor: on ? ui.primaryTint : ui.card,
});

export const chipTextStyle = ({ ui, typography }: Theme, textScale: number, on: boolean): TextStyle => ({
  ...typography.subhead,
  ...controlText,
  lineHeight: 22 * textScale,
  fontWeight: on ? "600" : "400",
  color: on ? ui.primary : ui.foreground,
});
