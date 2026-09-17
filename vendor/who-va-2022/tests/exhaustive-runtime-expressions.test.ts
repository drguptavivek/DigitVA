import { describe, expect, it } from "vitest";

import {
  applyCalculations,
  evaluateExpression,
  parseExpression,
  validateAnswer,
  whoVa2022Instrument,
  type AnswerValue,
  type InstrumentQuestion,
  type SubmissionData
} from "../src/index.js";

const NOW = new Date("2026-07-17T10:30:00.000Z");

const calculationSeed: SubmissionData = {
  Id10020: "yes",
  Id10021: "2000-06-20",
  Id10022: "yes",
  Id10023_a: "2026-07-17",
  age_group: "child",
  age_child_unit: "months",
  age_child_months: 18,
  id10120_unit: "months",
  Id10121: 2,
  Id10120_0: 2,
  Id10148_units: "months",
  Id10148_c: 2,
  Id10154_units: "months",
  Id10154_b: 2,
  id10161_unit: "years",
  Id10161_0: 2,
  Id10163: 2,
  Id10167_units: "months",
  Id10167_c: 2,
  Id10173_nc: ["periodic"],
  Id10182_units: "months",
  Id10182_b: 2,
  id10196_unit: "months",
  Id10198: 2,
  Id10201_unit: "months",
  Id10202: 2,
  Id10205_unit: "months",
  Id10206: 2,
  Id10209_units: "months",
  Id10209_b: 2,
  Id10213_units: "days",
  Id10213_a: 60,
  Id10216_units: "days",
  Id10216_b: 2,
  Id10232_units: "months",
  Id10232_b: 2,
  Id10248_units: "months",
  Id10248_b: 2,
  Id10250_units: "months",
  Id10250_b: 2,
  Id10262_units: "months",
  Id10262_b: 2,
  Id10266_units: "months",
  Id10266_b: 2,
  Id10274_units: "months",
  Id10274_c: 2
};

const constraintBase: SubmissionData = {
  ageInDays2: 20,
  ageInDaysNeonate: 20,
  ageInMonthsByYear: 24,
  ageInYears2: 5,
  Id10021: "2026-07-01",
  Id10176: 5,
  Id10114: "no",
  Id10098: "yes",
  Id10077_a: "more",
  Id10259: "no",
  Id10363: "yes",
  Id10387: "yes",
  Id10388: "yes",
  Id10413: "yes"
};

function expressionAst(question: InstrumentQuestion, key: "constraint" | "calculation") {
  const expression = question[key];
  if (!expression) throw new Error(`${question.name} has no ${key}`);
  return expression.ast ?? parseExpression(expression.source);
}

function validCurrentValue(question: InstrumentQuestion): AnswerValue {
  const source = question.constraint?.source ?? "";
  if (question.name === "age_group") return "adult";
  if (question.dataType === "date") return "2026-07-17";
  if (question.dataType === "string[]") {
    const exclusiveValues = ["None", "dk", "ref", "DK", "Ref", "all_over", "no"];
    return [question.choices?.find((choice) => !exclusiveValues.includes(choice.value))?.value ?? ""];
  }
  if (question.dataType === "string") {
    if (source.includes("regex(")) return "Jane Doe";
    if (source.includes("Id10413")) return question.choices?.[0]?.value ?? "yes";
    return "yes";
  }
  if (source.includes(".>27")) return 28;
  if (source.includes(".>11")) return 12;
  if (source.includes(".>0")) return 1;
  if (source.includes(".>=18")) return 18;
  if (source.includes(".>=1")) return 1;
  return 0;
}

function invalidCurrentValue(question: InstrumentQuestion): AnswerValue {
  const source = question.constraint?.source ?? "";
  if (question.name === "age_group") return "child";
  if (question.name === "Id10260") return "DK Ref";
  if (question.dataType === "date") return source.includes("Id10021") ? "2026-06-01" : "2999-01-01";
  if (question.dataType === "string[]") {
    const exclusive =
      ["None", "dk", "ref", "DK", "Ref", "all_over", "no"].find((value) => source.includes(`'${value}'`)) ??
      "no";
    const other = question.choices?.find((choice) => choice.value !== exclusive)?.value ?? exclusive;
    return [exclusive, other];
  }
  if (question.dataType === "string") {
    if (source.includes("regex(")) return "Jane123";
    if (source.includes("Id10387")) return "no";
    if (source.includes("Id10413")) return "cigarettes";
    return "no";
  }
  if (source.includes(".>27")) return 27;
  if (source.includes(".>11")) return 11;
  if (source.includes(".>0")) return 0;
  if (source.includes(".>=18")) return 17;
  if (source.includes(".>=1")) return 0;
  return -1;
}

function constraintData(question: InstrumentQuestion): SubmissionData {
  const data = { ...constraintBase };
  const source = question.constraint?.source ?? "";
  if (question.name === "age_group") data.ageInDays2 = 12 * 365.25 + 1;
  if (source.includes("Id10387")) {
    data.Id10387 = "no";
    data.Id10388 = "no";
  }
  if (source.includes("Id10413")) data.Id10413 = "no";
  return data;
}

describe("exhaustive WHO VA runtime expressions", () => {
  const calculatedQuestions = whoVa2022Instrument.questions.filter((question) => question.calculation);
  const constrainedQuestions = whoVa2022Instrument.questions.filter((question) => question.constraint);

  it("evaluates every calculation through the row-order calculation chain", () => {
    expect(calculatedQuestions).toHaveLength(38);

    const calculated = applyCalculations(whoVa2022Instrument, calculationSeed);

    for (const question of calculatedQuestions) {
      const expected = evaluateExpression(expressionAst(question, "calculation"), calculated);
      expect(calculated[question.name], question.name).toEqual(expected);
    }
  });

  it("accepts a valid current value for every configured constraint", () => {
    expect(constrainedQuestions).toHaveLength(88);

    for (const question of constrainedQuestions) {
      const data = constraintData(question);
      const value = validCurrentValue(question);
      const direct = evaluateExpression(expressionAst(question, "constraint"), data, {
        currentValue: value,
        now: NOW
      });
      const issues = validateAnswer(question, value, data);

      expect(direct, question.name).toBe(true);
      expect(issues, question.name).toEqual([]);
    }
  });

  it("rejects an invalid current value for every substantive configured constraint", () => {
    // These constraints are preserved from the XLSForm source, but their
    // forbidden values are not valid app choices for the compiled question.
    // They are therefore evaluable but cannot fire as constraint errors through
    // normal runtime validation.
    const inertConstraintNames = new Set(["Id10260", "Id10414", "Id10414_a", "Id10414_b"]);

    for (const question of constrainedQuestions) {
      const data = constraintData(question);
      const value = invalidCurrentValue(question);
      const direct = evaluateExpression(expressionAst(question, "constraint"), data, {
        currentValue: value,
        now: NOW
      });

      if (inertConstraintNames.has(question.name)) {
        expect(() =>
          evaluateExpression(expressionAst(question, "constraint"), data, { currentValue: value, now: NOW })
        ).not.toThrow();
        expect(validateAnswer(question, value, data), question.name).not.toContainEqual(
          expect.objectContaining({ code: "constraint", question: question.name })
        );
        continue;
      }

      expect(direct, question.name).toBe(false);
      expect(validateAnswer(question, value, data), question.name).toContainEqual(
        expect.objectContaining({ code: "constraint", question: question.name })
      );
    }
  });
});
