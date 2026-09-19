// The intake page's client-side translation apply, under `node --test`.
//
// `applyTranslations` is pure, so it needs no DOM: it takes the pre-built
// instrument and a locale's strings and returns a new instrument. That purity
// is the property most worth holding — it is what makes switching locale twice
// give the same answer as switching once, and what keeps a failed fetch from
// leaving a half-translated form on screen.
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import test from "node:test";

import { applyTranslations } from "../../../app/static/js/intake/translations.js";

/** A two-question instrument with one choice list and one section. */
function instrument() {
  return {
    id: "who-va-2022",
    sections: [{ name: "consent", label: { en: "Consent" } }],
    questions: [
      {
        name: "Id10004",
        label: { en: "Did the respondent give consent?" },
        hint: { en: "Read it out." },
        guidance: { en: "Consent is mandatory." },
        listName: "yesno",
        choices: [
          { value: "yes", label: { en: "Yes" } },
          { value: "no", label: { en: "No" } },
        ],
      },
      { name: "Id10007", label: { en: "Name of respondent" }, hint: {}, guidance: {} },
    ],
  };
}

const hindi = {
  version: 3,
  questions: {
    consent: { label: "सहमति" },
    Id10004: {
      label: "क्या उत्तरदाता ने सहमति दी?",
      hint: "इसे पढ़कर सुनाएँ।",
      guidance_hint: "सहमति अनिवार्य है।",
    },
  },
  choices: { "yesno/yes": { label: "हाँ" } },
};

test("it sets the locale's strings and leaves English untouched", () => {
  const base = instrument();
  const localized = applyTranslations(base, hindi, "hi");

  // Present first: the Hindi strings really landed, on questions, hints,
  // guidance, the section and the choice.
  assert.equal(localized.questions[0].label.hi, "क्या उत्तरदाता ने सहमति दी?");
  assert.equal(localized.questions[0].hint.hi, "इसे पढ़कर सुनाएँ।");
  assert.equal(localized.questions[0].guidance.hi, "सहमति अनिवार्य है।");
  assert.equal(localized.sections[0].label.hi, "सहमति");
  assert.equal(localized.questions[0].choices[0].label.hi, "हाँ");

  // Then what must not have moved.
  assert.equal(localized.questions[0].label.en, "Did the respondent give consent?");
  assert.equal(localized.questions[0].choices[0].label.en, "Yes");
  assert.equal(localized.sections[0].label.en, "Consent");
});

test("an item the locale does not translate keeps only English", () => {
  const localized = applyTranslations(instrument(), hindi, "hi");
  assert.equal(localized.questions[1].label.en, "Name of respondent");
  assert.equal(localized.questions[1].label.hi, undefined);
  assert.equal(localized.questions[0].choices[1].label.hi, undefined);
  assert.equal(localized.questions[0].choices[1].label.en, "No");
});

test("the instrument it is given is never mutated", () => {
  const base = instrument();
  const before = JSON.stringify(base);
  const localized = applyTranslations(base, hindi, "hi");

  assert.equal(localized.questions[0].label.hi, "क्या उत्तरदाता ने सहमति दी?");
  assert.equal(JSON.stringify(base), before);
  assert.notEqual(localized, base);
});

test("switching locale re-applies from the base, never accumulating", () => {
  const base = instrument();
  const tamil = { version: 1, questions: { Id10004: { label: "சம்மதம்?" } }, choices: {} };

  const hi = applyTranslations(base, hindi, "hi");
  assert.equal(hi.questions[0].label.hi, "क्या उत्तरदाता ने सहमति दी?");

  // The picker re-applies from the same base copy, so the previous locale's
  // strings are not carried into the next instrument.
  const ta = applyTranslations(base, tamil, "ta");
  assert.equal(ta.questions[0].label.ta, "சம்மதம்?");
  assert.equal(ta.questions[0].label.hi, undefined);
});

test("no translations (the base locale) returns an untouched copy", () => {
  const base = instrument();
  const same = applyTranslations(base, null, "en");
  assert.deepEqual(same, base);
  assert.notEqual(same, base);
});
