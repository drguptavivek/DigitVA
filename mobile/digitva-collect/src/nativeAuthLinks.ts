/** Longest typed mobile number a sign-in screen takes; the server refuses longer (app/routes/api/auth.py MOBILE_MAX_CHARS). */
export const MOBILE_MAX_CHARS = 16;

/**
 * Turn the India UI's optional +91/91/0 prefix into its ten-digit display value.
 * Values with an unexpected length remain invalid and are rejected on submit;
 * this function does not silently discard digits from a malformed paste.
 */
export function mobileDigitsFromInput(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) return digits.slice(2);
  if (digits.length === 11 && digits.startsWith("0")) return digits.slice(1);
  return digits;
}

/**
 * The mobile field after a keystroke or paste: India's country code is fixed (+91 shown beside the field), so it
 * holds at most 10 digits. A change that would leave more than 10 (an 11th digit, a malformed paste) is refused and
 * the field keeps its value, rather than cutting digits silently. International numbers can widen this later.
 */
export function nextMobileDigits(previous: string, typed: string): string {
  const digits = mobileDigitsFromInput(typed);
  return digits.length > 10 ? previous : digits;
}

/** Return the existing device API identifier form, or undefined for invalid input. */
export function normalizeMobileIdentifier(value: string): string | undefined {
  const digits = mobileDigitsFromInput(value);
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : undefined;
}

/** Sign-in code characters: capitals and digits without 0 O 1 I L (app/services/mobile_sign_in_service.py CODE_ALPHABET). */
const CODE_CHARS = /^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}$/;

/**
 * Whether a typed value has a sign-in code's shape, read as the server reads it (`_typed_code`: spaces and `-`
 * dropped, any case): 8 code characters (`K7PQ-M3XR`), or 6 digits issued before 2026-11-16.
 */
export function looksLikeSignInCode(value: string): boolean {
  const typed = value.replace(/[\s-]/g, "").toUpperCase();
  return CODE_CHARS.test(typed) || /^\d{6}$/.test(typed);
}

/** The code field as the person types: capitals, at most 8 characters, a `-` after the fourth (`K7PQ-M3XR`). */
export function formatSignInCode(value: string): string {
  const typed = value.replace(/[\s-]/g, "").toUpperCase().slice(0, 8);
  return typed.length > 4 ? `${typed.slice(0, 4)}-${typed.slice(4)}` : typed;
}
