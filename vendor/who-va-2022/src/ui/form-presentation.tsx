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
  name: "next" | "preview" | "save";
  primitives: Required<Pick<WhoVaPrimitiveSet, "Svg" | "SvgCircle" | "SvgPath">>;
}): React.ReactElement {
  const { Svg, SvgCircle, SvgPath } = primitives;
  const iconProps = {
    fill: "none",
    height: 20,
    // Literals because react-native-svg cannot read a CSS variable the way the
    // themed text primitives can: brand-deep, or white on the primary button.
    stroke: name === "next" ? "#ffffff" : "#004687",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: 2,
    viewBox: "0 0 24 24",
    width: 20
  };
  return (
    <Svg {...iconProps} style={formStyles.icon} aria-hidden="true" focusable="false">
      {name === "next" ? (
        <>
          <SvgPath d="M5 12h14" />
          <SvgPath d="m13 6 6 6-6 6" />
        </>
      ) : name === "save" ? (
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

export { prefersReducedMotion } from "./web-theme.js";

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
  shell: { flex: 1, position: "relative" as const },
  // Wide layout: the section rail beside the question column.
  layoutRow: { alignItems: "flex-start" as const, columnGap: 20, flexDirection: "row" as const },
  mainColumn: { flex: 1, minWidth: 0 },
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
  // Wide forms put the label, code and hint in a left column and the control
  // in a right one; narrow forms stack them.
  questionRow: { columnGap: 24, flexDirection: "row" as const },
  questionLead: { flexBasis: "36%" as const, flexGrow: 0, flexShrink: 0, maxWidth: 300 },
  questionBody: { flex: 1, minWidth: 0 },
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
    justifyContent: "center" as const,
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
  navPrimaryButton: {
    alignItems: "center" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    justifyContent: "center" as const,
    minHeight: 44,
    minWidth: 112,
    paddingHorizontal: 18,
    paddingVertical: 10
  },
  // Narrow layout: a small secondary row (save, preview) above a full-width
  // row of Back and Next.
  navigationNarrow: { marginTop: 16, marginBottom: 8, rowGap: 8 },
  navRowSecondary: { columnGap: 8, flexDirection: "row" as const, justifyContent: "flex-end" as const },
  navRowPrimary: { columnGap: 8, flexDirection: "row" as const },
  navSmallButton: { minHeight: 40, paddingHorizontal: 10, paddingVertical: 8 },
  navSmallText: { fontSize: 14 },
  navGrow: { flex: 1 },
  navGrowPrimary: { flex: 2 },
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
