import { AttachmentProcessingError } from "../attachments.js";
import { localizeText, type WhoVaUiMessages } from "../i18n.js";
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
  choice: withWebTheme(
    {
      borderWidth: 1,
      borderColor: "#9fb4ad",
      borderRadius: 8,
      padding: 12,
      marginTop: 7,
      backgroundColor: "#ffffff"
    },
    { borderColor: "controlBorder", borderRadius: "controlRadius", backgroundColor: "surface" }
  ),
  choiceSelected: withWebTheme(
    { borderColor: "#147d64", backgroundColor: "#e3f4ee" },
    { borderColor: "brand", backgroundColor: "brandSoft" }
  ),
  choiceText: withWebTheme({ color: "#213b34" }, { color: "inkSubtle" }),
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

export function questionLabel(question: InstrumentQuestion, locale: string): string {
  return localized(question.label, locale, question.name).replace(
    /^(\([^)]+\))\s*\[([^\]]+)\](.*)$/s,
    "$1 $2$3"
  );
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
