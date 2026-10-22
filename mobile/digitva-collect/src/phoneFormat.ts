/**
 * The VA form's one phone format: exactly 10 digits, shown as 3-3-4
 * ("987 654 3210"), no country code, no restriction on the first digit. The
 * server stores and decides the plain 10 digits (app/utils/phone.py).
 */

export const PHONE_PLACEHOLDER = "___ ___ ____";

const PHONE = /^(?:\+91|91|0)?([0-9]{10})$/;

/**
 * Whitespace as Python's `str.isspace()` / `re` `\s` sees it (the server's rule): JS `\s` differs
 * (it adds U+FEFF and leaves out U+001C-U+001F and U+0085). Shared with identifiers.ts.
 */
export const PY_SPACE = "\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const PHONE_SEPARATORS = new RegExp(`[${PY_SPACE}()-]`, "g");

/**
 * The 10 digits of a phone number, or null when it is not one: exactly the server's
 * app/utils/phone.py. Whitespace, hyphens and parentheses are ignored; a +91, 91 or 0 in front is
 * dropped; only ASCII digits count (tests/fixtures/phone_vectors.json).
 */
export function normalisePhone(value: string): string | null {
  return PHONE.exec(value.replace(PHONE_SEPARATORS, ""))?.[1] ?? null;
}

/**
 * The digits to keep for text typed or pasted into a phone field: digits only,
 * at most 10. A paste (more than one new character; *previous* is the digits
 * held before) that is a number with +91/91/0 in front loses that prefix; one
 * extra typed digit never does, so a number starting 0 or 91 can be typed.
 */
export function phoneDigits(text: string, previous = ""): string {
  const digits = text.replace(/\D/g, "");
  if (digits.length - previous.length > 1) return normalisePhone(digits) ?? digits.slice(0, 10);
  return digits.slice(0, 10);
}

/** Digits grouped 3-3-4 as far as they go ("98765" -> "987 65"). */
export function formatPhone(digits: string): string {
  return [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6, 10)].filter(Boolean).join(" ");
}

/** What the field shows: plain digits grouped 3-3-4; an older stored value that is not plain digits is shown as it is until it is edited. */
export function phoneDisplay(value: string): string {
  return /^\d{0,10}$/.test(value) ? formatPhone(value) : value;
}
