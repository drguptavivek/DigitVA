// Apply a locale's instrument translations to a pre-built instrument.
//
// The instrument's structure is pre-built and immutable (decision O1,
// docs/policy/va-web-form-options.md): a translation only supplies the text a
// question, hint, guidance note, section or choice is shown with. The server
// serves that text from
// GET /api/v1/instruments/<instrument_code>/translations/<locale>, keyed by
// the same item names the instrument carries.
//
// This function is pure: it never mutates the instrument it is given, so
// switching locale twice starts from the same English base both times and a
// failed fetch cannot leave a half-translated form on screen.

const clone = (value) =>
  typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));

// The instrument's own field name for each translated XLSForm column.
const QUESTION_FIELDS = [
  ["label", "label"],
  ["hint", "hint"],
  ["guidance_hint", "guidance"],
];

function setLocalized(target, key, locale, text) {
  if (typeof text !== "string" || !text) return;
  if (!target[key] || typeof target[key] !== "object") target[key] = {};
  target[key][locale] = text;
}

/**
 * Return a copy of `instrument` carrying `translations` under `locale`.
 *
 * @param {object} instrument  The pre-built instrument.
 * @param {object} translations  {questions: {name: {label, hint, guidance_hint}},
 *                                choices: {"list/value": {label}}}
 * @param {string} locale  The locale code the strings are filed under.
 * @returns {object} A new instrument; the original is untouched.
 */
export function applyTranslations(instrument, translations, locale) {
  if (!instrument) return instrument;
  const copy = clone(instrument);
  if (!locale || !translations) return copy;

  const questions = translations.questions || {};
  const choices = translations.choices || {};

  for (const section of copy.sections || []) {
    // Section labels come from the same `question` map: a group row is a named
    // row of the survey sheet, which is how the importer keys it.
    const entry = questions[section.name];
    if (entry) setLocalized(section, "label", locale, entry.label);
  }

  for (const question of copy.questions || []) {
    const entry = questions[question.name];
    if (entry) {
      for (const [field, target] of QUESTION_FIELDS) {
        setLocalized(question, target, locale, entry[field]);
      }
    }
    if (!question.listName) continue;
    for (const choice of question.choices || []) {
      const entry = choices[`${question.listName}/${choice.value}`];
      if (entry) setLocalized(choice, "label", locale, entry.label);
    }
  }

  return copy;
}

export default applyTranslations;
