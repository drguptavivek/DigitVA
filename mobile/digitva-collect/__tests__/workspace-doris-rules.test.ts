import type { JsonObject } from "../src/workspace/contracts";
import { MSG, PREGNANCY_AGE_BAND, ageFromDates, applyVisibility, deriveEstimatedAge, derivesAtLoad, reportedAge, unitTooLarge, visibility, warnings } from "../src/workspace/doris/rules";

const cert = (age: string | undefined, rest: JsonObject = {}, sex?: number): JsonObject => ({
  AdministrativeData: { ...(age ? { EstimatedAge: age } : {}), ...(sex ? { Sex: sex } : {}) },
  ...rest,
});
const shown = (c: JsonObject) => visibility(c, reportedAge(c));
const TODAY = "2026-06-15";

describe("reported age", () => {
  it("reads EstimatedAge only: dates and the case header age are never a fallback", () => {
    expect(reportedAge(cert("P3D"))?.days).toBe(3);
    expect(reportedAge({ AdministrativeData: { DateBirth: "2000-03-01", DateDeath: "2010-03-01" } })).toBeNull();
    expect(reportedAge({})).toBeNull();
    expect(reportedAge(cert(""))).toBeNull();
  });
  it("keeps entered infant data when Estimated age is cleared (age unknown hides nothing)", () => {
    const c = { AdministrativeData: { EstimatedAge: "" }, FetalOrInfantDeath: { BirthWeight: 3000 } } as JsonObject;
    expect(shown(c).fetalOrInfant).toBe(true);
    expect(applyVisibility(c).FetalOrInfantDeath).toEqual({ BirthWeight: 3000 });
  });
});

describe("V1 fetal or infant death card", () => {
  it.each([["P0D", true], ["P364D", true], ["P365D", false], ["P11M", true], ["P1Y", false], ["P12M", false], ["P9Y", false], ["P77Y", false]])("age %s -> shown %s", (age, expected) => {
    expect(shown(cert(age)).fetalOrInfant).toBe(expected);
  });
  it("is shown when the age is unknown, so entry is never blocked", () => {
    expect(shown(cert(undefined)).fetalOrInfant).toBe(true);
  });
  it("removes every FetalOrInfantDeath key for an adult", () => {
    const c = cert("P40Y", { FetalOrInfantDeath: { BirthWeight: 3000, Stillborn: 0 } });
    expect(c.FetalOrInfantDeath).toBeDefined();
    expect(applyVisibility(c).FetalOrInfantDeath).toBeUndefined();
  });
});

describe("V2 hours survived", () => {
  it.each([["P0D", true], ["P6D", true], ["PT23H", true], ["P1W", false], ["P7D", false], ["P3M", false]])("age %s -> shown %s", (age, expected) => {
    expect(shown(cert(age)).hoursSurvived).toBe(expected);
  });
  it("is hidden when Stillborn is Yes, kept for No, and dropped from the certificate", () => {
    expect(shown(cert("P2D", { FetalOrInfantDeath: { Stillborn: 1 } })).hoursSurvived).toBe(false);
    expect(shown(cert("P2D", { FetalOrInfantDeath: { Stillborn: 0 } })).hoursSurvived).toBe(true);
    const c = cert("P2D", { FetalOrInfantDeath: { Stillborn: 1, DeathWithin24h: 5, BirthWeight: 3000 } });
    expect(applyVisibility(c).FetalOrInfantDeath).toEqual({ Stillborn: 1, BirthWeight: 3000 });
    const infant = cert("P30D", { FetalOrInfantDeath: { DeathWithin24h: 5 } });
    expect(applyVisibility(infant).FetalOrInfantDeath).toBeUndefined();
  });
});

describe("V3 pregnancy", () => {
  it.each([[1, false], [2, true], [9, false], [undefined, false]])("sex %s -> shown %s", (sex, expected) => {
    expect(shown(cert("P30Y", {}, sex)).pregnancy).toBe(expected);
  });
  it("drops MaternalDeath unless female", () => {
    const rest = { MaternalDeath: { WasPregnant: 1 } };
    expect(applyVisibility(cert("P30Y", rest, 1)).MaternalDeath).toBeUndefined();
    expect(applyVisibility(cert("P30Y", rest, 2)).MaternalDeath).toEqual({ WasPregnant: 1 });
  });
  it.each([[1, true], [0, false], [9, false], [undefined, false]])("WasPregnant %s -> follow-ups kept %s", (answer, kept) => {
    const maternal: JsonObject = { TimeFromPregnancy: 1, PregnancyContribute: 2, ...(answer === undefined ? {} : { WasPregnant: answer }) };
    const result = applyVisibility(cert("P30Y", { MaternalDeath: maternal }, 2)).MaternalDeath as JsonObject | undefined;
    if (kept) expect(result).toEqual({ WasPregnant: 1, TimeFromPregnancy: 1, PregnancyContribute: 2 });
    else {
      expect(shown(cert("P30Y", { MaternalDeath: maternal }, 2)).pregnancy).toBe(true);
      expect(result?.TimeFromPregnancy).toBeUndefined();
      expect(result?.PregnancyContribute).toBeUndefined();
      expect(result?.WasPregnant).toBe(answer);
    }
  });
  it.each([["P9Y", true], ["P10Y", false], ["P54Y", false], ["P55Y", true], ["P77Y", true]])("pregnant Yes, age %s -> warn %s", (age, warn) => {
    const w = warnings(cert(age, { MaternalDeath: { WasPregnant: 1 } }, 2), TODAY)["MaternalDeath.WasPregnant"];
    if (warn) expect(w).toBe(MSG.pregnancyAge); else expect(w).toBeUndefined();
  });
  it.each([[undefined], [0], [9]])("age 72 with pregnancy answer %s -> no warning", (answer) => {
    const yes = warnings(cert("P72Y", { MaternalDeath: { WasPregnant: 1 } }, 2), TODAY)["MaternalDeath.WasPregnant"];
    expect(yes).toBe(MSG.pregnancyAge); // subject present before asserting absence
    const rest: JsonObject = answer === undefined ? {} : { MaternalDeath: { WasPregnant: answer } };
    expect(warnings(cert("P72Y", rest, 2), TODAY)["MaternalDeath.WasPregnant"]).toBeUndefined();
  });
  it("keeps the band in one constant", () => { expect(PREGNANCY_AGE_BAND).toEqual([10, 54]); });
  it("does not warn for a male (the card is hidden)", () => {
    expect(warnings(cert("P77Y", { MaternalDeath: { WasPregnant: 1 } }, 1), TODAY)["MaternalDeath.WasPregnant"]).toBeUndefined();
  });
});

describe("V4 surgery and V5 autopsy", () => {
  it.each([[1, true], [0, false], [9, false], [undefined, false]])("surgery %s -> detail %s", (answer, expected) => {
    expect(shown(cert("P30Y", answer === undefined ? {} : { Surgery: { WasPerformed: answer } })).surgeryDetail).toBe(expected);
  });
  it("drops date and reason, keeps the answer", () => {
    const c = cert("P30Y", { Surgery: { WasPerformed: 0, Date: "2026-01-01", Reason: "x" }, Autopsy: { WasRequested: 0, Findings: 1 } });
    const out = applyVisibility(c);
    expect(out.Surgery).toEqual({ WasPerformed: 0 });
    expect(out.Autopsy).toEqual({ WasRequested: 0 });
  });
  it("keeps the follow-ups on Yes", () => {
    const c = cert("P30Y", { Surgery: { WasPerformed: 1, Date: "2026-01-01" }, Autopsy: { WasRequested: 1, Findings: 1 } });
    expect(applyVisibility(c)).toMatchObject({ Surgery: { Date: "2026-01-01" }, Autopsy: { Findings: 1 } });
  });
});

describe("V6 manner of death", () => {
  it.each([[0, false], [1, true], [2, true], [3, true], [4, true], [5, true], [6, true], [7, true], [9, false], [undefined, false]])("manner %s -> external fields %s", (manner, expected) => {
    expect(shown(cert("P30Y", manner === undefined ? {} : { MannerOfDeath: { MannerOfDeath: manner } })).externalCause).toBe(expected);
  });
  it("matches the web rule (codes 1 to 7 shown) for every code 0-9 and unset", () => {
    const web = (m: number | undefined) => typeof m === "number" && m >= 1 && m <= 7;
    const codes = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, undefined];
    for (const m of codes) {
      expect(shown(cert("P30Y", m === undefined ? {} : { MannerOfDeath: { MannerOfDeath: m } })).externalCause).toBe(web(m));
    }
    expect(shown(cert("P30Y", { MannerOfDeath: { MannerOfDeath: 1 } })).externalCause).toBe(true);
    expect(shown(cert("P30Y", { MannerOfDeath: { MannerOfDeath: 8 } })).externalCause).toBe(false);
  });
  it("drops the three external-cause keys for Disease but keeps the manner", () => {
    const c = cert("P30Y", { MannerOfDeath: { MannerOfDeath: 0, DateOfExternalCauseOrPoisoning: "2026-01-01", DescriptionExternalCause: "x", PlaceOfOccuranceExternalCause: 4 } });
    expect(applyVisibility(c).MannerOfDeath).toEqual({ MannerOfDeath: 0 });
  });
});

describe("V9 intervals", () => {
  const lines = (...intervals: string[]) => ({ Part1: intervals.map((Interval) => ({ Conditions: [{ Text: "x", Interval }] })) });
  it("warns when an interval exceeds the age at death", () => {
    expect(warnings(cert("P3D", lines("P5D")), TODAY)["Part1.0"]).toBe(MSG.intervalLonger);
    expect(warnings(cert("P3D", lines("P3D")), TODAY)["Part1.0"]).toBeUndefined();
    expect(warnings(cert("P3D", lines("PT5H")), TODAY)["Part1.0"]).toBeUndefined();
    expect(warnings(cert("P6M", lines("P1Y")), TODAY)["Part1.0"]).toBe(MSG.intervalLonger);
    expect(warnings(cert("P1Y", lines("P12M")), TODAY)["Part1.0"]).toBeUndefined();
  });
  it("allows no slack: one day longer than the age warns, equal does not", () => {
    expect(warnings(cert("P3D", lines("P4D")), TODAY)["Part1.0"]).toBe(MSG.intervalLonger);
    expect(warnings(cert("P3D", lines("P3D")), TODAY)["Part1.0"]).toBeUndefined();
    expect(warnings(cert("P3D", { Part2: { Conditions: [{ Text: "x", Interval: "P4D" }] } }), TODAY).Part2).toBe(MSG.intervalLonger);
    expect(warnings(cert("P3D", { Part2: { Conditions: [{ Text: "x", Interval: "P3D" }] } }), TODAY).Part2).toBeUndefined();
    expect(warnings(cert("P20D", lines("P1M")), TODAY)["Part1.0"]).toBe(MSG.intervalLonger);
    expect(unitTooLarge("W", reportedAge(cert("P6D")))).toBe(true);
    expect(unitTooLarge("W", reportedAge(cert("P7D")))).toBe(false);
    expect(unitTooLarge("D", reportedAge(cert("PT12H")))).toBe(true);
  });
  it("warns when a Due to line is shorter than the line above, never on the first line", () => {
    const w = warnings(cert("P77Y", lines("P2D", "P1D", "P5D")), TODAY);
    expect(w["Part1.0"]).toBeUndefined();
    expect(w["Part1.1"]).toBe(MSG.shorterThanAbove);
    expect(w["Part1.2"]).toBeUndefined();
  });
  it("skips lines without an interval", () => {
    expect(warnings(cert("P77Y", { Part1: [{ Conditions: [] }, { Conditions: [{ Text: "x" }] }] }), TODAY)).toEqual({});
  });
  it("greys unit options clearly larger than the age", () => {
    const infant = reportedAge(cert("P20D"));
    expect(unitTooLarge("Y", infant)).toBe(true);
    expect(unitTooLarge("M", infant)).toBe(true);
    expect(unitTooLarge("W", infant)).toBe(false);
    expect(unitTooLarge("D", infant)).toBe(false);
    expect(unitTooLarge("Y", reportedAge(cert("P1Y")))).toBe(false);
    expect(unitTooLarge("Y", null)).toBe(false);
    expect(unitTooLarge("unknown", infant)).toBe(false);
  });
});

describe("V10 dates", () => {
  const dates = (admin: JsonObject, rest: JsonObject = {}) => ({ AdministrativeData: admin, ...rest });
  it("warns when birth is after death or death is in the future", () => {
    expect(warnings(dates({ DateBirth: "2020-01-02", DateDeath: "2020-01-01" }), TODAY)["AdministrativeData.DateBirth"]).toBe(MSG.birthAfterDeath);
    expect(warnings(dates({ DateBirth: "2020-01-01", DateDeath: "2020-01-01" }), TODAY)["AdministrativeData.DateBirth"]).toBeUndefined();
    expect(warnings(dates({ DateDeath: "2026-06-16" }), TODAY)["AdministrativeData.DateDeath"]).toBe(MSG.deathFuture);
    expect(warnings(dates({ DateDeath: TODAY }), TODAY)["AdministrativeData.DateDeath"]).toBeUndefined();
  });
  it("compares partial dates at the coarser precision", () => {
    const birth = (b: string, d: string) => warnings(dates({ DateBirth: b, DateDeath: d }), TODAY)["AdministrativeData.DateBirth"];
    expect(birth("2021", "2020-01-15")).toBe(MSG.birthAfterDeath);
    expect(birth("2021-05", "2020-12-31")).toBe(MSG.birthAfterDeath);
    expect(birth("2020-02", "2020-01-15")).toBe(MSG.birthAfterDeath);
    expect(birth("2020", "2020-01-15")).toBeUndefined();
    expect(birth("2020-01", "2020-01-15")).toBeUndefined();
    // A stored partial date of death is tolerated without any warning.
    expect(birth("2021", "2020-01")).toBeUndefined();
    const death = (d: string) => warnings(dates({ DateDeath: d }), TODAY)["AdministrativeData.DateDeath"];
    expect(death("2027")).toBeUndefined();
    expect(death("2026-07")).toBeUndefined();
  });
  it("compares a partial injury date at the coarser precision", () => {
    const w = (date: string, admin: JsonObject = { DateBirth: "2000-05-10", DateDeath: "2020-05-10" }) => warnings(dates(admin, { MannerOfDeath: { MannerOfDeath: 1, DateOfExternalCauseOrPoisoning: date } }), TODAY)["MannerOfDeath.DateOfExternalCauseOrPoisoning"];
    expect(w("1999")).toBe(MSG.injuryRange);
    expect(w("2000-04")).toBe(MSG.injuryRange);
    expect(w("2021")).toBe(MSG.injuryRange);
    expect(w("2020-06")).toBe(MSG.injuryRange);
    expect(w("2000")).toBeUndefined();
    expect(w("2000-05")).toBeUndefined();
    expect(w("2020-05")).toBeUndefined();
    expect(w("2020", { DateBirth: "2000", DateDeath: "2020" })).toBeUndefined();
    expect(w("2021", { DateBirth: "2000", DateDeath: "2020" })).toBeUndefined();
  });
  it("needs a full surgery date and a full death date for the 4-week rule", () => {
    const w = (surgery: string, death: string) => warnings(dates({ DateDeath: death }, { Surgery: { WasPerformed: 1, Date: surgery } }), TODAY)["Surgery.Date"];
    expect(w("2020-01-01", "2020-03-01")).toBe(MSG.surgeryRange);
    expect(w("2020-01", "2020-03-01")).toBeUndefined();
    expect(w("2020-01-01", "2020-03")).toBeUndefined();
    expect(w("2020", "2020-03-01")).toBeUndefined();
  });
  it("checks the injury date against birth and death", () => {
    const base = { DateBirth: "2000-01-01", DateDeath: "2020-01-01" };
    const w = (date: string) => warnings(dates(base, { MannerOfDeath: { MannerOfDeath: 1, DateOfExternalCauseOrPoisoning: date } }), TODAY)["MannerOfDeath.DateOfExternalCauseOrPoisoning"];
    expect(w("1999-12-31")).toBe(MSG.injuryRange);
    expect(w("2020-01-02")).toBe(MSG.injuryRange);
    expect(w("2010-05-05")).toBeUndefined();
  });
  it("checks surgery within 4 weeks before death", () => {
    const w = (date: string) => warnings(dates({ DateDeath: "2020-03-01" }, { Surgery: { WasPerformed: 1, Date: date } }), TODAY)["Surgery.Date"];
    expect(w("2020-02-02")).toBeUndefined();
    expect(w("2020-02-01")).toBe(MSG.surgeryRange);
    expect(w("2020-03-01")).toBeUndefined();
    expect(w("2020-03-02")).toBe(MSG.surgeryRange);
  });
  it("warns when the estimated age and the dates differ by more than a year", () => {
    const w = (age: string) => warnings(dates({ EstimatedAge: age, DateBirth: "1950-01-01", DateDeath: "2020-01-01" }), TODAY)["AdministrativeData.EstimatedAge"];
    expect(w("P70Y")).toBeUndefined();
    expect(w("P71Y")).toBe(MSG.ageMismatch);
    expect(w("P75Y")).toBe(MSG.ageMismatch);
    expect(w("P60Y")).toBe(MSG.ageMismatch);
  });
});

describe("message wording (policy strings)", () => {
  it("matches doris-certificate-rules.md exactly", () => {
    expect(MSG).toEqual({
      intervalLonger: "Interval is longer than the age at death",
      shorterThanAbove: "Usually longer than the line above",
      pregnancyAge: "Pregnancy is unusual at this age",
      birthAfterDeath: "Date of birth is after the date of death",
      deathFuture: "Date of death is in the future",
      injuryRange: "Date of injury is outside birth to death",
      surgeryRange: "Outside the 4 weeks before death",
      ageMismatch: "Estimated age differs from the dates by more than a year",
      birthWeight: "Unusual birth weight (200 to 7000 g)",
      weeks: "Unusual number of weeks (20 to 45)",
      motherAge: "Unusual age of mother (10 to 60)",
      hours: "Hours survived should be 0 to 24",
    });
  });
});

describe("V11 plausibility", () => {
  const fetal = (values: JsonObject) => warnings(cert("P2D", { FetalOrInfantDeath: values }), TODAY);
  it("flags values outside the plausible range and accepts the bounds", () => {
    expect(fetal({ BirthWeight: 199 })["FetalOrInfantDeath.BirthWeight"]).toBe(MSG.birthWeight);
    expect(fetal({ BirthWeight: 7001 })["FetalOrInfantDeath.BirthWeight"]).toBe(MSG.birthWeight);
    expect(fetal({ BirthWeight: 200 })["FetalOrInfantDeath.BirthWeight"]).toBeUndefined();
    expect(fetal({ BirthWeight: 7000 })["FetalOrInfantDeath.BirthWeight"]).toBeUndefined();
    expect(fetal({ PregnancyWeeks: 19 })["FetalOrInfantDeath.PregnancyWeeks"]).toBe(MSG.weeks);
    expect(fetal({ PregnancyWeeks: 46 })["FetalOrInfantDeath.PregnancyWeeks"]).toBe(MSG.weeks);
    expect(fetal({ PregnancyWeeks: 45 })["FetalOrInfantDeath.PregnancyWeeks"]).toBeUndefined();
    expect(fetal({ AgeMother: 9 })["FetalOrInfantDeath.AgeMother"]).toBe(MSG.motherAge);
    expect(fetal({ AgeMother: 61 })["FetalOrInfantDeath.AgeMother"]).toBe(MSG.motherAge);
    expect(fetal({ AgeMother: 60 })["FetalOrInfantDeath.AgeMother"]).toBeUndefined();
    expect(fetal({ DeathWithin24h: 25 })["FetalOrInfantDeath.DeathWithin24h"]).toBe(MSG.hours);
    expect(fetal({ DeathWithin24h: 24 })["FetalOrInfantDeath.DeathWithin24h"]).toBeUndefined();
    expect(fetal({ DeathWithin24h: 0 })["FetalOrInfantDeath.DeathWithin24h"]).toBeUndefined();
  });
});

describe("dates outside 1900..today are warned, not blocked", () => {
  const dates = (admin: JsonObject) => ({ AdministrativeData: admin }) as JsonObject;
  it("a birth year after the death date warns, a 1890 birth year does not", () => {
    expect(warnings(dates({ DateBirth: "2027", DateDeath: "2026-06-01" }), TODAY)["AdministrativeData.DateBirth"]).toBe(MSG.birthAfterDeath);
    expect(warnings(dates({ DateBirth: "1890", DateDeath: "2026-06-01" }), TODAY)["AdministrativeData.DateBirth"]).toBeUndefined();
  });
  it("a death date after today warns", () => {
    expect(warnings(dates({ DateDeath: "2027-01-01" }), TODAY)["AdministrativeData.DateDeath"]).toBe(MSG.deathFuture);
  });
});

describe("EstimatedAge derived from the dates (V7 editor side)", () => {
  it("completed years, months or days, calendar-exact at the boundaries", () => {
    expect(ageFromDates("1996-08-12", "2025-06-12")).toBe("P28Y");
    expect(ageFromDates("1996-08-12", "2025-08-12")).toBe("P29Y");
    expect(ageFromDates("1996-08-12", "2025-08-11")).toBe("P28Y");
    expect(ageFromDates("2025-01-10", "2025-12-09")).toBe("P10M");
    expect(ageFromDates("2025-01-10", "2025-12-10")).toBe("P11M");
    expect(ageFromDates("2025-01-01", "2025-01-01")).toBe("P0D");
    expect(ageFromDates("2025-01-01", "2025-01-31")).toBe("P30D");
    expect(ageFromDates("2000-01-31", "2000-02-29")).toBe("P29D");
  });
  it("is null for partial dates, impossible dates and a death before birth", () => {
    expect(ageFromDates("1996", "2025-06-12")).toBeNull();
    expect(ageFromDates("1996-08", "2025-06-12")).toBeNull();
    expect(ageFromDates("1996-08-12", "2025-02-30")).toBeNull();
    expect(ageFromDates("2025-05-02", "2025-05-01")).toBeNull();
  });
  it("fills a blank age and refreshes only the value it derived itself", () => {
    const dated = { AdministrativeData: { DateBirth: "1996-08-12", DateDeath: "2025-06-12" } } as JsonObject;
    const first = deriveEstimatedAge(dated, null);
    expect(first.derived).toBe("P28Y");
    expect((first.certificate.AdministrativeData as JsonObject).EstimatedAge).toBe("P28Y");
    expect(dated.AdministrativeData).not.toHaveProperty("EstimatedAge");
    const moved = deriveEstimatedAge({ AdministrativeData: { ...(first.certificate.AdministrativeData as JsonObject), DateDeath: "2025-08-12" } }, first.derived);
    expect((moved.certificate.AdministrativeData as JsonObject).EstimatedAge).toBe("P29Y");
  });
  it("never overwrites a typed value, and a cleared value stays empty until a date changes", () => {
    const typed = { AdministrativeData: { DateBirth: "1996-08-12", DateDeath: "2025-06-12", EstimatedAge: "P40Y" } } as JsonObject;
    const kept = deriveEstimatedAge(typed, null);
    expect(kept.certificate).toBe(typed);
    expect(kept.derived).toBeNull();
  });
  it("removes its own derived value when a date becomes partial, and does nothing for partial dates", () => {
    const stale = { AdministrativeData: { DateBirth: "1996-08-12", DateDeath: "2025", EstimatedAge: "P28Y" } } as JsonObject;
    const result = deriveEstimatedAge(stale, "P28Y");
    expect(result.derived).toBeNull();
    expect(result.certificate.AdministrativeData).toEqual({ DateBirth: "1996-08-12", DateDeath: "2025" });
    const partial = { AdministrativeData: { DateBirth: "1996", DateDeath: "2025-06-12" } } as JsonObject;
    expect(deriveEstimatedAge(partial, null).certificate).toBe(partial);
  });
  it("a cleared age is refilled by the next date change (the panel calls the derive only on date edits)", () => {
    // After the coder clears EstimatedAge the panel passes derived=null; the next DateDeath edit refills it.
    const refilled = deriveEstimatedAge({ AdministrativeData: { DateBirth: "1996-08-12", DateDeath: "2025-08-12" } }, null);
    expect(refilled.derived).toBe("P29Y");
    expect((refilled.certificate.AdministrativeData as JsonObject).EstimatedAge).toBe("P29Y");
  });
  it("a 29 February birthday is reached on 1 March in a non-leap year, and month ends use the calendar", () => {
    expect(ageFromDates("2000-02-29", "2026-02-28")).toBe("P25Y");
    expect(ageFromDates("2000-02-29", "2026-03-01")).toBe("P26Y");
    expect(ageFromDates("2024-02-29", "2028-02-29")).toBe("P4Y");
    expect(ageFromDates("2025-01-31", "2025-02-28")).toBe("P28D");
    expect(ageFromDates("2025-01-31", "2025-03-01")).toBe("P1M");
    expect(ageFromDates("2025-03-31", "2025-04-30")).toBe("P30D");
  });
  it("derives at load only for a prefill seed, never for a saved certificate", () => {
    expect(derivesAtLoad({ "AdministrativeData.DateBirth": { sources: ["Id10020"] } }, null)).toBe(true);
    expect(derivesAtLoad({}, null)).toBe(false);
    expect(derivesAtLoad({ "AdministrativeData.DateBirth": { sources: ["Id10020"] } }, { doris: {} })).toBe(false);
  });
});
