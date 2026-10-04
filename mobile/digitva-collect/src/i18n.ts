/**
 * App UI strings: one JSON dictionary per language and a tiny t().
 * The questionnaire has its own language picker; during a browser interview,
 * the app chrome follows that selected form language as well.
 *
 * REVIEW NEEDED: strings/hi.json was written by a non-native author and must
 * be reviewed by a native Hindi speaker before field use (same process as
 * digitva-fb5 for the questionnaire translations).
 */
import en from "./strings/en.json";
import hi from "./strings/hi.json";

export type StringKey = keyof typeof en;

const DICTIONARIES: Record<string, Partial<Record<StringKey, string>>> = { en, hi };
export const UI_LOCALES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" }
 ] as const;

let current = "en";

/** Resolve an exact locale first, then its base language, then English. */
export function normalizeLocale(code: string | null | undefined): string {
  const normalized = (code ?? "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized && Object.hasOwn(DICTIONARIES, normalized)) return normalized;
  const base = normalized.split("-")[0];
  return Object.hasOwn(DICTIONARIES, base) ? base : "en";
}

/** Use `code` when a dictionary exists for it (or its base language), else English. */
export function setUiLocale(code: string | null | undefined): string {
  current = normalizeLocale(code);
  return current;
}

export const uiLocale = () => current;

/** The string for `key` in the current language, falling back to English, then the key itself. */
export function t(key: StringKey, vars: Record<string, string | number> = {}): string {
  const text = DICTIONARIES[current]?.[key] ?? en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

/** Offer only server-enabled languages supported by this release. */
export function questionnaireLocales<T extends { code: string }>(available: T[] | undefined): T[] {
  return (available ?? []).filter((entry) => UI_LOCALES.some((locale) => locale.code === entry.code));
}

/** New drafts use the enabled default, then enabled English, then the first supported language. */
export function questionnaireDefault(available: Array<{ code: string }> | undefined, requested: string | undefined): string {
  if (available === undefined) return "en"; // Legacy settings predate the enabled-language list.
  const locales = questionnaireLocales(available);
  if (!locales.length) throw new Error("questionnaire_language_not_enabled");
  return locales.find((entry) => entry.code === requested)?.code ??
    locales.find((entry) => entry.code === "en")?.code ?? locales[0]?.code ?? "en";
}
