import { describe, expect, it } from "vitest";

import generatedInstrument from "../src/generated/who-va-2022.instrument.json";

import {
  getQuestion,
  isQuestionRelevant,
  validateAnswer,
  validateSubmission,
  whoVa2022Instrument,
  type AnswerValue,
  type InstrumentQuestion
} from "../src/index.js";

function unconstrainedInterviewerQuestion(): InstrumentQuestion {
  const question = { ...getQuestion(whoVa2022Instrument, "Id10010"), constraintMessage: {} };
  delete question.constraint;
  return question;
}

describe("shared field and submission validation", () => {
  it("exposes validation metadata on every generated WHO question", () => {
    for (const question of generatedInstrument.questions) {
      expect(question.validation).toBeDefined();
      expect(question.validation).toMatchObject({
        required: question.required,
        dataType: question.dataType,
        constraintMessage: question.constraintMessage
      });
      expect(question.validation.choiceValues ?? []).toEqual(
        question.choices?.map((choice) => choice.value) ?? []
      );
      expect(question.validation.constraint?.source).toBe(question.constraint?.source);
    }
  });

  it("rejects an unlisted coded value at the field boundary", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10010b");
    expect(validateAnswer(question, "unknown", {})).toEqual([
      expect.objectContaining({ question: "Id10010b", code: "choice" })
    ]);
  });

  it("evaluates question relevance without a renderer", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10019");
    expect(isQuestionRelevant(whoVa2022Instrument, question, { Id10013: "yes" })).toBe(true);
    expect(isQuestionRelevant(whoVa2022Instrument, question, { Id10013: "no" })).toBe(false);
  });

  it("enforces the XLSForm constraint and message for interviewer age", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10010a");
    expect(validateAnswer(question, 17, {})).toEqual([
      expect.objectContaining({
        question: "Id10010a",
        code: "constraint",
        message: "Interviewer should be an adult and not older than 89"
      })
    ]);
    expect(validateAnswer(question, 18, {})).toEqual([]);
    expect(validateAnswer(question, 99, {})).toEqual([]);
  });

  it("rejects alphanumeric and special characters in the interviewer name", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10010");
    expect(validateAnswer(question, "Anita Rao", {})).toEqual([]);
    expect(validateAnswer(question, "Anita2", {})).toEqual([
      expect.objectContaining({
        question: "Id10010",
        code: "constraint",
        message: "Interviewer name can contain letters and spaces only"
      })
    ]);
    expect(validateAnswer(question, "Anita-Rao", {})).toEqual([
      expect.objectContaining({ question: "Id10010", code: "constraint" })
    ]);
  });

  it("rejects alphanumeric and special characters in the respondent name", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10007");
    expect(validateAnswer(question, "Ravi Kumar", {})).toEqual([]);
    expect(validateAnswer(question, "Ravi2", {})).toEqual([
      expect.objectContaining({
        question: "Id10007",
        code: "constraint",
        message: "Respondent name can contain letters and spaces only"
      })
    ]);
    expect(validateAnswer(question, "Ravi-Kumar", {})).toEqual([
      expect.objectContaining({ question: "Id10007", code: "constraint" })
    ]);
  });

  it("enforces the complete labour-duration coding rule for Id10382", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10382");
    const expectedMessage =
      "Enter a whole number of hours from 0 to 98. Use 0 for less than 1 hour; use 23 or 25 when only the less-than or more-than-24-hour estimate is known; use 88 for refused; and use 99 for don't know. If the actual duration was 88 hours, enter 87.";

    expect(validateAnswer(question, -1, {})).toEqual([
      expect.objectContaining({ question: "Id10382", code: "constraint", message: expectedMessage })
    ]);
    expect(validateAnswer(question, 12.5, {})).toEqual([
      expect.objectContaining({ question: "Id10382", code: "type" })
    ]);
    expect(validateAnswer(question, 100, {})).toEqual([
      expect.objectContaining({ question: "Id10382", code: "constraint", message: expectedMessage })
    ]);
    for (const value of [0, 12, 23, 25, 87, 88, 98, 99]) {
      expect(validateAnswer(question, value, {})).toEqual([]);
    }
  });

  it("explains the date-of-death constraint in interviewer-facing language", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10023_a");
    expect(validateAnswer(question, "2026-07-01", { Id10021: "2026-07-05" })).toEqual([
      {
        question: "Id10023_a",
        code: "constraint",
        message: "Date of death must be on or after the date of birth and cannot be in the future."
      }
    ]);
  });

  it.each(["2026-02-29", "2026-02-30", "2026-04-31", "2026-13-01"])(
    "rejects the impossible ISO date %s at the public validation boundary",
    (value) => {
      const question = getQuestion(whoVa2022Instrument, "Id10021");
      expect(validateAnswer(question, value, { Id10021: value })).toEqual([
        expect.objectContaining({ question: "Id10021", code: "type" })
      ]);
    }
  );

  it("accepts a valid leap day at the public validation boundary", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10021");
    expect(validateAnswer(question, "2024-02-29", { Id10021: "2024-02-29" })).toEqual([]);
  });

  it.each([{}, { name: "orphaned.jpg" }, { uri: "" }, { uri: "   " }])(
    "rejects the malformed attachment answer %j",
    (value) => {
      const question = {
        ...unconstrainedInterviewerQuestion(),
        name: "attachment",
        control: "file" as const,
        dataType: "attachment" as const,
        constraintMessage: {}
      };

      expect(validateAnswer(question, value as AnswerValue, {})).toEqual([
        expect.objectContaining({ question: "attachment", code: "type" })
      ]);
    }
  );

  it("accepts an attachment object with a non-empty locator", () => {
    const question = {
      ...unconstrainedInterviewerQuestion(),
      name: "attachment",
      control: "file" as const,
      dataType: "attachment" as const,
      constraintMessage: {}
    };

    expect(validateAnswer(question, { uri: "who-va-attachment:stored-id" }, {})).toEqual([]);
  });

  it.each([{}, { startedAt: "" }, { startedAt: "not-a-timestamp" }, { startedAt: "0" }])(
    "rejects the malformed audit answer %j",
    (value) => {
      const question = {
        ...unconstrainedInterviewerQuestion(),
        name: "audit",
        sourceType: "audit",
        control: "system" as const,
        dataType: "audit" as const,
        constraintMessage: {}
      };

      expect(validateAnswer(question, value as AnswerValue, {})).toEqual([
        expect.objectContaining({ question: "audit", code: "type" })
      ]);
    }
  );

  it("accepts a timestamped audit record through the system-control boundary", () => {
    const question = {
      ...unconstrainedInterviewerQuestion(),
      name: "audit",
      sourceType: "audit",
      control: "system" as const,
      dataType: "audit" as const,
      constraintMessage: {}
    };

    expect(validateAnswer(question, { startedAt: "2026-07-18T12:00:00.000Z" }, {})).toEqual([]);
  });

  it("accepts a baby reported as neither under 2.5 kg nor over 4.5 kg", () => {
    const question = getQuestion(whoVa2022Instrument, "Id10365");
    const data = { Id10363: "no", Id10365: "no" };

    expect(validateAnswer(question, "no", data)).toEqual([]);
    expect(
      validateSubmission(
        { ...whoVa2022Instrument, sections: [], questions: [{ ...question, sectionPath: [] }] },
        data
      )
    ).toMatchObject({ valid: true, issues: [] });
  });

  it("does not require a question when its relevance path is false", () => {
    const result = validateSubmission(whoVa2022Instrument, { Id10013: "no" });
    expect(result.issues.some((issue) => issue.question === "Id10019" && issue.code === "required")).toBe(
      false
    );
  });
});
