/**
 * Reduction of the national identification number answer (Id10073).
 *
 * Port of reduce_national_id in app/utils/national_id.py; both sides are held
 * to tests/national-id-vectors.json. The full Aadhaar or VID is never kept on
 * a device: only the last 3 digits, in a fixed 12-character form
 * (XXXXXXXXX123). Idempotent: an already reduced value comes back unchanged.
 */
import type { SubmissionData } from "./types.js";

export const NATIONAL_ID_FIELD = "Id10073";
const KEEP_DIGITS = 3;
const STORED_WIDTH = 12;
const NOT_ANSWERED = new Set(["na", "n/a", "none", "null"]);

function isReduced(value: string): boolean {
  return new RegExp(`^X{${STORED_WIDTH - KEEP_DIGITS}}(?:[0-9]{${KEEP_DIGITS}}|X{${KEEP_DIGITS}})$`).test(value);
}

/** Python str.strip() whitespace; JS trim() differs (U+FEFF, \x1c-\x1f, \x85). */
const PY_SPACE = "\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "g");

/** Value 0-9 of a decimal digit of any script (Unicode digit runs are 10 wide). */
function digitValue(char: string): number {
  let start = char.codePointAt(0)!;
  const first = start;
  while (start > 0 && /^\p{Nd}$/u.test(String.fromCodePoint(start - 1))) start -= 1;
  return (first - start) % 10;
}

/** The stored form of an Id10073 answer, or null when it holds no number ("-", "NA", blank). */
export function reduceNationalId(value: unknown): string | null {
  if (value == null || typeof value === "boolean") return null;
  const text = String(value).replace(PY_STRIP, "");
  if (NOT_ANSWERED.has(text.toLowerCase()) || !/[\p{L}\p{N}]/u.test(text)) return null;
  if (isReduced(text)) return text;
  const digits = [...text.normalize("NFKC")]
    .filter((char) => /^\p{Nd}$/u.test(char))
    .map(digitValue)
    .join("");
  if (digits.length < KEEP_DIGITS) return "X".repeat(STORED_WIDTH);
  return "X".repeat(STORED_WIDTH - KEEP_DIGITS) + digits.slice(-KEEP_DIGITS);
}

/** The answer to store: reduced when it holds a number, otherwise as given. */
export function reduceNationalIdAnswer<T>(value: T): T | string {
  return reduceNationalId(value) ?? value;
}

/** *data* with Id10073 reduced; the same object when nothing changes. */
export function reduceNationalIdData(data: SubmissionData): SubmissionData {
  const value = data[NATIONAL_ID_FIELD];
  if (typeof value !== "string") return data;
  const reduced = reduceNationalIdAnswer(value);
  return reduced === value ? data : { ...data, [NATIONAL_ID_FIELD]: reduced };
}
