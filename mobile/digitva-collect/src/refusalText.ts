/**
 * The "Fix: Section › Question (name)" text for the questions a refused submit names (the 422's `fields`).
 * Shared by the browser interview (src/web/InterviewScreen.tsx) and the phone (src/nativeRoutes/form.tsx).
 * Only definition labels are used, never answers.
 */
import { localizeText, type InstrumentDefinition } from "@drguptavivek/who-2022-va";

const MAX_REFUSAL_FIELDS = 5;
const MAX_LABEL_CHARS = 80;

function plainLabel(text: Record<string, string | undefined>, locale: string, fallback: string): string {
  const flat = localizeText(text, locale, fallback).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  return flat.length > MAX_LABEL_CHARS ? `${flat.slice(0, MAX_LABEL_CHARS - 1)}…` : flat;
}

/** The instrument questions a refusal's `fields` name, in order, without repeats; names it does not hold (e.g. "consent") are skipped. */
function namedQuestions(fields: unknown, instrument: InstrumentDefinition | undefined) {
  if (!instrument || !Array.isArray(fields)) return [];
  const found: InstrumentDefinition["questions"] = [];
  for (const name of new Set(fields.filter((field): field is string => typeof field === "string"))) {
    const question = instrument.questions.find((entry) => entry.name === name);
    if (question) found.push(question);
    if (found.length === MAX_REFUSAL_FIELDS) break;
  }
  return found;
}

/** "Section › Question (name)" joined by "; "; "" when nothing matched. */
export function refusalFieldsText(fields: unknown, instrument: InstrumentDefinition | undefined, language: string): string {
  return namedQuestions(fields, instrument).map((question) => {
    const sectionName = question.sectionPath[0] ?? question.sectionPath.at(-1);
    const section = instrument!.sections.find((entry) => entry.name === sectionName);
    return `${section ? `${plainLabel(section.label, language, section.name)} › ` : ""}${plainLabel(question.label, language, question.name)} (${question.name})`;
  }).join("; ");
}

/** The section of the first question a refusal names, for a "go there" button; undefined when none matched. */
export function refusalFirstSection(fields: unknown, instrument: InstrumentDefinition | undefined): string | undefined {
  const question = namedQuestions(fields, instrument)[0];
  return question ? (question.sectionPath[0] ?? question.sectionPath.at(-1)) : undefined;
}
