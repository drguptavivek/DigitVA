import { calculateRegistrationAge, sameRegistrationAgeParts } from "../src/registrationAgeDisplay";

const fields = (date_of_death: string, extra: Record<string, string> = {}) => ({
  date_of_death,
  ...extra
});

describe("calculateRegistrationAge", () => {
  it.each([
    ["2026-01-01", "2026-01-01", 0],
    ["2026-01-01", "2026-01-30", 29]
  ])("uses days for an exact age below 30 days", (birth, death, days) => {
    expect(calculateRegistrationAge(fields(death, { date_of_birth: birth }))).toEqual({
      kind: "days",
      precision: "exact",
      exact: true,
      min: { years: 0, months: 0, days },
      max: { years: 0, months: 0, days }
    });
  });

  it("switches to calendar units at 30 days while retaining complete date components", () => {
    expect(calculateRegistrationAge(fields("2026-01-31", { date_of_birth: "2026-01-01" }))).toEqual({
      kind: "calendar",
      precision: "exact",
      exact: true,
      min: { years: 0, months: 0, days: 30 },
      max: { years: 0, months: 0, days: 30 }
    });
  });

  it("calculates completed years and months across month ends", () => {
    expect(calculateRegistrationAge(fields("2021-02-28", { date_of_birth: "2020-01-31" }))).toEqual({
      kind: "calendar",
      precision: "exact",
      exact: true,
      min: { years: 1, months: 1, days: 0 },
      max: { years: 1, months: 1, days: 0 }
    });
    expect(calculateRegistrationAge(fields("2021-02-28", { date_of_birth: "2020-02-29" }))).toEqual({
      kind: "calendar",
      precision: "exact",
      exact: true,
      min: { years: 1, months: 0, days: 0 },
      max: { years: 1, months: 0, days: 0 }
    });
  });

  it("returns a calendar range for a year-only birth date", () => {
    expect(calculateRegistrationAge(fields("2026-03-15", { date_of_birth_partial: "2025" }))).toEqual({
      kind: "calendar",
      precision: "year",
      exact: false,
      min: { years: 0, months: 2, days: 15 },
      max: { years: 1, months: 2, days: 14 }
    });
  });

  it("clamps a month/year range to the death date in the same period", () => {
    expect(calculateRegistrationAge(fields("2026-04-15", { date_of_birth_partial: "2026-04" }))).toEqual({
      kind: "days",
      precision: "month",
      exact: false,
      min: { years: 0, months: 0, days: 0 },
      max: { years: 0, months: 0, days: 14 }
    });
  });

  it("also clamps a year-only range when death occurs in that year", () => {
    expect(calculateRegistrationAge(fields("2026-01-15", { date_of_birth_partial: "2026" }))).toEqual({
      kind: "days",
      precision: "year",
      exact: false,
      min: { years: 0, months: 0, days: 0 },
      max: { years: 0, months: 0, days: 14 }
    });
  });

  it("keeps a calendar range when only residual days differ", () => {
    const display = calculateRegistrationAge(fields("2026-01-31", { date_of_birth_partial: "2025-01" }));
    expect(display).toMatchObject({ kind: "calendar", precision: "month", exact: false });
    expect(display?.min).toEqual({ years: 1, months: 0, days: 0 });
    expect(display?.max).toEqual({ years: 1, months: 0, days: 30 });
    expect(sameRegistrationAgeParts(display!.min, display!.max)).toBe(false);
  });

  it("keeps a partial day-only range as a range", () => {
    const display = calculateRegistrationAge(fields("2026-01-15", { date_of_birth_partial: "2026-01" }));
    expect(display).toMatchObject({ kind: "days", precision: "month", exact: false });
    expect(display?.min.days).toBe(0);
    expect(display?.max.days).toBe(14);
    expect(display?.min.days).not.toBe(display?.max.days);
  });

  it("marks a partial range that crosses 30 days as mixed", () => {
    expect(calculateRegistrationAge(fields("2026-04-15", { date_of_birth_partial: "2026-03" }))).toEqual({
      kind: "mixed",
      precision: "month",
      exact: false,
      min: { years: 0, months: 0, days: 15 },
      max: { years: 0, months: 1, days: 14 }
    });
  });

  it("returns undefined for incomplete, invalid, future or conflicting dates", () => {
    expect(calculateRegistrationAge(fields("2026-01-01"))).toBeUndefined();
    expect(calculateRegistrationAge(fields("2026-01-01", { date_of_birth: "2026-02-01" }))).toBeUndefined();
    expect(calculateRegistrationAge(fields("2026-01-01", { date_of_birth_partial: "2026-02" }))).toBeUndefined();
    expect(calculateRegistrationAge(fields("2026-01-01", { date_of_birth: "2026-02-30" }))).toBeUndefined();
    expect(calculateRegistrationAge(fields("2026-01-01", { date_of_birth: "2026-01-01", date_of_birth_partial: "2025" }))).toBeUndefined();
  });
});
