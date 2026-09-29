/**
 * App UI strings: one JSON dictionary per language and a tiny t().
 * The questionnaire has its own language picker; this covers only the app's
 * own screens.
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
];

let current = "en";

/** Use `code` when a dictionary exists for it (or its base language), else English. */
export function setUiLocale(code: string | null | undefined): string {
  const base = (code ?? "").toLowerCase().split(/[-_]/)[0];
  current = base in DICTIONARIES ? base : "en";
  return current;
}

export const uiLocale = () => current;

/** The string for `key` in the current language, falling back to English, then the key itself. */
export function t(key: StringKey, vars: Record<string, string | number> = {}): string {
  const text = DICTIONARIES[current]?.[key] ?? en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match));
}
