/** Presentation-only helpers and styles for the shared questionnaire form. */
import React from "react";

import { resolveUiMessages } from "../i18n.js";
import { localized } from "./localize.js";
import type { AnswerValue, InstrumentQuestion, SubmissionData } from "../types.js";
import type { WhoVaPrimitiveSet } from "./create-who-va-form.js";
import { withWebTheme } from "./web-theme.js";

export function FooterIcon({
  name,
  primitives
}: {
  name: "preview" | "save";
  primitives: Required<Pick<WhoVaPrimitiveSet, "Svg" | "SvgCircle" | "SvgPath">>;
}): React.ReactElement {
  const { Svg, SvgCircle, SvgPath } = primitives;
  const iconProps = {
    fill: "none",
    height: 20,
    // The brand-deep default; a literal because react-native-svg cannot read
    // a CSS variable the way the themed text primitives can.
    stroke: "#004687",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: 2,
    viewBox: "0 0 24 24",
    width: 20
  };
  return (
    <Svg {...iconProps} style={formStyles.icon} aria-hidden="true" focusable="false">
      {name === "save" ? (
        <>
          <SvgPath d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />
          <SvgPath d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" />
          <SvgPath d="M7 3v4a1 1 0 0 0 1 1h7" />
        </>
      ) : (
        <>
          <SvgPath d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
          <SvgCircle cx="12" cy="12" r="3" />
        </>
      )}
    </Svg>
  );
}

export { localized, localizedRich } from "./localize.js";

export function interpolateSubmissionReferences(value: string, data: SubmissionData): string {
  return value.replace(/\$\{([^}]+)\}/g, (_match, name: string) => {
    const answer = data[name];
    if (answer == null) return "";
    return Array.isArray(answer) ? answer.join(" ") : String(answer);
  });
}

export function interviewerQuestionLabel(value: string): string {
  return value.replace(/^(\([^)]+\))\s*\[([^\]]+)\](.*)$/s, "$1 $2$3");
}

/**
 * Splits the WHO code a label opens with, `(Id10010b) Sex of VA interviewer`,
 * from the question text, so the form can show the code as a small chip
 * instead of leading every label with it. A label without a code comes back
 * unchanged with an empty `code`.
 */
export function splitQuestionCode(label: string): { code: string; text: string } {
  const match = /^\(([^)\s]+)\)\s*(.*)$/s.exec(label);
  if (!match) return { code: "", text: label };
  return { code: match[1] ?? "", text: match[2] ?? "" };
}

export function hasAnswer(value: AnswerValue | undefined): value is AnswerValue {
  return value != null && value !== "" && (!Array.isArray(value) || value.length > 0);
}

export function previewAnswer(
  question: InstrumentQuestion,
  value: AnswerValue,
  locale: string,
  messages: ReturnType<typeof resolveUiMessages>
): string {
  const choiceLabel = (choiceValue: string) => {
    const choice = question.choices?.find((candidate) => candidate.value === choiceValue);
    return choice ? localized(choice.label, locale, choiceValue) : choiceValue;
  };
  if (Array.isArray(value)) return value.map(choiceLabel).join(", ");
  if (typeof value === "string") return choiceLabel(value);
  if (typeof value === "boolean") return value ? messages.yes : messages.no;
  if (typeof value === "number") return String(value);
  if (value == null) return messages.recorded;
  const attachment = value as Record<string, unknown>;
  for (const property of ["name", "originalName", "fileName", "uri"] as const) {
    const candidate = attachment[property];
    if (typeof candidate === "string" && candidate) return candidate;
  }
  return messages.recorded;
}

/**
 * True when the viewer asked for reduced motion. Shared with native, where
 * `window` does not exist, so every browser global is guarded.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Line heights are explicit throughout: Devanagari, Bengali, Tamil, Kannada
// and Malayalam carry marks above and below the baseline that a tight default
// clips, and the form is filled in those scripts.
export const formStyles = {
  root: withWebTheme({ flex: 1, backgroundColor: "#f6f8f7" }, { backgroundColor: "canvas" }),
  content: withWebTheme(
    { padding: 20, maxWidth: 760, width: "100%", alignSelf: "center" as const },
    { padding: "formPadding", maxWidth: "formMaxWidth" }
  ),
  progress: withWebTheme(
    { color: "#47625b", marginBottom: 6, fontSize: 13, lineHeight: 18 },
    { color: "muted" }
  ),
  sectionSwitcher: {
    alignItems: "center" as const,
    columnGap: 6,
    flexDirection: "row" as const,
    flexWrap: "nowrap" as const,
    marginBottom: 16
  },
  sectionSwitcherViewport: {
    flex: 1,
    overflowX: "auto" as const,
    overflowY: "hidden" as const
  },
  sectionSwitcherTrack: {
    columnGap: 6,
    flexDirection: "row" as const,
    flexWrap: "nowrap" as const,
    paddingVertical: 1
  },
  // A tab is a label over a progress track: the track fills as the section's
  // required answers come in, so status reads as progress rather than as a
  // badge floating over the corner.
  sectionButton: withWebTheme(
    {
      backgroundColor: "#ffffff",
      borderColor: "#dce6e1",
      borderRadius: 8,
      borderWidth: 1,
      justifyContent: "space-between" as const,
      minHeight: 48,
      minWidth: 128,
      width: 128,
      overflow: "hidden" as const
    },
    { backgroundColor: "surface", borderColor: "border" }
  ),
  sectionButtonStarted: withWebTheme({ borderColor: "#8fbfaf" }, { borderColor: "controlBorder" }),
  sectionButtonComplete: withWebTheme(
    { backgroundColor: "#edf7f2", borderColor: "#147d64" },
    { backgroundColor: "brandSoft", borderColor: "brand" }
  ),
  sectionButtonActive: withWebTheme(
    { backgroundColor: "#12372d", borderColor: "#12372d" },
    { backgroundColor: "brandDeep", borderColor: "brandDeep" }
  ),
  sectionButtonError: withWebTheme(
    { backgroundColor: "#fff1f0", borderColor: "#d66552" },
    { backgroundColor: "dangerSoft", borderColor: "dangerBorder" }
  ),
  sectionButtonBody: {
    alignItems: "center" as const,
    columnGap: 4,
    flex: 1,
    flexDirection: "row" as const,
    justifyContent: "center" as const,
    paddingHorizontal: 10,
    paddingVertical: 8
  },
  sectionButtonText: withWebTheme(
    {
      color: "#183d33",
      flexShrink: 1,
      fontSize: 13,
      fontWeight: "600" as const,
      lineHeight: 18,
      textAlign: "center" as const
    },
    { color: "ink" }
  ),
  sectionButtonTextActive: { color: "#ffffff" },
  sectionButtonTextError: withWebTheme({ color: "#8c3022" }, { color: "dangerStrong" }),
  sectionStatusGlyph: withWebTheme(
    { color: "#147d64", fontSize: 13, fontWeight: "700" as const, lineHeight: 18 },
    { color: "brand" }
  ),
  sectionStatusGlyphActive: { color: "#ffffff" },
  sectionProgressTrack: withWebTheme(
    { backgroundColor: "#dce6e1", height: 4, width: "100%" },
    { backgroundColor: "border" }
  ),
  sectionProgressTrackActive: { backgroundColor: "rgba(255, 255, 255, 0.3)" },
  sectionProgressFill: withWebTheme({ backgroundColor: "#147d64", height: 4 }, { backgroundColor: "brand" }),
  sectionProgressFillStarted: { width: "50%" },
  sectionProgressFillComplete: { width: "100%" },
  sectionProgressFillActive: { backgroundColor: "#ffffff" },
  sectionSliderButton: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#dce6e1",
      borderRadius: 8,
      borderWidth: 1,
      justifyContent: "center" as const,
      minHeight: 44,
      minWidth: 40,
      paddingHorizontal: 0,
      paddingVertical: 0
    },
    { backgroundColor: "surface", borderColor: "border" }
  ),
  sectionSliderButtonDisabled: withWebTheme(
    { backgroundColor: "#eef3f0", borderColor: "#dce6e1", opacity: 0.55 },
    { backgroundColor: "canvas", borderColor: "border" }
  ),
  sectionSliderButtonText: withWebTheme(
    { color: "#183d33", fontSize: 18, fontWeight: "700" as const, lineHeight: 22 },
    { color: "ink" }
  ),
  sectionSliderButtonTextDisabled: withWebTheme({ color: "#8ca099" }, { color: "muted" }),
  sectionTitle: withWebTheme(
    { color: "#12372d", fontSize: 22, fontWeight: "700" as const, lineHeight: 30, marginBottom: 12 },
    { color: "brandDeep" }
  ),
  // One surface per section; questions are separated by a rule rather than
  // each carrying its own card, which halves the chrome on a long page.
  sectionCard: withWebTheme(
    {
      backgroundColor: "#ffffff",
      borderColor: "#dce6e1",
      borderRadius: 12,
      borderWidth: 1,
      overflow: "hidden" as const,
      paddingHorizontal: 16
    },
    { backgroundColor: "surface", borderColor: "border", borderRadius: "cardRadius" }
  ),
  question: withWebTheme(
    {
      borderBottomWidth: 1,
      borderBottomColor: "#e6ede9",
      paddingVertical: 16
    },
    { borderBottomColor: "border" }
  ),
  questionError: withWebTheme(
    { borderLeftWidth: 3, borderLeftColor: "#d66552", marginLeft: -16, paddingLeft: 13 },
    { borderLeftColor: "dangerBorder" }
  ),
  questionHeader: {
    alignItems: "flex-start" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    justifyContent: "space-between" as const
  },
  label: withWebTheme(
    { color: "#142a24", fontSize: 16, fontWeight: "600" as const, lineHeight: 24, marginBottom: 8 },
    { color: "ink" }
  ),
  labelWithStatus: { flex: 1 },
  // The WHO code, kept beside the label for coders but out of its way.
  codeChip: withWebTheme(
    {
      alignSelf: "flex-start" as const,
      backgroundColor: "#eef3f0",
      borderRadius: 4,
      color: "#536b64",
      fontSize: 11,
      lineHeight: 16,
      marginBottom: 4,
      paddingHorizontal: 6,
      paddingVertical: 1
    },
    { backgroundColor: "canvas", color: "muted" }
  ),
  questionStatusBadge: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#147d64",
      borderRadius: 999,
      height: 22,
      justifyContent: "center" as const,
      marginTop: 1,
      width: 22
    },
    { backgroundColor: "brand" }
  ),
  questionStatusBadgeText: { color: "#ffffff", fontSize: 13, fontWeight: "700" as const, lineHeight: 16 },
  required: withWebTheme({ color: "#a23a2a" }, { color: "danger" }),
  hint: withWebTheme({ color: "#536b64", fontSize: 14, lineHeight: 20, marginBottom: 8 }, { color: "muted" }),
  guidance: withWebTheme(
    { color: "#315e73", fontSize: 14, lineHeight: 20, marginBottom: 8 },
    { color: "guidance" }
  ),
  // The English beside a translation (`show-english`): secondary and muted.
  english: withWebTheme(
    { color: "#536b64", fontSize: 13, fontStyle: "italic" as const, lineHeight: 19, marginBottom: 8 },
    { color: "muted" }
  ),
  note: withWebTheme(
    {
      backgroundColor: "#edf5f2",
      borderLeftWidth: 3,
      borderLeftColor: "#147d64",
      marginLeft: -16,
      marginRight: -16,
      paddingLeft: 13,
      paddingRight: 16
    },
    { backgroundColor: "brandSoft", borderLeftColor: "brand" }
  ),
  error: withWebTheme({ color: "#a23a2a", marginTop: 8, fontSize: 14, lineHeight: 20 }, { color: "danger" }),
  navigation: {
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    alignItems: "center" as const,
    justifyContent: "flex-end" as const,
    marginTop: 16,
    marginBottom: 8,
    rowGap: 8
  },
  navButton: { minHeight: 44, minWidth: 72, paddingHorizontal: 14, paddingVertical: 10 },
  navIconButton: {
    alignItems: "center" as const,
    columnGap: 6,
    flexDirection: "row" as const,
    justifyContent: "center" as const,
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 12,
    paddingVertical: 10
  },
  navPrimaryButton: { minHeight: 44, minWidth: 96, paddingHorizontal: 18, paddingVertical: 10 },
  icon: { height: 20, width: 20 },
  draftStatus: withWebTheme(
    {
      color: "#536b64",
      fontSize: 13,
      lineHeight: 18,
      marginTop: 4,
      marginBottom: 24,
      textAlign: "right" as const
    },
    { color: "muted" }
  ),
  previewIntro: withWebTheme(
    { color: "#536b64", fontSize: 14, lineHeight: 20, marginBottom: 16 },
    { color: "muted" }
  ),
  previewAnswer: withWebTheme({ color: "#142a24", fontSize: 16, lineHeight: 24 }, { color: "ink" }),
  previewEmpty: withWebTheme(
    { color: "#536b64", fontSize: 15, lineHeight: 22, paddingVertical: 16 },
    { color: "muted" }
  )
};
