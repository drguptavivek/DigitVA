/** Presentation-only helpers and styles for the shared questionnaire form. */
import React from "react";

import { localizeText, resolveUiMessages } from "../i18n.js";
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
    height: 22,
    stroke: "#183d33",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: 2,
    viewBox: "0 0 24 24",
    width: 22
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

function plainText(value: string | undefined): string {
  if (!value) return "";
  return value
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .trim();
}

export function localized(
  text: Record<string, string | undefined>,
  locale: string,
  fallback: string
): string {
  return plainText(localizeText(text, locale, fallback));
}

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

export const formStyles = {
  root: withWebTheme({ flex: 1, backgroundColor: "#f6f8f7" }, { backgroundColor: "canvas" }),
  content: withWebTheme(
    { padding: 20, maxWidth: 760, width: "100%", alignSelf: "center" as const },
    { padding: "formPadding", maxWidth: "formMaxWidth" }
  ),
  progress: withWebTheme({ color: "#47625b", marginBottom: 6, fontSize: 13 }, { color: "muted" }),
  sectionSwitcher: {
    alignItems: "center" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "nowrap" as const,
    marginBottom: 12,
    rowGap: 8
  },
  sectionSwitcherViewport: {
    flex: 1,
    maxWidth: 472,
    overflowX: "auto" as const,
    overflowY: "hidden" as const
  },
  sectionSwitcherTrack: {
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "nowrap" as const,
    paddingVertical: 1
  },
  sectionButton: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#dce6e1",
      borderRadius: 8,
      borderWidth: 1,
      justifyContent: "center" as const,
      minHeight: 38,
      minWidth: 112,
      position: "relative" as const,
      width: 112,
      paddingHorizontal: 12,
      paddingVertical: 8
    },
    { backgroundColor: "surface", borderColor: "border" }
  ),
  sectionButtonStarted: withWebTheme(
    { backgroundColor: "#f5fbf8", borderColor: "#8fbfaf" },
    { backgroundColor: "brandSoft", borderColor: "brand" }
  ),
  sectionButtonComplete: withWebTheme(
    { backgroundColor: "#edf7f2", borderColor: "#147d64" },
    { backgroundColor: "brandSoft", borderColor: "brand" }
  ),
  sectionSliderButton: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#dce6e1",
      borderRadius: 8,
      borderWidth: 1,
      justifyContent: "center" as const,
      minHeight: 38,
      minWidth: 38,
      paddingHorizontal: 0,
      paddingVertical: 0
    },
    { backgroundColor: "surface", borderColor: "border" }
  ),
  sectionSliderButtonDisabled: withWebTheme(
    { backgroundColor: "#eef3f0", borderColor: "#dce6e1", opacity: 0.55 },
    { backgroundColor: "canvas", borderColor: "border" }
  ),
  sectionButtonActive: withWebTheme(
    { backgroundColor: "#12372d", borderColor: "#12372d" },
    { backgroundColor: "brandDeep", borderColor: "brandDeep" }
  ),
  sectionButtonError: withWebTheme(
    { backgroundColor: "#fff1f0", borderColor: "#d66552" },
    { backgroundColor: "dangerSoft", borderColor: "dangerBorder" }
  ),
  sectionButtonText: withWebTheme(
    { color: "#183d33", fontSize: 13, fontWeight: "700" as const, textAlign: "center" as const },
    { color: "ink" }
  ),
  sectionSliderButtonText: withWebTheme(
    { color: "#183d33", fontSize: 18, fontWeight: "700" as const, lineHeight: 20 },
    { color: "ink" }
  ),
  sectionSliderButtonTextDisabled: withWebTheme({ color: "#8ca099" }, { color: "muted" }),
  sectionButtonTextActive: { color: "#ffffff" },
  sectionButtonTextError: withWebTheme({ color: "#8c3022" }, { color: "dangerStrong" }),
  sectionStatusBadge: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#147d64",
      borderRadius: 999,
      height: 18,
      justifyContent: "center" as const,
      position: "absolute" as const,
      right: 5,
      top: 4,
      width: 18
    },
    { backgroundColor: "brand" }
  ),
  sectionStatusBadgeStarted: withWebTheme({ backgroundColor: "#dbe9e4" }, { backgroundColor: "border" }),
  sectionStatusBadgeActive: { backgroundColor: "#ffffff" },
  sectionStatusBadgeText: { color: "#ffffff", fontSize: 12, fontWeight: "700" as const, lineHeight: 14 },
  sectionStatusBadgeTextStarted: withWebTheme({ color: "#315e52" }, { color: "inkSubtle" }),
  sectionStatusBadgeTextActive: withWebTheme({ color: "#12372d" }, { color: "brandDeep" }),
  sectionTitle: withWebTheme(
    { color: "#12372d", fontSize: 24, fontWeight: "700" as const, marginBottom: 18 },
    { color: "brandDeep" }
  ),
  question: withWebTheme(
    {
      backgroundColor: "#ffffff",
      borderRadius: 12,
      padding: 16,
      marginBottom: 12,
      borderWidth: 1,
      borderColor: "#dce6e1"
    },
    { backgroundColor: "surface", borderRadius: "cardRadius", borderColor: "border" }
  ),
  questionError: withWebTheme({ borderColor: "#d66552" }, { borderColor: "dangerBorder" }),
  questionHeader: {
    alignItems: "flex-start" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    justifyContent: "space-between" as const
  },
  label: withWebTheme(
    { color: "#142a24", fontSize: 16, fontWeight: "600" as const, marginBottom: 8 },
    { color: "ink" }
  ),
  labelWithStatus: { flex: 1 },
  questionStatusBadge: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#147d64",
      borderRadius: 999,
      height: 22,
      justifyContent: "center" as const,
      marginTop: -1,
      width: 22
    },
    { backgroundColor: "brand" }
  ),
  questionStatusBadgeText: { color: "#ffffff", fontSize: 14, fontWeight: "700" as const, lineHeight: 16 },
  required: withWebTheme({ color: "#a23a2a" }, { color: "danger" }),
  hint: withWebTheme({ color: "#536b64", fontSize: 13, marginBottom: 10 }, { color: "muted" }),
  guidance: withWebTheme({ color: "#315e73", fontSize: 13, marginBottom: 10 }, { color: "guidance" }),
  note: withWebTheme(
    { backgroundColor: "#edf5f2", borderLeftWidth: 4, borderLeftColor: "#147d64" },
    { backgroundColor: "brandSoft", borderLeftColor: "brand" }
  ),
  error: withWebTheme({ color: "#a23a2a", marginTop: 8, fontSize: 13 }, { color: "danger" }),
  navigation: {
    columnGap: 10,
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    marginTop: 12,
    marginBottom: 12,
    rowGap: 10
  },
  navButton: { minHeight: 40, minWidth: 68, paddingHorizontal: 12, paddingVertical: 10 },
  navIconButton: {
    alignItems: "center" as const,
    justifyContent: "center" as const,
    minHeight: 40,
    minWidth: 44,
    paddingHorizontal: 0,
    paddingVertical: 0
  },
  navPrimaryButton: { minHeight: 42, minWidth: 76, paddingHorizontal: 14, paddingVertical: 10 },
  icon: { height: 22, width: 22 },
  draftStatus: withWebTheme(
    { color: "#536b64", fontSize: 12, marginTop: 4, marginBottom: 24 },
    { color: "muted" }
  ),
  previewIntro: withWebTheme({ color: "#536b64", fontSize: 14, marginBottom: 18 }, { color: "muted" }),
  previewAnswer: withWebTheme({ color: "#142a24", fontSize: 16 }, { color: "ink" }),
  previewEmpty: withWebTheme({ color: "#536b64", fontSize: 15, paddingVertical: 16 }, { color: "muted" })
};
