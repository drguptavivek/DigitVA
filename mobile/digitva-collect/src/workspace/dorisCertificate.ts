/**
 * Bound and normalise a WHO death certificate before DORIS and CoDEdit: a port of app/services/doris_certificate.py
 * (the same checks in the same order, the same field paths and messages), so a certificate the server refuses is
 * refused here with the same words, and one it accepts reaches the engine byte for byte as the server would send it.
 * Where the Python relies on a language rule it is kept: lengths count code points, `x.get(k)` is null for a missing
 * key and for an explicit null, and a stripped string is stripped of Unicode whitespace.
 */
import { WHO_RELEASE, type WhoEngineApi } from "./whoEngineApi";
import { codePointLength, isRecord, type JsonRecord } from "./whoText";

export const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_PART1_LINES = 5;
const MAX_CONDITIONS_PER_LINE = 8;
const MAX_TOTAL_CONDITIONS = 20;
const MAX_TEXT_LENGTH = 500;

const CERTIFICATE_KEYS = new Set([
  "ICDVersion", "ICDMinorVersion", "AdministrativeData", "Part1", "Part2", "Surgery", "Autopsy", "MannerOfDeath",
  "FetalOrInfantDeath", "MaternalDeath",
]);
const CONDITION_KEYS = new Set(["Text", "Code", "LinearizationURI", "FoundationURI", "Interval"]);
const UNKNOWN_MEASUREMENTS = new Set(["BirthWeight", "PregnancyWeeks", "AgeMother"]);
const EXPRESSION_SEPARATOR = /\s*([&/])\s*/;
const DATE_RE = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;
const DURATION_RE = /^P(?:(?:(?:\d+(?:\.\d+)?Y)?(?:\d+(?:\.\d+)?M)?(?:\d+(?:\.\d+)?D)?)(?:T(?:\d+(?:\.\d+)?H)?(?:\d+(?:\.\d+)?M)?(?:\d+(?:\.\d+)?S)?)?|\d+(?:\.\d+)?W)?$/;

const YES_NO_UNKNOWN = new Set([0, 1, 9]);
const SEX_VALUES = new Set([1, 2, 9]);
const MANNER_OF_DEATH_VALUES = new Set([0, 1, 2, 3, 4, 5, 6, 7, 9]);
const PLACE_OF_OCCURRENCE_VALUES = new Set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
const MATERNAL_TIMING_VALUES = new Set([0, 1, 2, 3, 9]);

export interface DorisFieldError {
  path: string;
  message: string;
}

/** The server's DorisCertificateError: what is wrong with the certificate, by field path. */
export class DorisCertificateError extends Error {
  constructor(readonly fields: DorisFieldError[]) {
    super("The DORIS certificate is invalid.");
    this.name = "DorisCertificateError";
  }
}

const fail = (path: string, message: string) => new DorisCertificateError([{ path, message }]);
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
/** `value.get(key)`: null for a missing key and for an explicit null. */
const get = (source: JsonRecord, key: string): unknown => source[key] ?? null;
const hasUnsupported = (source: JsonRecord, allowed: ReadonlySet<string>) => Object.keys(source).some((key) => !allowed.has(key));
const own = (source: object, key: string) => Object.prototype.hasOwnProperty.call(source, key);

/** json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":")) for JSON values. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function utf8Bytes(text: string): number {
  let bytes = 0;
  for (const char of text) {
    const point = char.codePointAt(0)!;
    bytes += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
  }
  return bytes;
}

function integer(value: unknown, path: string, rules: { values?: ReadonlySet<number>; minimum?: number; maximum?: number }): number {
  if (typeof value !== "number" || !Number.isInteger(value)) throw fail(path, "Must be an integer.");
  if (rules.values && !rules.values.has(value)) throw fail(path, "Contains an unsupported value.");
  if (rules.minimum !== undefined && value < rules.minimum) throw fail(path, `Must be at least ${rules.minimum}.`);
  if (rules.maximum !== undefined && value > rules.maximum) throw fail(path, `Must be at most ${rules.maximum}.`);
  return value;
}

function text(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) throw fail(path, "Must be non-empty text.");
  if (codePointLength(value) > MAX_TEXT_LENGTH) throw fail(path, `Must be ${MAX_TEXT_LENGTH} characters or fewer.`);
  return value.trim();
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function date(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim() || codePointLength(value) > 64) throw fail(path, "Must be a valid date.");
  const trimmed = value.trim();
  const match = DATE_RE.exec(trimmed);
  if (match === null) throw fail(path, "Must be a valid date.");
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, timezone] = match;
  const year = Number(yearText);
  const month = monthText === undefined ? undefined : Number(monthText);
  const day = dayText === undefined ? undefined : Number(dayText);
  if (year < 1) throw fail(path, "Must be a valid date.");
  if (month !== undefined && !(month >= 1 && month <= 12)) throw fail(path, "Must be a valid date.");
  // The pattern allows a day only after a month, so `month` is set whenever `day` is.
  if (day !== undefined && (day < 1 || day > daysInMonth(year, month as number))) throw fail(path, "Must be a valid date.");
  if (hourText !== undefined && Number(hourText) > 23) throw fail(path, "Must be a valid date.");
  if (minuteText !== undefined && Number(minuteText) > 59) throw fail(path, "Must be a valid date.");
  if (secondText !== undefined && Number(secondText) > 59) throw fail(path, "Must be a valid date.");
  if (timezone !== undefined && timezone !== "Z" && (Number(timezone.slice(-5, -3)) > 23 || Number(timezone.slice(-2)) > 59)) {
    throw fail(path, "Must be a valid date.");
  }
  if (trimmed.includes("T") && day === undefined) throw fail(path, "Must be a valid date.");
  return trimmed;
}

function duration(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim() || codePointLength(value) > 64) throw fail(path, "Must be a valid ISO 8601 duration.");
  const trimmed = value.trim();
  if (!DURATION_RE.test(trimmed)) throw fail(path, "Must be a valid ISO 8601 duration.");
  return trimmed;
}

type Validator = (value: unknown, path: string) => unknown;

function nestedObject(value: unknown, path: string, fields: Record<string, Validator>): JsonRecord {
  if (!isRecord(value)) throw fail(path, "Must be an object.");
  if (Object.keys(value).some((key) => !own(fields, key))) throw fail(path, "Contains unsupported fields.");
  const normalized: JsonRecord = {};
  for (const [key, raw] of Object.entries(value)) normalized[key] = fields[key](raw, `${path}.${key}`);
  return normalized;
}

const oneOf = (values: ReadonlySet<number>): Validator => (item, itemPath) => integer(item, itemPath, { values });

const normalizeAdministrativeData = (value: unknown, path: string) =>
  nestedObject(value, path, { DateBirth: date, DateDeath: date, Sex: oneOf(SEX_VALUES), EstimatedAge: duration });
const normalizeSurgery = (value: unknown, path: string) =>
  nestedObject(value, path, { WasPerformed: oneOf(YES_NO_UNKNOWN), Date: date, Reason: text });
const normalizeAutopsy = (value: unknown, path: string) =>
  nestedObject(value, path, { WasRequested: oneOf(YES_NO_UNKNOWN), Findings: oneOf(YES_NO_UNKNOWN) });
const normalizeMannerOfDeath = (value: unknown, path: string) =>
  nestedObject(value, path, {
    MannerOfDeath: oneOf(MANNER_OF_DEATH_VALUES),
    DateOfExternalCauseOrPoisoning: date,
    DescriptionExternalCause: text,
    PlaceOfOccuranceExternalCause: oneOf(PLACE_OF_OCCURRENCE_VALUES),
  });
const normalizeMaternalDeath = (value: unknown, path: string) =>
  nestedObject(value, path, {
    WasPregnant: oneOf(YES_NO_UNKNOWN),
    TimeFromPregnancy: oneOf(MATERNAL_TIMING_VALUES),
    PregnancyContribute: oneOf(YES_NO_UNKNOWN),
  });

function normalizeFetalOrInfantDeath(value: unknown, path: string): JsonRecord {
  const validators: Record<string, Validator> = {
    MultiplePregnancy: oneOf(YES_NO_UNKNOWN),
    Stillborn: oneOf(YES_NO_UNKNOWN),
    DeathWithin24h: (item, itemPath) => integer(item, itemPath, { minimum: 0, maximum: 24 }),
    BirthWeight: (item, itemPath) => integer(item, itemPath, { minimum: 1, maximum: 9999 }),
    PregnancyWeeks: (item, itemPath) => integer(item, itemPath, { minimum: 1, maximum: 50 }),
    AgeMother: (item, itemPath) => integer(item, itemPath, { minimum: 10, maximum: 80 }),
    PerinatalDescription: text,
  };
  if (!isRecord(value)) throw fail(path, "Must be an object.");
  if (Object.keys(value).some((key) => !own(validators, key))) throw fail(path, "Contains unsupported fields.");
  const normalized: JsonRecord = {};
  for (const [key, raw] of Object.entries(value)) {
    // WHO's exchange format represents unknown fetal measurements by omission.
    if (UNKNOWN_MEASUREMENTS.has(key) && (raw === null || raw === "")) continue;
    normalized[key] = validators[key](raw, `${path}.${key}`);
  }
  return normalized;
}

function validateCondition(condition: unknown, path: string): JsonRecord {
  if (!isRecord(condition)) throw fail(path, "Must be an object.");
  if (hasUnsupported(condition, CONDITION_KEYS)) throw fail(path, "Contains unsupported fields.");
  const result = clone(condition);
  const conditionText = result.Text;
  if (typeof conditionText !== "string" || !conditionText.trim()) throw fail(`${path}.Text`, "Enter condition text.");
  if (codePointLength(conditionText) > MAX_TEXT_LENGTH) throw fail(`${path}.Text`, "Must be 500 characters or fewer.");
  result.Text = conditionText.trim();

  const code = get(result, "Code");
  const uri = get(result, "LinearizationURI");
  if ((code === null) !== (uri === null)) throw fail(path, "Code and LinearizationURI must be supplied together.");
  if (code !== null) {
    if (typeof code !== "string" || !code.trim() || codePointLength(code) > 128) throw fail(`${path}.Code`, "Must be a valid ICD-11 expression.");
    if (typeof uri !== "string" || !uri.trim() || codePointLength(uri) > 2048) throw fail(`${path}.LinearizationURI`, "Must be a valid WHO URI.");
    result.Code = code.trim();
    result.LinearizationURI = uri.trim();
  }
  for (const key of ["FoundationURI", "Interval"]) {
    const value = get(result, key);
    if (value !== null && typeof value !== "string") throw fail(`${path}.${key}`, "Must be text.");
    if (typeof value === "string") result[key] = value.trim();
  }
  if (result.Interval) result.Interval = duration(result.Interval, `${path}.Interval`);
  return result;
}

function normalizeConditions(raw: unknown, path: string): JsonRecord[] {
  if (!Array.isArray(raw) || raw.length === 0) throw fail(path, "Enter at least one condition.");
  if (raw.length > MAX_CONDITIONS_PER_LINE) throw fail(path, "A line may contain at most 8 conditions.");
  const conditions = raw.map((item, index) => validateCondition(item, `${path}[${index}]`));
  if (new Set(conditions.map((item) => get(item, "Interval"))).size > 1) {
    throw fail(path, "All conditions on a line must use the same interval.");
  }
  return conditions;
}

const AGE_UNIT_DAYS: Record<string, number> = { Y: 365.25, M: 30.4375, W: 7, D: 1 };
const TIME_UNIT_DAYS: Record<string, number> = { H: 1 / 24, M: 1 / 1440, S: 1 / 86400 };
const AGE_RE = /^P(?:(\d+(?:\.\d+)?)([YMWD]))?(?:T(\d+(?:\.\d+)?)([HMS]))?$/;
const EXTERNAL_CAUSE_KEYS = ["DateOfExternalCauseOrPoisoning", "DescriptionExternalCause", "PlaceOfOccuranceExternalCause"];

/** Days in a simple ISO age (`P65Y`, `P3D`, `PT5H`); null when blank or odd. Mirrors `durationDays` of doris_rules.js. */
function ageDays(value: unknown): number | null {
  const match = typeof value === "string" ? AGE_RE.exec(value.trim()) : null;
  if (!match || !(match[1] || match[3])) return null;
  return Number(match[1] || 0) * (AGE_UNIT_DAYS[match[2]] ?? 0) + Number(match[3] || 0) * (TIME_UNIT_DAYS[match[4]] ?? 0);
}

/** Remove the keys rules V1-V6 hide, in place; returns the dropped `Section.Field` paths. An unknown age hides nothing. */
export function dropInapplicableSections(certificate: JsonRecord): string[] {
  const dropped: string[] = [];
  const read = (section: string, field: string): unknown => {
    const value = certificate[section];
    return isRecord(value) ? get(value, field) : null;
  };
  const drop = (section: string, fields?: readonly string[]) => {
    const value = certificate[section];
    if (!isRecord(value)) return;
    for (const field of fields ?? Object.keys(value)) {
      if (field in value) {
        delete value[field];
        dropped.push(`${section}.${field}`);
      }
    }
    if (Object.keys(value).length === 0) delete certificate[section];
  };

  const days = ageDays(read("AdministrativeData", "EstimatedAge"));
  if (days !== null && days >= 365) drop("FetalOrInfantDeath");
  else if ((days !== null && days >= 7) || read("FetalOrInfantDeath", "Stillborn") === 1) drop("FetalOrInfantDeath", ["DeathWithin24h"]);
  if (read("AdministrativeData", "Sex") !== 2) drop("MaternalDeath");
  else if (read("MaternalDeath", "WasPregnant") !== 1) drop("MaternalDeath", ["TimeFromPregnancy", "PregnancyContribute"]);
  if (read("Surgery", "WasPerformed") !== 1) drop("Surgery", ["Date", "Reason"]);
  if (read("Autopsy", "WasRequested") !== 1) drop("Autopsy", ["Findings"]);
  const manner = read("MannerOfDeath", "MannerOfDeath");
  if (!(typeof manner === "number" && manner >= 1 && manner <= 7)) drop("MannerOfDeath", EXTERNAL_CAUSE_KEYS);
  return dropped;
}

/** Copy of `certificate` safe to send to WHO, plus the paths left out: DORIS crashes on a year-only birth or death date when both are present. */
export function whoSafeCertificate(certificate: JsonRecord): [JsonRecord, string[]] {
  const safe = clone(certificate);
  const admin = safe.AdministrativeData;
  const omitted: string[] = [];
  if (isRecord(admin) && admin.DateBirth && admin.DateDeath) {
    for (const key of ["DateBirth", "DateDeath"]) {
      if (codePointLength(admin[key] as string) === 4) {
        delete admin[key];
        omitted.push(`AdministrativeData.${key}`);
      }
    }
  }
  return [safe, omitted];
}

/** A bounded, normalised copy of the certificate, without mutating the caller's. Throws DorisCertificateError. */
export function normalizeCertificate(certificate: unknown, release: string = WHO_RELEASE): JsonRecord {
  if (!isRecord(certificate)) throw fail("certificate", "Must be an object.");
  if (hasUnsupported(certificate, CERTIFICATE_KEYS)) throw fail("certificate", "Contains unsupported fields.");
  if (certificate.ICDVersion !== "ICD11") throw fail("certificate.ICDVersion", "Must be ICD11.");
  const supplied = get(certificate, "ICDMinorVersion");
  if (supplied !== null && supplied !== release) throw fail("certificate.ICDMinorVersion", "Must match the configured release.");

  const result = clone(certificate);
  result.ICDMinorVersion = release;
  const normalizers: [string, (value: unknown, path: string) => JsonRecord][] = [
    ["AdministrativeData", normalizeAdministrativeData],
    ["Surgery", normalizeSurgery],
    ["Autopsy", normalizeAutopsy],
    ["MannerOfDeath", normalizeMannerOfDeath],
    ["FetalOrInfantDeath", normalizeFetalOrInfantDeath],
    ["MaternalDeath", normalizeMaternalDeath],
  ];
  for (const [key, normalize] of normalizers) {
    if (key in result) result[key] = normalize(result[key], `certificate.${key}`);
  }
  dropInapplicableSections(result);

  const part1 = result.Part1;
  if (!Array.isArray(part1) || part1.length === 0) throw fail("certificate.Part1", "Enter at least one Part I line.");
  if (part1.length > MAX_PART1_LINES) throw fail("certificate.Part1", "Part I may contain at most 5 lines.");
  let total = 0;
  result.Part1 = part1.map((line, index) => {
    const path = `certificate.Part1[${index}]`;
    if (!isRecord(line) || Object.keys(line).length !== 1 || !("Conditions" in line)) throw fail(path, "Must contain only Conditions.");
    const conditions = normalizeConditions(line.Conditions, `${path}.Conditions`);
    total += conditions.length;
    return { Conditions: conditions };
  });

  const part2 = get(result, "Part2");
  if (part2 !== null) {
    if (!isRecord(part2) || Object.keys(part2).length !== 1 || !("Conditions" in part2)) throw fail("certificate.Part2", "Must contain only Conditions.");
    const raw = part2.Conditions;
    if (!Array.isArray(raw)) throw fail("certificate.Part2.Conditions", "Must be a list.");
    if (raw.length > 0) {
      const conditions = normalizeConditions(raw, "certificate.Part2.Conditions");
      total += conditions.length;
      result.Part2 = { Conditions: conditions };
    } else {
      result.Part2 = { Conditions: [] };
    }
  }
  if (total > MAX_TOTAL_CONDITIONS) throw fail("certificate", "A certificate may contain at most 20 conditions.");
  if (utf8Bytes(canonicalJson(result)) > MAX_REQUEST_BYTES) throw fail("certificate", "The certificate is too large.");
  return result;
}

/** The canonical release-pinned URI expression of a code, through WHO codeinfo; null when WHO does not know it. */
export async function expectedExpressionUri(who: WhoEngineApi, code: string): Promise<string | null> {
  const parts = code.split(EXPRESSION_SEPARATOR);
  const expression = await who.codeinfo(code);
  if (!expression || expression.code !== code) return null;
  if (parts.length === 1) {
    const uri = expression.stemId;
    return typeof uri === "string" && uri ? uri : null;
  }
  const uris: string[] = [];
  for (let index = 0; index < parts.length; index += 2) {
    const token = parts[index];
    const info = await who.codeinfo(token);
    if (!info || info.code !== token) return null;
    const uri = info.stemId;
    if (typeof uri !== "string" || !uri) return null;
    uris.push(uri);
  }
  return uris.slice(1).reduce((expected, uri, index) => `${expected} ${parts[2 * index + 1]} ${uri}`, uris[0]);
}

/** Verify every supplied complete code and URI against codeinfo. Throws DorisCertificateError at the first mismatch. */
export async function verifyCertificateCodes(who: WhoEngineApi, certificate: JsonRecord): Promise<void> {
  const groups: [string, JsonRecord[]][] = (certificate.Part1 as JsonRecord[]).map((line, index) => [
    `certificate.Part1[${index}].Conditions`, line.Conditions as JsonRecord[],
  ]);
  const part2 = isRecord(certificate.Part2) ? (certificate.Part2.Conditions as JsonRecord[]) : [];
  if (part2.length > 0) groups.push(["certificate.Part2.Conditions", part2]);
  for (const [groupPath, conditions] of groups) {
    for (const [index, condition] of conditions.entries()) {
      const code = get(condition, "Code");
      if (code === null) continue;
      if (await expectedExpressionUri(who, code as string) !== condition.LinearizationURI) {
        throw fail(`${groupPath}[${index}].LinearizationURI`, "Does not match the selected ICD-11 code.");
      }
    }
  }
}
