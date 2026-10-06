import type { InstrumentDefinition } from "@drguptavivek/who-2022-va";
import { applyTranslations } from "../src/translations";

it("localizes constraint messages without changing the English instrument", () => {
  const instrument = {
    sections: [],
    questions: [
      {
        name: "question",
        label: { en: "Question" },
        hint: { en: "English hint" },
        guidance: { en: "English guidance" },
        constraintMessage: { en: "English validation message" }
      }
    ]
  } as unknown as InstrumentDefinition;

  const translated = applyTranslations(
    instrument,
    {
      questions: {
        question: {
          label: "Pregunta",
          hint: "Pista",
          guidance_hint: "",
          constraint_message: "Mensaje de validación"
        }
      }
    },
    "es"
  );
  const translatedQuestion = translated.questions[0] as unknown as Record<
    string,
    Record<string, string>
  >;

  expect(translatedQuestion.constraintMessage).toEqual({
    en: "English validation message",
    es: "Mensaje de validación"
  });
  expect(translatedQuestion.label).toEqual({ en: "Question", es: "Pregunta" });
  expect(translatedQuestion.hint).toEqual({ en: "English hint", es: "Pista" });
  expect(translatedQuestion.guidance).toEqual({ en: "English guidance" });
  expect((instrument.questions[0] as unknown as Record<string, unknown>).constraintMessage).toEqual({
    en: "English validation message"
  });
});
