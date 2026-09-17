import { describe, expect, it } from "vitest";

import {
  applyCalculations,
  createWhoVaSession,
  evaluateExpression,
  parseExpression,
  validateSubmission,
  whoVa2022Instrument,
  type InstrumentDefinition,
  type SubmissionData
} from "../src/index.js";

const calculatedQuestions = whoVa2022Instrument.questions.filter((question) => question.calculation);
const questionOrder = new Map(
  whoVa2022Instrument.questions.map((question) => [question.name, question.order])
);

function references(source: string): string[] {
  return [...source.matchAll(/\$\{([^}]+)\}/g)].map((match) => match[1] as string);
}

describe("WHO VA sequential calculation graph", () => {
  it("keeps every calculation dependency on an earlier XLSForm row", () => {
    expect(calculatedQuestions).toHaveLength(38);

    for (const question of calculatedQuestions) {
      for (const dependency of references(question.calculation?.source ?? "")) {
        expect(
          questionOrder.get(dependency),
          `${question.name} references unknown ${dependency}`
        ).toBeDefined();
        expect(
          questionOrder.get(dependency),
          `${question.name} must be calculated after ${dependency}`
        ).toBeLessThan(question.order);
      }
    }
  });

  it("settles the complete known-date age chain in row order", () => {
    const result = applyCalculations(whoVa2022Instrument, {
      Id10020: "yes",
      Id10021: "2026-06-20",
      Id10022: "yes",
      Id10023_a: "2026-07-17",
      // Persisted calculated values are never trusted; the current answers
      // must replace them and settle every downstream intermediate again.
      ageInDays: 999,
      isNeonatal: "0"
    });

    expect(result).toMatchObject({
      Id10023: "2026-07-17",
      ageInDays: 27,
      ageInYears: 0,
      ageInYearsRemain: 27,
      ageInMonths: 0,
      ageInMonthsRemain: 27,
      isNeonatal1: "1",
      isChild1: "0",
      isAdult1: "0",
      isNeonatal: "1",
      isChild: "0",
      isAdult: "0",
      ageInDaysNeonate: 27
    });
  });

  it("re-settles downstream intermediates when an earlier answer changes", () => {
    const session = createWhoVaSession(whoVa2022Instrument, {
      initialData: {
        Id10020: "yes",
        Id10021: "2026-06-20",
        Id10022: "yes",
        Id10023_a: "2026-07-17"
      }
    });

    expect(session.getSnapshot().data).toMatchObject({ ageInDays: 27, isNeonatal: "1", isChild: "0" });

    session.setAnswer("Id10021", "2026-06-19");

    const data = session.getSnapshot().data;
    const childNote = whoVa2022Instrument.questions.find((question) => question.name === "displayAgeChild");
    const neonateNote = whoVa2022Instrument.questions.find(
      (question) => question.name === "displayAgeNeonate"
    );
    expect(data).toMatchObject({ ageInDays: 28, isNeonatal: "0", isChild: "1" });
    expect(
      evaluateExpression(childNote!.relevant!.ast ?? parseExpression(childNote!.relevant!.source), data)
    ).toBe(true);
    expect(
      evaluateExpression(neonateNote!.relevant!.ast ?? parseExpression(neonateNote!.relevant!.source), data)
    ).toBe(false);
  });

  it.each([
    {
      label: "neonate fallback",
      input: { age_group: "neonate", age_neonate_days: 12 },
      expected: { isNeonatal: "1", isChild: "0", isAdult: "0", ageInDaysNeonate: 12 }
    },
    {
      label: "child fallback",
      input: { age_group: "child", age_child_unit: "months", age_child_months: 18 },
      expected: { isNeonatal: "0", isChild: "1", isAdult: "0", ageInMonthsByYear: 18, ageInYears2: 1 }
    },
    {
      label: "adult fallback",
      input: { age_group: "adult", age_adult: 40 },
      expected: { isNeonatal: "0", isChild: "0", isAdult: "1", ageInMonthsByYear: 480, ageInYears2: 40 }
    }
  ])("settles the $label intermediate chain", ({ input, expected }) => {
    expect(applyCalculations(whoVa2022Instrument, input)).toMatchObject(expected);
  });

  it("evaluates every later duration-conversion calculation from current submission values", () => {
    const input: SubmissionData = {
      age_group: "child",
      age_child_unit: "months",
      age_child_months: 18,
      id10120_unit: "months",
      Id10121: 2,
      Id10148_units: "months",
      Id10148_c: 2,
      Id10154_units: "months",
      Id10154_b: 2,
      id10161_unit: "years",
      Id10163: 2,
      Id10167_units: "months",
      Id10167_c: 2,
      Id10173_nc: 4,
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

    expect(applyCalculations(whoVa2022Instrument, input)).toMatchObject({
      Id10120: 60,
      Id10148: 60,
      Id10154: 60,
      Id10161: 730,
      Id10167: 60,
      Id10173: 4,
      Id10182: 60,
      Id10197: 60,
      Id10201: 60,
      Id10205: 60,
      Id10209: 60,
      Id10213: 2,
      Id10216: 48,
      Id10232: 60,
      Id10248: 60,
      Id10250: 60,
      Id10262: 60,
      Id10266: 60,
      Id10274: 60
    });
  });

  it("omits relevance-gated calculated outputs when their branch is inactive", () => {
    const instrument: InstrumentDefinition = {
      id: "relevant-calculation",
      title: "Relevant calculation",
      version: "1",
      defaultLanguage: "English (en)",
      sourceFile: "test.xlsx",
      sections: [{ name: "main", sourceRow: 1, order: 1, label: { en: "Main" } }],
      questions: [
        {
          name: "enabled",
          order: 1,
          sourceRow: 2,
          sourceType: "text",
          dataType: "string",
          control: "text",
          label: { en: "Enabled" },
          hint: {},
          guidance: {},
          required: false,
          readOnly: false,
          constraintMessage: {},
          sectionPath: ["main"]
        },
        {
          name: "input",
          order: 2,
          sourceRow: 3,
          sourceType: "integer",
          dataType: "number",
          control: "integer",
          label: { en: "Input" },
          hint: {},
          guidance: {},
          required: false,
          readOnly: false,
          constraintMessage: {},
          sectionPath: ["main"]
        },
        {
          name: "output",
          order: 3,
          sourceRow: 4,
          sourceType: "calculate",
          dataType: "calculated",
          control: "calculated",
          label: {},
          hint: {},
          guidance: {},
          required: false,
          readOnly: true,
          constraintMessage: {},
          relevant: { source: "${enabled} = 'yes'" },
          calculation: { source: "${input} * 2" },
          sectionPath: ["main"]
        }
      ]
    };

    expect(validateSubmission(instrument, { enabled: "no", input: 30 }).data.output).toBeUndefined();
    expect(validateSubmission(instrument, { enabled: "yes", input: 30 }).data.output).toBe(60);
  });
});
