import { describe, expect, it } from "vitest";

import { createWhoVaSession } from "../src/engine/session.js";
import { createWhoVa2022Instrument } from "../src/instrument.js";
import {
  ageGroupOfDays,
  ageSuggestions,
  boundaryFix,
  deriveAge,
  narrationLanguageFromText,
  narrationLanguageSuggestion
} from "../src/ui/assists.js";

const ALL = new Set([
  "age_group",
  "age_neonate_days",
  "age_child_unit",
  "age_child_days",
  "age_child_months",
  "age_child_years",
  "age_adult"
]);
const exact = (dob: string, dod: string) => ({ Id10020: "yes", Id10021: dob, Id10022: "yes", Id10023: dod });
const yearsOnly = (dobYear: number, dodYear: number) => ({
  Id10020: "no",
  dob_precision: "year",
  dob_year: `${dobYear}-01-01`,
  Id10022: "no",
  Id10024: `${dodYear}-01-01`
});

describe("age group thresholds", () => {
  it("matches isNeonatal1 / isChild1 / isAdult1 exactly", () => {
    expect(ageGroupOfDays(27)).toBe("neonate");
    expect(ageGroupOfDays(28)).toBe("child");
    expect(ageGroupOfDays(4382)).toBe("child");
    expect(ageGroupOfDays(4383)).toBe("adult");
  });
});

describe("deriveAge", () => {
  it("uses the exact number of days between exact dates", () => {
    expect(deriveAge(exact("2026-01-01", "2026-01-26"))).toEqual({ precision: "exact", days: 25, group: "neonate" });
    expect(deriveAge(exact("2020-01-01", "2024-01-01"))?.group).toBe("child");
    expect(deriveAge(exact("1980-01-01", "2024-01-01"))?.group).toBe("adult");
  });

  it("suggests from years only when unambiguous: 1..11 child, 13+ adult, 0 and 12 nothing", () => {
    expect(deriveAge(yearsOnly(2017, 2021))).toMatchObject({ precision: "years", years: 4, group: "child" });
    expect(deriveAge(yearsOnly(2010, 2021))?.group).toBe("child");
    expect(deriveAge(yearsOnly(2008, 2021))?.group).toBe("adult");
    expect(deriveAge(yearsOnly(2021, 2021))?.group).toBeUndefined();
    expect(deriveAge(yearsOnly(2009, 2021))?.group).toBeUndefined();
  });

  it("uses the year difference when one date is only a year", () => {
    const data = { Id10020: "yes", Id10021: "2017-06-01", Id10022: "no", Id10024: "2021-01-01" };
    expect(deriveAge(data)).toMatchObject({ precision: "years", years: 4, group: "child" });
  });

  it("gives a month-precision birth a group only when every day in the month fits one", () => {
    const base = { Id10020: "no", dob_precision: "month_year", Id10022: "yes" };
    expect(deriveAge({ ...base, dob_month_year: "1960-03-01", Id10023: "2024-01-01" })?.group).toBe("adult");
    expect(deriveAge({ ...base, dob_month_year: "2023-12-01", Id10023: "2024-01-10" })?.group).toBeUndefined();
  });

  it("has nothing to say without both dates", () => {
    expect(deriveAge({ Id10020: "no" })).toBeUndefined();
  });
});

describe("ageSuggestions", () => {
  it("suggests the group and the number in the unit the days call for, from exact dates", () => {
    expect(ageSuggestions(exact("2026-01-01", "2026-01-26"), ALL)).toMatchObject({
      age_group: { value: "neonate", kind: "suggested" },
      age_neonate_days: { value: 25, kind: "calculated" }
    });
    const child = (dob: string, dod: string) => ageSuggestions(exact(dob, dod), ALL);
    expect(child("2026-01-01", "2026-02-15")).toMatchObject({
      age_child_unit: { value: "days" },
      age_child_days: { value: 45 }
    });
    expect(child("2025-01-01", "2025-08-01")).toMatchObject({
      age_child_unit: { value: "months" },
      age_child_months: { value: 6 }
    });
    expect(child("2018-01-01", "2024-02-01")).toMatchObject({
      age_child_unit: { value: "years" },
      age_child_years: { value: 6 }
    });
    expect(ageSuggestions(exact("1980-01-01", "2024-01-01"), ALL)).toMatchObject({
      age_group: { value: "adult" },
      age_adult: { value: 44, kind: "calculated" }
    });
  });

  it("follows the unit the interviewer chose", () => {
    const data = { ...exact("2025-01-01", "2025-08-01"), age_child_unit: "years" };
    expect(ageSuggestions(data, ALL).age_child_years).toEqual({ value: 0, kind: "calculated" });
  });

  it("estimates years only for child and adult, never days or months", () => {
    const child = ageSuggestions(yearsOnly(2017, 2021), ALL);
    expect(child.age_group).toEqual({ value: "child", kind: "suggested" });
    expect(child.age_child_unit).toEqual({ value: "years", kind: "estimate" });
    expect(child.age_child_years).toEqual({ value: 4, kind: "estimate" });
    expect(child.age_child_days).toBeUndefined();
    expect(child.age_neonate_days).toBeUndefined();
    expect(ageSuggestions(yearsOnly(1980, 2021), ALL).age_adult).toEqual({ value: 41, kind: "estimate" });
  });

  it("suggests nothing when the years are ambiguous", () => {
    expect(ageSuggestions(yearsOnly(2009, 2021), ALL)).toEqual({});
  });

  it("only suggests for questions that are shown", () => {
    expect(ageSuggestions(yearsOnly(2017, 2021), new Set(["age_group"]))).toEqual({
      age_group: { value: "child", kind: "suggested" }
    });
  });
});

describe("boundaryFix", () => {
  it("moves child days under 28 to the neonate question", () => {
    expect(boundaryFix("age_child_days", 25)).toMatchObject({
      messageKey: "fixToNeonate",
      count: 25,
      set: expect.arrayContaining([
        ["age_group", "neonate"],
        ["age_neonate_days", 25],
        ["age_child_days", undefined]
      ])
    });
  });
  it("converts child days over 60 to months", () => {
    expect(boundaryFix("age_child_days", 90)?.set).toEqual(
      expect.arrayContaining([
        ["age_child_unit", "months"],
        ["age_child_months", 3]
      ])
    );
  });
  it("offers Adult for child years from 12 and Child for neonate days over 27", () => {
    expect(boundaryFix("age_child_years", 12)?.set).toEqual(
      expect.arrayContaining([
        ["age_group", "adult"],
        ["age_adult", 12]
      ])
    );
    expect(boundaryFix("age_neonate_days", 30)?.set).toEqual(
      expect.arrayContaining([
        ["age_group", "child"],
        ["age_child_unit", "days"],
        ["age_child_days", 30]
      ])
    );
  });
  it("offers nothing inside the limits", () => {
    expect(boundaryFix("age_child_days", 28)).toBeUndefined();
    expect(boundaryFix("age_child_days", 60)).toBeUndefined();
    expect(boundaryFix("age_child_years", 11)).toBeUndefined();
    expect(boundaryFix("age_neonate_days", 27)).toBeUndefined();
    expect(boundaryFix("age_neonate_days", undefined)).toBeUndefined();
  });
});

describe("narration language", () => {
  const offered = new Set(["english", "hindi", "bangla"]);
  it("reads the script", () => {
    expect(narrationLanguageFromText("उसे तीन दिन से बुखार था")).toBe("hindi");
    expect(narrationLanguageFromText("He had fever for three days")).toBe("english");
    expect(narrationLanguageFromText("bukhar tha teen din se")).toBe("english");
    expect(narrationLanguageFromText("জ্বর ছিল")).toBe("bangla");
    expect(narrationLanguageFromText("12345 ...")).toBeUndefined();
  });
  it("falls back to the app language for an empty narrative and respects what is offered", () => {
    expect(narrationLanguageSuggestion(undefined, "hi", offered)).toBe("hindi");
    expect(narrationLanguageSuggestion("", "en-IN", offered)).toBe("english");
    expect(narrationLanguageSuggestion("", "kn", offered)).toBeUndefined();
    expect(narrationLanguageSuggestion("जी", "en", offered)).toBe("hindi");
  });
});

describe("session.goToQuestion", () => {
  const instrument = createWhoVa2022Instrument(["digitva_core"]);
  const open = (data: Record<string, string> = { Id10013: "yes" }) => createWhoVaSession(instrument, { initialData: data });

  it("opens the section that shows the question and keeps the issues", () => {
    const session = open();
    expect(session.goToQuestion("Id10476")).toMatchObject({ status: "shown", question: "Id10476", section: "narrat" });
    expect(session.getSnapshot().currentSection.name).toBe("narrat");
  });

  it("moves a question hidden by skip logic to the question that controls it", () => {
    const session = open();
    const result = session.goToQuestion("age_neonate_days");
    expect(result).toMatchObject({ status: "hidden", question: "age_group", requested: "age_neonate_days" });
    expect(session.getSnapshot().currentSection.name).toBe("info_on_deceased");
  });

  it("reports an unknown or unreachable question", () => {
    const session = open({});
    expect(session.goToQuestion("nope")).toEqual({ status: "unavailable", requested: "nope" });
    // Consent not given: the narrative sits behind it, and Id10013 is its controller.
    expect(session.goToQuestion("Id10476")).toMatchObject({ status: "hidden", question: "Id10013" });
  });
});
