/**
 * Client-side checks for a new demo account. They mirror the server's so the
 * user is told early; the server stays authoritative
 * (app/services/user_account_service.py `clean_username`,
 * app/services/public_demo_service.py `_check_password`). No React Native
 * imports, so screens and tests can use it alone.
 */
import type { StringKey } from "./i18n";

export const USERNAME_RE = /^[a-z][a-z0-9._-]{2,29}$/;
export const PASSWORD_MIN_LENGTH = 12;
const RESERVED = new Set([
  "admin", "administrator", "root", "support", "help", "system", "digitva", "staff",
  "moderator", "owner", "security", "test", "null", "demo", "official", "who",
]);
const RESERVED_PREFIXES = ["support", "root", "security", "who", "official", "admin", "digitva"];

/** The lower-cased username the server will see. */
export const normalizeUsername = (value: string) => value.trim().toLowerCase();

/** The UI string key for the first thing wrong with a new demo account's fields, else undefined. */
export function validateSignUp(username: string, password: string, confirm: string): StringKey | undefined {
  const name = normalizeUsername(username);
  if (!USERNAME_RE.test(name)) return "demoErrUsernameRule";
  const squashed = name.replace(/[._-]/g, "");
  if (RESERVED.has(squashed) || RESERVED_PREFIXES.some((prefix) => squashed.startsWith(prefix))) {
    return "demoErrUsernameReserved";
  }
  if (password.length < PASSWORD_MIN_LENGTH) return "demoErrPasswordShort";
  if (password.trim().toLowerCase() === name) return "demoErrPasswordIsUsername";
  if (password !== confirm) return "demoErrPasswordMatch";
  return undefined;
}
