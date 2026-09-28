import { AttachmentProcessingError } from "../attachments.js";
import { type WhoVaUiMessages } from "../i18n.js";
import { localized, plainText } from "./localize.js";
import type { AnswerValue, AttachmentReference, InstrumentQuestion } from "../types.js";
import { withWebTheme } from "./web-theme.js";

export const questionControlStyles = {
  input: withWebTheme(
    {
      borderWidth: 1,
      borderColor: "#9fb4ad",
      borderRadius: 8,
      minHeight: 44,
      paddingHorizontal: 12,
      paddingVertical: 9,
      color: "#142a24",
      backgroundColor: "#ffffff"
    },
    { borderColor: "controlBorder", borderRadius: "controlRadius", color: "ink", backgroundColor: "surface" }
  ),
  narrativeInput: { minHeight: 160, textAlignVertical: "top" as const },
  inputError: withWebTheme(
    { borderColor: "#b34231", backgroundColor: "#fff8f6" },
    { borderColor: "danger", backgroundColor: "dangerSoft" }
  ),
  inputReadOnly: withWebTheme({ opacity: 0.72, backgroundColor: "#eef3f1" }, { backgroundColor: "border" }),
  // A choice is a row: the radio or checkbox indicator, then the label. The
  // whole row is the touch target (48px tall at minimum).
  choice: withWebTheme(
    {
      alignItems: "flex-start" as const,
      borderWidth: 1,
      borderColor: "#9fb4ad",
      borderRadius: 8,
      columnGap: 12,
      flexDirection: "row" as const,
      minHeight: 48,
      paddingHorizontal: 12,
      paddingVertical: 11,
      marginTop: 8,
      backgroundColor: "#ffffff"
    },
    { borderColor: "controlBorder", borderRadius: "controlRadius", backgroundColor: "surface" }
  ),
  choiceSelected: withWebTheme(
    { borderColor: "#147d64", backgroundColor: "#e3f4ee" },
    { borderColor: "brand", backgroundColor: "brandSoft" }
  ),
  choiceText: withWebTheme(
    { color: "#213b34", flexShrink: 1, fontSize: 16, lineHeight: 24 },
    { color: "inkSubtle" }
  ),
  choiceIndicator: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#9fb4ad",
      borderWidth: 2,
      flexShrink: 0,
      height: 22,
      justifyContent: "center" as const,
      marginTop: 1,
      width: 22
    },
    { backgroundColor: "surface", borderColor: "controlBorder" }
  ),
  choiceIndicatorRadio: { borderRadius: 999 },
  choiceIndicatorCheckbox: { borderRadius: 4 },
  choiceIndicatorSelected: withWebTheme({ borderColor: "#147d64" }, { borderColor: "brand" }),
  choiceIndicatorRadioDot: withWebTheme(
    { backgroundColor: "#147d64", borderRadius: 999, height: 10, width: 10 },
    { backgroundColor: "brand" }
  ),
  choiceIndicatorCheckboxSelected: withWebTheme({ backgroundColor: "#147d64" }, { backgroundColor: "brand" }),
  choiceIndicatorCheck: { color: "#ffffff", fontSize: 14, fontWeight: "700" as const, lineHeight: 16 },
  // The English beneath a translated choice label (`show-english`).
  choiceEnglish: withWebTheme(
    { color: "#536b64", fontSize: 13, fontStyle: "italic" as const, lineHeight: 19 },
    { color: "muted" }
  ),
  // Layout appearances: `columns`, `columns-n`, `columns-pack`, `likert`,
  // and the range `picker`/`rating` all lay choices out along a row.
  choiceRow: {
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    alignItems: "flex-start" as const,
    marginTop: 7
  },
  choiceInline: { marginTop: 0, marginRight: 7, flexGrow: 0, flexShrink: 1 },
  // `columns-pack` fits as many choices per line as will go, so a cell must be
  // free to size to its own label rather than to a share of the row.
  choicePacked: { flexBasis: "auto" as const },
  choiceLikert: {
    flexGrow: 1,
    flexBasis: 0,
    marginRight: 7,
    marginTop: 0,
    alignItems: "center" as const
  },
  // `no-buttons`: the cell itself is the target, so drop the control chrome.
  choiceBare: withWebTheme(
    { borderWidth: 0, backgroundColor: "transparent" },
    { backgroundColor: "surface" }
  ),
  searchInput: { marginBottom: 7 },
  // Short choice lists as a grid of equal cells (see useChoicePresentation).
  choiceGrid: {
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "wrap" as const,
    marginTop: 8,
    rowGap: 8
  },
  choiceCell: { marginRight: 0, marginTop: 0 },
  // Numeric fields: a compact box between a "-" and a "+" button, then the unit.
  numberRow: {
    alignItems: "center" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "wrap" as const
  },
  numberInput: { paddingHorizontal: 8, textAlign: "center" as const },
  stepButton: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#dce6e1",
      borderRadius: 8,
      height: 44,
      justifyContent: "center" as const,
      width: 44
    },
    { backgroundColor: "border", borderRadius: "controlRadius" }
  ),
  stepGlyph: withWebTheme(
    { color: "#183d33", fontSize: 22, fontWeight: "700" as const, lineHeight: 26 },
    { color: "brandDeep" }
  ),
  // Date and time boxes are sized for a date, not the column, and never wider than it.
  // DD-MMM-YYYY as three parts styled as one field, plus the calendar button.
  dateGroup: {
    alignItems: "center" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    flexWrap: "wrap" as const
  },
  dateField: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#9fb4ad",
      borderRadius: 8,
      borderWidth: 1,
      flexDirection: "row" as const,
      minHeight: 44,
      paddingHorizontal: 4
    },
    { backgroundColor: "surface", borderColor: "controlBorder", borderRadius: "controlRadius" }
  ),
  datePart: withWebTheme(
    {
      borderWidth: 0,
      color: "#142a24",
      fontSize: 16,
      minHeight: 40,
      paddingHorizontal: 6,
      textAlign: "center" as const
    },
    { color: "ink" }
  ),
  datePartDay: { width: 44 },
  datePartMonth: { minWidth: 72 },
  datePartYear: { width: 68 },
  dateSeparator: withWebTheme({ color: "#536b64", fontSize: 16 }, { color: "muted" }),
  hiddenPicker: { height: 1, left: 0, opacity: 0, position: "absolute" as const, top: 0, width: 1 },
  dateInput: { maxWidth: "100%", width: 192 },
  timeInput: { maxWidth: "100%", width: 144 },
  dateTimeInput: { maxWidth: "100%", width: 256 },
  formatHint: withWebTheme(
    { color: "#536b64", fontSize: 13, lineHeight: 18, marginTop: 4 },
    { color: "muted" }
  ),
  unit: withWebTheme({ color: "#536b64", fontSize: 15, lineHeight: 22 }, { color: "muted" }),
  // `signature`/`draw` replace capture-or-select, so those buttons are removed
  // from the layout rather than merely disabled.
  hidden: { display: "none" as const },
  star: { paddingHorizontal: 3, paddingVertical: 2 },
  starFilled: withWebTheme({ color: "#147d64", fontSize: 26 }, { color: "brand" }),
  starEmpty: withWebTheme({ color: "#9fb4ad", fontSize: 26 }, { color: "controlBorder" }),
  dropdownList: { marginTop: 6 },
  hint: withWebTheme({ color: "#536b64", fontSize: 13, marginBottom: 10 }, { color: "muted" }),
  actions: { flexDirection: "row" as const, flexWrap: "wrap" as const, marginTop: 8 },
  button: withWebTheme(
    {
      minHeight: 44,
      borderRadius: 8,
      paddingHorizontal: 18,
      paddingVertical: 12,
      backgroundColor: "#147d64",
      justifyContent: "center" as const
    },
    { borderRadius: "controlRadius", backgroundColor: "brand" }
  ),
  buttonSecondary: withWebTheme({ backgroundColor: "#dce6e1" }, { backgroundColor: "border" }),
  buttonError: withWebTheme(
    { borderWidth: 1, borderColor: "#b34231", backgroundColor: "#b34231" },
    { borderColor: "danger", backgroundColor: "danger" }
  ),
  buttonSecondaryError: withWebTheme(
    { borderWidth: 1, borderColor: "#b34231", backgroundColor: "#fff8f6" },
    { borderColor: "danger", backgroundColor: "dangerSoft" }
  ),
  buttonDanger: withWebTheme({ backgroundColor: "#f3ded9" }, { backgroundColor: "dangerSoft" }),
  buttonDisabled: { opacity: 0.45 },
  buttonText: withWebTheme({ color: "#ffffff", fontWeight: "700" as const }, { color: "surface" }),
  buttonTextSecondary: withWebTheme({ color: "#183d33", fontWeight: "700" as const }, { color: "brandDeep" }),
  buttonTextDanger: withWebTheme({ color: "#8c3022", fontWeight: "700" as const }, { color: "dangerStrong" }),
  imageFrame: withWebTheme(
    {
      overflow: "hidden" as const,
      minHeight: 220,
      borderRadius: 8,
      backgroundColor: "#10231e",
      alignItems: "center" as const,
      justifyContent: "center" as const,
      marginTop: 8
    },
    { borderRadius: "controlRadius", backgroundColor: "imageBackground" }
  ),
  image: { width: "100%", height: 260, resizeMode: "contain" as const },
  attachmentName: withWebTheme({ color: "#213b34", marginTop: 10 }, { color: "inkSubtle" }),
  attachmentError: withWebTheme(
    { color: "#a23a2a", fontSize: 13, fontWeight: "700" as const, marginTop: 8 },
    { color: "danger" }
  )
};

export { localized, localizedRich } from "./localize.js";

export function questionLabel(question: InstrumentQuestion, locale: string): string {
  return localized(question.label, locale, question.name).replace(
    /^(\([^)]+\))\s*\[([^\]]+)\](.*)$/s,
    "$1 $2$3"
  );
}

/**
 * Digits typed on an Indic keyboard (Devanagari, Bengali, Gurmukhi, Gujarati,
 * Odia, Tamil, Telugu, Kannada, Malayalam) as ASCII digits. Every one of
 * those blocks keeps its zero at offset 0x6, so one arithmetic covers them.
 * The stored answer stays the number/ASCII string the engine already uses.
 */
export function asciiDigits(text: string): string {
  return text.replace(
    /[\u0966-\u096F\u09E6-\u09EF\u0A66-\u0A6F\u0AE6-\u0AEF\u0B66-\u0B6F\u0BE6-\u0BEF\u0C66-\u0C6F\u0CE6-\u0CEF\u0D66-\u0D6F]/g,
    (digit) => String(((digit.codePointAt(0) ?? 0) & 0xf) - 6)
  );
}

/**
 * The numeric bounds an XLSForm constraint states outright (`. >= 18 and
 * . < 90`). A bound that refers to another answer (`${ageInDays}`) or a
 * special code (`or . = 99`) is left open: the buttons stop at what is
 * known, typing is never blocked.
 */
export function constraintBounds(question: InstrumentQuestion): { min?: number; max?: number } {
  const bounds: { min?: number; max?: number } = {};
  const source = question.constraint?.source ?? "";
  for (const match of source.matchAll(/\.\s*(>=|>|<=|<)\s*(-?\d+(?:\.\d+)?)/g)) {
    const [, operator, digits] = match;
    const number = Number(digits);
    if (operator === ">=" && bounds.min === undefined) bounds.min = number;
    if (operator === ">" && bounds.min === undefined) bounds.min = number + 1;
    if (operator === "<=" && bounds.max === undefined) bounds.max = number;
    if (operator === "<" && bounds.max === undefined) bounds.max = number - 1;
  }
  return bounds;
}

const UNIT_WORDS: ReadonlyArray<
  [
    RegExp,
    keyof Pick<
      WhoVaUiMessages,
      "unitDays" | "unitMonths" | "unitYears" | "unitHours" | "unitMinutes" | "unitWeeks" | "unitGrams"
    >
  ]
> = [
  [/\bdays?\b/i, "unitDays"],
  [/\bmonths?\b/i, "unitMonths"],
  [/\byears?\b/i, "unitYears"],
  [/\bhours?\b/i, "unitHours"],
  [/\bminutes?\b/i, "unitMinutes"],
  [/\bweeks?\b/i, "unitWeeks"],
  [/\bgram(?:me)?s?\b/i, "unitGrams"]
];

/**
 * The unit a numeric question implies, read from its English label and hint,
 * but only when exactly one unit word occurs: "How many (months/years)" names
 * two and gets none.
 */
export function numericUnit(question: InstrumentQuestion, messages: WhoVaUiMessages): string {
  const english = `${plainText(question.label.en)} ${plainText(question.hint?.en)}`;
  const found = UNIT_WORDS.filter(([pattern]) => pattern.test(english));
  const key = found.length === 1 ? found[0]?.[1] : undefined;
  return key ? messages[key] : "";
}

export function languageChoiceLabel(choice: NonNullable<InstrumentQuestion["choices"]>[number]): string {
  const english = plainText(choice.label.en) || choice.value;
  const baseLanguage = choice.value.split("-")[0] ?? choice.value;
  const local = plainText(choice.label[choice.value] ?? choice.label[baseLanguage] ?? choice.label.en);
  return `${english} (${local || english})`;
}

export function attachmentDetails(value: AnswerValue | undefined): {
  uri?: string;
  name?: string;
  mimeType?: string;
} {
  if (typeof value === "string") return { uri: value, name: value.split("/").at(-1) ?? value };
  if (value == null || Array.isArray(value) || typeof value !== "object") return {};
  return {
    ...(typeof value.uri === "string" ? { uri: value.uri } : {}),
    ...(typeof value.originalName === "string"
      ? { name: value.originalName }
      : typeof value.name === "string"
        ? { name: value.name }
        : {}),
    ...(typeof value.mimeType === "string" ? { mimeType: value.mimeType } : {})
  };
}

export function attachmentMimeType(value: AnswerValue | undefined): string | undefined {
  if (value == null || Array.isArray(value) || typeof value !== "object") return undefined;
  return typeof value.mimeType === "string" ? value.mimeType : undefined;
}

export function attachmentReference(value: AnswerValue | undefined): AttachmentReference | undefined {
  if (value == null || Array.isArray(value) || typeof value !== "object") return undefined;
  return typeof value.uri === "string" && value.uri ? (value as AttachmentReference) : undefined;
}

export function attachmentErrorMessage(error: unknown, messages: WhoVaUiMessages): string {
  if (!(error instanceof AttachmentProcessingError)) return messages.attachmentProcessingFailed;
  const localizedMessages = {
    "image-input-too-large": messages.imageInputTooLarge,
    "image-type-not-allowed": messages.imageTypeNotAllowed,
    "image-dimensions-invalid": messages.imageDimensionsInvalid,
    "image-dimensions-too-large": messages.imageDimensionsTooLarge,
    "image-decode-failed": messages.imageDecodeFailed,
    "image-output-invalid": messages.imageOutputInvalid,
    "image-output-too-large": messages.imageOutputTooLarge,
    "image-processing-unavailable": messages.imageProcessingUnavailable,
    "attachment-storage-failed": messages.attachmentStorageFailed,
    "pdf-input-too-large": messages.pdfInputTooLarge,
    "pdf-type-not-allowed": messages.pdfTypeNotAllowed,
    "pdf-render-failed": messages.pdfRenderFailed,
    "pdf-too-many-pages": messages.pdfTooManyPages,
    "pdf-output-too-large": messages.pdfOutputTooLarge,
    "pdf-processing-unavailable": messages.pdfProcessingUnavailable
  } satisfies Record<typeof error.code, string>;
  return localizedMessages[error.code];
}
