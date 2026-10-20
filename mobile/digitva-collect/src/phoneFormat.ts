/**
 * The VA form's one phone format: exactly 10 digits, shown as 3-3-4
 * ("987 654 3210"), no country code, no restriction on the first digit. The
 * server stores and decides the plain 10 digits (web_intake_service._clean_phone).
 */

export const PHONE_PLACEHOLDER = "___ ___ ____";

const PHONE = /^(?:\+91|91|0)?(\d{10})$/;

/** The 10 digits of a phone number, or null when it is not one. Spaces, hyphens and parentheses are ignored; a +91, 91 or 0 in front is dropped. */
export function normalisePhone(value: string): string | null {
  return PHONE.exec(value.replace(/[\s()-]/g, ""))?.[1] ?? null;
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
