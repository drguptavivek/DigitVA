import type { RegistrationFields } from "./cases";

/** Completed calendar units for one possible age at the date of death. */
export interface RegistrationAgeParts {
  years: number;
  months: number;
  days: number;
}

export type RegistrationAgeDisplayKind = "days" | "calendar" | "mixed";
export type RegistrationBirthPrecision = "exact" | "month" | "year";

/**
 * An age estimate for the registration screen.
 *
 * For a partial birth date, `min` is the age for the latest feasible birthday
 * and `max` is the age for the earliest feasible birthday. `kind` tells the
 * screen how to localise the range: days when both ends are under 30 days,
 * calendar units when both ends reach 30 days, and mixed when the range spans
 * that presentation boundary.
 */
export interface RegistrationAgeDisplay {
  kind: RegistrationAgeDisplayKind;
  precision: RegistrationBirthPrecision;
  exact: boolean;
  min: RegistrationAgeParts;
  max: RegistrationAgeParts;
}

/** Compare all completed calendar units, including residual days. */
export function sameRegistrationAgeParts(left: RegistrationAgeParts, right: RegistrationAgeParts): boolean {
  return left.years === right.years && left.months === right.months && left.days === right.days;
}

interface DateParts {
  year: number;
  month: number;
  day: number;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const PARTIAL_DATE = /^(\d{4})(?:-(\d{2}))?$/;
const DAY_MS = 24 * 60 * 60 * 1000;

function dateFromParts(parts: DateParts): Date {
  // setUTCFullYear avoids Date.UTC's special handling of years 0 through 99.
  const value = new Date(0);
  value.setUTCHours(0, 0, 0, 0);
  value.setUTCFullYear(parts.year, parts.month - 1, parts.day);
  return value;
}

function parseDate(value: string): DateParts | undefined {
  const match = DATE.exec(value);
  if (!match) return undefined;
  const parts = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
  const date = dateFromParts(parts);
  return date.getUTCFullYear() === parts.year &&
    date.getUTCMonth() + 1 === parts.month &&
    date.getUTCDate() === parts.day
    ? parts
    : undefined;
}

function compareDates(left: DateParts, right: DateParts): number {
  return dateFromParts(left).getTime() - dateFromParts(right).getTime();
}

function daysInMonth(year: number, month: number): number {
  const firstOfFollowingMonth = dateFromParts({ year, month: month + 1, day: 1 });
  firstOfFollowingMonth.setUTCDate(0);
  return firstOfFollowingMonth.getUTCDate();
}

function addYears(date: DateParts, years: number): DateParts {
  return {
    year: date.year + years,
    month: date.month,
    day: Math.min(date.day, daysInMonth(date.year + years, date.month))
  };
}

function addMonths(date: DateParts, months: number): DateParts {
  const monthIndex = date.year * 12 + date.month - 1 + months;
  const year = Math.floor(monthIndex / 12);
  const month = (monthIndex % 12) + 1;
  return { year, month, day: Math.min(date.day, daysInMonth(year, month)) };
}

function daysBetween(start: DateParts, end: DateParts): number {
  return Math.round((dateFromParts(end).getTime() - dateFromParts(start).getTime()) / DAY_MS);
}

function calendarAge(birth: DateParts, death: DateParts): RegistrationAgeParts | undefined {
  if (compareDates(birth, death) > 0) return undefined;

  let years = death.year - birth.year;
  let cursor = addYears(birth, years);
  if (compareDates(cursor, death) > 0) {
    years -= 1;
    cursor = addYears(birth, years);
  }

  let months = (death.year - cursor.year) * 12 + death.month - cursor.month;
  let monthCursor = addMonths(cursor, months);
  if (compareDates(monthCursor, death) > 0) {
    months -= 1;
    monthCursor = addMonths(cursor, months);
  }

  return { years, months, days: daysBetween(monthCursor, death) };
}

function birthBounds(value: string): {
  precision: RegistrationBirthPrecision;
  earliest: DateParts;
  latest: DateParts;
} | undefined {
  const match = PARTIAL_DATE.exec(value);
  if (!match) return undefined;
  const year = Number(match[1]);
  if (!match[2]) {
    return {
      precision: "year",
      earliest: { year, month: 1, day: 1 },
      latest: { year, month: 12, day: 31 }
    };
  }

  const month = Number(match[2]);
  if (month < 1 || month > 12) return undefined;
  return {
    precision: "month",
    earliest: { year, month, day: 1 },
    latest: { year, month, day: daysInMonth(year, month) }
  };
}

function ageKind(minDays: number, maxDays: number): RegistrationAgeDisplayKind {
  if (maxDays < 30) return "days";
  if (minDays >= 30) return "calendar";
  return "mixed";
}

/**
 * Calculate the age at death without manufacturing an exact birth date for a
 * month/year or year-only entry. All dates are parsed as UTC calendar dates.
 */
export function calculateRegistrationAge(
  fields: Pick<RegistrationFields, "date_of_death" | "date_of_birth" | "date_of_birth_partial">
): RegistrationAgeDisplay | undefined {
  const death = parseDate(fields.date_of_death?.trim() ?? "");
  if (!death) return undefined;

  const exactValue = fields.date_of_birth?.trim() ?? "";
  const partialValue = fields.date_of_birth_partial?.trim() ?? "";
  if (exactValue && partialValue) return undefined;

  if (exactValue) {
    const birth = parseDate(exactValue);
    if (!birth || compareDates(birth, death) > 0) return undefined;
    const age = calendarAge(birth, death);
    if (!age) return undefined;
    const elapsedDays = daysBetween(birth, death);
    return {
      kind: elapsedDays < 30 ? "days" : "calendar",
      precision: "exact",
      exact: true,
      min: age,
      max: age
    };
  }

  if (!partialValue) return undefined;
  const bounds = birthBounds(partialValue);
  if (!bounds) return undefined;
  if (compareDates(bounds.earliest, death) > 0) return undefined;

  // A death inside the selected year/month makes the death date the latest
  // feasible birthday. This gives a zero-age lower bound rather than a
  // negative estimate.
  const latest = compareDates(bounds.latest, death) > 0 ? death : bounds.latest;
  const youngest = calendarAge(latest, death);
  const oldest = calendarAge(bounds.earliest, death);
  if (!youngest || !oldest) return undefined;

  const youngestDays = daysBetween(latest, death);
  const oldestDays = daysBetween(bounds.earliest, death);
  return {
    kind: ageKind(youngestDays, oldestDays),
    precision: bounds.precision,
    exact: false,
    min: youngest,
    max: oldest
  };
}
