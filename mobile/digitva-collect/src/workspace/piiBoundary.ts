/**
 * Rule 6, the non-PII boundary of ICD-11 / DORIS: nothing that names a person or carries a registration identifier
 * reaches the engine. A port of vendor/who-icd11-api/src/privacy.rs (the rule the desktop host applies to every WHO
 * request); the Python server has no copy of it. The check runs before any engine call and the refusal names the
 * path of the offending field, never its value.
 *
 * One deliberate difference: Rust's `\d` and `\b` are Unicode, and here digits of the Indian scripts the phone is
 * used in (Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam) and Arabic-Indic digits
 * are turned into ASCII first, instead of relying on a JavaScript engine's `\p{Nd}`.
 */
import { isRecord } from "./whoText";

const FORBIDDEN_KEYS = new Set([
  "name", "deceased_name", "informant_name", "respondent_name", "father_name", "mother_name", "spouse_name",
  "phone", "informant_phone", "respondent_phone", "mobile", "contact_number",
  "address", "house_address", "permanent_address",
  "aadhaar", "aadhaar_number", "aadhaar_last3", "abha", "abha_id", "abha_number", "national_id",
  "identifiers", "registration_number", "crs_number", "mccd_number", "certificate_number",
]);

const AADHAAR = /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/;
const PHONE = /(?:^|[^\d])(?:\+91[\s-]?)?[6-9]\d{9}(?:$|[^\d])/;
const WHO_URI = /https?:\/\/id\.who\.int\/icd\/[^\s&]+/g;
// Code points of each script's digit zero (digits are the ten after it).
const DIGIT_ZEROS = [0x660, 0x6f0, 0x966, 0x9e6, 0xa66, 0xae6, 0xb66, 0xbe6, 0xc66, 0xce6, 0xd66];

/** Raised for a field that must not cross the boundary; `path` is where it was, `reason` says which rule. */
export class PiiBoundaryError extends Error {
  constructor(readonly path: string, readonly reason: string) {
    super(`PII boundary violation at ${path}: ${reason}`);
    this.name = "PiiBoundaryError";
  }
}

function asciiDigits(text: string): string {
  let out = "";
  for (const char of text) {
    const point = char.codePointAt(0)!;
    const zero = point < 0x660 ? undefined : DIGIT_ZEROS.find((start) => point >= start && point < start + 10);
    out += zero === undefined ? char : String(point - zero);
  }
  return out;
}

/** Throws when `text` holds a 12-digit Aadhaar-like or a 10-digit phone number (WHO URIs, whose ids are long numbers, are ignored). */
export function assertNoPiiInText(text: string, path: string): void {
  const scrubbed = asciiDigits(text).replace(WHO_URI, "");
  if (AADHAAR.test(scrubbed)) throw new PiiBoundaryError(path, "Input contains a 12-digit Aadhaar-like identifier pattern.");
  if (PHONE.test(scrubbed)) throw new PiiBoundaryError(path, "Input contains a 10-digit phone number pattern.");
}

/** Throws on a forbidden key or an Aadhaar/phone pattern anywhere in a JSON value. */
export function assertNoPii(value: unknown, path: string): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoPii(item, `${path}[${index}]`));
  } else if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      const childPath = path ? `${path}.${key}` : key;
      if (FORBIDDEN_KEYS.has(key.trim().toLowerCase())) {
        throw new PiiBoundaryError(childPath, `Field '${key}' is personal or registration identifier data and must never cross the ICD-11/DORIS boundary.`);
      }
      assertNoPii(child, childPath);
    }
  } else if (typeof value === "string") {
    assertNoPiiInText(value, path);
  }
}
