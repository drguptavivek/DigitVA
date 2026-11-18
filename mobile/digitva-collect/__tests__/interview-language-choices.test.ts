import type { InstrumentDefinition } from "@drguptavivek/who-2022-va";

import { addInterviewLanguages } from "../src/formDefinitions";

// digitva-te2a: "Interview language" (`language`) offers the project's Narration languages setting.
const instrument = () => ({
  questions: [
    { name: "language", choices: [{ value: "en", label: { en: "English" }, sourceRow: 3 }], validation: { choiceValues: ["en"] } },
  ],
}) as unknown as InstrumentDefinition;

test("adds the narration languages after English, in their own script, without a second English", () => {
  const copy = instrument();
  addInterviewLanguages(copy, [
    { code: "english", label: "English" },
    { code: "hindi", label: "Hindi" },
    { code: "khasi", label: "Khasi" },
  ]);
  const question = copy.questions[0];
  expect(question.choices?.map((choice) => choice.value)).toEqual(["en", "hindi", "khasi"]);
  expect(question.choices?.[1].label).toEqual({ en: "Hindi", hindi: "हिन्दी" });
  expect(question.choices?.[2].label).toEqual({ en: "Khasi" });
  expect(question.validation?.choiceValues).toEqual(["en", "hindi", "khasi"]);
});

test("no narration languages leaves English alone", () => {
  const copy = instrument();
  addInterviewLanguages(copy, []);
  expect(copy.questions[0].choices?.map((choice) => choice.value)).toEqual(["en"]);
});
