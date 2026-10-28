import { PII_FIELD_IDS } from "../standalone/pii";
import type { SmartVaOptions, SmartVaRequest } from "./contracts";

const NAN_CHECK_COLUMNS = [
  "ageInDays",
  "ageInDays2",
  "ageInYears",
  "ageInYearsRemain",
  "ageInMonths",
  "ageInMonthsRemain",
] as const;

const SMARTVA_COLUMN = /^[Ii]d\d+(_\w+)?$|^age|^is/;

function normalizedHeader(header: string): string {
  return header.trim().replace(/[:/]/g, "-").split("-").at(-1) ?? "";
}

function isBlank(value: unknown): boolean {
  return value === null
    || value === undefined
    || (typeof value === "number" && Number.isNaN(value))
    || (typeof value === "string" && ["", "nan"].includes(value.trim().toLowerCase()));
}

function pythonString(value: unknown): string {
  if (isBlank(value)) return "";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") {
    if (value === Infinity) return "inf";
    if (value === -Infinity) return "-inf";
    return String(value);
  }
  if (Array.isArray(value)) return `[${value.map(pythonRepr).join(", ")}]`;
  if (typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>).map(([key, entry]) => `${pythonRepr(key)}: ${pythonRepr(entry)}`).join(", ")}}`;
  }
  return String(value);
}

function pythonRepr(value: unknown): string {
  if (typeof value === "string") {
    const quote = value.includes("'") && !value.includes('"') ? '"' : "'";
    return `${quote}${value
      .replace(/\\/g, "\\\\")
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t")
      .replace(new RegExp(quote, "g"), `\\${quote}`)}${quote}`;
  }
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number" && Number.isNaN(value)) return "nan";
  if (value === Infinity) return "inf";
  if (value === -Infinity) return "-inf";
  if (Array.isArray(value)) return `[${value.map(pythonRepr).join(", ")}]`;
  if (typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>).map(([key, entry]) => `${pythonRepr(key)}: ${pythonRepr(entry)}`).join(", ")}}`;
  }
  return String(value);
}

function pythonRound(value: number): number {
  const floor = Math.floor(value);
  const fraction = value - floor;
  if (fraction < 0.5) return floor;
  if (fraction > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}

function pythonFloat(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string" && value.trim() !== "") return Number(value);
  return Number.NaN;
}

function isSmartVaHeader(header: string): boolean {
  const name = normalizedHeader(header);
  return name === "sid" || SMARTVA_COLUMN.test(name);
}

function isPrivateHeader(header: string, sealedFieldIds: ReadonlySet<string>): boolean {
  const name = normalizedHeader(header);
  return name === "sealed" || PII_FIELD_IDS.has(name) || sealedFieldIds.has(name);
}

/** Mirrors the server's SmartVA cleaner, with PII filtering applied to normalized paths too. */
export function cleanSmartVaInput(
  payload: Record<string, unknown>,
  sid: string,
  sealedFields: readonly string[] = [],
): Record<string, string> {
  const sealedFieldIds = new Set(sealedFields);
  const row: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (!sealedFieldIds.has(key) && key !== "sealed") row[key] = value;
  }

  for (const column of NAN_CHECK_COLUMNS) {
    if (column in row && isBlank(row[column])) row[column] = "";
  }

  if ("ageInDays" in row && "finalAgeInYears" in row && isBlank(row.ageInDays) && !isBlank(row.finalAgeInYears)) {
    const years = pythonFloat(row.finalAgeInYears);
    if (Number.isFinite(years)) row.ageInDays = String(pythonRound(years * 365));
  }

  if (!isBlank(row.ageInDays) && isBlank(row.age_neonate_days) && isBlank(row.age_group) && isBlank(row.age_adult)) {
    const days = pythonFloat(row.ageInDays);
    if (Number.isFinite(days) && days <= 28) row.age_neonate_days = String(Math.trunc(days));
  }

  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(row)) {
    if (isSmartVaHeader(key) && !isPrivateHeader(key, sealedFieldIds)) cleaned[key] = pythonString(value);
  }
  cleaned.sid = sid;
  return cleaned;
}

export function createSmartVaRequest(
  input: Record<string, string>,
  options: SmartVaOptions,
): SmartVaRequest {
  for (const [key, value] of Object.entries(input)) {
    if (typeof value !== "string" || !isSmartVaHeader(key) || isPrivateHeader(key, new Set())) {
      throw new TypeError("SmartVA input contains an invalid or private field.");
    }
  }
  if (typeof input.sid !== "string" || input.sid.trim() === "") {
    throw new TypeError("SmartVA sid is required.");
  }
  if (typeof options.country !== "string" || options.country.trim() === "") {
    throw new TypeError("SmartVA country is required.");
  }
  for (const key of ["hiv", "malaria", "hce", "freetext"] as const) {
    if (typeof options[key] !== "boolean") throw new TypeError(`SmartVA ${key} option is required.`);
  }
  return { schema_version: 1, input, options: { ...options } };
}
