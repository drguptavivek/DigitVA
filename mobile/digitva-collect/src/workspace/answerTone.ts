import type { JsonValue } from "./contracts";

/** Answer text as the web's ResponseValue flattens it before testing for Yes/No (CategoryPanel.web.tsx `primitive`). */
export function answerText(value: JsonValue): string {
  if (value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(answerText).filter(Boolean).join(", ");
  return Object.entries(value).map(([key, item]) => `${key.replace(/_/g, " ")}: ${answerText(item)}`).join(" · ");
}

export type AnswerTone = "info" | "red" | "green" | null;

/**
 * Badge colour of a category answer, decided as the web ResponseValue does: `info` wins; a Yes is red and a No
 * green, swapped when the field is `flip`ped; any other answer has no badge.
 */
export function answerTone(value: JsonValue, flip: boolean, info: boolean): AnswerTone {
  if (info) return "info";
  const normalized = answerText(value).trim().toLowerCase();
  const isYes = normalized === "yes";
  const isNo = normalized === "no";
  if (!isYes && !isNo) return null;
  return (flip ? isNo : isYes) ? "red" : "green";
}

/** "(Id10123) Deceased died suddenly" or "(narr_language) ..." -> the field id and the question text; no id leaves the label whole. */
export function splitFieldId(label: string): { id: string | null; text: string } {
  const match = /^\(([A-Za-z]\w*)\)\s*(.+)$/s.exec(label);
  return match ? { id: match[1], text: match[2] } : { id: null, text: label };
}
