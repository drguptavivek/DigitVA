/**
 * Apply a locale's instrument translations to the pre-built instrument.
 * Port of app/static/js/intake/translations.js (the web intake page); keep
 * the two in step. Pure: the base instrument is never mutated, so switching
 * language always starts from English.
 */
import type { InstrumentDefinition } from "@drguptavivek/who-2022-va";

export interface Translations {
  questions?: Record<string, { label?: string; hint?: string; guidance_hint?: string }>;
  choices?: Record<string, { label?: string }>;
}

const QUESTION_FIELDS = [
  ["label", "label"],
  ["hint", "hint"],
  ["guidance_hint", "guidance"]
] as const;

type Localizable = Record<string, unknown>;

function setLocalized(target: Localizable, key: string, locale: string, text: unknown) {
  if (typeof text !== "string" || !text) return;
  if (!target[key] || typeof target[key] !== "object") target[key] = {};
  (target[key] as Record<string, string>)[locale] = text;
}

export function applyTranslations(
  instrument: InstrumentDefinition,
  translations: Translations | null,
  locale: string
): InstrumentDefinition {
  const copy = JSON.parse(JSON.stringify(instrument)) as InstrumentDefinition;
  if (!translations) return copy;
  const questions = translations.questions ?? {};
  const choices = translations.choices ?? {};
  for (const section of copy.sections as unknown as Array<Localizable & { name: string }>) {
    const entry = questions[section.name];
    if (entry) setLocalized(section, "label", locale, entry.label);
  }
  for (const question of copy.questions as unknown as Array<
    Localizable & { name: string; listName?: string; choices?: Array<Localizable & { value: string }> }
  >) {
    const entry = questions[question.name];
    if (entry) for (const [field, target] of QUESTION_FIELDS) setLocalized(question, target, locale, entry[field]);
    if (!question.listName) continue;
    for (const choice of question.choices ?? []) {
      const c = choices[`${question.listName}/${choice.value}`];
      if (c) setLocalized(choice, "label", locale, c.label);
    }
  }
  return copy;
}
