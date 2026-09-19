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

    // 533 = 464 pristine WHO VA expressions + 40 added when the DigitVA
    // extension questions (ABHA, narration language, md_im1..30, ds_im1..5)
    // were composed into the instrument in src/digitva-extension.ts /
    // src/instrument.ts (commit 2fc60ea), + 3 added by WP-A2's conditional
    // composition: consent_mode's own relevance, and the ds_available/
    // md_available gate relevance now carried by ds_count/md_count, + 26
    // added by the social_autopsy layer mirrored from ND01 (the
    // reachinghealthcare/eventchronology group relevance, the sa06_a/sa03/
    // sa05/sa05_a/sa07_a/sa11/sa12/sa08 question relevance, the sa13..sa19
    // literal-comparison relevance, and the sa09/sa13..sa19 constraints).
    // This count is asserted explicitly, not derived from
    // whoVa2022Instrument, because the count under test is exactly
    // whoVa2022Instrument's own expression count — deriving it from the
    // instrument would make the assertion vacuous.
    expect(expressions).toHaveLength(533);
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

// XPath 1.0 string literals have no backslash escape mechanism: a backslash
// is an ordinary literal character, and the only quote-escaping convention
// is a doubled quote (`''` / `""`). These tests pin that rule directly at
// the tokenizer level, asserting the parsed literal VALUE rather than just
// "it parses" -- each one fails under the backslash-unescaping tokenizer
// this rule replaces (whether the pre-existing one that unescaped every
// backslash, or the intermediate one that special-cased only `\'`/`\"`).
describe("string literal tokenization", () => {
  function literalValue(source: string): unknown {
    const node = parseExpression(source);
    if (node.type !== "literal") throw new Error(`expected a literal node for ${source}`);
    return node.value;
  }

  it("preserves \\d untouched inside a regex() pattern (ND01's sa13..sa19 constraint)", () => {
    const source = "regex(.,'^(?!0{1,3}$)\\d{1,3}$')";
    const ast = parseExpression(source);
    expect(
      evaluateExpression(ast, {}, { currentValue: "5", now: new Date("2026-07-17T10:30:00.000Z") })
    ).toBe(true);
    expect(
      evaluateExpression(ast, {}, { currentValue: "000", now: new Date("2026-07-17T10:30:00.000Z") })
    ).toBe(false);
  });

  it("leaves a doubled backslash as two literal backslash characters", () => {
    expect(literalValue("'a\\\\b'")).toBe("a\\\\b");
  });

  it("does not throw on a literal ending in a backslash immediately before the closing quote", () => {
    // Regression case: a backslash-then-quote at the end of a literal must
    // not be read as an escaped quote, which would swallow the real
    // terminator and run the literal into the rest of the expression.
    const ast = parseExpression("'a\\\\' = 'x'");
    expect(evaluateExpression(ast, {}, { now: new Date("2026-07-17T10:30:00.000Z") })).toBe(false);
  });

  it("treats \\n as backslash-plus-n, never a newline", () => {
    const value = literalValue("'\\n'");
    expect(value).toBe("\\n");
    expect(value).not.toBe("\n");
  });

  it("still supports the doubled-quote escape convention in both quote styles", () => {
    expect(literalValue("'it''s'")).toBe("it's");
    expect(literalValue('"she said ""hi"""')).toBe('she said "hi"');
  });

  it("still throws on genuinely invalid syntax", () => {
    expect(() => parseExpression("1 +")).toThrow();
  });
});
