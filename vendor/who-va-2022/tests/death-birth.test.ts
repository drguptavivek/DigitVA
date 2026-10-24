import { describe, expect, it } from "vitest";

import { createWhoVa2022Instrument } from "../src/instrument.js";
import { validateAnswer } from "../src/engine/validation.js";

// Owner rule 2026-10-24 (digitva-08bj): the year of death (Id10024) is not
// before the year of birth, same year valid; the exact death date asked without
// a full birth date (Id10023_b) is not before the partial birth date.
const instrument = createWhoVa2022Instrument(new Set(["digitva_core", "doris_support_whova_2022"]));
const find = (name: string, source = instrument) => source.questions.find((q) => q.name === name)!;
const check = (name: string, value: string, data: Record<string, unknown> = {}, locale = "en") =>
  validateAnswer(find(name), value, { ...data, [name]: value } as never, locale).map((issue) => issue.message);

const YEAR = "The year of death cannot be before the year of birth.";
const DATE = "The date of death cannot be before the date of birth.";
const DOB = { Id10020: "yes", Id10021: "2020-06-15" };
const MONTH = { Id10020: "no", dob_precision: "month_year", dob_month_year: "2020-06-01" };
const BIRTH_YEAR = { Id10020: "no", dob_precision: "year", dob_year: "2020-01-01" };

describe("Id10024 year of death", () => {
  it.each([
    ["Id10021", DOB],
    ["dob_month_year", MONTH],
    ["dob_year", BIRTH_YEAR]
  ])("is not before the birth year (%s)", (_source, data) => {
    expect(check("Id10024", "2019-01-01", data)).toEqual([YEAR]);
    expect(check("Id10024", "2020-01-01", data)).toEqual([]);
    expect(check("Id10024", "2021-01-01", data)).toEqual([]);
  });

  it("accepts the birth year itself through 31 December, leap or ordinary, and rejects the next 1 January", () => {
    expect(check("Id10024", "2024-01-01", { ...DOB, Id10021: "2024-12-31" })).toEqual([]);
    expect(check("Id10024", "2023-01-01", { ...DOB, Id10021: "2023-12-31" })).toEqual([]);
    expect(check("Id10024", "2000-01-01", { ...DOB, Id10021: "2000-12-31" })).toEqual([]);
    expect(check("Id10024", "2024-01-01", { ...DOB, Id10021: "2025-01-01" })).toEqual([YEAR]);
    expect(check("Id10024", "2023-01-01", { ...DOB, Id10021: "2024-01-01" })).toEqual([YEAR]);
    expect(check("Id10024", "1999-01-01", { ...DOB, Id10021: "2000-01-01" })).toEqual([YEAR]);
  });

  it("with no birth known keeps only the existing checks", () => {
    expect(check("Id10024", "1990-01-01")).toEqual([]);
    expect(check("Id10024", "1990-01-01", { Id10020: "no" })).toEqual([]);
    expect(check("Id10024", "1900-01-01")).not.toEqual([]);
    expect(check("Id10024", "2999-01-01")).not.toEqual([]);
  });

  it("ignores a birth answer whose branch is no longer taken", () => {
    expect(check("Id10024", "2019-01-01", { ...DOB, Id10020: "no" })).toEqual([]);
    expect(check("Id10024", "2019-01-01", { ...MONTH, dob_precision: "year" })).toEqual([]);
  });

  it("says it in Hindi", () => {
    expect(check("Id10024", "2019-01-01", DOB, "hi")[0]).toContain("जन्म के वर्ष से पहले");
  });

  it("is kept when WHO overrides are off (the server composition)", () => {
    const server = createWhoVa2022Instrument(new Set(["digitva_core"]), { whoOverrides: false });
    expect(find("Id10024", server).constraint?.source).toBe(find("Id10024").constraint?.source);
    expect(find("Id10023_b", server).constraint?.source).toBe(find("Id10023_b").constraint?.source);
  });
});

describe("Id10023_b date of death", () => {
  it("is not before a month-and-year or year-only birth; the same month or year is valid", () => {
    expect(check("Id10023_b", "2020-05-31", MONTH)).toEqual([DATE]);
    expect(check("Id10023_b", "2020-06-01", MONTH)).toEqual([]);
    expect(check("Id10023_b", "2020-06-20", MONTH)).toEqual([]);
    expect(check("Id10023_b", "2019-12-31", BIRTH_YEAR)).toEqual([DATE]);
    expect(check("Id10023_b", "2020-01-01", BIRTH_YEAR)).toEqual([]);
  });

  it("with no birth known checks only the future; Hindi message", () => {
    expect(check("Id10023_b", "1990-01-01", { Id10020: "no" })).toEqual([]);
    expect(check("Id10023_b", "2999-01-01", MONTH)).toEqual(["Date of death cannot be in the future."]);
    expect(check("Id10023_b", "2019-12-31", BIRTH_YEAR, "hi")[0]).toContain("जन्म की तारीख से पहले");
  });

  it("Id10023_a keeps WHO's own not-before-birth check", () => {
    expect(find("Id10023_a").constraint?.source).toContain("${Id10021}");
    expect(check("Id10023_a", "2020-06-14", { ...DOB, Id10022: "yes" })).not.toEqual([]);
    expect(check("Id10023_a", "2020-06-15", { ...DOB, Id10022: "yes" })).toEqual([]);
  });
});
