import { describe, expect, it } from "vitest";

import { evaluateExpression, parseExpression } from "../src/index.js";

describe("portable XLSForm expression engine", () => {
  it("parses and evaluates coded-choice relevance without a UI runtime", () => {
    const expression = parseExpression("selected(${Id10013}, 'yes')");

    expect(expression).toEqual({
      type: "call",
      name: "selected",
      arguments: [
        { type: "reference", name: "Id10013" },
        { type: "literal", value: "yes" }
      ]
    });
    expect(evaluateExpression(expression, { Id10013: "yes" })).toBe(true);
    expect(evaluateExpression(expression, { Id10013: "no" })).toBe(false);
  });
});
