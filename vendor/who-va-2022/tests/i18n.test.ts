import { describe, expect, it } from "vitest";

import {
  createWhoVaLanguageLoader,
  createWhoVaSession,
  localizeText,
  resolveUiMessages,
  withInstrumentTranslations
} from "../src/index.js";
import type { InstrumentDefinition } from "../src/types.js";

const instrument: InstrumentDefinition = {
  id: "i18n-test",
  title: "I18n test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "test.xlsx",
  sections: [{ name: "main", sourceRow: 1, order: 1, label: { en: "Main" } }],
  questions: [
    {
      name: "symptom",
      order: 1,
      sourceRow: 2,
      sourceType: "select_one symptoms",
      dataType: "string",
      control: "singleChoice",
      label: { en: "Symptom" },
      hint: { en: "Choose one" },
      guidance: {},
      required: true,
      readOnly: false,
      choices: [{ value: "fever", sourceRow: 2, label: { en: "Fever" } }],
      constraint: { source: ". = 'fever'" },
      constraintMessage: { en: "Choose fever" },
      sectionPath: ["main"]
    }
  ]
};

describe("instrument internationalization", () => {
  it("falls back from a regional locale to its base language and then English", () => {
    expect(localizeText({ en: "Name", fr: "Nom" }, "fr-CA")).toBe("Nom");
    expect(localizeText({ en: "Name" }, "sw")).toBe("Name");
  });

  it("adds one locale across section, question, hint, response, and constraint message", () => {
    const translated = withInstrumentTranslations(instrument, {
      fr: {
        sections: { main: "Principal" },
        questions: {
          symptom: {
            label: "Symptôme",
            hint: "Choisissez une réponse",
            constraintMessage: "Choisissez fièvre",
            choices: { fever: "Fièvre" }
          }
        }
      }
    });

    expect(translated.sections[0]?.label.fr).toBe("Principal");
    expect(translated.questions[0]?.label.fr).toBe("Symptôme");
    expect(translated.questions[0]?.hint.fr).toBe("Choisissez une réponse");
    expect(translated.questions[0]?.choices?.[0]?.label.fr).toBe("Fièvre");
    expect(translated.questions[0]?.constraintMessage.fr).toBe("Choisissez fièvre");
    expect(instrument.questions[0]?.label.fr).toBeUndefined();
  });

  it("retains unchanged question objects when applying a partial translation overlay", () => {
    const unchangedQuestion = {
      ...instrument.questions[0]!,
      name: "unchanged",
      order: 2,
      label: { en: "Unchanged" }
    };
    const extended = { ...instrument, questions: [...instrument.questions, unchangedQuestion] };

    const translated = withInstrumentTranslations(extended, {
      fr: { questions: { symptom: { label: "Symptôme" } } }
    });

    expect(translated.questions[0]).not.toBe(extended.questions[0]);
    expect(translated.questions[1]).toBe(extended.questions[1]);
    expect(translated.questions[1]?.label).toBe(extended.questions[1]?.label);
  });

  it("uses the session locale for required validation and supports translated UI phrases", () => {
    const translated = withInstrumentTranslations(instrument, {
      fr: { questions: { symptom: { label: "Symptôme" } } }
    });
    const uiTranslations = {
      fr: { required: "{label} est obligatoire" }
    };
    const session = createWhoVaSession(translated, { locale: "fr-CA", uiTranslations });

    expect(session.next().issues[0]?.message).toBe("Symptôme est obligatoire");
    expect(resolveUiMessages("fr-CA", uiTranslations).back).toBe("Back");
  });

  it("loads and caches an independent language file only when requested", async () => {
    let imports = 0;
    const loadLanguage = createWhoVaLanguageLoader(instrument, {
      fr: async () => {
        imports += 1;
        return {
          default: {
            locale: "fr",
            instrument: {
              sections: { main: "Principal" },
              questions: {
                symptom: {
                  label: "Symptôme",
                  hint: "Choisissez une réponse",
                  constraintMessage: "Choisissez fièvre",
                  choices: { fever: "Fièvre" }
                }
              }
            },
            ui: { next: "Suivant", required: "{label} est obligatoire" }
          }
        };
      }
    });

    expect(imports).toBe(0);
    const french = await loadLanguage("fr-CA");
    const again = await loadLanguage("fr-CA");

    expect(imports).toBe(1);
    expect(again).toBe(french);
    expect(french.locale).toBe("fr");
    expect(french.instrument.questions[0]?.choices?.[0]?.label.fr).toBe("Fièvre");
    expect(resolveUiMessages(french.locale, french.uiTranslations).next).toBe("Suivant");

    const session = createWhoVaSession(instrument);
    session.setAnswer("symptom", "fever");
    session.setInstrument(french.instrument);
    session.setLocale(french.locale, french.uiTranslations);
    expect(session.getSnapshot().data.symptom).toBe("fever");
    expect(session.getSnapshot().questions[0]?.label.fr).toBe("Symptôme");
  });

  it("evicts the least-recently-used translated instrument when the cache is full", async () => {
    let frenchImports = 0;
    let swahiliImports = 0;
    const loadLanguage = createWhoVaLanguageLoader(
      instrument,
      {
        fr: async () => {
          frenchImports += 1;
          return { locale: "fr", instrument: { questions: { symptom: { label: "Symptôme" } } } };
        },
        sw: async () => {
          swahiliImports += 1;
          return { locale: "sw", instrument: { questions: { symptom: { label: "Dalili" } } } };
        }
      },
      { maxCachedLanguages: 1 }
    );

    await loadLanguage("fr");
    await loadLanguage("sw");
    await loadLanguage("fr");

    expect(frenchImports).toBe(2);
    expect(swahiliImports).toBe(1);
  });
});
