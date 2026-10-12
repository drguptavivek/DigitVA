// Pure certificate rules (owner spec: docs/policy/doris-certificate-rules.md).
// "Hide" = section/field not rendered AND its keys removed from what is sent to /process and saved.
// "Warn" = inline message under the field; never blocks Process or Save.
// No React here so the rules are unit-testable on their own.

import type { JsonObject, JsonValue } from "../contracts";
import { INTERVAL_UNITS, parseInterval } from "./interval";

/** Soft pregnancy age band, inclusive. One place. */
export const PREGNANCY_AGE_BAND: readonly [number, number] = [10, 54];

const DAYS_PER_YEAR = 365.25;
const UNIT_DAYS: Record<string, number> = { Y: DAYS_PER_YEAR, M: DAYS_PER_YEAR / 12, W: 7, D: 1, H: 1 / 24, MI: 1 / 1440, S: 1 / 86400 };

/** Age at death. `years` is days / 365.25. */
export interface Age { days: number; years: number }

function obj(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

/** Days since 1970 for a real full ISO date, else null (partial "YYYY" / "YYYY-MM" are ignored). */
export function isoDay(value: unknown): number | null {
  const match = typeof value === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return Math.round(date.getTime() / 86400000);
}

/** "2025", "2025-03" or "2025-03-04" as [year, month|null, day|null] (as doris_rules.js parseDate), else null. */
type DateParts = [number, number | null, number | null];
function parseDate(value: unknown): DateParts | null {
  const match = typeof value === "string" ? /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(value.trim()) : null;
  return match ? [Number(match[1]), match[2] ? Number(match[2]) : null, match[3] ? Number(match[3]) : null] : null;
}

/** Compares at the coarser precision of the two dates: -1, 0, 1, or null when either is missing. */
function compareDates(a: DateParts | null, b: DateParts | null): -1 | 0 | 1 | null {
  if (!a || !b) return null;
  for (let i = 0; i < 3; i += 1) {
    if (a[i] === null || b[i] === null) return 0;
    if (a[i] !== b[i]) return (a[i] as number) < (b[i] as number) ? -1 : 1;
  }
  return 0;
}

/** Interval length in days from an ISO 8601 duration; null when not a single number + unit. */
export function intervalDays(raw: unknown): number | null {
  const parsed = parseInterval(raw);
  if (!parsed.representable || parsed.value === "") return null;
  return Number(parsed.value) * UNIT_DAYS[parsed.unit];
}

/**
 * The reported age used by every rule: AdministrativeData.EstimatedAge only (as the web editor's
 * ageInDays and the server's drop_inapplicable_sections do). Blank or unrepresentable means unknown:
 * rules then hide nothing, so data entry is never blocked and clearing the field never deletes data.
 */
export function reportedAge(certificate: JsonObject): Age | null {
  const days = intervalDays(obj(certificate.AdministrativeData).EstimatedAge);
  return days === null ? null : { days, years: days / DAYS_PER_YEAR };
}

/** Which conditional parts of the certificate are shown. Unknown age/sex-independent parts default to shown. */
export interface Visibility {
  fetalOrInfant: boolean;
  hoursSurvived: boolean;
  pregnancy: boolean;
  pregnancyFollowup: boolean;
  surgeryDetail: boolean;
  autopsyFindings: boolean;
  externalCause: boolean;
}

/** DORIS manner codes 1 to 7 are external causes; 0 Disease, 9 Unknown, unset and any other code are not. */
export function isExternalManner(manner: unknown): boolean {
  return typeof manner === "number" && manner >= 1 && manner <= 7;
}

export function visibility(certificate: JsonObject, age: Age | null): Visibility {
  const stillborn = obj(certificate.FetalOrInfantDeath).Stillborn === 1;
  return {
    fetalOrInfant: age === null || age.days < 365,
    hoursSurvived: (age === null || age.days < 7) && !stillborn,
    pregnancy: obj(certificate.AdministrativeData).Sex === 2,
    pregnancyFollowup: obj(certificate.MaternalDeath).WasPregnant === 1,
    surgeryDetail: obj(certificate.Surgery).WasPerformed === 1,
    autopsyFindings: obj(certificate.Autopsy).WasRequested === 1,
    externalCause: isExternalManner(obj(certificate.MannerOfDeath).MannerOfDeath),
  };
}

function drop(certificate: JsonObject, section: string, keys?: string[]): void {
  if (!keys) { delete certificate[section]; return; }
  const target = obj(certificate[section]);
  for (const key of keys) delete target[key];
  if (!Object.keys(target).length) delete certificate[section];
}

/** Returns a copy of the certificate without the keys of every hidden section or field. */
export function applyVisibility(certificate: JsonObject): JsonObject {
  const result = JSON.parse(JSON.stringify(certificate)) as JsonObject;
  const shown = visibility(result, reportedAge(result));
  if (!shown.fetalOrInfant) drop(result, "FetalOrInfantDeath");
  else if (!shown.hoursSurvived) drop(result, "FetalOrInfantDeath", ["DeathWithin24h"]);
  if (!shown.pregnancy) drop(result, "MaternalDeath");
  else if (!shown.pregnancyFollowup) drop(result, "MaternalDeath", ["TimeFromPregnancy", "PregnancyContribute"]);
  if (!shown.surgeryDetail) drop(result, "Surgery", ["Date", "Reason"]);
  if (!shown.autopsyFindings) drop(result, "Autopsy", ["Findings"]);
  if (!shown.externalCause) drop(result, "MannerOfDeath", ["DateOfExternalCauseOrPoisoning", "DescriptionExternalCause", "PlaceOfOccuranceExternalCause"]);
  return result;
}

/** True when this unit is clearly longer than the age (greyed in the unit list, still selectable). */
export function unitTooLarge(unit: string, age: Age | null): boolean {
  if (age === null || age.days <= 0 || !INTERVAL_UNITS.some((item) => item.value === unit)) return false;
  return UNIT_DAYS[unit] > age.days;
}

export const MSG = {
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
} as const;

/** Warnings keyed by field path: "Section.Key" for answers, "Part1.<i>" / "Part2" for lines. */
export type Warnings = Record<string, string>;

function outside(value: unknown, min: number, max: number): boolean {
  return typeof value === "number" && (value < min || value > max);
}

/** Interval-vs-age and ordering warnings for the Part I / Part II lines (V9). */
function lineWarnings(certificate: JsonObject, age: Age | null, out: Warnings): void {
  const lineInterval = (line: unknown): number | null => {
    const first = Array.isArray(obj(line).Conditions) ? (obj(line).Conditions as JsonValue[])[0] : undefined;
    return intervalDays(obj(first).Interval);
  };
  const lines = Array.isArray(certificate.Part1) ? certificate.Part1 : [];
  lines.forEach((line, index) => {
    const days = lineInterval(line);
    if (days === null) return;
    if (age !== null && days > age.days) out[`Part1.${index}`] = MSG.intervalLonger;
    else if (index > 0) {
      const above = lineInterval(lines[index - 1]);
      if (above !== null && days < above) out[`Part1.${index}`] = MSG.shorterThanAbove;
    }
  });
  const part2 = lineInterval(certificate.Part2);
  if (part2 !== null && age !== null && part2 > age.days) out.Part2 = MSG.intervalLonger;
}

/** Soft warnings for the whole certificate; `today` is the user's local ISO date. */
export function warnings(certificate: JsonObject, today: string): Warnings {
  const out: Warnings = {};
  const age = reportedAge(certificate);
  const admin = obj(certificate.AdministrativeData);
  const shown = visibility(certificate, age);
  // Birth and injury may be partial ("2025", "2025-03") and compare at the coarser precision. Date of death is a
  // plain calendar date; a stored partial one is tolerated but takes no part in any warning.
  const birth = parseDate(admin.DateBirth);
  const death = isoDay(admin.DateDeath) === null ? null : parseDate(admin.DateDeath);

  lineWarnings(certificate, age, out);

  if (compareDates(birth, death) === 1) out["AdministrativeData.DateBirth"] = MSG.birthAfterDeath;
  if (compareDates(death, parseDate(today)) === 1) out["AdministrativeData.DateDeath"] = MSG.deathFuture;
  // Both dates and the estimate must be full/valid; the web compares EstimatedAge only, in days.
  const birthDay = isoDay(admin.DateBirth);
  const deathDay = isoDay(admin.DateDeath);
  const estimated = intervalDays(admin.EstimatedAge);
  if (birthDay !== null && deathDay !== null && estimated !== null && Math.abs(estimated - (deathDay - birthDay)) > DAYS_PER_YEAR) out["AdministrativeData.EstimatedAge"] = MSG.ageMismatch;

  const injury = parseDate(obj(certificate.MannerOfDeath).DateOfExternalCauseOrPoisoning);
  if (shown.externalCause && (compareDates(injury, birth) === -1 || compareDates(injury, death) === 1)) out["MannerOfDeath.DateOfExternalCauseOrPoisoning"] = MSG.injuryRange;
  // The 4-week rule needs a full surgery date and a full death date.
  const surgeryDay = isoDay(obj(certificate.Surgery).Date);
  if (shown.surgeryDetail && surgeryDay !== null && deathDay !== null && (surgeryDay > deathDay || surgeryDay < deathDay - 28)) out["Surgery.Date"] = MSG.surgeryRange;

  if (shown.pregnancy && obj(certificate.MaternalDeath).WasPregnant === 1 && age !== null && (age.years < PREGNANCY_AGE_BAND[0] || age.years >= PREGNANCY_AGE_BAND[1] + 1)) out["MaternalDeath.WasPregnant"] = MSG.pregnancyAge;

  const fetal = obj(certificate.FetalOrInfantDeath);
  if (shown.fetalOrInfant && outside(fetal.BirthWeight, 200, 7000)) out["FetalOrInfantDeath.BirthWeight"] = MSG.birthWeight;
  if (shown.fetalOrInfant && outside(fetal.PregnancyWeeks, 20, 45)) out["FetalOrInfantDeath.PregnancyWeeks"] = MSG.weeks;
  if (shown.fetalOrInfant && outside(fetal.AgeMother, 10, 60)) out["FetalOrInfantDeath.AgeMother"] = MSG.motherAge;
  if (shown.fetalOrInfant && shown.hoursSurvived && outside(fetal.DeathWithin24h, 0, 24)) out["FetalOrInfantDeath.DeathWithin24h"] = MSG.hours;
  return out;
}
