import { describe, expect, it } from "vitest";

import { evaluateExpression, parseExpression, whoVa2022Instrument } from "../src/index.js";

describe("WHO VA expression semantics", () => {
  it.each([
    ["selected(${single}, 'yes')", { single: "yes" }, undefined, true],
    ["selected(${multiple}, 'yes')", { multiple: ["no", "yes"] }, undefined, true],
    ["count-selected(.) = 2", {}, ["one", "two"], true],
    ["not(selected(., 'dk'))", {}, ["yes"], true],
    ["regex(., '^[A-Za-z ]+$')", {}, "Anita Rao", true],
    ["string-length(${missing}) = 0", {}, undefined, true],
    ["if(${missing} = 'NaN', 12, 0)", { missing: Number.NaN }, undefined, 12],
    ["int(27 div 12)", {}, undefined, 2],
    ["27 mod 12", {}, undefined, 3],
    ["date('2026-07-17') - date('2026-06-20')", {}, undefined, 27],
    [". <= today()", {}, "2026-07-17", true],
    ["if(true, 1, null)", {}, undefined, 1]
  ])("evaluates %s", (source, data, currentValue, expected) => {
    expect(
      evaluateExpression(parseExpression(source as string), data, {
        currentValue,
        now: new Date("2026-07-17T10:30:00.000Z")
      })
    ).toEqual(expected);
  });

  it("can evaluate every compiled calculation, relevance, and constraint AST", () => {
    const expressions = [
      ...whoVa2022Instrument.questions.flatMap((question) =>
        [question.calculation, question.relevant, question.constraint].filter((value) => value != null)
      ),
      ...whoVa2022Instrument.sections.flatMap((section) => (section.relevant ? [section.relevant] : []))
    ];

    expect(expressions).toHaveLength(464);
    for (const expression of expressions) {
      expect(
        () =>
          evaluateExpression(
            expression.ast ?? parseExpression(expression.source),
            {},
            { currentValue: undefined, now: new Date("2026-07-17T10:30:00.000Z") }
          ),
        expression.source
      ).not.toThrow();
    }
  });
});
