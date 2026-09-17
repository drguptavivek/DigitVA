import { describe, expect, it } from "vitest";

import { whoVa2022Instrument } from "../src/instrument.js";
import { dateFormatPlaceholder, formatDisplayDate, parseDisplayDate } from "../src/ui/date-value.js";

describe("shared WHO date control", () => {
  it("routes every generated WHO date question through the shared date control", () => {
    expect(
      whoVa2022Instrument.questions
        .filter((question) => question.control === "date")
        .map((question) => question.name)
    ).toEqual(["Id10021", "Id10023_a", "Id10023_b", "Id10024", "Id10071"]);
    expect(whoVa2022Instrument.questions.find((question) => question.name === "Id10024")?.appearance).toBe(
      "year"
    );
  });

  it.each([
    ["en-GB", "DD-MMM-YYYY", "17-Jul-2026"],
    ["en-US", "MMM-DD-YYYY", "Jul-17-2026"],
    ["ja-JP", "YYYY-MMM-DD", "2026-7月-17"]
  ])("uses locale date ordering for %s", (locale, placeholder, display) => {
    expect(dateFormatPlaceholder(locale)).toBe(placeholder);
    expect(formatDisplayDate("2026-07-17", locale)).toBe(display);
    expect(parseDisplayDate(display, locale)).toBe("2026-07-17");
  });

  it("rejects impossible fallback dates", () => {
    expect(parseDisplayDate("31-Feb-2026", "en-GB")).toBeUndefined();
  });
});
