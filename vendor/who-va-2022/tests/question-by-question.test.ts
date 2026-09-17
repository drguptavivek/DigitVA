import { describe, expect, it } from "vitest";

import {
  isQuestionRelevant,
  validateAnswer,
  validateSubmission,
  whoVa2022Instrument,
  type AnswerValue,
  type ExpressionNode,
  type InstrumentQuestion
} from "../src/index.js";

const knownNames = new Set(whoVa2022Instrument.questions.map((question) => question.name));

function references(node: ExpressionNode | undefined): string[] {
  if (!node) return [];
  switch (node.type) {
    case "reference":
      return [node.name];
    case "unary":
      return references(node.operand);
    case "binary":
      return [...references(node.left), ...references(node.right)];
    case "call":
      return node.arguments.flatMap(references);
    default:
      return [];
  }
}

function invalidTypeValue(question: InstrumentQuestion): AnswerValue | undefined {
  switch (question.dataType) {
    case "string":
      return 42;
    case "number":
      return "not-a-number";
    case "boolean":
      return "not-a-boolean";
    case "date":
      return "17/07/2026";
    case "dateTime":
      return "not-a-date-time";
    case "string[]":
      return "not-an-array";
    case "attachment":
      return 42;
    case "audit":
      return "not-an-audit-object";
    case "calculated":
    case "none":
      return undefined;
  }
}

function representativeValue(question: InstrumentQuestion): AnswerValue | undefined {
  switch (question.dataType) {
    case "string":
      return question.choices?.[0]?.value ?? "test";
    case "number":
      return 1;
    case "boolean":
      return true;
    case "date":
      return "2020-01-01";
    case "dateTime":
      return "2020-01-01T00:00:00.000Z";
    case "string[]":
      return question.choices?.[0] ? [question.choices[0].value] : ["test"];
    case "attachment":
      return { uri: "attachment://test" };
    case "audit":
      return { startedAt: "2020-01-01T00:00:00.000Z" };
    case "calculated":
    case "none":
      return undefined;
  }
}

function isolatedQuestion(question: InstrumentQuestion): InstrumentQuestion {
  const { relevant: _relevant, ...withoutRelevance } = question;
  return { ...withoutRelevance, sectionPath: [] };
}

describe("question-by-question canonical runtime contract", () => {
  it.each(whoVa2022Instrument.questions.map((question) => [question.name, question] as const))(
    "%s has coherent choices, expressions, and validation behavior",
    (name, generated) => {
      const choiceValues = generated.choices?.map((choice) => choice.value) ?? [];
      expect(new Set(choiceValues).size).toBe(choiceValues.length);
      for (const choice of generated.choices ?? []) expect(choice.label.en).toBeTruthy();

      for (const expression of [generated.relevant, generated.constraint, generated.calculation]) {
        if (!expression) continue;
        expect(expression.ast).toBeDefined();
        for (const dependency of references(expression.ast)) {
          expect(knownNames.has(dependency), `${name} references unknown question ${dependency}`).toBe(true);
        }
      }

      expect(() => isQuestionRelevant(whoVa2022Instrument, generated, {})).not.toThrow();
      const invalidValue = invalidTypeValue(generated);
      if (invalidValue !== undefined && !["note", "calculated", "system"].includes(generated.control)) {
        const fieldIssues = validateAnswer(generated, invalidValue, {});
        expect(fieldIssues.some((issue) => issue.code === "type")).toBe(true);
        const isolated = isolatedQuestion(generated);
        const submission = validateSubmission(
          { ...whoVa2022Instrument, sections: [], questions: [isolated] },
          { [generated.name]: invalidValue }
        );
        expect(submission.issues.map((issue) => issue.code)).toEqual(fieldIssues.map((issue) => issue.code));
      }
      if (generated.choices?.length) {
        const invalidChoice: AnswerValue =
          generated.dataType === "string[]" ? ["__not_a_who_value__"] : "__not_a_who_value__";
        expect(validateAnswer(generated, invalidChoice, {}).some((issue) => issue.code === "choice")).toBe(
          true
        );
      }
      const sample = representativeValue(generated);
      if (sample !== undefined && !["note", "calculated", "system"].includes(generated.control)) {
        const fieldIssues = validateAnswer(generated, sample, { [generated.name]: sample });
        expect(fieldIssues.some((issue) => issue.code === "unsupported-expression")).toBe(false);
        const isolated = isolatedQuestion(generated);
        const submission = validateSubmission(
          { ...whoVa2022Instrument, sections: [], questions: [isolated] },
          { [generated.name]: sample }
        );
        expect(submission.issues.map((issue) => issue.code)).toEqual(fieldIssues.map((issue) => issue.code));
      }
    }
  );
});
