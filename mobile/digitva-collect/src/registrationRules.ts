/** Browser-safe registration rules shared by the web intake screens. */
import type { StringKey } from "./i18n";
import { normalisePhone } from "./phoneFormat";
import { correctedNow } from "./phoneClock";

export interface RegistrationFields {
  deceased_name: string;
  deceased_sex: string;
  date_of_death: string;
  date_of_birth?: string;
  date_of_birth_partial?: string;
  age_years?: string;
  abha_number?: string;
  abha_address?: string;
  place_of_death?: string;
  address?: string;
  address_house_street?: string;
  address_village_ward?: string;
  address_landmark?: string;
  informant_name?: string;
  informant_phone?: string;
  informant_phone_2?: string;
  father_name?: string;
  mother_name?: string;
  remarks?: string;
  identifiers?: Record<string, string>;
}

export const SEX_VALUES = ["male", "female", "undetermined", "unknown"] as const;
export const MAX_REGISTRATION_AGE = 125;
export const AGE_REVIEW_THRESHOLD = 85;
const ABHA_NUMBER = /^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$/;
const ABHA_ADDRESS = /^[A-Za-z0-9._]{4,32}@(abdm|sbx)$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const PARTIAL_BIRTH_DATE = /^(?:\d{4}|\d{4}-(0[1-9]|1[0-2]))$/;

function isRealDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isPartialBirthDate(value: string): boolean {
  return PARTIAL_BIRTH_DATE.test(value);
}

export interface RegistrationAgeRange {
  youngestPossibleAge: number;
  oldestPossibleAge: number;
}

function dateParts(value: string): [number, number, number] | undefined {
  if (!isRealDate(value)) return undefined;
  return [Number(value.slice(0, 4)), Number(value.slice(5, 7)), Number(value.slice(8, 10))];
}

function ageAtDeath(birth: [number, number, number], death: [number, number, number]): number {
  let age = death[0] - birth[0];
  if (death[1] < birth[1] || (death[1] === birth[1] && death[2] < birth[2])) age -= 1;
  return age;
}

function birthBounds(value: string): [[number, number, number], [number, number, number]] | undefined {
  if (/^\d{4}$/.test(value)) {
    const year = Number(value);
    return [[year, 1, 1], [year, 12, 31]];
  }
  if (/^\d{4}-\d{2}$/.test(value)) {
    const year = Number(value.slice(0, 4));
    const month = Number(value.slice(5, 7));
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return [[year, month, 1], [year, month, lastDay]];
  }
  const exact = dateParts(value);
  return exact ? [exact, exact] : undefined;
}

export function registrationAgeRange(
  fields: Pick<RegistrationFields, "date_of_death" | "date_of_birth" | "date_of_birth_partial">
): RegistrationAgeRange | undefined {
  const death = dateParts(fields.date_of_death?.trim() ?? "");
  if (!death) return undefined;
  const birthValue = fields.date_of_birth?.trim() || fields.date_of_birth_partial?.trim();
  if (!birthValue) return undefined;
  const bounds = birthBounds(birthValue);
  if (!bounds) return undefined;
  return { youngestPossibleAge: ageAtDeath(bounds[1], death), oldestPossibleAge: ageAtDeath(bounds[0], death) };
}

export function registrationNeedsAgeConfirmation(fields: RegistrationFields): boolean {
  const age = fields.age_years?.trim() ?? "";
  if (/^\d{1,3}$/.test(age) && Number(age) > AGE_REVIEW_THRESHOLD) return true;
  return (registrationAgeRange(fields)?.oldestPossibleAge ?? 0) > AGE_REVIEW_THRESHOLD;
}

export function validateRegistration(
  fields: RegistrationFields,
  today: string
): Partial<Record<keyof RegistrationFields, StringKey>> {
  const errors: Partial<Record<keyof RegistrationFields, StringKey>> = {};
  const value = (key: Exclude<keyof RegistrationFields, "identifiers">) => (fields[key] ?? "").trim();
  if (!value("deceased_name")) errors.deceased_name = "errRequired";
  if (!(SEX_VALUES as readonly string[]).includes(value("deceased_sex"))) errors.deceased_sex = "errRequired";
  for (const key of ["date_of_death", "date_of_birth"] as const) {
    const v = value(key);
    if (!v) continue;
    if (!isRealDate(v)) errors[key] = "errDate";
    else if (v > today) errors[key] = "errFutureDate";
  }
  const partialBirth = value("date_of_birth_partial");
  if (partialBirth && !isPartialBirthDate(partialBirth)) errors.date_of_birth_partial = "errDate";
  if (value("date_of_birth") && partialBirth) errors.date_of_birth_partial = "errBirthPrecision";
  if (!value("date_of_death")) errors.date_of_death = "errRequired";
  if (!errors.date_of_birth && !errors.date_of_death && value("date_of_birth") && value("date_of_birth") > value("date_of_death")) {
    errors.date_of_birth = "errBirthAfterDeath";
  }
  if (!errors.date_of_birth_partial && !errors.date_of_death && partialBirth) {
    const death = value("date_of_death");
    const deathComparable = partialBirth.length === 4 ? death.slice(0, 4) : death.slice(0, 7);
    if (partialBirth > today.slice(0, partialBirth.length)) errors.date_of_birth_partial = "errFutureDate";
    else if (partialBirth > deathComparable) errors.date_of_birth_partial = "errBirthAfterDeath";
  }
  const age = value("age_years");
  if (age && !(/^\d{1,3}$/.test(age) && Number(age) <= MAX_REGISTRATION_AGE)) errors.age_years = "errAge";
  if (!errors.date_of_birth && !errors.date_of_birth_partial && !errors.date_of_death) {
    const range = registrationAgeRange(fields);
    if (range && range.youngestPossibleAge > MAX_REGISTRATION_AGE) {
      if (value("date_of_birth")) errors.date_of_birth = "errAge";
      else if (partialBirth) errors.date_of_birth_partial = "errAge";
    }
  }
  if (value("abha_number") && !ABHA_NUMBER.test(value("abha_number"))) errors.abha_number = "errAbhaNumber";
  if (value("abha_address") && !ABHA_ADDRESS.test(value("abha_address"))) errors.abha_address = "errAbhaAddress";
  for (const key of ["informant_phone", "informant_phone_2"] as const) {
    if (value(key) && !normalisePhone(value(key))) errors[key] = "errPhone";
  }
  return errors;
}

type AgeInfoFields = Pick<RegistrationFields, "date_of_birth" | "date_of_birth_partial" | "age_years">;
const AGE_INFO_KEYS = ["date_of_birth", "date_of_birth_partial", "age_years"] as const;

export function registrationAgeInfoIssue(fields: AgeInfoFields, stored?: AgeInfoFields): "errBirthOrAge" | undefined {
  const text = (source: AgeInfoFields, key: (typeof AGE_INFO_KEYS)[number]) => String(source[key] ?? "").trim();
  if (AGE_INFO_KEYS.some((key) => text(fields, key))) return undefined;
  if (stored && AGE_INFO_KEYS.every((key) => text(fields, key) === text(stored, key))) return undefined;
  return "errBirthOrAge";
}

export function visitAt(date: string): string | null {
  if (!isRealDate(date)) return null;
  const at = new Date(`${date}T09:00:00`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

export function localToday(now = correctedNow()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
