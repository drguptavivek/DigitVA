import { describe, expect, it } from "vitest";

import { ENGLISH_UI_MESSAGES } from "../src/i18n.js";
import type { InstrumentQuestion } from "../src/types.js";
import { instructionLabel, splitQuestionCode } from "../src/ui/form-presentation.js";
import { asciiDigits, constraintBounds, numericUnit } from "../src/ui/question-control-support.js";
import { dateBounds } from "../src/ui/question-controls.js";

function question(overrides: Partial<InstrumentQuestion>): InstrumentQuestion {
  return {
    name: "q",
    control: "integer",
    dataType: "int",
    label: { en: "How many days?" },
    required: false,
    sectionPath: [],
    order: 1,
    sourceRow: 1,
    ...overrides
  } as InstrumentQuestion;
}

describe("interviewer instruction labels", () => {
  it("strips the brackets and marks the label", () => {
    expect(instructionLabel("[Enter adult's age in years:]")).toEqual({
      instruction: true,
      text: "Enter adult's age in years:"
    });
  });
  it("tolerates whitespace inside and around the brackets", () => {
    expect(instructionLabel(" [ Please ask the following ] ")).toEqual({
      instruction: true,
      text: "Please ask the following"
    });
  });
  it("leaves an ordinary label alone, and a bracket in the middle", () => {
    expect(instructionLabel("What is the age?")).toEqual({ instruction: false, text: "What is the age?" });
    expect(instructionLabel("Age [years]")).toEqual({ instruction: false, text: "Age [years]" });
  });
  it("works on a Hindi label and on a translation without brackets", () => {
    expect(instructionLabel("[वयस्क की आयु वर्षों में दर्ज करें:]")).toEqual({
      instruction: true,
      text: "वयस्क की आयु वर्षों में दर्ज करें:"
    });
    expect(instructionLabel("वयस्क की आयु वर्षों में दर्ज करें:").instruction).toBe(false);
  });
  it("composes with the code chip split", () => {
    const { code, text } = splitQuestionCode("(Id10310) [ Please ask about pregnancy ]");
    expect(code).toBe("Id10310");
    expect(instructionLabel(text)).toEqual({ instruction: true, text: "Please ask about pregnancy" });
  });
});

describe("numeric field helpers", () => {
  it("normalises Indic digits to ASCII", () => {
    expect(asciiDigits("१२३")).toBe("123");
    expect(asciiDigits("৪৫")).toBe("45");
    expect(asciiDigits("೯೦")).toBe("90");
    expect(asciiDigits("42")).toBe("42");
  });
  it("reads literal bounds from a constraint and leaves special codes open", () => {
    expect(constraintBounds(question({ constraint: { source: "(.>=18 and .<90) or .=99" } }))).toEqual({
      min: 18,
      max: 89
    });
    expect(constraintBounds(question({ constraint: { source: ".>27 and .<=60" } }))).toEqual({
      min: 28,
      max: 60
    });
    expect(constraintBounds(question({ constraint: { source: ".>=0 and .<=${ageInDaysNeonate}" } }))).toEqual(
      {
        min: 0
      }
    );
    expect(constraintBounds(question({}))).toEqual({});
  });
  it("names a unit only when the label names exactly one", () => {
    expect(
      numericUnit(question({ label: { en: "[Enter child's age in months:]" } }), ENGLISH_UI_MESSAGES)
    ).toBe("months");
    expect(
      numericUnit(
        question({ label: { en: "What was the weight (in grammes) at birth?" } }),
        ENGLISH_UI_MESSAGES
      )
    ).toBe("grammes");
    expect(numericUnit(question({ label: { en: "How many (months/years)" } }), ENGLISH_UI_MESSAGES)).toBe("");
    expect(numericUnit(question({ label: { en: "Age of VA interviewer" } }), ENGLISH_UI_MESSAGES)).toBe("");
  });
});

describe("date picker bounds", () => {
  it("turns today() and literal dates into ISO min/max", () => {
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    expect(dateBounds(question({ control: "date", constraint: { source: ". <= today()" } }))).toEqual({
      max: iso
    });
    expect(
      dateBounds(
        question({ control: "date", constraint: { source: ". <= today() and .>= date(date('1915-01-01'))" } })
      )
    ).toEqual({ max: iso, min: "1915-01-01" });
    expect(
      dateBounds(question({ control: "date", constraint: { source: ".>=${Id10021} and . <= today()" } }))
    ).toEqual({ max: iso });
  });
});
