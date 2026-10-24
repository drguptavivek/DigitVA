import { describe, expect, it } from "vitest";

import { createWhoVa2022Instrument } from "../src/instrument.js";
import { validateAnswer } from "../src/engine/validation.js";

// Owner rule 2026-10-24 (digitva-y5te): Id10071 is neither in the future nor
// before the death (the day when known, else only the year).
const question = createWhoVa2022Instrument(new Set(["digitva_core"])).questions.find(
  (candidate) => candidate.name === "Id10071"
)!;
const check = (value: string, data: Record<string, unknown> = {}, locale = "en") =>
  validateAnswer(question, value, { ...data, Id10071: value } as never, locale).map((issue) => issue.message);

const BEFORE = "Date of registration cannot be before the date of death.";
const FUTURE = "Date of registration cannot be in the future.";
const KNOWN_DAY = { Id10022: "yes", Id10023: "2024-05-10" };
const YEAR_ONLY = { Id10022: "no", Id10024: "2024-01-01" };
const iso = (offsetDays: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

describe("Id10071 date of registration", () => {
  it("rejects a registration before the known date of death, accepts the same day and later", () => {
    expect(check("2024-05-09", KNOWN_DAY)).toEqual([BEFORE]);
    expect(check("2024-05-10", KNOWN_DAY)).toEqual([]);
    expect(check("2024-06-01", KNOWN_DAY)).toEqual([]);
  });

  it("with only the death year, rejects an earlier year and never a same-year date", () => {
    expect(check("2023-12-31", YEAR_ONLY)).toEqual([BEFORE]);
    expect(check("2024-01-01", YEAR_ONLY)).toEqual([]);
    expect(check("2024-02-15", YEAR_ONLY)).toEqual([]);
    expect(check("2023-12-31", { Id10022: "ref", Id10024: "2024-01-01" })).toEqual([BEFORE]);
  });

  it("rejects the future, today is fine", () => {
    expect(check(iso(1), KNOWN_DAY)).toEqual([FUTURE]);
    expect(check(iso(0), KNOWN_DAY)).toEqual([]);
  });

  it("with an unknown death date checks only the future", () => {
    expect(check("1990-01-01")).toEqual([]);
    expect(check("1990-01-01", { Id10022: "no" })).toEqual([]);
    expect(check(iso(1))).toEqual([FUTURE]);
  });

  it("says it in Hindi", () => {
    expect(check("2024-05-09", KNOWN_DAY, "hi")[0]).toContain("मृत्यु की तारीख से पहले");
    expect(check(iso(1), KNOWN_DAY, "hi")[0]).toContain("भविष्य");
  });

  it("is kept when WHO overrides are off (the server composition)", () => {
    const server = createWhoVa2022Instrument(new Set(["digitva_core"]), { whoOverrides: false });
    expect(server.questions.find((candidate) => candidate.name === "Id10071")?.constraint?.source).toBe(
      question.constraint?.source
    );
  });
});
